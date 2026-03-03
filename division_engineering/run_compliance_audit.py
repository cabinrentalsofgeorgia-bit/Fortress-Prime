"""
Fortress Prime — Portfolio-Wide Compliance Audit
===================================================
Runs the ComplianceEngine's rental safety checks across ALL properties.

Uses MEP system data from engineering.mep_systems to determine what
systems are registered, and generates compliance reports per property.

Results are:
    1. Printed to console
    2. Saved to engineering.compliance_log in PostgreSQL
    3. Available via Watchtower briefing (Stream 5)

Usage:
    python division_engineering/run_compliance_audit.py
    python division_engineering/run_compliance_audit.py --property "Buckhorn Lodge"
    python division_engineering/run_compliance_audit.py --critical-only
"""

import os
import sys
import json
import psycopg2
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from division_engineering.code_compliance import ComplianceEngine

PG_HOST = os.environ.get("DB_HOST", "localhost")
PG_DB = os.environ.get("DB_NAME", "fortress_db")
PG_USER = os.environ.get("DB_USER", "miner_bot")
PG_PASS = os.environ.get("DB_PASSWORD", os.environ.get("DB_PASS", ""))
PG_PORT = os.environ.get("DB_PORT", "5432")


def get_conn():
    return psycopg2.connect(
        host=PG_HOST, database=PG_DB, user=PG_USER,
        password=PG_PASS, port=PG_PORT,
    )


def get_property_features(cur, prop_id, prop_name):
    """
    Build feature dict for a property from MEP system data.
    Since conditions are 'unknown', we report what's REGISTERED
    and flag everything for inspection.
    """
    cur.execute("""
        SELECT system_type, condition, fuel_type, capacity
        FROM engineering.mep_systems
        WHERE property_id = %s
    """, (prop_id,))
    systems = cur.fetchall()

    system_types = {s[0] for s in systems}
    fuel_types = {s[2] for s in systems if s[2]}

    features = {
        # What's registered
        "smoke_detectors": "smoke_detector" in system_types,
        "co_detectors": "co_detector" in system_types,
        "fire_extinguishers": "fire_extinguisher" in system_types,
        "has_hot_tub": "hot_tub" in system_types,
        "has_fireplace": "fireplace" in system_types,
        "has_deck": "deck_structure" in system_types,
        "has_garage": False,  # Would need inspection to confirm
        "propane": "propane" in fuel_types,

        # These need physical inspection to verify
        "hot_tub_gfci": None,  # Unknown until inspected
        "deck_railings_compliant": None,  # Unknown until inspected
        "egress_windows_verified": None,  # Unknown until inspected
        "bedrooms": None,  # Not in MEP data, need property details

        # System counts
        "total_mep_systems": len(systems),
        "systems_unknown_condition": sum(1 for s in systems if s[1] == "unknown"),
    }

    return features


