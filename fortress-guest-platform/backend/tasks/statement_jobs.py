"""
Phase F — Owner Statement ARQ cron jobs and alert email.

Two cron jobs:
  generate_monthly_statements_job  — fires 12th of month at 06:00 ET
      Generates draft OwnerBalancePeriod rows for the previous calendar month.

  send_approved_statements_job     — fires 15th of month at 09:30 ET
      Emails all approved-but-not-yet-emailed statements to owners.
      Gated by CROG_STATEMENTS_PARALLEL_MODE (default True = emails suppressed
      until Phase G validation completes).

Both jobs:
  - Open their own AsyncSessionLocal sessions (not shared with the worker ctx)
  - Catch all exceptions internally so no exception propagates to the ARQ loop
  - Send a run-summary to OWNER_STATEMENT_ALERT_EMAIL after each run
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import structlog
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.owner_balance_period import OwnerBalancePeriod
from backend.models.owner_payout import OwnerPayoutAccount
from backend.models.property import Property
from backend.services.email_service import is_email_configured, send_email
from backend.services.statement_pdf import render_owner_statement_pdf
from backend.services.statement_workflow import (
    generate_monthly_statements,
    mark_statement_emailed,
)

logger = structlog.get_logger(service="statement_jobs")
_UTC = timezone.utc


# ── Date helpers ──────────────────────────────────────────────────────────────

def compute_previous_month(today: date) -> tuple[date, date]:
    """
    Return (period_start, period_end) for the calendar month preceding today.

    Examples:
      today=2026-05-12  →  (2026-04-01, 2026-04-30)
      today=2026-01-15  →  (2025-12-01, 2025-12-31)
      today=2026-03-12  →  (2026-02-01, 2026-02-28)  [or Feb 29 in leap year]
    """
    first_of_this_month = today.replace(day=1)
    period_end = first_of_this_month - timedelta(days=1)      # last day of prev month
    period_start = period_end.replace(day=1)                  # first day of prev month
    return period_start, period_end


# ── Alert email ───────────────────────────────────────────────────────────────

@dataclass
class JobSummary:
    job_name: str
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    parallel_mode_active: bool = False
    # Generation counts
    created: int = 0
    updated: int = 0
    skipped_locked: int = 0
    skipped_not_renting: int = 0
    skipped_not_enrolled: int = 0
    error_count: int = 0
    # Send counts
    sent: int = 0
    send_failed: int = 0
    # Per-owner outcome rows: [(owner_name, property_name, status, detail)]
    outcomes: list[tuple[str, str, str, str]] = field(default_factory=list)
    # Unexpected exception (if the job itself crashed)
    fatal_error: Optional[str] = None


def _send_alert_email_summary(
    summary: JobSummary,
    run_timestamp: datetime,
) -> None:
    """
    Send the post-run alert email to OWNER_STATEMENT_ALERT_EMAIL.
    Logs a loud error if the env var is unset (does not raise).
    """
    alert_addr = settings.owner_statement_alert_email
    if not alert_addr:
        logger.error(
            "owner_statement_alert_email_not_configured",
            job=summary.job_name,
            message="OWNER_STATEMENT_ALERT_EMAIL not configured — alert email cannot be sent",
        )
        return

    if not is_email_configured():
        logger.warning("smtp_not_configured_skipping_alert", job=summary.job_name)
        return

    period_str = ""
    if summary.period_start and summary.period_end:
        period_str = (
            f"{summary.period_start.strftime('%B %Y')} "
            f"({summary.period_start} to {summary.period_end})"
        )

    # Subject
    parallel_prefix = "PARALLEL MODE " if summary.parallel_mode_active else ""
    if summary.job_name == "generate_monthly_statements":
        stats = f"{summary.created} created, {summary.error_count} errors"
    else:
        stats = f"{summary.sent} sent, {summary.send_failed} failed"
    subject = (
        f"[Crog-VRS] {parallel_prefix}{summary.job_name} "
        f"for {period_str} — {stats}"
    )
    if summary.fatal_error:
        subject = f"[Crog-VRS] FAILED {summary.job_name} — see details"

    # Build body rows
    outcome_rows_txt = "\n".join(
        f"  {owner:30s}  {prop:25s}  {status:15s}  {detail}"
        for owner, prop, status, detail in summary.outcomes[:50]
    )
    if len(summary.outcomes) > 50:
        outcome_rows_txt += f"\n  ... and {len(summary.outcomes) - 50} more"

    parallel_notice = (
        "\n*** PARALLEL MODE ACTIVE ***\n"
        "Statements were generated for internal comparison only.\n"
        "Real owner emails were NOT sent.\n"
        "Set CROG_STATEMENTS_PARALLEL_MODE=false to enable real sends.\n"
        if summary.parallel_mode_active else ""
    )

    text_body = textwrap.dedent(f"""
        Crog-VRS Owner Statement Job Run
        =================================
        Job:        {summary.job_name}
        Period:     {period_str or 'N/A'}
        Run time:   {run_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
        {parallel_notice}
        {"FATAL ERROR: " + summary.fatal_error if summary.fatal_error else ""}

        Results
        -------
        Created/drafted:   {summary.created}
        Updated drafts:    {summary.updated}
        Skipped (locked):  {summary.skipped_locked}
        Skipped (no rent): {summary.skipped_not_renting}
        Skipped (no enrl): {summary.skipped_not_enrolled}
        Errors:            {summary.error_count}
        Emails sent:       {summary.sent}
        Emails failed:     {summary.send_failed}

        Per-owner outcomes
        ------------------
        {outcome_rows_txt or '  (none)'}

        Review the statement queue at:
          GET /api/admin/payouts/statements?status=pending_approval
          GET /api/admin/payouts/statements?status=approved
    """).strip()

    html_body = (
        f"<pre>{text_body}</pre>"
    )

    ok = send_email(
        to=alert_addr,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    if ok:
        logger.info("alert_email_sent", job=summary.job_name, to=alert_addr)
    else:
        logger.error("alert_email_failed", job=summary.job_name, to=alert_addr)


# ── F2: Statement generation cron job ────────────────────────────────────────

async def generate_monthly_statements_job(ctx: dict[str, Any]) -> None:
    """
    ARQ cron job — runs 12th of each month at 06:00 AM Eastern.

    Generates draft OwnerBalancePeriod rows for the previous calendar month
    by calling generate_monthly_statements(). Unconditionally runs regardless
    of CROG_STATEMENTS_PARALLEL_MODE — the parallel-mode flag only suppresses
    email sends, not statement generation.

    Never raises: all exceptions are caught, logged, and reported via alert email.
    """
    run_ts = datetime.now(_UTC)
    today = date.today()
    period_start, period_end = compute_previous_month(today)

    log = logger.bind(
        job="generate_monthly_statements",
        period_start=str(period_start),
        period_end=str(period_end),
    )
    log.info("generate_monthly_statements_job_start")

    summary = JobSummary(
        job_name="generate_monthly_statements",
        period_start=period_start,
        period_end=period_end,
        parallel_mode_active=settings.crog_statements_parallel_mode,
    )

    try:
        async with AsyncSessionLocal() as db:
            result = await generate_monthly_statements(
                db,
                period_start=period_start,
                period_end=period_end,
                dry_run=False,
            )

        for outcome in result.results:
            # Fetch property name for the alert summary
            prop_name = outcome.property_id or ""
            if outcome.property_id:
                try:
                    import uuid as _uuid
                    prop_uuid = _uuid.UUID(outcome.property_id)
                    async with AsyncSessionLocal() as db2:
                        prop = await db2.get(Property, prop_uuid)
                        if prop:
                            prop_name = prop.name
                except (ValueError, Exception):
                    pass

            summary.outcomes.append((
                outcome.owner_name or "(unknown)",
                prop_name[:25],
                outcome.status,
                outcome.error_message or "",
            ))

            if outcome.status == "created":
                summary.created += 1
            elif outcome.status == "updated":
                summary.updated += 1
            elif outcome.status == "skipped_locked":
                summary.skipped_locked += 1
            elif outcome.status == "skipped_not_renting":
                summary.skipped_not_renting += 1
            elif outcome.status == "skipped_not_enrolled":
                summary.skipped_not_enrolled += 1
            elif outcome.status == "error":
                summary.error_count += 1

        log.info(
            "generate_monthly_statements_job_complete",
            created=summary.created,
            updated=summary.updated,
            errors=summary.error_count,
        )

    except Exception as exc:
        summary.fatal_error = str(exc)[:500]
        log.error("generate_monthly_statements_job_crashed", error=str(exc))

    finally:
        _send_alert_email_summary(summary, run_ts)


# ── F3: Statement send cron job ───────────────────────────────────────────────

async def send_approved_statements_job(ctx: dict[str, Any]) -> None:
    """
    ARQ cron job — runs 15th of each month at 09:30 AM Eastern.

    Emails all OwnerBalancePeriod rows where status='approved' and
    emailed_at IS NULL, attaching the rendered PDF statement.

    Gated by CROG_STATEMENTS_PARALLEL_MODE:
      True  → logs and exits without querying DB or sending emails.
      False → sends real emails to real owner email addresses.

    Never raises: all exceptions are caught and logged.
    """
    run_ts = datetime.now(_UTC)
    today = date.today()
    period_start, period_end = compute_previous_month(today)

    log = logger.bind(job="send_approved_statements")
    log.info("send_approved_statements_job_start")

    summary = JobSummary(
        job_name="send_approved_statements",
        period_start=period_start,
        period_end=period_end,
        parallel_mode_active=settings.crog_statements_parallel_mode,
    )

    try:
        if settings.crog_statements_parallel_mode:
            log.info(
                "parallel_mode_active_skipping_sends",
                message="Parallel mode active — real email sends suppressed",
            )
            _send_alert_email_summary(summary, run_ts)
            return

        # Find all approved, un-emailed statements
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(OwnerBalancePeriod)
                .where(
                    OwnerBalancePeriod.status == "approved",
                    OwnerBalancePeriod.emailed_at.is_(None),
                )
                .order_by(OwnerBalancePeriod.id)
            )
            periods = result.scalars().all()

        if not periods:
            log.info("no_approved_statements_to_send")
            _send_alert_email_summary(summary, run_ts)
            return

        for period in periods:
            owner_name = "(unknown)"
            owner_email = None
            prop_name = "(unknown property)"

            try:
                # Load OPA + property for owner email and names
                async with AsyncSessionLocal() as db:
                    opa = await db.get(OwnerPayoutAccount, period.owner_payout_account_id)
                    if opa is None:
                        raise ValueError(f"OPA {period.owner_payout_account_id} not found")
                    owner_name = opa.owner_name or "(unknown)"
                    owner_email = opa.owner_email
                    if not owner_email:
                        raise ValueError(f"Owner {owner_name} has no email address")

                    prop_name = opa.property_id
                    try:
                        import uuid as _uuid
                        prop_uuid = _uuid.UUID(opa.property_id)
                        prop = await db.get(Property, prop_uuid)
                        if prop:
                            prop_name = prop.name
                    except ValueError:
                        pass

                # Render PDF
                async with AsyncSessionLocal() as db:
                    pdf_bytes = await render_owner_statement_pdf(db, period.id)

                # Build filename: owner_statement_{last}_{prop_short}_{YYYY-MM}.pdf
                last_name = (owner_name.split()[0] if owner_name.split() else "owner").lower()
                last_name = re.sub(r"[^a-z0-9]+", "_", last_name)[:20]
                prop_short = re.sub(r"[^a-z0-9]+", "_", prop_name.lower())[:20]
                period_str = period.period_start.strftime("%Y-%m")
                filename = f"owner_statement_{last_name}_{prop_short}_{period_str}.pdf"

                month_year = period.period_start.strftime("%B %Y")
                subject = f"Your statement for {month_year} — Cabin Rentals of Georgia"

                text_body = (
                    f"Hello {owner_name},\n\n"
                    f"Your owner statement for {month_year} is attached.\n\n"
                    f"Please review and contact us if you have any questions.\n\n"
                    f"Cabin Rentals of Georgia\n"
                    f"Blue Ridge, GA"
                )
                html_body = (
                    f"<p>Hello {owner_name},</p>"
                    f"<p>Your owner statement for <strong>{month_year}</strong> is attached.</p>"
                    f"<p>Please review and contact us if you have any questions.</p>"
                    f"<p>Cabin Rentals of Georgia<br/>Blue Ridge, GA</p>"
                )

                ok = send_email(
                    to=owner_email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    attachments=[{
                        "filename": filename,
                        "content": pdf_bytes,
                        "mime_type": "application/pdf",
                    }],
                )

                if ok:
                    # Transition statement to emailed
                    async with AsyncSessionLocal() as db:
                        await mark_statement_emailed(db, period.id)
                    summary.sent += 1
                    summary.outcomes.append((
                        owner_name, prop_name[:25], "sent", f"→ {owner_email}"
                    ))
                    log.info(
                        "statement_sent",
                        period_id=period.id,
                        owner=owner_name,
                        to=owner_email,
                    )
                else:
                    summary.send_failed += 1
                    summary.outcomes.append((
                        owner_name, prop_name[:25], "send_failed", "SMTP returned False"
                    ))
                    log.error(
                        "statement_send_failed",
                        period_id=period.id,
                        owner=owner_name,
                    )

            except Exception as exc:
                summary.send_failed += 1
                err_msg = str(exc)[:120]
                summary.outcomes.append((
                    owner_name, prop_name[:25], "error", err_msg
                ))
                log.error(
                    "statement_send_exception",
                    period_id=period.id,
                    owner=owner_name,
                    error=err_msg,
                )
                # Continue processing remaining statements — one failure does not block others

        log.info(
            "send_approved_statements_job_complete",
            sent=summary.sent,
            failed=summary.send_failed,
        )

    except Exception as exc:
        summary.fatal_error = str(exc)[:500]
        log.error("send_approved_statements_job_crashed", error=str(exc))

    finally:
        _send_alert_email_summary(summary, run_ts)
