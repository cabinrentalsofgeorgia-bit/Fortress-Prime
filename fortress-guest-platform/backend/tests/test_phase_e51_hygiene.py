"""
Phase E.5.1 tests — PDF fixture hygiene.

Test groups:
  --- Regeneration script structure ---
  1.  regenerate_pdf_demos module imports without error
  2.  SCENARIOS list exists and has the expected two entries
  3.  main() function exists
  4.  _render_scenario() function exists
  5.  _owner_address_from_info() produces correct multi-line output
  6.  _owner_address_from_info() handles empty fields gracefully

  --- renderer: _build_pdf_bytes is a pure function ---
  7.  _build_pdf_bytes() is importable from statement_pdf
  8.  _build_pdf_bytes() accepts keyword arguments for all required fields
  9.  render_owner_statement_pdf() still works (regression guard)

  --- crog_output/ directory rules ---
  10. crog_output README.md exists and contains the DO NOT rule
  11. crog_output .gitignore exists and force-includes PDFs
  12. streamline_reference README.md exists
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"
_CROG_OUTPUT = _FIXTURES / "crog_output"
_SL_REF = _FIXTURES / "streamline_reference"


# ── 1–4. Regeneration script structure ───────────────────────────────────────

def test_regenerate_pdf_demos_imports():
    """Module must import without errors."""
    import backend.scripts.regenerate_pdf_demos  # noqa: F401


def test_scenarios_list_has_two_entries():
    from backend.scripts.regenerate_pdf_demos import SCENARIOS
    assert len(SCENARIOS) == 2, f"Expected 2 scenarios, got {len(SCENARIOS)}"
    stems = {s["filename_stem"] for s in SCENARIOS}
    assert "knight_cherokee_sunrise_2026_02" in stems
    assert "dutil_above_timberline_2026_01" in stems


def test_main_function_exists():
    from backend.scripts.regenerate_pdf_demos import main
    assert callable(main)
    assert inspect.iscoroutinefunction(main), "main() must be an async function"


def test_render_scenario_function_exists():
    from backend.scripts.regenerate_pdf_demos import _render_scenario
    assert callable(_render_scenario)
    assert inspect.iscoroutinefunction(_render_scenario)


# ── 5–6. _owner_address_from_info helper ─────────────────────────────────────

def test_owner_address_from_info_full():
    """E6.6: _owner_address_from_info returns single-line Streamline format."""
    from backend.scripts.regenerate_pdf_demos import _owner_address_from_info
    info = {
        "address1":    "PO Box 982",
        "address2":    {},          # Streamline returns {} for empty
        "city":        "Morganton",
        "state":       "GA",
        "zip":         "30560",
        "country_name": "US",
    }
    result = _owner_address_from_info(info)
    assert result == "PO Box 982 Morganton, GA 30560"
    assert "\n" not in result


def test_owner_address_from_info_empty_fields():
    from backend.scripts.regenerate_pdf_demos import _owner_address_from_info
    # All empty → should return ""
    info = {
        "address1": {},
        "city": {},
        "state": {},
        "zip": {},
    }
    result = _owner_address_from_info(info)
    assert result == ""


# ── 7–9. PDF renderer ─────────────────────────────────────────────────────────

def test_build_pdf_bytes_is_importable():
    from backend.services.statement_pdf import _build_pdf_bytes
    assert callable(_build_pdf_bytes)
    assert not inspect.iscoroutinefunction(_build_pdf_bytes), (
        "_build_pdf_bytes must be a plain (sync) function, not a coroutine"
    )


def test_build_pdf_bytes_signature_has_required_params():
    from backend.services.statement_pdf import _build_pdf_bytes
    sig = inspect.signature(_build_pdf_bytes)
    required = {
        "period_start", "period_end", "status",
        "opening_balance", "closing_balance",
        "total_revenue", "total_commission", "total_charges",
        "total_payments", "total_owner_income",
        "owner_name", "owner_address",
        "prop_display_name", "prop_address",
        "stmt", "ytd",
    }
    params = set(sig.parameters.keys())
    missing = required - params
    assert not missing, f"_build_pdf_bytes is missing parameters: {missing}"


@pytest.mark.asyncio
async def test_render_owner_statement_pdf_regression():
    """DB-backed render still works after the refactor."""
    from decimal import Decimal
    from datetime import date
    import uuid
    import psycopg2
    from backend.core.database import AsyncSessionLocal
    from backend.services.statement_pdf import render_owner_statement_pdf

    DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"
    uid = uuid.uuid4().hex[:8]
    prop_id = f"e51-regression-{uid}"

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (property_id) DO UPDATE SET owner_name=EXCLUDED.owner_name
        RETURNING id
    """, (prop_id, f"E51 Regression {uid}", f"e51-{uid}@test.com",
          f"acct_e51_{uid}", Decimal("0.3000"), "active"))
    opa_id = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO owner_balance_periods
            (owner_payout_account_id, period_start, period_end,
             opening_balance, closing_balance, total_revenue, total_commission,
             total_charges, total_payments, total_owner_income, status)
        VALUES (%s,%s,%s, 0, 0, 0, 0, 0, 0, 0, 'approved')
        RETURNING id
    """, (opa_id, date(2093, 5, 1), date(2093, 5, 31)))
    obp_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    async with AsyncSessionLocal() as db:
        pdf_bytes = await render_owner_statement_pdf(db, obp_id)

    assert pdf_bytes[:4] == b"%PDF"


# ── 10–12. Directory rules ────────────────────────────────────────────────────

def test_crog_output_readme_has_do_not_rule():
    readme = _CROG_OUTPUT / "README.md"
    assert readme.exists(), "crog_output/README.md must exist"
    text = readme.read_text()
    assert "MUST NOT" in text or "DO NOT" in text, (
        "README must contain an explicit prohibition on tests writing to this directory"
    )


def test_crog_output_gitignore_force_includes_pdfs():
    gitignore = _CROG_OUTPUT / ".gitignore"
    assert gitignore.exists(), "crog_output/.gitignore must exist"
    text = gitignore.read_text()
    assert "!*.pdf" in text, (
        ".gitignore must contain '!*.pdf' to force-include PDFs in git"
    )


def test_streamline_reference_readme_exists():
    readme = _SL_REF / "README.md"
    assert readme.exists(), "streamline_reference/README.md must exist"
    text = readme.read_text()
    assert "knight_cherokee_sunrise" in text.lower() or "cherokee" in text.lower()
    assert "dutil" in text.lower() or "timberline" in text.lower()
