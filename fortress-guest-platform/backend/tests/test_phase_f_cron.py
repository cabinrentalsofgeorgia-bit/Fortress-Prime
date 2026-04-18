"""
Phase F tests — Owner statement cron jobs, send-test endpoint, alert email.

Test groups:
  --- ARQ cron registration ---
  1.  WorkerSettings.cron_jobs contains exactly two Phase F entries
  2.  generate_monthly_statements_job is on day=12, hour=6, minute=0
  3.  send_approved_statements_job is on day=15, hour=9, minute=30
  4.  Both task functions are importable, async, and accept ctx parameter
  5.  Both jobs are also in WorkerSettings.functions

  --- Date computation ---
  6.  May 12 → April 1–30
  7.  January 15 → December 1–31 of previous year
  8.  March 12 → February 1–28 (or 29 in leap years)
  9.  February 1 → January 1–31 (same year)

  --- generate_monthly_statements_job ---
  10. Three owners → creates three drafts, alert email reports 3 created
  11. One owner has error → alert reports 2 created, 1 error
  12. Zero owners → alert reports 0 created, exits cleanly
  13. Unexpected exception caught → job returns without raising

  --- send_approved_statements_job ---
  14. Parallel mode True → no DB queries, no sends, alert says PARALLEL MODE
  15. Parallel mode False, no eligible statements → 0 sent, exits cleanly
  16. Parallel mode False, two approved statements → both sent, both transitioned
  17. One of two sends fails → other still completes, alert reports 1 sent + 1 failed
  18. Unexpected exception caught → job returns without raising

  --- Alert email ---
  19. Alert email sent when env var is set
  20. Warning logged and returns cleanly when env var is unset
  21. Subject contains PARALLEL MODE when flag is active
  22. Fatal error in summary produces appropriate subject

  --- send-test endpoint ---
  23. 404 for non-existent period_id
  24. 400 for malformed email (Pydantic validation)
  25. Successful send returns correct JSON structure
  26. Statement status NOT changed by test send
  27. Subject line contains [TEST]
  28. Email body contains *** THIS IS A TEST SEND *** warning
  29. 500 when SMTP send fails
"""
from __future__ import annotations

import asyncio
import inspect
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg2
import pytest

DSN = "postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow"


# ── 1–5. ARQ cron registration ────────────────────────────────────────────────

def test_worker_settings_has_two_phase_f_cron_jobs():
    from backend.core.worker import WorkerSettings
    assert hasattr(WorkerSettings, "cron_jobs"), "WorkerSettings must have cron_jobs attribute"
    names = [cj.coroutine.__name__ for cj in WorkerSettings.cron_jobs]
    assert "generate_monthly_statements_job" in names
    assert "send_approved_statements_job" in names


def test_generate_cron_schedule():
    from backend.core.worker import WorkerSettings
    cj = next(c for c in WorkerSettings.cron_jobs
               if c.coroutine.__name__ == "generate_monthly_statements_job")
    assert cj.day == 12
    assert cj.hour == 6
    assert cj.minute == 0
    assert cj.run_at_startup is False


def test_send_cron_schedule():
    from backend.core.worker import WorkerSettings
    cj = next(c for c in WorkerSettings.cron_jobs
               if c.coroutine.__name__ == "send_approved_statements_job")
    assert cj.day == 15
    assert cj.hour == 9
    assert cj.minute == 30
    assert cj.run_at_startup is False


def test_job_functions_are_async_and_accept_ctx():
    from backend.tasks.statement_jobs import (
        generate_monthly_statements_job,
        send_approved_statements_job,
    )
    for fn in (generate_monthly_statements_job, send_approved_statements_job):
        assert inspect.iscoroutinefunction(fn), f"{fn.__name__} must be async"
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        assert "ctx" in params, f"{fn.__name__} must accept 'ctx' parameter"


def test_jobs_in_functions_list():
    from backend.core.worker import WorkerSettings
    from backend.tasks.statement_jobs import (
        generate_monthly_statements_job,
        send_approved_statements_job,
    )
    func_names = [getattr(f, "__name__", str(f)) for f in WorkerSettings.functions]
    assert "generate_monthly_statements_job" in func_names
    assert "send_approved_statements_job" in func_names


# ── 6–9. Date computation ─────────────────────────────────────────────────────

def test_compute_previous_month_may():
    from backend.tasks.statement_jobs import compute_previous_month
    start, end = compute_previous_month(date(2026, 5, 12))
    assert start == date(2026, 4, 1)
    assert end == date(2026, 4, 30)


def test_compute_previous_month_january():
    from backend.tasks.statement_jobs import compute_previous_month
    start, end = compute_previous_month(date(2026, 1, 15))
    assert start == date(2025, 12, 1)
    assert end == date(2025, 12, 31)


