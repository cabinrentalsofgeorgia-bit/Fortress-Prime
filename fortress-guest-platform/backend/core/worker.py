"""
ARQ worker entrypoints for the Fortress asynchronous engine.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import traceback
from typing import Any

import structlog
from sqlalchemy import select

from backend.core.config import settings
from backend.core.council_stream import create_council_redis, publish_council_event
from backend.core.database import AsyncSessionLocal
from backend.core.queue import get_arq_redis_settings
from backend.models.async_job import AsyncJobRun
from backend.services.async_jobs import mark_job_failed, mark_job_running, mark_job_succeeded
from backend.services.seo_deploy_consumer import SEODeployWorker
from backend.services.seo_grading_service import SEOGradingWorker
from backend.services.seo_rewrite_swarm import SEORewriteSwarmWorker
from backend.tasks.media_tasks import ingest_property_media
from backend.vrs.application.rule_engine import RuleEngine
from backend.vrs.domain.automations import StreamlineEventPayload, VRSRuleEngine
from backend.vrs.infrastructure.seo_event_bus import create_seo_event_redis

logger = structlog.get_logger(service="arq_worker")
boot_logger = logging.getLogger("arq.worker")
APP_ROOT = Path(__file__).resolve().parents[2]
SEO_CONSUMER_SPECS = (
    ("seo_grading_worker", "seo_grading_task", "seo_grading_task", SEOGradingWorker, "SEO_GRADING_CONSUMER_ENABLED"),
    ("seo_rewrite_worker", "seo_rewrite_task", "seo_rewrite_task", SEORewriteSwarmWorker, "SEO_REWRITE_CONSUMER_ENABLED"),
    ("seo_deploy_worker", "seo_deploy_task", "seo_deploy_task", SEODeployWorker, "SEO_DEPLOY_CONSUMER_ENABLED"),
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


async def startup(ctx: dict[str, Any]) -> None:
    ctx["app_root"] = APP_ROOT
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
            return

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
        await mark_job_running(db, job, attempts=job_try)
        try:
            result = await runner(db, job)
        except Exception as exc:
            logger.exception("async_job_failed", job_id=job_id, job_name=job.job_name)
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
        )
        return {"shadow_audit": result}

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


async def run_deep_entity_swarm_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    async def runner(db, job: AsyncJobRun) -> dict[str, Any]:
        from backend.services.deep_entity_swarm import run_deep_entity_swarm

        return await run_deep_entity_swarm(db, payload=job.payload_json or {})

    return await _with_job(job_id, int(ctx.get("job_try", 1)), runner)


class WorkerSettings:
    functions = [
        process_streamline_event_job,
        sync_knowledge_base_job,
        reindex_property_knowledge,
        vectorize_new_records_job,
        rebuild_history_index_job,
        run_shadow_audit_job,
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
        run_deep_entity_swarm_job,
        ingest_property_media,
    ]
    redis_settings = get_arq_redis_settings()
    queue_name = settings.arq_queue_name
    max_jobs = settings.arq_concurrency
    job_timeout = settings.arq_job_timeout_seconds
    keep_result = settings.arq_keep_result_seconds
    max_tries = settings.arq_max_tries
    on_startup = startup
    on_shutdown = shutdown
