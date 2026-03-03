"""
Entity Roster Extraction Engine — Vector 1

Pulls the full owner/property roster from Streamline VRS, cross-references
owner names to unit IDs, fetches live balances, archives statement PDFs to
NAS, and writes everything to the Iron Dome staging tables.

Tables written:
  - owner_property_map      (owner-to-unit cross-reference)
  - trust_balance            (live Streamline owner_balance -> owner_funds)
  - management_splits        (updated from split_config.json)
  - owner_statement_archive  (monthly statement metadata + PDF paths)

Usage:
    cd fortress-guest-platform && python3 -m tools.entity_extractor
"""

import asyncio
import base64
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from backend.integrations.streamline_vrs import StreamlineVRS

log = structlog.get_logger("entity_extractor")

DB_DSN = os.getenv(
    "ENTITY_DB_DSN",
    "dbname=fortress_guest user=fgp_app password=F0rtr3ss_Gu3st_2026! host=localhost",
)

NAS_STATEMENT_PATH = os.getenv(
    "NAS_STATEMENT_PATH",
    "/mnt/fortress_nas/sectors/legal/owner-statements",
)

LOOKBACK_MONTHS = int(os.getenv("LOOKBACK_MONTHS", "6"))
SPLIT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "split_config.json")


def _get_db():
    return psycopg2.connect(DB_DSN)


def _best_phone(owner_raw: Dict[str, Any]) -> str:
    """Extract the best available phone from Streamline's multi-field layout."""
    for field in ("mobile_phone", "home_phone", "business_phone", "local_phone"):
        val = owner_raw.get(field)
        if val and not isinstance(val, dict):
            return str(val).strip()
    return ""


def _normalize_owner_properties(owner_raw: Dict[str, Any]) -> List[str]:
    """Handle Streamline's inconsistent property field (dict vs list)."""
    prop_data = owner_raw.get("property", [])
    if isinstance(prop_data, dict):
        prop_data = [prop_data]
    if not isinstance(prop_data, list):
        return []
    return [p.get("property_name", "") for p in prop_data if p.get("property_name")]