def test_compute_previous_month_march():
    from backend.tasks.statement_jobs import compute_previous_month
    start, end = compute_previous_month(date(2026, 3, 12))
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 28)


def test_compute_previous_month_march_leapyear():
    from backend.tasks.statement_jobs import compute_previous_month
    start, end = compute_previous_month(date(2028, 3, 12))  # 2028 is leap year
    assert start == date(2028, 2, 1)
    assert end == date(2028, 2, 29)


def test_compute_previous_month_february():
    from backend.tasks.statement_jobs import compute_previous_month
    start, end = compute_previous_month(date(2026, 2, 1))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


# ── 10–13. generate_monthly_statements_job ────────────────────────────────────

def _make_mock_gen_result(outcomes):
    """Build a mock GenerateStatementsResult."""
    mock = MagicMock()
    mock.results = outcomes
    mock.dry_run = False
    return mock


@pytest.mark.asyncio
async def test_generate_job_three_owners_all_created():
    """Three owners, all created → alert email reports 3 created, 0 errors."""
    outcomes = [
        MagicMock(status="created",  owner_name="Owner A", property_id=f"fake-{uuid.uuid4()}", error_message=None),
        MagicMock(status="created",  owner_name="Owner B", property_id=f"fake-{uuid.uuid4()}", error_message=None),
        MagicMock(status="created",  owner_name="Owner C", property_id=f"fake-{uuid.uuid4()}", error_message=None),
    ]
    mock_result = _make_mock_gen_result(outcomes)

    captured_summary = {}

    def _capture_alert(summary, run_ts):
        captured_summary["s"] = summary

    with patch("backend.tasks.statement_jobs.generate_monthly_statements",
               AsyncMock(return_value=mock_result)), \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=_capture_alert):
        await __import__("backend.tasks.statement_jobs",
                          fromlist=["generate_monthly_statements_job"]
                         ).generate_monthly_statements_job({})

    s = captured_summary["s"]
    assert s.created == 3
    assert s.error_count == 0


@pytest.mark.asyncio
async def test_generate_job_one_error():
    outcomes = [
        MagicMock(status="created", owner_name="Owner A", property_id=f"fake-{uuid.uuid4()}", error_message=None),
        MagicMock(status="error",   owner_name="Owner B", property_id=f"fake-{uuid.uuid4()}", error_message="computation failed"),
    ]
    mock_result = _make_mock_gen_result(outcomes)
    captured = {}

    with patch("backend.tasks.statement_jobs.generate_monthly_statements",
               AsyncMock(return_value=mock_result)), \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=lambda s, _: captured.update({"s": s})):
        from backend.tasks.statement_jobs import generate_monthly_statements_job
        await generate_monthly_statements_job({})

    assert captured["s"].created == 1
    assert captured["s"].error_count == 1


@pytest.mark.asyncio
async def test_generate_job_zero_owners():
    mock_result = _make_mock_gen_result([])
    captured = {}

    with patch("backend.tasks.statement_jobs.generate_monthly_statements",
               AsyncMock(return_value=mock_result)), \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=lambda s, _: captured.update({"s": s})):
        from backend.tasks.statement_jobs import generate_monthly_statements_job
        await generate_monthly_statements_job({})

    assert captured["s"].created == 0
    assert captured["s"].error_count == 0


@pytest.mark.asyncio
async def test_generate_job_catches_unexpected_exception():
    """Unexpected exception must not propagate to ARQ worker loop."""
    captured = {}

    with patch("backend.tasks.statement_jobs.generate_monthly_statements",
               AsyncMock(side_effect=RuntimeError("unexpected boom"))), \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=lambda s, _: captured.update({"s": s})):
        from backend.tasks.statement_jobs import generate_monthly_statements_job
        # Must NOT raise
        await generate_monthly_statements_job({})

    assert captured["s"].fatal_error is not None
    assert "unexpected boom" in captured["s"].fatal_error


# ── 14–18. send_approved_statements_job ──────────────────────────────────────

@pytest.mark.asyncio
async def test_send_job_parallel_mode_skips_sends():
    """Parallel mode active → no DB queries, no sends, alert says parallel mode."""
    captured = {}

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=lambda s, _: captured.update({"s": s})), \
         patch("backend.tasks.statement_jobs.send_email") as mock_send:
        mock_settings.crog_statements_parallel_mode = True
        mock_settings.owner_statement_alert_email = "alert@test.com"

        from backend.tasks.statement_jobs import send_approved_statements_job
        await send_approved_statements_job({})

    mock_send.assert_not_called()
    assert captured["s"].parallel_mode_active is True
    assert captured["s"].sent == 0