def run_audit(conn, property_filter=None, critical_only=False, active_only=True):
    """Run compliance audit across all (or filtered) properties."""
    engine = ComplianceEngine()
    cur = conn.cursor()

    # Get properties — default to active (Streamline-managed) only
    if property_filter:
        cur.execute(
            "SELECT id, name FROM properties WHERE name ILIKE %s ORDER BY name",
            (f"%{property_filter}%",),
        )
    elif active_only:
        cur.execute(
            "SELECT id, name FROM properties "
            "WHERE management_status = 'active' ORDER BY name"
        )
    else:
        cur.execute("SELECT id, name FROM properties ORDER BY name")

    properties = cur.fetchall()

    print(f"\n{'='*75}")
    print(f"  FORTRESS PRIME — RENTAL SAFETY COMPLIANCE AUDIT")
    print(f"  ComplianceEngine: {len(engine.requirements)} code requirements loaded")
    print(f"  Properties: {len(properties)}")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*75}\n")

    total_critical = 0
    total_inspections = 0
    results = []

    for prop_id, prop_name in properties:
        features = get_property_features(cur, prop_id, prop_name)
        report = engine.check_rental_safety(prop_name, features)

        # Also evaluate as a rental renovation project
        project_eval = engine.evaluate_project(
            project_type="renovation",
            is_rental=True,
            property_features=features,
        )

        total_critical += report["critical_failures"]
        total_inspections += report["needs_inspection"]

        status_icon = {
            "COMPLIANT": "PASS",
            "NEEDS_REVIEW": "REVIEW",
            "CRITICAL": "FAIL",
        }.get(report["overall_status"], "?")

        if critical_only and report["overall_status"] == "COMPLIANT":
            continue

        print(f"  {prop_name:<30} [{status_icon:>6}]  "
              f"checks={report['total_checks']}  "
              f"pass={report['passed']}  "
              f"critical={report['critical_failures']}  "
              f"inspect={report['needs_inspection']}")

        # Print details for non-passing items
        for check in report["checks"]:
            if check["status"] not in ("pass",):
                marker = "!!!" if check["status"] == "fail" else " ? "
                print(f"    {marker} {check['item']:<20} [{check['code']}] "
                      f"{check['detail'][:60]}")

        # Log to compliance_log
        for check in report["checks"]:
            if check["status"] in ("fail", "needs_inspection"):
                severity = "CRITICAL" if check["status"] == "fail" else "MEDIUM"
                try:
                    cur.execute("""
                        INSERT INTO engineering.compliance_log
                        (property_name, code_reference, issue_title,
                         description, severity, status, discipline,
                         assessed_by, assessed_at, ai_json)
                        VALUES (%s, %s, %s, %s, %s, 'open', 'general',
                                'ComplianceEngine v1', CURRENT_TIMESTAMP, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        prop_name,
                        check["code"],
                        check["item"],
                        check["detail"],
                        severity,
                        json.dumps({"source": "automated_audit", "features": features}),
                    ))
                except Exception:
                    conn.rollback()

        # Store applicable code requirements count
        report["applicable_requirements"] = project_eval["total_requirements"]
        results.append(report)
        print()

    conn.commit()

    # Summary
    print(f"{'='*75}")
    print(f"  AUDIT SUMMARY")
    print(f"{'='*75}")
    print(f"  Properties audited:     {len(results)}")
    print(f"  Total critical failures: {total_critical}")
    print(f"  Total needs inspection:  {total_inspections}")

    compliant = sum(1 for r in results if r["overall_status"] == "COMPLIANT")
    review = sum(1 for r in results if r["overall_status"] == "NEEDS_REVIEW")
    critical = sum(1 for r in results if r["overall_status"] == "CRITICAL")

    print(f"\n  Compliant:    {compliant:>3} properties")
    print(f"  Needs review: {review:>3} properties")
    print(f"  Critical:     {critical:>3} properties")

    if total_critical > 0:
        print(f"\n  ACTION REQUIRED: {total_critical} critical code violations detected.")
        print(f"  These items require immediate attention before next guest check-in.")

    if total_inspections > 0:
        print(f"\n  INSPECTIONS NEEDED: {total_inspections} items need physical verification.")
        print(f"  Schedule property inspections to confirm compliance status.")

    # Log summary to compliance_log
    try:
        cur.execute("""
            INSERT INTO engineering.compliance_log
            (property_name, code_reference, issue_title,
             description, severity, status, discipline,
             assessed_by, assessed_at, ai_json)
            VALUES ('PORTFOLIO', 'AUDIT-SUMMARY', 'Portfolio Compliance Audit',
                    %s, %s, 'open', 'general',
                    'ComplianceEngine v1', CURRENT_TIMESTAMP, %s)
        """, (
            f"Audited {len(results)} properties: {compliant} compliant, "
            f"{review} need review, {critical} critical. "
            f"{total_critical} critical failures, {total_inspections} inspections needed.",
            "CRITICAL" if critical > 0 else "MEDIUM" if review > 0 else "LOW",
            json.dumps({
                "audit_date": datetime.now(timezone.utc).isoformat(),
                "properties_audited": len(results),
                "compliant": compliant,
                "needs_review": review,
                "critical": critical,
                "total_critical_failures": total_critical,
                "total_inspections_needed": total_inspections,
            }),
        ))
        conn.commit()
    except Exception:
        conn.rollback()

    print(f"\n{'='*75}\n")
    return results


def main():
    conn = get_conn()

    prop_filter = None
    critical_only = "--critical-only" in sys.argv

    if "--property" in sys.argv:
        idx = sys.argv.index("--property")
        if idx + 1 < len(sys.argv):
            prop_filter = sys.argv[idx + 1]

    run_audit(conn, property_filter=prop_filter, critical_only=critical_only)
    conn.close()


if __name__ == "__main__":
    main()