async def extract_entity_roster():
    sl = StreamlineVRS()
    if not sl.is_configured:
        log.error("streamline_not_configured", hint="Check .env for STREAMLINE_API_*")
        return

    with open(SPLIT_CONFIG_PATH) as f:
        split_config = json.load(f).get("splits", {})

    conn = _get_db()
    cur = conn.cursor()

    # ------------------------------------------------------------------
    # Phase 1: Fetch the canonical property list (14 units)
    # ------------------------------------------------------------------
    log.info("phase_1_properties")
    raw_props = await sl._call("GetPropertyList", {})

    prop_list: List[Dict] = []
    if isinstance(raw_props, dict) and "property" in raw_props:
        p = raw_props["property"]
        prop_list = p if isinstance(p, list) else [p]
    elif isinstance(raw_props, list):
        prop_list = raw_props

    prop_name_to_id: Dict[str, str] = {}
    for p in prop_list:
        uid = str(p.get("id", ""))
        name = p.get("name", "")
        if uid and name:
            prop_name_to_id[name] = uid

    log.info("properties_loaded", count=len(prop_name_to_id))
    for name, uid in sorted(prop_name_to_id.items()):
        print(f"  {uid:>8}: {name}")

    # ------------------------------------------------------------------
    # Phase 2: Fetch raw owner list with property linkage
    # ------------------------------------------------------------------
    log.info("phase_2_owners")
    raw_owners_resp = await sl._call("GetOwnerList", {})
    raw_owners: List[Dict] = []
    if isinstance(raw_owners_resp, dict) and "owner" in raw_owners_resp:
        o = raw_owners_resp["owner"]
        raw_owners = o if isinstance(o, list) else [o]

    log.info("owners_loaded", count=len(raw_owners))

    # Build the cross-reference: one row per (owner_id, unit_id) pair
    mappings: List[Dict[str, Any]] = []
    unmatched_names: List[str] = []

    for owner in raw_owners:
        oid = str(owner.get("owner_id", ""))
        name = f"{owner.get('first_name', '')} {owner.get('last_name', '')}".strip()
        email = owner.get("email", "") or ""
        phone = _best_phone(owner)
        prop_names = _normalize_owner_properties(owner)

        for pname in prop_names:
            uid = prop_name_to_id.get(pname)
            if uid:
                mappings.append({
                    "sl_owner_id": oid,
                    "unit_id": uid,
                    "owner_name": name,
                    "email": email,
                    "phone": phone,
                    "property_name": pname,
                })
            else:
                unmatched_names.append(f"owner={oid} ({name}), property_name='{pname}'")

    log.info("cross_reference_built",
             matched=len(mappings), unmatched=len(unmatched_names))
    if unmatched_names:
        for u in unmatched_names:
            log.warning("unmatched_property", detail=u)

    # ------------------------------------------------------------------
    # Phase 3: Fetch live balances for all 14 units
    # ------------------------------------------------------------------
    log.info("phase_3_balances")
    balances: Dict[str, float] = {}
    for uid in sorted(prop_name_to_id.values()):
        try:
            bal_resp = await sl.fetch_unit_owner_balance(int(uid))
            balances[uid] = float(bal_resp.get("owner_balance", 0.0))
        except Exception as e:
            log.warning("balance_fetch_failed", unit_id=uid, error=str(e))
            balances[uid] = 0.0

    for uid, bal in sorted(balances.items()):
        pname = next((n for n, u in prop_name_to_id.items() if u == uid), uid)
        print(f"  {uid:>8}: ${bal:>12,.2f}  ({pname})")

    # ------------------------------------------------------------------
    # Phase 4: Write owner_property_map + update trust_balance + management_splits
    # ------------------------------------------------------------------
    log.info("phase_4_write_db")

    for m in mappings:
        uid = m["unit_id"]
        bal = balances.get(uid, 0.0)

        cur.execute("""
            INSERT INTO owner_property_map
                (sl_owner_id, unit_id, owner_name, email, phone, property_name, live_balance, synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (sl_owner_id, unit_id) DO UPDATE SET
                owner_name    = EXCLUDED.owner_name,
                email         = EXCLUDED.email,
                phone         = EXCLUDED.phone,
                property_name = EXCLUDED.property_name,
                live_balance  = EXCLUDED.live_balance,
                synced_at     = CURRENT_TIMESTAMP
        """, (m["sl_owner_id"], uid, m["owner_name"], m["email"], m["phone"],
              m["property_name"], bal))

    # Update trust_balance with live Streamline balances
    for uid, bal in balances.items():
        cur.execute("""
            UPDATE trust_balance
            SET owner_funds = %s, last_updated = CURRENT_TIMESTAMP
            WHERE property_id = %s
        """, (bal, uid))

    # Update management_splits from split_config.json
    updated_splits = 0
    for pname, cfg in split_config.items():
        uid = cfg.get("unit_id") or prop_name_to_id.get(pname)
        if not uid:
            continue
        owner_pct = Decimal(str(cfg["owner_pct"]))
        pm_pct = Decimal(str(cfg["pm_pct"]))
        cur.execute("""
            UPDATE management_splits
            SET owner_pct = %s, pm_pct = %s, effective_date = %s
            WHERE property_id = %s
        """, (owner_pct, pm_pct, cfg.get("effective_from", "2023-01-01"), uid))
        if cur.rowcount > 0:
            updated_splits += 1

    conn.commit()
    log.info("db_writes_committed",
             owner_map_rows=len(mappings),
             balances_updated=len(balances),
             splits_updated=updated_splits)

    # ------------------------------------------------------------------
    # Phase 5: Archive monthly statements (last N months per owner/unit)
    #
    # Uses _raw_call to bypass the circuit breaker. E0191 ("statement not
    # found") is a normal data-absence response, not a service failure.
    # The breaker would trip after 3 E0191s and block all remaining calls.
    # ------------------------------------------------------------------
    log.info("phase_5_statements", lookback_months=LOOKBACK_MONTHS)

    nas_available = os.path.isdir(os.path.dirname(NAS_STATEMENT_PATH))
    if not nas_available:
        fallback_path = os.path.join(os.path.dirname(__file__), "..", "data", "owner-statements")
        log.warning("nas_not_available", fallback=fallback_path)
        statement_base = fallback_path
    else:
        statement_base = NAS_STATEMENT_PATH

    os.makedirs(statement_base, exist_ok=True)

    total_archived = 0
    total_pdfs = 0
    total_no_data = 0

    for m in mappings:
        oid = m["sl_owner_id"]
        uid = m["unit_id"]
        pname = m["property_name"]

        for months_back in range(1, LOOKBACK_MONTHS + 1):
            today = date.today()
            target_first = (today.replace(day=1) - timedelta(days=1))
            for _ in range(months_back - 1):
                target_first = (target_first.replace(day=1) - timedelta(days=1))
            period_start = target_first.replace(day=1)
            period_end = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

            params = {
                "owner_id": str(oid),
                "unit_id": str(uid),
                "status_id": "1",
                "skip_pdf": "0",
                "startdate": period_start.strftime("%m/%d/%y"),
                "enddate": period_end.strftime("%m/%d/%y"),
            }

            try:
                stmt_resp = await sl._raw_call("GetMonthEndStatement", params)
            except Exception as e:
                err_str = str(e)
                if "E0191" in err_str:
                    total_no_data += 1
                else:
                    log.warning("statement_fetch_error",
                                owner_id=oid, unit_id=uid,
                                period=f"{period_start}..{period_end}",
                                error=err_str[:200])
                continue

            if not stmt_resp or not isinstance(stmt_resp, dict):
                continue

            stmts_raw = stmt_resp.get("statements", {}).get("statement", [])
            if isinstance(stmts_raw, dict):
                stmts_raw = [stmts_raw]
            if not stmts_raw:
                continue

            for stmt in stmts_raw:
                stmt_id = str(stmt.get("id", ""))
                b64_pdf = stmt.get("pdf", "")

                pdf_path: Optional[str] = None
                if b64_pdf and isinstance(b64_pdf, str) and len(b64_pdf) > 100:
                    owner_dir = os.path.join(statement_base, oid)
                    os.makedirs(owner_dir, exist_ok=True)
                    fname = f"{period_start.strftime('%Y-%m')}_{uid}_{stmt_id}.pdf"
                    pdf_path = os.path.join(owner_dir, fname)
                    try:
                        with open(pdf_path, "wb") as fp:
                            fp.write(base64.b64decode(b64_pdf))
                        total_pdfs += 1
                    except Exception as e:
                        log.warning("pdf_write_failed", path=pdf_path, error=str(e))
                        pdf_path = None

                cur.execute("""
                    INSERT INTO owner_statement_archive
                        (streamline_statement_id, sl_owner_id, unit_id,
                         period_start, period_end, pdf_path, extracted_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (sl_owner_id, unit_id, period_start, period_end)
                    DO UPDATE SET
                        streamline_statement_id = EXCLUDED.streamline_statement_id,
                        pdf_path = EXCLUDED.pdf_path,
                        archived_at = CURRENT_TIMESTAMP
                """, (
                    stmt_id, oid, uid,
                    period_start, period_end,
                    pdf_path,
                    json.dumps({
                        "location_name": stmt.get("location_name"),
                        "name": stmt.get("name"),
                        "total_number": stmt.get("total_number"),
                    }),
                ))
                total_archived += 1

        conn.commit()

    log.info("statement_phase_summary",
             archived=total_archived, pdfs=total_pdfs,
             no_data_periods=total_no_data)

    print(f"\n  Phase 5 complete: {total_archived} archived, {total_pdfs} PDFs, "
          f"{total_no_data} periods with no data")

    # ------------------------------------------------------------------
    # Final Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  VECTOR 1: ENTITY ROSTER EXTRACTION — FINAL REPORT")
    print("=" * 70)

    cur.execute("SELECT COUNT(*) FROM owner_property_map")
    opm_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM owner_statement_archive")
    osa_count = cur.fetchone()[0]

    cur.execute("""
        SELECT opm.sl_owner_id, opm.owner_name, opm.unit_id, opm.property_name,
               opm.live_balance, ms.owner_pct, ms.pm_pct
        FROM owner_property_map opm
        LEFT JOIN management_splits ms ON ms.property_id = opm.unit_id
        ORDER BY opm.owner_name, opm.property_name
    """)
    rows = cur.fetchall()

    print(f"\n  Owner/Property Pairs Mapped: {opm_count}")
    print(f"  Statement Archive Rows:      {osa_count}")
    print(f"  PDFs Saved:                  {total_pdfs}")
    print(f"\n  {'Owner':<25} {'Property':<40} {'Unit ID':>8}  {'Balance':>10}  {'Split':>8}")
    print(f"  {'-'*25} {'-'*40} {'-'*8}  {'-'*10}  {'-'*8}")

    for row in rows:
        oid, oname, uid, pname, bal, opct, ppct = row
        split_str = f"{opct}/{ppct}" if opct else "N/A"
        print(f"  {oname:<25} {pname:<40} {uid:>8}  ${bal:>9,.2f}  {split_str:>8}")

    if unmatched_names:
        print(f"\n  UNMATCHED ({len(unmatched_names)}):")
        for u in unmatched_names:
            print(f"    - {u}")

    print("\n" + "=" * 70)

    cur.close()
    conn.close()


if __name__ == "__main__":
    asyncio.run(extract_entity_roster())