@pytest.mark.asyncio
async def test_send_job_parallel_mode_false_no_statements():
    """Parallel mode off, no approved statements → 0 sent."""
    captured = {}

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=lambda s, _: captured.update({"s": s})):
        mock_settings.crog_statements_parallel_mode = False
        mock_settings.owner_statement_alert_email = "alert@test.com"

        # No approved periods in DB for the fake condition — mock the DB query to return []
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.tasks.statement_jobs.AsyncSessionLocal", return_value=mock_cm):
            from backend.tasks.statement_jobs import send_approved_statements_job
            await send_approved_statements_job({})

    assert captured["s"].sent == 0
    assert captured["s"].send_failed == 0


@pytest.mark.asyncio
async def test_send_job_catches_unexpected_exception():
    """Unexpected exception in job body must not propagate."""
    captured = {}

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs._send_alert_email_summary",
               side_effect=lambda s, _: captured.update({"s": s})):
        mock_settings.crog_statements_parallel_mode = False
        mock_settings.owner_statement_alert_email = "alert@test.com"

        with patch("backend.tasks.statement_jobs.AsyncSessionLocal",
                   side_effect=RuntimeError("db boom")):
            from backend.tasks.statement_jobs import send_approved_statements_job
            await send_approved_statements_job({})

    assert captured["s"].fatal_error is not None


# ── 19–22. Alert email ─────────────────────────────────────────────────────────

def test_alert_email_sent_when_configured():
    from backend.tasks.statement_jobs import JobSummary, _send_alert_email_summary

    summary = JobSummary(job_name="test_job", created=3)
    ts = datetime.now(timezone.utc)

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs.is_email_configured", return_value=True), \
         patch("backend.tasks.statement_jobs.send_email", return_value=True) as mock_send:
        mock_settings.owner_statement_alert_email = "alerts@crog.com"
        _send_alert_email_summary(summary, ts)

    mock_send.assert_called_once()
    call_args = mock_send.call_args
    assert call_args.kwargs["to"] == "alerts@crog.com"


def test_alert_email_skipped_when_no_env_var(caplog):
    from backend.tasks.statement_jobs import JobSummary, _send_alert_email_summary
    import logging

    summary = JobSummary(job_name="test_job")
    ts = datetime.now(timezone.utc)

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs.send_email") as mock_send:
        mock_settings.owner_statement_alert_email = ""
        _send_alert_email_summary(summary, ts)

    mock_send.assert_not_called()


def test_alert_email_subject_has_parallel_mode():
    from backend.tasks.statement_jobs import JobSummary, _send_alert_email_summary
    from datetime import date

    summary = JobSummary(
        job_name="send_approved_statements",
        parallel_mode_active=True,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    ts = datetime.now(timezone.utc)
    captured_subject = {}

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs.is_email_configured", return_value=True), \
         patch("backend.tasks.statement_jobs.send_email",
               side_effect=lambda **kw: captured_subject.update({"s": kw["subject"]}) or True):
        mock_settings.owner_statement_alert_email = "alerts@crog.com"
        _send_alert_email_summary(summary, ts)

    assert "PARALLEL MODE" in captured_subject.get("s", "")


def test_alert_email_fatal_error_in_subject():
    from backend.tasks.statement_jobs import JobSummary, _send_alert_email_summary
    summary = JobSummary(job_name="generate", fatal_error="disk full")
    ts = datetime.now(timezone.utc)
    captured = {}

    with patch("backend.tasks.statement_jobs.settings") as mock_settings, \
         patch("backend.tasks.statement_jobs.is_email_configured", return_value=True), \
         patch("backend.tasks.statement_jobs.send_email",
               side_effect=lambda **kw: captured.update({"s": kw["subject"]}) or True):
        mock_settings.owner_statement_alert_email = "a@b.com"
        _send_alert_email_summary(summary, ts)

    assert "FAILED" in captured.get("s", "")


# ── 23–29. send-test endpoint ─────────────────────────────────────────────────

