"""
ARQ worker entrypoints for the Fortress asynchronous engine.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import pickle
import traceback
from typing import Any

import structlog
from sqlalchemy import and_, or_, select

from backend.core.config import settings
from backend.core.council_stream import create_council_redis, publish_council_event
from backend.core.database import AsyncSessionLocal
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.core.queue import create_arq_pool, get_arq_redis_settings
from backend.models.async_job import AsyncJobRun
from arq.cron import cron as arq_cron
import pytz as _pytz
from backend.tasks.statement_jobs import (
    generate_monthly_statements_job,
    send_approved_statements_job,
)
from backend.services.async_jobs import (
    count_jobs_by_status,
    enqueue_async_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    utcnow,
)
from backend.services.airdna_client import AirDNASyncJobPayload, run_airdna_sync
from backend.services.acquisition_foia import FoiaIngestJobPayload, run_fannin_foia_ingest
from backend.services.acquisition_ingestion import AcquisitionIngestionRequest, run_acquisition_ingestion_cycle
from backend.services.scout_action_router import research_scout_action_router
from backend.services.research_scout import ResearchScoutService
from backend.services.seo_deploy_consumer import SEODeployWorker
from backend.services.seo_grading_service import SEOGradingWorker
from backend.services.reconciliation_janitor import reconciliation_janitor
from backend.services.seo_shadow_observer import observe_semrush_parity
from backend.services.seo_rewrite_swarm import SEORewriteSwarmWorker
from backend.services.worker_hardening import enforce_sovereign_boundary
from backend.tasks.legacy_refactor_tasks import refactor_legacy_html_task
from backend.tasks.media_tasks import ingest_property_media
from backend.vrs.application.rule_engine import RuleEngine
from backend.vrs.domain.automations import StreamlineEventPayload, VRSRuleEngine
from backend.vrs.infrastructure.seo_event_bus import create_seo_event_redis

logger = structlog.get_logger(service="arq_worker")
boot_logger = logging.getLogger("arq.worker")
APP_ROOT = Path(__file__).resolve().parents[2]
research_scout_service = ResearchScoutService()
SEO_CONSUMER_SPECS = (
    ("seo_grading_worker", "seo_grading_task", "seo_grading_task", SEOGradingWorker, "SEO_GRADING_CONSUMER_ENABLED"),
    ("seo_rewrite_worker", "seo_rewrite_task", "seo_rewrite_task", SEORewriteSwarmWorker, "SEO_REWRITE_CONSUMER_ENABLED"),
    ("seo_deploy_worker", "seo_deploy_task", "seo_deploy_task", SEODeployWorker, "SEO_DEPLOY_CONSUMER_ENABLED"),
)
REQUIRED_ARQ_FUNCTION_NAMES = (
    "process_streamline_event_job",
    "run_concierge_shadow_draft_job",
    "run_hunter_queue_sweep_job",
    "run_hunter_execute_job",
    "run_hunter_recovery_draft_job",
)
WATCHDOG_OBSERVED_JOB_NAMES = (
    "process_streamline_event",
    "concierge_shadow_draft_cycle",
    "hunter_queue_sweep",
    "hunter_execute",
    "hunter_recovery_draft",
)


def _log_background_task_result(task_name: str, task: asyncio.Task[Any]) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        boot_logger.info("SEO consumer task cancelled: %s", task_name)
        return
    if exc is not None:
        boot_logger.error("FATAL: %s crashed", task_name)
        boot_logger.error("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    else:
        boot_logger.warning("SEO consumer task exited cleanly: %s", task_name)


def _enabled_seo_consumer_specs() -> tuple[tuple[str, str, str, type[Any], str], ...]:
    def _env_flag_enabled(env_var: str) -> bool:
        raw = os.getenv(env_var, "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    return tuple(spec for spec in SEO_CONSUMER_SPECS if _env_flag_enabled(spec[4]))


def _registered_worker_function_names() -> tuple[str, ...]:
    seen: list[str] = []
    for fn in WorkerSettings.functions:
        name = getattr(fn, "__name__", "").strip()
        if name:
            seen.append(name)
    return tuple(seen)


def _validate_worker_registry() -> None:
    names = _registered_worker_function_names()
    missing = sorted(set(REQUIRED_ARQ_FUNCTION_NAMES) - set(names))
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if missing or duplicates:
        logger.error(
            "arq_worker_registry_invalid",
            missing=missing,
            duplicates=duplicates,
            registered=list(names),
        )
        raise RuntimeError(
            f"ARQ worker registry invalid: missing={missing or 'none'} duplicates={duplicates or 'none'}"
        )
    logger.info("arq_worker_registry_validated", required=list(REQUIRED_ARQ_FUNCTION_NAMES))


def _timestamp_ms_to_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)


def _normalize_arq_result_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"value": str(value)}


async def _reconcile_jobs_from_arq_results(db, jobs: list[AsyncJobRun], redis) -> int:
    reconciled = 0
    if not jobs:
        return reconciled

    from uuid import UUID

    from backend.services.hunter_service import mark_hunter_candidate_failed, mark_hunter_recovery_op_retry

    for job in jobs:
        job_id = str(job.arq_job_id or job.id)
        raw_result = await redis.get(f"arq:result:{job_id}")
        if not raw_result:
            continue
        try:
            result_data = pickle.loads(raw_result)
        except Exception as exc:
            logger.warning(
                "async_job_watchdog_result_decode_failed",
                job_id=job_id,
                job_name=job.job_name,
                error=str(exc)[:400],
            )
            continue

        attempts = max(1, int(result_data.get("t") or job.attempts or 0))
        started_at = _timestamp_ms_to_utc(result_data.get("st"))
        finished_at = _timestamp_ms_to_utc(result_data.get("ft")) or utcnow()
        if started_at is not None and job.started_at is None:
            job.started_at = started_at

        if bool(result_data.get("s")):
            job.status = "succeeded"
            job.result_json = _normalize_arq_result_payload(result_data.get("r"))
            job.error_text = None
        else:
            if job.job_name == "hunter_execute":
                session_fp = str((job.payload_json or {}).get("session_fp") or "").strip().lower()
                if session_fp:
                    await mark_hunter_candidate_failed(db, session_fp=session_fp, error_text=str(result_data.get("r")))
            if job.job_name == "hunter_recovery_draft":
                recovery_op_id = str((job.payload_json or {}).get("recovery_op_id") or "").strip()
                if recovery_op_id:
                    try:
                        await mark_hunter_recovery_op_retry(
                            db,
                            recovery_op_id=UUID(recovery_op_id),
                            request_id=job_id,
                            error_text=str(result_data.get("r")),
                        )
                    except Exception:
                        logger.warning(
                            "hunter_recovery_retry_mark_failed",
                            job_id=job_id,
                            recovery_op_id=recovery_op_id,
                        )
            job.status = "failed"
            job.result_json = {}
            job.error_text = str(result_data.get("r"))[:4000]

        job.attempts = attempts
        job.finished_at = finished_at
        reconciled += 1

    if reconciled:
        await db.commit()
    return reconciled


async def _load_stale_async_jobs(db) -> list[AsyncJobRun]:
    current_time = utcnow()
    queued_cutoff = current_time - timedelta(seconds=max(60, int(settings.async_job_stale_queued_seconds)))
    running_cutoff = current_time - timedelta(seconds=max(120, int(settings.async_job_stale_running_seconds)))

    stmt = (
        select(AsyncJobRun)
        .where(AsyncJobRun.job_name.in_(WATCHDOG_OBSERVED_JOB_NAMES))
        .where(
            or_(
                and_(
                    AsyncJobRun.status == "queued",
                    AsyncJobRun.created_at <= queued_cutoff,
                ),
                and_(
                    AsyncJobRun.status == "running",
                    AsyncJobRun.started_at.is_not(None),
                    AsyncJobRun.started_at <= running_cutoff,
                ),
            )
        )
        .order_by(AsyncJobRun.created_at.asc())
        .limit(50)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _repair_stale_async_jobs(db, jobs: list[AsyncJobRun]) -> int:
    repaired = 0
    if not jobs:
        return repaired

    from uuid import UUID

    from backend.services.hunter_service import mark_hunter_candidate_failed, mark_hunter_recovery_op_retry

    for job in jobs:
        if job.job_name != "hunter_execute":
            if job.job_name != "hunter_recovery_draft":
                continue
            recovery_op_id = str((job.payload_json or {}).get("recovery_op_id") or "").strip()
            if not recovery_op_id:
                continue
            reason = f"watchdog_recovered_stale_{job.status}"
            try:
                await mark_hunter_recovery_op_retry(
                    db,
                    recovery_op_id=UUID(recovery_op_id),
                    request_id=str(job.id),
                    error_text=reason,
                )
            except Exception:
                logger.warning(
                    "hunter_recovery_watchdog_mark_failed",
                    job_id=str(job.id),
                    recovery_op_id=recovery_op_id,
                )
            await mark_job_failed(db, job, reason, attempts=max(1, int(job.attempts or 0)))
            repaired += 1
            continue
        session_fp = str((job.payload_json or {}).get("session_fp") or "").strip().lower()
        if not session_fp:
            continue
        reason = f"watchdog_recovered_stale_{job.status}"
        await mark_hunter_candidate_failed(db, session_fp=session_fp, error_text=reason)
        await mark_job_failed(db, job, reason, attempts=max(1, int(job.attempts or 0)))
        repaired += 1
    return repaired


async def _run_async_job_watchdog_once() -> None:
    async with AsyncSessionLocal() as db:
        pool = await create_arq_pool()
        try:
            stale_jobs = await _load_stale_async_jobs(db)
            if not stale_jobs:
                return
            reconciled = await _reconcile_jobs_from_arq_results(db, stale_jobs, pool)
            if reconciled:
                logger.info("async_job_watchdog_reconciled_results", reconciled_count=reconciled)
                stale_jobs = await _load_stale_async_jobs(db)
                if not stale_jobs:
                    return
            logger.error(
                "async_job_watchdog_stale_jobs_detected",
                count=len(stale_jobs),
                jobs=[
                    {
                        "id": str(job.id),
                        "job_name": job.job_name,
                        "status": job.status,
                        "request_id": job.request_id,
                    }
                    for job in stale_jobs
                ],
            )
            repaired = await _repair_stale_async_jobs(db, stale_jobs)
            logger.warning(
                "async_job_watchdog_completed",
                stale_count=len(stale_jobs),
                repaired_count=repaired,
            )
        finally:
            await pool.aclose()


async def _async_job_watchdog_loop() -> None:
    interval = max(30, int(settings.async_job_watchdog_interval_seconds))
    while True:
        try:
            await _run_async_job_watchdog_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("async_job_watchdog_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def startup(ctx: dict[str, Any]) -> None:
    ctx["app_root"] = APP_ROOT
    await enforce_sovereign_boundary()
    _validate_worker_registry()
    boot_logger.info("========================================")
    boot_logger.info("ARQ WORKER BOOT SEQUENCE INITIATED")
    boot_logger.info("========================================")
    logger.info("arq_worker_startup", queue_name=settings.arq_queue_name, concurrency=settings.arq_concurrency)

    # SEO Swarm BRPOP consumers — detached into background tasks so they
    # don't block ARQ's finite job processing loop.
    try:
        consumer_specs = _enabled_seo_consumer_specs()
        if not consumer_specs:
            logger.info("seo_swarm_consumers_disabled")
            boot_logger.info("SEO Swarm Consumers disabled for this worker.")
        else:
            boot_logger.info("Initializing SEO Swarm Consumers...")
            redis_client = await create_seo_event_redis()
            ctx["seo_redis"] = redis_client

            enabled_task_names: list[str] = []
            for worker_key, task_key, task_name, worker_cls, _flag_name in consumer_specs:
                worker = worker_cls(redis_client)
                ctx[worker_key] = worker
                task = asyncio.create_task(worker.start(), name=task_name)
                ctx[task_key] = task
                task.add_done_callback(
                    lambda completed_task, current_task_name=task_name: _log_background_task_result(
                        current_task_name,
                        completed_task,
                    ),
                )
                enabled_task_names.append(task_name)

            logger.info("seo_swarm_consumers_started", consumers=enabled_task_names)
            boot_logger.info("SUCCESS: seo_swarm_consumers_started (%s)", ", ".join(enabled_task_names))
    except Exception as exc:
        logger.warning("seo_swarm_consumers_init_failed", error=str(exc)[:300])
        boot_logger.error("FATAL: seo_swarm_consumers_init_failed")
        boot_logger.error(traceback.format_exc())

    if settings.semrush_shadow_observer_enabled:
        observer_task = asyncio.create_task(
            _semrush_shadow_observer_loop(),
            name="semrush_shadow_observer_task",
        )
        ctx["semrush_shadow_observer_task"] = observer_task
        observer_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "semrush_shadow_observer_task",
                completed_task,
            ),
        )
        logger.info(
            "semrush_shadow_observer_started",
            interval_seconds=settings.semrush_shadow_observer_interval_seconds,
        )
    else:
        logger.info("semrush_shadow_observer_disabled")

    if settings.deferred_api_reconciliation_enabled:
        recon_task = asyncio.create_task(
            _deferred_api_reconciliation_loop(),
            name="deferred_api_reconciliation_task",
        )
        ctx["deferred_api_reconciliation_task"] = recon_task
        recon_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "deferred_api_reconciliation_task",
                completed_task,
            ),
        )
        logger.info(
            "deferred_api_reconciliation_started",
            interval_seconds=settings.deferred_api_reconciliation_interval_seconds,
        )
    else:
        logger.info("deferred_api_reconciliation_disabled")

    if settings.research_scout_enabled:
        scout_task = asyncio.create_task(
            _research_scout_loop(),
            name="research_scout_task",
        )
        ctx["research_scout_task"] = scout_task
        scout_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "research_scout_task",
                completed_task,
            ),
        )
        logger.info(
            "research_scout_started",
            interval_seconds=settings.research_scout_interval_seconds,
            market=settings.research_scout_market,
        )
    else:
        logger.info("research_scout_disabled")

    if settings.acquisition_worker_enabled:
        acquisition_task = asyncio.create_task(
            _acquisition_ingestion_loop(),
            name="acquisition_ingestion_task",
        )
        ctx["acquisition_ingestion_task"] = acquisition_task
        acquisition_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "acquisition_ingestion_task",
                completed_task,
            ),
        )
        logger.info(
            "acquisition_ingestion_started",
            interval_seconds=settings.acquisition_worker_interval_seconds,
            county_name=settings.acquisition_default_county,
        )
    else:
        logger.info("acquisition_ingestion_disabled")

    if settings.airdna_sync_enabled:
        airdna_task = asyncio.create_task(
            _airdna_sync_loop(),
            name="airdna_sync_task",
        )
        ctx["airdna_sync_task"] = airdna_task
        airdna_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "airdna_sync_task",
                completed_task,
            ),
        )
        logger.info(
            "airdna_sync_started",
            interval_seconds=settings.airdna_sync_interval_seconds,
            market=settings.airdna_market,
        )
    else:
        logger.info("airdna_sync_disabled")

    if settings.concierge_shadow_draft_enabled:
        concierge_task = asyncio.create_task(
            _concierge_shadow_draft_loop(),
            name="concierge_shadow_draft_task",
        )
        ctx["concierge_shadow_draft_task"] = concierge_task
        concierge_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "concierge_shadow_draft_task",
                completed_task,
            ),
        )
        logger.info(
            "concierge_shadow_draft_started",
            interval_seconds=settings.concierge_shadow_draft_interval_seconds,
        )
    else:
        logger.info("concierge_shadow_draft_disabled")

    if settings.hunter_queue_sweep_enabled:
        hunter_task = asyncio.create_task(
            _hunter_queue_sweep_loop(),
            name="hunter_queue_sweep_task",
        )
        ctx["hunter_queue_sweep_task"] = hunter_task
        hunter_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "hunter_queue_sweep_task",
                completed_task,
            ),
        )
        logger.info(
            "hunter_queue_sweep_started",
            interval_seconds=settings.hunter_queue_sweep_interval_seconds,
        )
    else:
        logger.info("hunter_queue_sweep_disabled")

    if settings.async_job_watchdog_enabled:
        watchdog_task = asyncio.create_task(
            _async_job_watchdog_loop(),
            name="async_job_watchdog_task",
        )
        ctx["async_job_watchdog_task"] = watchdog_task
        watchdog_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "async_job_watchdog_task",
                completed_task,
            ),
        )
        logger.info(
            "async_job_watchdog_started",
            interval_seconds=settings.async_job_watchdog_interval_seconds,
            stale_queued_seconds=settings.async_job_stale_queued_seconds,
            stale_running_seconds=settings.async_job_stale_running_seconds,
        )
    else:
        logger.info("async_job_watchdog_disabled")

    streamline_vrs = StreamlineVRS()
    if streamline_vrs.is_configured:
        ctx["streamline_vrs"] = streamline_vrs
        availability_task = asyncio.create_task(
            _streamline_availability_sync_loop(streamline_vrs),
            name="streamline_availability_sync_task",
        )
        ctx["streamline_availability_sync_task"] = availability_task
        availability_task.add_done_callback(
            lambda completed_task: _log_background_task_result(
                "streamline_availability_sync_task",
                completed_task,
            ),
        )
        logger.info(
            "streamline_availability_sync_started",
            interval_seconds=max(300, int(settings.streamline_sync_interval)),
        )
        from backend.workers.drift_sentry import drift_sentry_loop
        drift_task = asyncio.create_task(
            drift_sentry_loop(),
            name="drift_sentry_task",
        )
        ctx["drift_sentry_task"] = drift_task
        drift_task.add_done_callback(
            lambda t: _log_background_task_result("drift_sentry_task", t),
        )
        logger.info("drift_sentry_started_in_worker")

    else:
        logger.info("streamline_availability_sync_disabled", reason="streamline_not_configured")

    from backend.workers.hermes_sync import hermes_sync_loop
    hermes_task = asyncio.create_task(
        hermes_sync_loop(),
        name="hermes_sync_task",
    )
    ctx["hermes_sync_task"] = hermes_task
    hermes_task.add_done_callback(
        lambda t: _log_background_task_result("hermes_sync_task", t),
    )
    logger.info("hermes_sync_started_in_worker")

    if settings.recursive_agent_loop_enabled:
        from backend.workers.recursive_agent_loop import recursive_agent_loop
        ral_task = asyncio.create_task(
            recursive_agent_loop(),
            name="recursive_agent_loop_task",
        )
        ctx["recursive_agent_loop_task"] = ral_task
        ral_task.add_done_callback(
            lambda t: _log_background_task_result("recursive_agent_loop_task", t),
        )
        logger.info("recursive_agent_loop_started_in_worker",
                    interval=os.getenv("RECURSIVE_LOOP_INTERVAL", "1800"))
    else:
        logger.info("recursive_agent_loop_disabled")

    if settings.legal_email_intake_enabled:
        from backend.services.captain_multi_mailbox import (
            load_mailbox_configs,
            preflight_authenticate,
            run_captain_multi_mailbox_loop,
            validate_mailbox_credentials,
        )

        # Fail loud — both steps raise if config is bad or any mailbox
        # cannot authenticate. Startup aborts before the poll loop is
        # scheduled, so operators see the failure in the worker boot log
        # rather than silent failing patrols.
        mailboxes = load_mailbox_configs()
        validate_mailbox_credentials(mailboxes)
        preflight_results = await preflight_authenticate(mailboxes)
        for result in preflight_results:
            logger.info("captain_preflight_status", **result)

        captain_task = asyncio.create_task(
            run_captain_multi_mailbox_loop(),
            name="captain_multi_mailbox_task",
        )
        ctx["captain_multi_mailbox_task"] = captain_task
        captain_task.add_done_callback(
            lambda t: _log_background_task_result("captain_multi_mailbox_task", t),
        )
        logger.info(
            "captain_multi_mailbox_started_in_worker",
            mailboxes=[m.name for m in mailboxes],
        )

        # Legacy single-mailbox loop — deprecated. Captain owns legal@ now.
        # Gated behind LEGACY_LEGAL_INTAKE_ENABLED (default false) for
        # emergency rollback only. If set true while Captain is also running,
        # both loops race on the legal@ UNSEEN flag.
        if settings.legacy_legal_intake_enabled:
            logger.warning(
                "legacy_legal_intake_enabled_deprecated",
                note="Captain multi-mailbox supersedes this path. "
                     "LEGACY_LEGAL_INTAKE_ENABLED is for emergency rollback only.",
            )
            from backend.services.legal_email_intake import run_legal_intake_loop
            legal_intake_task = asyncio.create_task(
                run_legal_intake_loop(),
                name="legal_intake_task",
            )
            ctx["legal_intake_task"] = legal_intake_task
            legal_intake_task.add_done_callback(
                lambda t: _log_background_task_result("legal_intake_task", t),
            )
            logger.info("legacy_legal_email_intake_started_in_worker",
                        interval=settings.legal_email_poll_interval)
    else:
        logger.info("legal_email_intake_disabled")

    reservation_confirmed_task = asyncio.create_task(
        _reservation_confirmed_consumer_loop(),
        name="reservation_confirmed_consumer_task",
    )
    ctx["reservation_confirmed_consumer_task"] = reservation_confirmed_task
    reservation_confirmed_task.add_done_callback(
        lambda t: _log_background_task_result("reservation_confirmed_consumer_task", t),
    )
    logger.info("reservation_confirmed_consumer_wired")

    payout_sweep_task = asyncio.create_task(
        _payout_sweep_loop(),
        name="payout_sweep_task",
    )
    ctx["payout_sweep_task"] = payout_sweep_task
    payout_sweep_task.add_done_callback(
        lambda t: _log_background_task_result("payout_sweep_task", t),
    )
    logger.info("payout_sweep_loop_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("arq_worker_shutdown", queue_name=settings.arq_queue_name)

    for key in ("seo_grading_worker", "seo_rewrite_worker", "seo_deploy_worker"):
        worker = ctx.get(key)
        if worker is not None:
            worker.stop()

    tasks = [ctx[k] for k in ("seo_grading_task", "seo_rewrite_task", "seo_deploy_task") if k in ctx]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("seo_swarm_consumers_stopped")

    redis_client = ctx.get("seo_redis")
    if redis_client is not None:
        await redis_client.aclose()

    observer_task = ctx.get("semrush_shadow_observer_task")
    if observer_task is not None:
        observer_task.cancel()
        await asyncio.gather(observer_task, return_exceptions=True)

    recon_task = ctx.get("deferred_api_reconciliation_task")
    if recon_task is not None:
        recon_task.cancel()
        await asyncio.gather(recon_task, return_exceptions=True)

    scout_task = ctx.get("research_scout_task")
    if scout_task is not None:
        scout_task.cancel()
        await asyncio.gather(scout_task, return_exceptions=True)

    acquisition_task = ctx.get("acquisition_ingestion_task")
    if acquisition_task is not None:
        acquisition_task.cancel()
        await asyncio.gather(acquisition_task, return_exceptions=True)

    airdna_task = ctx.get("airdna_sync_task")
    if airdna_task is not None:
        airdna_task.cancel()
        await asyncio.gather(airdna_task, return_exceptions=True)

    concierge_task = ctx.get("concierge_shadow_draft_task")
    if concierge_task is not None:
        concierge_task.cancel()
        await asyncio.gather(concierge_task, return_exceptions=True)

    hunter_task = ctx.get("hunter_queue_sweep_task")
    if hunter_task is not None:
        hunter_task.cancel()
        await asyncio.gather(hunter_task, return_exceptions=True)

    watchdog_task = ctx.get("async_job_watchdog_task")
    if watchdog_task is not None:
        watchdog_task.cancel()
        await asyncio.gather(watchdog_task, return_exceptions=True)

    availability_task = ctx.get("streamline_availability_sync_task")
    if availability_task is not None:
        availability_task.cancel()
        await asyncio.gather(availability_task, return_exceptions=True)

    payout_sweep_task = ctx.get("payout_sweep_task")
    if payout_sweep_task is not None:
        payout_sweep_task.cancel()
        await asyncio.gather(payout_sweep_task, return_exceptions=True)

    streamline_vrs = ctx.get("streamline_vrs")
    if streamline_vrs is not None:
        await streamline_vrs.close()


async def _enqueue_semrush_shadow_observation_if_idle() -> None:
    if not settings.agentic_system_active:
        logger.info("semrush_shadow_observer_skip", reason="agentic_system_inactive")
        return

    async with AsyncSessionLocal() as db:
        queued = await count_jobs_by_status(
            db,
            status="queued",
            job_name="seo_parity_observation",
        )
        running = await count_jobs_by_status(
            db,
            status="running",
            job_name="seo_parity_observation",
        )
        if queued > 0 or running > 0:
            logger.info(
                "semrush_shadow_observer_skip",
                reason="job_already_in_flight",
                queued=queued,
                running=running,
            )
            return

        job = await enqueue_async_job(
            db,
            worker_name="run_seo_parity_observation_job",
            job_name="seo_parity_observation",
            payload={},
            requested_by="system_shadow_parallel",
            tenant_id=None,
            request_id="semrush-shadow-observer",
        )
        logger.info("semrush_shadow_observer_enqueued", job_id=str(job.id))


async def _semrush_shadow_observer_loop() -> None:
    interval = max(60, int(settings.semrush_shadow_observer_interval_seconds))
    while True:
        try:
            await _enqueue_semrush_shadow_observation_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("semrush_shadow_observer_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _deferred_api_reconciliation_loop() -> None:
    interval = max(30, int(settings.deferred_api_reconciliation_interval_seconds))
    while True:
        try:
            n = await reconciliation_janitor.sweep_deferred_writes()
            if n:
                logger.info("deferred_api_reconciliation_sweep_done", rows_touched=n)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("deferred_api_reconciliation_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _enqueue_research_scout_if_idle() -> None:
    if not settings.agentic_system_active:
        logger.info("research_scout_skip", reason="agentic_system_inactive")
        return

    async with AsyncSessionLocal() as db:
        queued = await count_jobs_by_status(
            db,
            status="queued",
            job_name="research_scout_cycle",
        )
        running = await count_jobs_by_status(
            db,
            status="running",
            job_name="research_scout_cycle",
        )
        if queued > 0 or running > 0:
            logger.info(
                "research_scout_skip",
                reason="job_already_in_flight",
                queued=queued,
                running=running,
            )
            return

        job = await enqueue_async_job(
            db,
            worker_name="run_research_scout_job",
            job_name="research_scout_cycle",
            payload={"market": settings.research_scout_market},
            requested_by="system_research_scout",
            tenant_id=None,
            request_id="research-scout-observer",
        )
        logger.info("research_scout_enqueued", job_id=str(job.id))


async def _research_scout_loop() -> None:
    interval = max(3600, int(settings.research_scout_interval_seconds))
    while True:
        try:
            await _enqueue_research_scout_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("research_scout_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _enqueue_acquisition_ingestion_if_idle() -> None:
    if not settings.acquisition_worker_enabled:
        logger.info("acquisition_ingestion_skip", reason="feature_disabled")
        return

    async with AsyncSessionLocal() as db:
        queued = await count_jobs_by_status(
            db,
            status="queued",
            job_name="acquisition_ingestion_cycle",
        )
        running = await count_jobs_by_status(
            db,
            status="running",
            job_name="acquisition_ingestion_cycle",
        )
        if queued > 0 or running > 0:
            logger.info(
                "acquisition_ingestion_skip",
                reason="job_already_in_flight",
                queued=queued,
                running=running,
            )
            return

        payload = AcquisitionIngestionRequest().model_dump(mode="json")
        job = await enqueue_async_job(
            db,
            worker_name="run_acquisition_ingestion_job",
            job_name="acquisition_ingestion_cycle",
            payload=payload,
            requested_by="system_acquisition_ingestion",
            tenant_id=None,
            request_id="acquisition-ingestion-observer",
        )
        logger.info("acquisition_ingestion_enqueued", job_id=str(job.id))


async def _acquisition_ingestion_loop() -> None:
    interval = max(900, int(settings.acquisition_worker_interval_seconds))
    while True:
        try:
            await _enqueue_acquisition_ingestion_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("acquisition_ingestion_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _enqueue_airdna_sync_if_idle() -> None:
    if not settings.airdna_sync_enabled:
        logger.info("airdna_sync_skip", reason="feature_disabled")
        return

    async with AsyncSessionLocal() as db:
        queued = await count_jobs_by_status(
            db,
            status="queued",
            job_name="airdna_str_signal_sync",
        )
        running = await count_jobs_by_status(
            db,
            status="running",
            job_name="airdna_str_signal_sync",
        )
        if queued > 0 or running > 0:
            logger.info(
                "airdna_sync_skip",
                reason="job_already_in_flight",
                queued=queued,
                running=running,
            )
            return

        payload = AirDNASyncJobPayload().model_dump(mode="json")
        job = await enqueue_async_job(
            db,
            worker_name="run_airdna_sync_job",
            job_name="airdna_str_signal_sync",
            payload=payload,
            requested_by="system_airdna_sync",
            tenant_id=None,
            request_id="airdna-sync-observer",
        )
        logger.info("airdna_sync_enqueued", job_id=str(job.id))


async def _airdna_sync_loop() -> None:
    interval = max(900, int(settings.airdna_sync_interval_seconds))
    while True:
        try:
            await _enqueue_airdna_sync_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("airdna_sync_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _enqueue_concierge_shadow_draft_if_idle() -> None:
    if not settings.agentic_system_active:
        logger.info("concierge_shadow_draft_skip", reason="agentic_system_inactive")
        return
    if not settings.concierge_shadow_draft_enabled:
        logger.info("concierge_shadow_draft_skip", reason="feature_disabled")
        return

    async with AsyncSessionLocal() as db:
        queued = await count_jobs_by_status(
            db,
            status="queued",
            job_name="concierge_shadow_draft_cycle",
        )
        running = await count_jobs_by_status(
            db,
            status="running",
            job_name="concierge_shadow_draft_cycle",
        )
        if queued > 0 or running > 0:
            logger.info(
                "concierge_shadow_draft_skip",
                reason="job_already_in_flight",
                queued=queued,
                running=running,
            )
            return

        job = await enqueue_async_job(
            db,
            worker_name="run_concierge_shadow_draft_job",
            job_name="concierge_shadow_draft_cycle",
            payload={},
            requested_by="system_concierge_shadow_draft",
            tenant_id=None,
            request_id="concierge-shadow-draft-observer",
        )
        logger.info("concierge_shadow_draft_enqueued", job_id=str(job.id))


async def _concierge_shadow_draft_loop() -> None:
    interval = max(300, int(settings.concierge_shadow_draft_interval_seconds))
    while True:
        try:
            await _enqueue_concierge_shadow_draft_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("concierge_shadow_draft_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _enqueue_hunter_queue_sweep_if_idle() -> None:
    if not settings.agentic_system_active:
        logger.info("hunter_queue_sweep_skip", reason="agentic_system_inactive")
        return
    if not settings.hunter_queue_sweep_enabled:
        logger.info("hunter_queue_sweep_skip", reason="feature_disabled")
        return

    async with AsyncSessionLocal() as db:
        queued = await count_jobs_by_status(
            db,
            status="queued",
            job_name="hunter_queue_sweep",
        )
        running = await count_jobs_by_status(
            db,
            status="running",
            job_name="hunter_queue_sweep",
        )
        if queued > 0 or running > 0:
            logger.info(
                "hunter_queue_sweep_skip",
                reason="job_already_in_flight",
                queued=queued,
                running=running,
            )
            return

        job = await enqueue_async_job(
            db,
            worker_name="run_hunter_queue_sweep_job",
            job_name="hunter_queue_sweep",
            payload={},
            requested_by="system_hunter_queue_sweep",
            tenant_id=None,
            request_id="hunter-queue-sweep-observer",
        )
        logger.info("hunter_queue_sweep_enqueued", job_id=str(job.id))


async def _hunter_queue_sweep_loop() -> None:
    interval = max(300, int(settings.hunter_queue_sweep_interval_seconds))
    while True:
        try:
            await _enqueue_hunter_queue_sweep_if_idle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("hunter_queue_sweep_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _payout_sweep_loop() -> None:
    """
    Daily payout sweep that runs at 6am ET. Checks every hour whether the
    6am window has been hit and triggers the sweep once per day.
    """
    import pytz
    _ET = pytz.timezone("America/New_York")
    _last_sweep_date = None
    while True:
        try:
            now_et = datetime.now(_ET)
            today = now_et.date()
            if now_et.hour >= 6 and _last_sweep_date != today:
                from backend.services.payout_scheduler import run_payout_sweep
                result = await run_payout_sweep()
                _last_sweep_date = today
                logger.info("payout_sweep_daily_complete", **{k: str(v) for k, v in result.items()})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("payout_sweep_loop_error", error=str(exc)[:400])
        await asyncio.sleep(3600)  # check every hour


async def _streamline_availability_sync_loop(streamline_vrs: StreamlineVRS) -> None:
    interval = max(300, int(settings.streamline_sync_interval))
    while True:
        try:
            async with AsyncSessionLocal() as db:
                summary = await streamline_vrs.sync_property_availability(db)
                logger.info(
                    "streamline_availability_sync_complete",
                    synced=summary.get("synced"),
                    skipped=summary.get("skipped"),
                    bookings_found=summary.get("bookings_found"),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("streamline_availability_sync_loop_error", error=str(exc)[:400])
        await asyncio.sleep(interval)


async def _load_job(job_id: str) -> AsyncJobRun:
    async with AsyncSessionLocal() as db:
        job = await db.get(AsyncJobRun, job_id)
        if job is None:
            raise RuntimeError(f"Async job {job_id} not found")
        return job


async def _with_job(job_id: str, job_try: int, runner) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        job = await db.get(AsyncJobRun, job_id)
        if job is None:
            raise RuntimeError(f"Async job {job_id} not found")
        job_name = str(job.job_name)
        await mark_job_running(db, job, attempts=job_try)
        try:
            result = await runner(db, job)
        except Exception as exc:
            logger.exception("async_job_failed", job_id=job_id, job_name=job_name)
            await mark_job_failed(db, job, str(exc), attempts=job_try)
            raise
        await mark_job_succeeded(db, job, result)
        return result


async def process_streamline_event_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = StreamlineEventPayload.model_validate(job.payload_json or {})
        if (
            payload.entity_type == "iot"
            and payload.event_type in {"lock.checkout", "checkout", "checkout_detected"}
        ):
            property_id = payload.current_state.get("property_id") or payload.entity_id
            try:
                from backend.services.vrs_agent_dispatcher import handle_iot_checkout_event
            except ImportError as exc:
                raise RuntimeError("backend.services.vrs_agent_dispatcher is not available") from exc

            result_data = await handle_iot_checkout_event(
                db=db,
                property_id=property_id,
                event_data={"event_type": payload.event_type, **payload.current_state},
            )
            return {
                "entity_type": payload.entity_type,
                "entity_id": payload.entity_id,
                "event_type": payload.event_type,
                "dispatched": bool(result_data.get("dispatched", False)),
                "ticket_number": result_data.get("ticket_number"),
            }

        query = select(VRSRuleEngine).where(
            VRSRuleEngine.target_entity == payload.entity_type,
            VRSRuleEngine.trigger_event == payload.event_type,
            VRSRuleEngine.is_active == True,  # noqa: E712
        )
        matching_rules = (await db.execute(query)).scalars().all()

        fired = 0
        fired_rule_ids: list[str] = []
        for rule in matching_rules:
            if RuleEngine._evaluate_conditions(rule.conditions, payload):
                await RuleEngine._execute_action(rule, payload, db)
                fired += 1
                fired_rule_ids.append(str(rule.id))
        await db.commit()
        return {
            "entity_type": payload.entity_type,
            "entity_id": payload.entity_id,
            "event_type": payload.event_type,
            "rules_fired": fired,
            "rule_ids": fired_rule_ids,
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def sync_knowledge_base_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.knowledge_retriever import sync_knowledge_base_to_qdrant

        synced = await sync_knowledge_base_to_qdrant(db)
        return {"synced": synced, "job_name": job.job_name}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def reindex_property_knowledge(ctx: dict[str, Any], property_id: str) -> dict[str, Any]:
    from uuid import UUID

    from backend.services.knowledge_ingestion import KnowledgeIngestionService

    try:
        parsed_property_id = UUID(str(property_id).strip())
    except ValueError as exc:
        raise RuntimeError(f"Invalid property_id for knowledge reindex: {property_id}") from exc

    async with AsyncSessionLocal() as db:
        service = KnowledgeIngestionService()
        result = await service.ingest_property(db, parsed_property_id)

    logger.info("property_knowledge_reindexed", property_id=str(parsed_property_id))
    return result


async def vectorize_new_records_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.workers.vectorizer import vectorize_new_records

        summary = await vectorize_new_records(db)
        return {"summary": summary, "job_name": job.job_name}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def rebuild_history_index_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.history_query_tool import HistoryLibrarian

        payload = job.payload_json or {}
        librarian = HistoryLibrarian(history_path=str(payload.get("history_path") or "/mnt/history"))
        result = await librarian.rebuild_persistent_index()
        return {"history_path": librarian.history_path, "index_result": result}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_shadow_audit_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.shadow_mode_observer import run_shadow_audit

        payload = job.payload_json or {}
        result = await run_shadow_audit(
            payload=payload.get("payload") or {},
            legacy_result=payload.get("legacy_result"),
            metadata=payload.get("metadata"),
            audit_path=payload.get("audit_path"),
            remote_closer_url=payload.get("remote_closer_url"),
            timeout_seconds=float(payload.get("timeout_seconds") or 20.0),
            tolerance=payload.get("tolerance") or "0.01",
            request_id=str(job.id),
        )
        return {"shadow_audit": result}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_seo_parity_observation_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        summary = await observe_semrush_parity(db, persist_audit=True, request_id=str(job.id))
        return {"seo_parity": summary.model_dump()}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_research_scout_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        summary = await research_scout_service.run_cycle(db, scout_run_key=str(job.id))
        actions = await research_scout_action_router.route_inserted_findings(
            db,
            inserted_entry_ids=list(summary.get("inserted_entry_ids") or []),
        )
        summary["actions"] = actions
        return {"research_scout": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_acquisition_ingestion_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = AcquisitionIngestionRequest.model_validate(job.payload_json or {})
        summary = await run_acquisition_ingestion_cycle(db, payload)
        return {"acquisition_ingestion": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_fannin_foia_ingest_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = FoiaIngestJobPayload.model_validate(job.payload_json or {})
        file_bytes = Path(payload.spool_path).read_bytes()
        try:
            summary = await run_fannin_foia_ingest(
                db,
                filename=payload.filename,
                file_bytes=file_bytes,
                county_name=payload.county_name,
                dry_run=payload.dry_run,
            )
        finally:
            try:
                Path(payload.spool_path).unlink(missing_ok=True)
            except Exception:
                pass
        return {"foia_fannin_str_ingest": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_airdna_sync_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = AirDNASyncJobPayload.model_validate(job.payload_json or {})
        summary = await run_airdna_sync(db, payload)
        return {"airdna_sync": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_concierge_shadow_draft_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    from uuid import UUID

    from backend.services.concierge_recovery_parity import run_concierge_shadow_draft_cycle
    from backend.services.hunter_service import execute_hunter_candidate, mark_hunter_candidate_failed

    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = job.payload_json or {}
        try:
            run_uuid = UUID(str(job.id))
        except ValueError:
            run_uuid = None
        session_fp = str(payload.get("session_fp") or "").strip().lower()
        if session_fp:
            try:
                summary = await execute_hunter_candidate(
                    db,
                    session_fp=session_fp,
                    async_job_run_id=run_uuid,
                )
            except Exception as exc:
                await mark_hunter_candidate_failed(db, session_fp=session_fp, error_text=str(exc))
                raise
            return {"hunter_execute": summary}
        summary = await run_concierge_shadow_draft_cycle(
            db,
            async_job_run_id=run_uuid,
            request_id=str(job.id),
        )
        return {"concierge_recovery_parity": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_hunter_queue_sweep_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    from backend.services.hunter_service import sweep_hunter_queue

    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        summary = await sweep_hunter_queue(
            db,
            candidate_limit=settings.hunter_queue_candidate_limit,
            trigger=str(job.job_name or "scheduled"),
        )
        return {"hunter_queue_sweep": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_hunter_execute_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    from uuid import UUID

    from backend.services.hunter_service import execute_hunter_candidate, mark_hunter_candidate_failed

    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = job.payload_json or {}
        session_fp = str(payload.get("session_fp") or "").strip().lower()
        if not session_fp:
            raise RuntimeError("hunter_execute requires session_fp")
        try:
            run_uuid = UUID(str(job.id))
        except ValueError:
            run_uuid = None
        try:
            summary = await execute_hunter_candidate(
                db,
                session_fp=session_fp,
                async_job_run_id=run_uuid,
            )
        except Exception as exc:
            await mark_hunter_candidate_failed(db, session_fp=session_fp, error_text=str(exc))
            raise
        return {"hunter_execute": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_hunter_recovery_draft_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    from uuid import UUID

    from backend.services.hunter_service import execute_hunter_recovery_draft, mark_hunter_recovery_op_retry

    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        payload = job.payload_json or {}
        recovery_op_id = str(payload.get("recovery_op_id") or "").strip()
        if not recovery_op_id:
            raise RuntimeError("hunter_recovery_draft requires recovery_op_id")
        try:
            recovery_uuid = UUID(recovery_op_id)
        except ValueError as exc:
            raise RuntimeError(f"Invalid hunter recovery op id: {recovery_op_id}") from exc
        try:
            summary = await execute_hunter_recovery_draft(
                db,
                recovery_op_id=recovery_uuid,
                draft_context=payload.get("draft_context") if isinstance(payload.get("draft_context"), dict) else None,
                request_id=str(job.id),
            )
        except Exception as exc:
            await mark_hunter_recovery_op_retry(
                db,
                recovery_op_id=recovery_uuid,
                request_id=str(job.id),
                error_text=str(exc),
            )
            raise
        return {"hunter_recovery_draft": summary}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_contract_ingestion_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.api.admin import _run_contract_ingestion

        payload = job.payload_json or {}
        nas_path = str(payload.get("nas_path") or "").strip()
        owner_id = str(payload.get("owner_id") or "").strip()
        if not nas_path or not owner_id:
            raise RuntimeError("Contract ingestion requires nas_path and owner_id")
        await asyncio.to_thread(_run_contract_ingestion, nas_path, owner_id)
        return {"nas_path": nas_path, "owner_id": owner_id, "status": "ingested"}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_legal_graph_refresh_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.legal_case_graph import trigger_graph_refresh

        payload = job.payload_json or {}
        case_slug = str(payload.get("case_slug") or "").strip()
        if not case_slug:
            raise RuntimeError("Legal graph refresh requires case_slug")
        await trigger_graph_refresh(db, case_slug=case_slug)
        return {"case_slug": case_slug, "status": "refreshed"}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_legal_extraction_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.api.legal_cases import _run_extraction_job

        payload = job.payload_json or {}
        await _run_extraction_job(
            slug=str(payload.get("slug") or "").strip(),
            case_id=int(payload.get("case_id")),
            target=str(payload.get("target") or "").strip(),
            source_text=str(payload.get("source_text") or ""),
            correspondence_id=int(payload["correspondence_id"]) if payload.get("correspondence_id") is not None else None,
        )
        return {
            "slug": payload.get("slug"),
            "case_id": payload.get("case_id"),
            "target": payload.get("target"),
            "correspondence_id": payload.get("correspondence_id"),
            "status": "complete",
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_legal_chronology_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.legal_chronology import build_chronology

        payload = job.payload_json or {}
        case_slug = str(payload.get("case_slug") or "").strip()
        if not case_slug:
            raise RuntimeError("Chronology build requires case_slug")
        result = await build_chronology(db, case_slug)
        return {"chronology": result}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_dispute_evidence_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.dispute_defense import compile_and_submit_evidence

        payload = job.payload_json or {}
        dispute_id = str(payload.get("dispute_id") or "").strip()
        reservation_id = str(payload.get("reservation_id") or "").strip()
        if not dispute_id:
            raise RuntimeError("Dispute evidence job requires dispute_id")
        await compile_and_submit_evidence(dispute_id, reservation_id)
        return {"dispute_id": dispute_id, "reservation_id": reservation_id, "status": "submitted"}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def dispatch_copilot_email_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.api.copilot_queue import _dispatch_email

        payload = job.payload_json or {}
        message_id = str(payload.get("message_id") or "").strip()
        if not message_id:
            raise RuntimeError("Copilot dispatch job requires message_id")
        await _dispatch_email(message_id)
        return {"message_id": message_id, "status": "sent_or_recorded"}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def dispatch_post_payment_docs_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.api.checkout import _send_post_payment_docs

        payload = job.payload_json or {}
        guest_email = str(payload.get("guest_email") or "").strip()
        quote_data = payload.get("quote_data") or {}
        if not guest_email:
            raise RuntimeError("Post-payment docs job requires guest_email")
        await _send_post_payment_docs(guest_email, quote_data)
        return {"guest_email": guest_email, "quote_id": quote_data.get("quote_id"), "status": "sent_or_logged"}

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def process_legal_vault_upload_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.legal_ediscovery import process_vault_upload

        payload = job.payload_json or {}
        case_slug = str(payload.get("case_slug") or "").strip()
        spool_path = str(payload.get("spool_path") or "").strip()
        file_name = str(payload.get("file_name") or "unknown").strip() or "unknown"
        mime_type = str(payload.get("mime_type") or "application/octet-stream").strip()
        if not case_slug or not spool_path:
            raise RuntimeError("Legal vault upload requires case_slug and spool_path")
        file_bytes = Path(spool_path).read_bytes()
        try:
            result = await process_vault_upload(db, case_slug, file_bytes, file_name, mime_type)
        finally:
            try:
                Path(spool_path).unlink(missing_ok=True)
            except Exception:
                pass
        return {
            "case_slug": case_slug,
            "file_name": file_name,
            "mime_type": mime_type,
            "spool_path": spool_path,
            "result": result,
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_legal_council_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.legal_council import build_case_deliberation_payload, run_council_deliberation

        payload = dict(job.payload_json or {})
        case_type = str(payload.get("case_type") or "legal_case").strip().lower()
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if not payload.get("case_brief"):
            case_slug = str(payload.get("case_slug") or "").strip()
            if not case_slug:
                raise RuntimeError("Legal council job requires case_brief or case_slug")
            payload.update(await build_case_deliberation_payload(case_slug))

        redis = await create_council_redis()
        try:
            await publish_council_event(
                redis,
                job_id,
                {
                    "type": "session_start",
                    "session_id": job_id,
                    "job_id": job_id,
                },
            )

            async def on_progress(event: dict[str, Any]) -> None:
                event_payload = dict(event)
                event_payload.setdefault("session_id", job_id)
                event_payload.setdefault("job_id", job_id)
                await publish_council_event(redis, job_id, event_payload)

            try:
                result = await run_council_deliberation(
                    session_id=job_id,
                    case_brief=str(payload.get("case_brief") or ""),
                    context=str(payload.get("context") or ""),
                    progress_callback=on_progress,
                    case_slug=str(payload.get("case_slug") or ""),
                    case_number=str(payload.get("case_number") or ""),
                    trigger_type=str(payload.get("trigger_type") or "MANUAL_RUN"),
                )
            except Exception as exc:
                await publish_council_event(
                    redis,
                    job_id,
                    {
                        "type": "error",
                        "session_id": job_id,
                        "job_id": job_id,
                        "message": f"Council error: {type(exc).__name__}: {exc}",
                    },
                )
                raise
            if not isinstance(result, dict):
                result = {
                    "status": "error",
                    "session_id": job_id,
                    "job_id": job_id,
                    "message": "Council deliberation did not return a result payload",
                }
            result.setdefault("session_id", job_id)
            result.setdefault("job_id", job_id)
            result.setdefault("case_type", case_type)
            if metadata:
                result.setdefault("metadata", metadata)
                final_json_ld = metadata.get("final_json_ld")
                if isinstance(final_json_ld, dict):
                    result["final_json_ld"] = final_json_ld
            return result
        finally:
            await redis.aclose()

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_archive_seo_batch_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.scripts.generate_archive_seo_payloads import (
            DEFAULT_ARCHIVE_DIR,
            DEFAULT_SYSTEM_MESSAGE,
            DEFAULT_CHAT_BASE_URL,
            DEFAULT_MODEL,
            DEFAULT_API_BASE_URL,
            GeneratorConfig,
            _run,
        )

        payload = job.payload_json or {}
        output_dir = APP_ROOT / "backend" / "data" / "async_jobs" / str(job.id)
        output_dir.mkdir(parents=True, exist_ok=True)

        model_name = str(payload.get("model") or DEFAULT_MODEL or settings.dgx_reasoner_model).strip()
        if not model_name:
            raise RuntimeError("No model configured for archive SEO batch job")

        cfg = GeneratorConfig(
            archive_dir=Path(str(payload.get("archive_dir") or DEFAULT_ARCHIVE_DIR)),
            output_path=output_dir / "archive_seo_bulk_payloads.json",
            sql_output_path=output_dir / "archive_seo_bulk_payloads.sql",
            api_base_url=str(payload.get("api_base_url") or DEFAULT_API_BASE_URL).rstrip("/"),
            chat_completions_url=str(payload.get("chat_completions_url") or DEFAULT_CHAT_BASE_URL).rstrip("/"),
            model=model_name,
            campaign=str(payload.get("campaign") or "archive_async_engine"),
            rubric_version=str(payload.get("rubric_version") or "nemotron_archive_v1"),
            proposed_by=str(payload.get("proposed_by") or "dgx-nemotron"),
            run_id=str(payload.get("run_id") or f"archive-seo-{job.id}"),
            concurrency=max(1, int(payload.get("concurrency") or 4)),
            limit=int(payload["limit"]) if payload.get("limit") is not None else None,
            only_slug=str(payload["only_slug"]).strip() if payload.get("only_slug") else None,
            post_api=bool(payload.get("post_api", False)),
            dry_run=bool(payload.get("dry_run", False)),
            swarm_api_key=str(payload.get("swarm_api_key") or settings.swarm_api_key),
            system_message=str(payload.get("system_message") or DEFAULT_SYSTEM_MESSAGE),
            temperature=float(payload.get("temperature") or 0.2),
            max_tokens=max(256, int(payload.get("max_tokens") or 1800)),
            client_cert=str(payload["client_cert"]).strip() if payload.get("client_cert") else None,
            client_key=str(payload["client_key"]).strip() if payload.get("client_key") else None,
            verify_ssl=bool(payload.get("verify_ssl", False)),
            force_json_response=bool(payload.get("force_json_response", True)),
            disable_thinking=bool(payload.get("disable_thinking", True)),
            db_resume=bool(payload.get("db_resume", True)),
            write_db=bool(payload.get("write_db", True)),
            connect_timeout_s=float(payload.get("connect_timeout_s") or 15.0),
            read_timeout_s=float(payload.get("read_timeout_s") or 300.0),
            write_timeout_s=float(payload.get("write_timeout_s") or 30.0),
            pool_timeout_s=float(payload.get("pool_timeout_s") or 30.0),
        )
        exit_code = await _run(cfg)
        return {
            "exit_code": exit_code,
            "output_path": str(cfg.output_path),
            "sql_output_path": str(cfg.sql_output_path),
            "campaign": cfg.campaign,
            "run_id": cfg.run_id,
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_seo_redirect_batch_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        import json

        from backend.scripts.generate_seo_migration_map import RedirectCandidate, _persist_candidates

        payload = job.payload_json or {}
        input_path = Path(str(payload.get("input_path") or APP_ROOT / "backend" / "scripts" / "seo_migration_candidates_batch2_1617.json"))
        if not input_path.exists():
            raise RuntimeError(f"Redirect batch input not found: {input_path}")

        source_key = str(payload.get("source_key") or "redirects").strip() or "redirects"
        offset = max(0, int(payload.get("offset") or 0))
        limit_value = payload.get("limit")
        limit = max(1, int(limit_value)) if limit_value is not None else None
        min_confidence = float(payload.get("min_confidence") or 0.0)
        write_db = bool(payload.get("write_db", True))

        raw_payload = json.loads(input_path.read_text(encoding="utf-8"))
        raw_rows = raw_payload.get(source_key)
        if not isinstance(raw_rows, list):
            raise RuntimeError(f"Redirect batch payload missing list at key '{source_key}'")

        selected_rows = raw_rows[offset:]
        if limit is not None:
            selected_rows = selected_rows[:limit]

        candidates: list[RedirectCandidate] = []
        skipped_for_confidence = 0
        for item in selected_rows:
            if not isinstance(item, dict):
                continue
            confidence = float(item.get("confidence") or 0.0)
            if confidence < min_confidence:
                skipped_for_confidence += 1
                continue
            source_path = str(item.get("source_path") or "").strip()
            destination_path = str(item.get("destination_path") or "").strip()
            if not source_path or not destination_path:
                continue
            candidates.append(
                RedirectCandidate(
                    source_path=source_path,
                    destination_path=destination_path,
                    confidence=confidence,
                    strategy=str(item.get("strategy") or "batch_import").strip() or "batch_import",
                    reason=str(item.get("reason") or "batch_import").strip() or "batch_import",
                    source_type=str(item.get("source_type") or "batch_file").strip() or "batch_file",
                    title=str(item.get("title")).strip() if item.get("title") is not None else None,
                    source_ref=str(item.get("source_ref")).strip() if item.get("source_ref") is not None else None,
                    node_type=str(item.get("node_type")).strip() if item.get("node_type") is not None else None,
                    taxonomy_terms=[str(term).strip() for term in item.get("taxonomy_terms", []) if str(term).strip()]
                    if isinstance(item.get("taxonomy_terms"), list)
                    else None,
                )
            )

        output_dir = APP_ROOT / "backend" / "data" / "async_jobs" / str(job.id)
        output_dir.mkdir(parents=True, exist_ok=True)
        preview_path = output_dir / "seo_redirect_batch_preview.json"
        preview_path.write_text(
            json.dumps(
                {
                    "input_path": str(input_path),
                    "source_key": source_key,
                    "offset": offset,
                    "limit": limit,
                    "min_confidence": min_confidence,
                    "candidate_count": len(candidates),
                    "skipped_for_confidence": skipped_for_confidence,
                    "write_db": write_db,
                    "candidates": [
                        {
                            "source_path": candidate.source_path,
                            "destination_path": candidate.destination_path,
                            "confidence": round(candidate.confidence, 4),
                            "strategy": candidate.strategy,
                            "reason": candidate.reason,
                            "source_type": candidate.source_type,
                            "title": candidate.title,
                            "source_ref": candidate.source_ref,
                            "node_type": candidate.node_type,
                            "taxonomy_terms": candidate.taxonomy_terms,
                        }
                        for candidate in candidates[:250]
                    ],
                },
                indent=2,
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )

        inserted = 0
        updated = 0
        if write_db and candidates:
            inserted, updated = await _persist_candidates(candidates)

        return {
            "input_path": str(input_path),
            "source_key": source_key,
            "offset": offset,
            "limit": limit,
            "min_confidence": min_confidence,
            "processed_count": len(candidates),
            "skipped_for_confidence": skipped_for_confidence,
            "write_db": write_db,
            "inserted": inserted,
            "updated": updated,
            "preview_path": str(preview_path),
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_seo_fallback_swarm_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.seo_fallback_swarm import run_seo_fallback_swarm

        return await run_seo_fallback_swarm(db, payload=job.payload_json or {})

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_seo_remap_grading_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.seo_remap_grader import run_seo_remap_grading

        return await run_seo_remap_grading(db, payload=job.payload_json or {})

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_work_order_sync_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """
    On-demand Streamline work order sync.

    Fetches all maintenance tickets from Streamline VRS, upserts new ones into
    work_orders, and updates status on existing ones.  This mirrors the Phase 4
    logic in StreamlineVRS.run_full_sync() but is callable independently.

    Payload options (all optional):
      dry_run (bool) – log targets but skip DB writes; default: false
    """
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.integrations.streamline_vrs import StreamlineVRS
        from backend.models.workorder import WorkOrder
        from backend.models.property import Property
        from sqlalchemy import select

        payload = job.payload_json or {}
        dry_run = bool(payload.get("dry_run", False))

        vrs = StreamlineVRS()
        if not vrs.is_configured:
            return {"error": "Streamline VRS not configured", "synced": 0}

        remote_wos = await vrs.fetch_work_orders()
        created, updated, skipped = 0, 0, 0

        for rwo in remote_wos:
            sl_id = str(rwo.get("streamline_id", "")).strip()
            if not sl_id:
                skipped += 1
                continue

            if dry_run:
                logger.info("work_order_sync_dry_run", streamline_id=sl_id, subject=rwo.get("subject"))
                skipped += 1
                continue

            result = await db.execute(select(WorkOrder).where(WorkOrder.title == f"SL-{sl_id}"))
            existing = result.scalar_one_or_none()

            if existing:
                if rwo.get("status"):
                    existing.status = rwo["status"]  # type: ignore[assignment]
                updated += 1
            else:
                prop_result = await db.execute(
                    select(Property).where(Property.streamline_property_id == str(rwo.get("unit_id", "")))
                )
                prop = prop_result.scalar_one_or_none()
                from backend.models.workorder import WorkOrder as WO
                wo = WO(
                    ticket_number=f"SL-{sl_id}",
                    title=f"SL-{sl_id}",
                    description=rwo.get("description") or rwo.get("subject", "No description"),
                    category=rwo.get("category", "other") or "other",
                    priority=rwo.get("priority", "medium") or "medium",
                    status="open",
                    property_id=prop.id if prop else None,
                    created_by="streamline_sync",
                )
                db.add(wo)
                created += 1

        if not dry_run:
            await db.commit()

        return {
            "dry_run": dry_run,
            "fetched": len(remote_wos),
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_seo_property_sweep_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    """
    Sweep all active properties without an active SEO draft and submit them to
    the extraction pipeline. Each property gets one SEOPatch in "drafted" status
    per rubric. Properties already in ACTIVE_PATCH_STATUSES are skipped.

    Payload options (all optional):
      limit  (int)  – max properties to process; default: all
      dry_run (bool) – log targets but skip extraction; default: false
    """
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.seo_extraction_service import SEOExtractionSwarm
        from backend.models.seo_patch import SEOPatch, SEORubric
        from backend.models.property import Property
        from sqlalchemy import select, exists as sa_exists

        ACTIVE_PATCH_STATUSES = (
            "drafted", "grading", "needs_rewrite", "pending_human", "deployed",
        )

        payload = job.payload_json or {}
        limit = int(payload["limit"]) if payload.get("limit") is not None else None
        dry_run = bool(payload.get("dry_run", False))

        # Find active rubric
        rubric = (
            await db.execute(
                select(SEORubric).where(SEORubric.status == "active").order_by(SEORubric.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()

        if rubric is None:
            return {"error": "No active rubric found — run seed_seo_rubrics.py first", "processed": 0}

        # Properties that already have an active patch
        subq = select(SEOPatch.property_id).where(
            SEOPatch.status.in_(ACTIVE_PATCH_STATUSES),
            SEOPatch.property_id.isnot(None),
        ).scalar_subquery()

        q = (
            select(Property)
            .where(Property.is_active.is_(True))
            .where(~Property.id.in_(subq))
            .order_by(Property.name)
        )
        if limit:
            q = q.limit(limit)

        result = await db.execute(q)
        properties = result.scalars().all()

        if dry_run:
            return {
                "dry_run": True,
                "targets": [{"id": str(p.id), "name": p.name} for p in properties],
                "count": len(properties),
            }

        swarm = SEOExtractionSwarm(db)
        processed, skipped = 0, 0
        for prop in properties:
            try:
                result = await swarm.generate_initial_seo_draft(prop.id)
                if result:
                    processed += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning("seo_sweep_property_failed", property_id=str(prop.id), error=str(exc)[:200])
                skipped += 1

        return {
            "processed": processed,
            "skipped": skipped,
            "total_candidates": len(properties),
            "rubric_id": str(rubric.id),
        }

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def run_deep_entity_swarm_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.deep_entity_swarm import run_deep_entity_swarm

        return await run_deep_entity_swarm(db, payload=job.payload_json or {})

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


async def _reservation_confirmed_consumer_loop() -> None:
    """
    Redpanda/Kafka consumer for the ``reservation.confirmed`` topic.

    Sends a booking confirmation email to the guest for every confirmed
    reservation.  Runs as a long-lived background task started by the ARQ
    worker startup hook — identical lifecycle to the other background loops.
    """
    import json

    from aiokafka import AIOKafkaConsumer

    from backend.core.event_publisher import REDPANDA_BROKER
    from backend.models.property import Property
    from backend.models.reservation import Reservation
    from backend.services.smtp_dispatcher import SMTPDispatcher

    TOPIC = "reservation.confirmed"
    GROUP_ID = "arq-booking-confirmation-mailer"

    logger.info(
        "reservation_confirmed_consumer_starting", topic=TOPIC, group_id=GROUP_ID
    )
    dispatcher = SMTPDispatcher()

    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=REDPANDA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )

    try:
        await consumer.start()
        logger.info("reservation_confirmed_consumer_started", topic=TOPIC)

        async for msg in consumer:
            try:
                payload: dict = msg.value or {}
                reservation_id = payload.get("reservation_id")
                if not reservation_id:
                    continue

                async with AsyncSessionLocal() as db:
                    res = await db.get(Reservation, reservation_id)
                    if not res:
                        logger.warning(
                            "reservation_confirmed_consumer_not_found",
                            reservation_id=reservation_id,
                        )
                        continue

                    guest_email = (res.guest_email or "").strip()
                    if not guest_email:
                        logger.warning(
                            "reservation_confirmed_consumer_no_email",
                            reservation_id=reservation_id,
                        )
                        continue

                    prop = (
                        await db.get(Property, res.property_id)
                        if res.property_id
                        else None
                    )
                    property_name = prop.name if prop else "Your Cabin"

                    nights_val = None
                    if hasattr(res, "nights_count") and res.nights_count:
                        nights_val = res.nights_count
                    elif res.check_in_date and res.check_out_date:
                        nights_val = (res.check_out_date - res.check_in_date).days

                    quote_data: dict = {
                        "property_name": property_name,
                        "confirmation_code": res.confirmation_code
                        or payload.get("confirmation_code", ""),
                        "check_in_date": (
                            res.check_in_date.isoformat()
                            if res.check_in_date
                            else payload.get("check_in_date", "")
                        ),
                        "check_out_date": (
                            res.check_out_date.isoformat()
                            if res.check_out_date
                            else payload.get("check_out_date", "")
                        ),
                        "nights": nights_val,
                        "total_amount": float(
                            res.total_amount or payload.get("total_amount", 0)
                        ),
                    }

                    result = await dispatcher.send_confirmation(guest_email, quote_data)
                    logger.info(
                        "reservation_confirmation_email_dispatched",
                        reservation_id=reservation_id,
                        to=guest_email,
                        success=result.get("success"),
                        error=result.get("error"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "reservation_confirmed_consumer_message_error",
                    error=str(exc)[:400],
                )

    except asyncio.CancelledError:
        logger.info("reservation_confirmed_consumer_cancelled")
    except Exception as exc:
        logger.error(
            "reservation_confirmed_consumer_fatal", error=str(exc)[:400]
        )
    finally:
        try:
            await consumer.stop()
        except Exception:
            pass
        logger.info("reservation_confirmed_consumer_stopped")


class WorkerSettings:
    functions = [
        process_streamline_event_job,
        sync_knowledge_base_job,
        reindex_property_knowledge,
        vectorize_new_records_job,
        rebuild_history_index_job,
        run_shadow_audit_job,
        run_seo_parity_observation_job,
        run_research_scout_job,
        run_acquisition_ingestion_job,
        run_fannin_foia_ingest_job,
        run_airdna_sync_job,
        run_concierge_shadow_draft_job,
        run_hunter_queue_sweep_job,
        run_hunter_execute_job,
        run_hunter_recovery_draft_job,
        run_contract_ingestion_job,
        run_legal_graph_refresh_job,
        run_legal_extraction_job,
        run_legal_chronology_job,
        run_dispute_evidence_job,
        dispatch_copilot_email_job,
        dispatch_post_payment_docs_job,
        process_legal_vault_upload_job,
        run_legal_council_job,
        run_archive_seo_batch_job,
        run_seo_redirect_batch_job,
        run_seo_fallback_swarm_job,
        run_seo_remap_grading_job,
        run_seo_property_sweep_job,
        run_work_order_sync_job,
        run_deep_entity_swarm_job,
        refactor_legacy_html_task,
        ingest_property_media,
        # Phase F — Owner Statement jobs (also registered as cron below)
        generate_monthly_statements_job,
        send_approved_statements_job,
    ]
    # Phase F cron schedule — times in America/New_York (ARQ evaluates against
    # the WorkerSettings.timezone attribute, so cron values are local ET times)
    #   12th at 06:00 ET — generate draft statements for previous month
    #   15th at 09:30 ET — email all approved-but-not-yet-emailed statements
    cron_jobs = [
        arq_cron(generate_monthly_statements_job, day=12, hour=6,  minute=0,  second=0, run_at_startup=False),
        arq_cron(send_approved_statements_job,    day=15, hour=9,  minute=30, second=0, run_at_startup=False),
    ]
    timezone = _pytz.timezone("America/New_York")
    redis_settings = get_arq_redis_settings()
    queue_name = settings.arq_queue_name
    max_jobs = settings.arq_concurrency
    job_timeout = settings.arq_job_timeout_seconds
    keep_result = settings.arq_keep_result_seconds
    max_tries = settings.arq_max_tries
    on_startup = startup
    on_shutdown = shutdown