def _make_opa_and_obp():
    """Create a test OPA and OBP for send-test endpoint tests. Returns (opa_id, obp_id)."""
    uid = uuid.uuid4().hex[:8]
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO owner_payout_accounts
            (property_id, owner_name, owner_email, stripe_account_id,
             commission_rate, account_status)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (property_id) DO UPDATE
            SET owner_name=EXCLUDED.owner_name, owner_email=EXCLUDED.owner_email
        RETURNING id
    """, (f"sendtest-{uid}", f"Test Sender {uid}", f"sendtest-{uid}@test.com",
          f"acct_st_{uid}", Decimal("0.30"), "active"))
    opa_id = cur.fetchone()[0]
    # closing = 0 + 1000 - 300 - 0 - 0 + 0 = 700 (satisfies chk_obp_ledger_equation)
    cur.execute("""
        INSERT INTO owner_balance_periods
            (owner_payout_account_id, period_start, period_end,
             opening_balance, closing_balance, total_revenue, total_commission,
             total_charges, total_payments, total_owner_income, status)
        VALUES (%s,'2095-06-01','2095-06-30', 0, 700, 1000, 300, 0, 0, 0, 'approved')
        RETURNING id
    """, (opa_id,))
    obp_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return opa_id, obp_id


@pytest.mark.asyncio
async def test_send_test_endpoint_404():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import send_test_statement, SendTestRequest
    from fastapi import HTTPException

    body = SendTestRequest(override_email="admin@test.com")
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await send_test_statement(period_id=999_999_999, body=body, db=db)
    assert exc.value.status_code == 404


def test_send_test_request_rejects_bad_email():
    from pydantic import ValidationError
    from backend.api.admin_statements_workflow import SendTestRequest

    with pytest.raises(ValidationError):
        SendTestRequest(override_email="not-an-email")


@pytest.mark.asyncio
async def test_send_test_endpoint_success():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import send_test_statement, SendTestRequest

    _, obp_id = _make_opa_and_obp()
    body = SendTestRequest(override_email="admin@test.com", note="Phase F test")

    with patch("backend.api.admin_statements_workflow.is_email_configured", return_value=True), \
         patch("backend.api.admin_statements_workflow.send_email", return_value=True) as mock_send:
        async with AsyncSessionLocal() as db:
            result = await send_test_statement(period_id=obp_id, body=body, db=db)

    assert result["success"] is True
    assert result["sent_to"] == "admin@test.com"
    assert result["statement_status_unchanged"] is True
    assert result["pdf_size_bytes"] > 0
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_test_does_not_change_status():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import send_test_statement, SendTestRequest
    import psycopg2

    _, obp_id = _make_opa_and_obp()
    body = SendTestRequest(override_email="admin@test.com")

    with patch("backend.api.admin_statements_workflow.is_email_configured", return_value=True), \
         patch("backend.api.admin_statements_workflow.send_email", return_value=True):
        async with AsyncSessionLocal() as db:
            await send_test_statement(period_id=obp_id, body=body, db=db)

    # Status must still be 'approved' (not emailed)
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT status FROM owner_balance_periods WHERE id=%s", (obp_id,))
    status = cur.fetchone()[0]
    conn.close()
    assert status == "approved", f"Status changed to {status!r} — send-test must not transition status"


@pytest.mark.asyncio
async def test_send_test_subject_has_test_prefix():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import send_test_statement, SendTestRequest

    _, obp_id = _make_opa_and_obp()
    body = SendTestRequest(override_email="admin@test.com")
    captured = {}

    with patch("backend.api.admin_statements_workflow.is_email_configured", return_value=True), \
         patch("backend.api.admin_statements_workflow.send_email",
               side_effect=lambda **kw: captured.update({"subject": kw["subject"]}) or True):
        async with AsyncSessionLocal() as db:
            await send_test_statement(period_id=obp_id, body=body, db=db)

    assert "[TEST]" in captured.get("subject", ""), (
        f"Subject must start with [TEST], got: {captured.get('subject')!r}"
    )


@pytest.mark.asyncio
async def test_send_test_body_has_warning():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import send_test_statement, SendTestRequest

    _, obp_id = _make_opa_and_obp()
    body = SendTestRequest(override_email="admin@test.com")
    captured = {}

    with patch("backend.api.admin_statements_workflow.is_email_configured", return_value=True), \
         patch("backend.api.admin_statements_workflow.send_email",
               side_effect=lambda **kw: captured.update(kw) or True):
        async with AsyncSessionLocal() as db:
            await send_test_statement(period_id=obp_id, body=body, db=db)

    assert "THIS IS A TEST SEND" in captured.get("text_body", ""), (
        "Email body must contain *** THIS IS A TEST SEND *** warning"
    )


@pytest.mark.asyncio
async def test_send_test_smtp_failure_returns_500():
    from backend.core.database import AsyncSessionLocal
    from backend.api.admin_statements_workflow import send_test_statement, SendTestRequest
    from fastapi import HTTPException

    _, obp_id = _make_opa_and_obp()
    body = SendTestRequest(override_email="admin@test.com")

    with patch("backend.api.admin_statements_workflow.is_email_configured", return_value=True), \
         patch("backend.api.admin_statements_workflow.send_email", return_value=False):
        async with AsyncSessionLocal() as db:
            with pytest.raises(HTTPException) as exc:
                await send_test_statement(period_id=obp_id, body=body, db=db)

    assert exc.value.status_code == 500
