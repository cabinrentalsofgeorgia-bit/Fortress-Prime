# Fortress Legal Runtime Map

Last updated: 2026-05-03
Status: canonical runtime map, documentation-only foundation pass
Scope: Fortress Legal runtime surfaces inside Fortress Prime

This map records what the repository currently says about Fortress Legal runtime shape. It does not create features, change services, or decide open conflicts by assumption.

## Reading Rules

- **Authoritative** means the repo has a current code path, migration, or locked architecture document that callers already depend on.
- **Target** means a documented destination state that is not proven as the current runtime.
- **Legacy** means a prior or fallback path that still exists in code/docs and may still be reachable.
- **CONFLICT** marks facts that disagree. The conflict is preserved until an operator or follow-up PR resolves it.

Primary evidence reviewed:

- `CLAUDE.md`
- `docs/architecture/FORTRESS-LEGAL-CONSTITUTION.md`
- `docs/architecture/shared/infrastructure.md`
- `docs/architecture/shared/postgres-schemas.md`
- `docs/architecture/shared/qdrant-collections.md`
- `docs/architecture/cross-division/ADR-003-inference-cluster-topology.md`
- `docs/operational/spark-1-legal-migration-runbook.md`
- `docs/operational/spark1-current-state-2026-04-29.md`
- `docs/operational/qdrant-legal-audit-2026-04-29.md`
- `docs/operational/track-a-v3-case-i-vs-v2-regression-2026-05-02.md`
- `docs/operational/fortress-legal-runtime-ownership-audit-2026-05-03.md`
- `deploy/systemd/*`, `deploy/litellm_config.yaml`, `deploy/fortress-prime-compose.yaml`
- `fortress-guest-platform/backend/core/config.py`
- `fortress-guest-platform/backend/core/qdrant.py`
- `fortress-guest-platform/backend/core/vector_db.py`
- `fortress-guest-platform/backend/main.py`
- `fortress-guest-platform/backend/api/legal_*.py`
- `fortress-guest-platform/backend/services/legal_*.py`
- `fortress-guest-platform/backend/services/ediscovery_agent.py`
- `fortress-guest-platform/backend/services/ingest_run_tracker.py`
- `fortress-guest-platform/backend/services/qdrant_dual_writer.py`
- `fortress-guest-platform/backend/scripts/vault_ingest_legal_case.py`
- `fortress-guest-platform/backend/scripts/email_backfill_legal.py`

## 1. Spark Host Roles

| Host | Current / documented role | Fortress Legal runtime meaning | Conflicts and notes |
|---|---|---|---|
| `spark-1` | Target single-tenant Fortress Legal app host. Spark-1 current-state doc says Postgres, Redis, OCR, Python deps, and schema-only DBs exist. | **Target authority** for eventual legal isolation. | **CONFLICT:** migration docs say Legal belongs on Spark-1, but current-state capture says no service consumes Spark-1 Postgres yet and app wiring is incomplete. Treat as target, not proven current runtime. |
| `spark-2` | Current app/control-plane host. Tailscale access host for operator sessions. Docs place FastAPI, Postgres, Qdrant legal, Redis, ARQ, LiteLLM, command/control services here. | **Current practical runtime** for Fortress Prime and Legal until Spark-1 migration is completed and verified. | **CONFLICT:** shared infrastructure says Legal target is Spark-1, but operational runbook says the stack still runs on Spark-2 today. |
| `spark-3` | Mixed current/planned inference host. Some docs say planned Ray worker; deploy files include `fortress-nim-embed.service`. | Embedding/inference support host for legal retrieval in newer docs. | **CONFLICT:** host is described both as planned worker and active embed service (`:8102`) participant. Verify live systemd before treating it as mandatory. |
| `spark-4` | Planned inference worker and/or VRS Qdrant host. Deploy includes `fortress-qdrant-vrs.service`. | Secondary Qdrant for VRS dual-write, not primary legal store. | **CONFLICT:** docs describe Spark-4 as planned wipe/worker and also as active `192.168.0.106:6333` VRS Qdrant target. |
| `spark-5` | Active BRAIN/frontier inference in several current docs; newer Phase 9 docs also describe legal aliases routed through a Spark-3+4 TP=2 endpoint. | Legal reasoning/drafting may route through LiteLLM aliases backed by Spark-5 or Spark-3+4 depending on cutover status. | **CONFLICT:** older docs place 49B BRAIN on Spark-5; Phase 9 docs say BRAIN-49B retired and legal aliases route to Spark-3+4. Runtime must be checked against live LiteLLM config before legal run. |
| `spark-6` | Staged inference worker; cable pending in shared docs. | No authoritative Legal runtime dependency. | Treat as future capacity until live service evidence exists. |

Canonical conclusion: Fortress Legal's **target** isolation host is Spark-1, but the **current operational control plane** remains Spark-2 unless a later cutover document proves otherwise.

Live audit note: `docs/operational/fortress-legal-runtime-ownership-audit-2026-05-03.md` verified this current-state call on 2026-05-03. Spark-2 showed active backend, ARQ, command-center, Postgres, Redis, Qdrant, LiteLLM, Ollama, Ray head, and sync/indexing services. Spark-1 was reachable and running Postgres/Redis/NIM/Ollama/Ray worker, but no Legal backend, ARQ, command-center, Qdrant, or LiteLLM runtime was observed.

## 2. Database Names And Purposes

| Database | Purpose | Main callers | Authority / risk |
|---|---|---|---|
| `fortress_db` | Operational legal database for runtime legal services, e-discovery, mail/event ledger, `LegacySession`, and `legal.ingest_runs`. | `backend/services/ediscovery_agent.py`, `legal_mail_ingester.py`, `legal_dispatcher.py`, `ingest_run_tracker.py`, legal APIs. | **Authoritative for many Legal runtime writes today.** |
| `fortress_prod` | Canonical/mirror target for legal case metadata and production mirror rows. `vault_ingest_legal_case.py` treats `legal.cases.nas_layout` here as source of truth for batch ingest layout. | legal ingestion scripts, mirror writers, `hold_service.py`, Spark-1 mirror paths. | **Authoritative for case layout during batch ingest.** Mirror drift must be visible. |
| `fortress_shadow` | Runtime VRS/booking/control-plane DB for `AsyncSessionLocal` under current config. | General backend API/session contract, VRS, booking, owner/guest surfaces. | **Not the main legal operational DB.** It remains important because shared backend sessions default here in parts of the app. |
| `fortress_shadow_test` | Isolated test DB. | Test fixtures through `TEST_DATABASE_URL`. | Required for safe CI/test writes. |
| `fortress_pr366_schema_tmp` | Temporary schema snapshot DB used during PR #366 CI refresh. | CI/schema-dump only. | Not runtime. |
| `fortress_guest` | Legacy/dev compose DB name. | `deploy/fortress-prime-compose.yaml` and older scripts/docs. | **Legacy/conflicting.** Not canonical production. |

Current DB contract from `backend/core/config.py`:

- `POSTGRES_API_URI` is the runtime API DSN and should use role `fortress_api`.
- `POSTGRES_ADMIN_URI` is the admin/Alembic/script DSN and should use role `fortress_admin`.
- `TEST_DATABASE_URL` should point to `fortress_shadow_test` for tests.
- Allowed DB names are `fortress_prod`, `fortress_shadow`, `fortress_db`, and `fortress_shadow_test`.
- Allowed Postgres port is `5432`.

CONFLICT: `deploy/fortress-prime-compose.yaml` still defines `DATABASE_URL` against `fortress_guest` with an old role. Treat that compose file as a legacy/dev baseline unless it is brought forward to the current contract.

CONFLICT: Spark-1 current-state docs show `fortress_db`, `fortress_prod`, and `fortress_shadow_test` created on Spark-1, but `fortress_shadow` absent and no service wired to those DBs yet.

## 3. Qdrant Collections And Aliases

Primary Qdrant URL in code defaults to `http://localhost:6333`. Docs identify this as Spark-2 legal Qdrant. VRS secondary defaults to `http://192.168.0.106:6333`.

| Collection / alias | Vector size | Purpose | Current authority / conflict |
|---|---:|---|---|
| `legal_ediscovery` | 768 in legacy code/audit | Work-product and nonprivileged legal vault chunks. Hardcoded in `legal_ediscovery.py` and `vault_ingest_legal_case.py`. | **Legacy code authority.** Operational audit reported 738,918 points on 2026-04-29. |
| `legal_ediscovery_v2` | 2048 | Reindexed legal e-discovery collection using `legal-embed`. | **New retrieval authority per 2026-05-02 regression doc only when callers use alias.** |
| `legal_ediscovery_active` | alias | Qdrant alias documented as swapped to `legal_ediscovery_v2`. | **CONFLICT:** regression docs call alias swap canonical; ingest code still hardcodes `legal_ediscovery`. Verify all retrieval callers before treating v2 as universal runtime. |
| `legal_privileged_communications` | 768 | Physically separate privileged communications collection. | Hardcoded privileged path in `legal_ediscovery.py`. Audit reported 241,167 points. |
| `legal_privileged_communications_v2` | 2048 | Reindexed privileged collection. | Reindex complete but quality report says cutover deferred. Legacy collection remains active. |
| `legal_caselaw` | 768 | Georgia/state caselaw. | Audit reported 2,711 points. Some docs later accept `legal_caselaw_v2` for caller cutover. |
| `legal_caselaw_v2` | 2048 | Reindexed caselaw. | Accepted by quality report for cutover, but confirm caller code before relying on it. |
| `legal_caselaw_federal` | unknown/absent | Federal/11th Circuit caselaw target. | **CONFLICT:** older docs say empty/awaiting ingest; Qdrant audit says collection does not exist. |
| `legal_caselaw_federal_v2` | 2048 | Schema-only future federal collection. | Documented empty; no authoritative callers. |
| `legal_library` | 768 | Legacy legal-library corpus. | Audit reported only 3 points; older docs report larger/stale counts. |
| `legal_library_v2` | 2048 | Reindexed legal library. | Accepted for caller cutover in quality report. |
| `legal_headhunter_memory` | unknown | Counsel/recruiting memory. | Audit reported 0 points. |
| `legal_headhunter_memory_v2` | 2048 | Future/reindexed schema-only collection. | No content. |
| `legal_hive_mind_memory` | unknown | Hive-mind/drafting memory. | Audit reported 4 points. |
| `fgp_knowledge` | 768 | General Fortress knowledge collection from `QDRANT_COLLECTION_NAME` default. | Shared non-legal app knowledge. |
| `fgp_vrs_knowledge` | 768 | VRS secondary dual-write collection on Spark-4 Qdrant. | Controlled by `ENABLE_QDRANT_VRS_DUAL_WRITE` and `READ_FROM_VRS_STORE`. |
| `email_embeddings`, `fgp_sent_mail`, `fortress_knowledge` | varied | Email/general knowledge collections in older docs. | Not the canonical legal vault path. |

Model/service aliases used by Legal:

- `legal-embed` is the sovereign embedding alias in newer docs; retrieval-side calls need `input_type=query`, ingest-side calls need `input_type=passage`.
- `legal-reasoning`, `legal-drafting`, `legal-summarization`, `legal-classification`, and `legal-brain` are LiteLLM/legal inference aliases documented for Council/drafting routes.
- CONFLICT: older docs place legal frontier on Spark-5 BRAIN; Phase 9 docs place aliases on Spark-3+4 TP=2. Check live `deploy/litellm_config.yaml` and running gateway before major legal generation.

## 4. NAS Roots And Legal Source Drops

Authoritative locked NAS layout from the Fortress Legal Constitution:

| Root | Purpose | Authority |
|---|---|---|
| `/mnt/fortress_nas/legal_vault/<case_slug>/` | Stored NFS vault copies after ingest. | Used by `process_vault_upload()` through `NAS_VAULT_ROOT`. |
| `/mnt/fortress_nas/Corporate_Legal/Business_Legal/<case_slug>/` | Curated case source folders and generated briefing output. | Locked in Constitution and populated in `legal.cases.nas_layout` for Case I/II. |
| `/mnt/fortress_nas/intel/judges/<court>/<judge-slug>.md` | Judge intelligence. | Locked intel layout. |
| `/mnt/fortress_nas/intel/firms/<firm-slug>.md` | Firm intelligence. | Locked intel layout. |
| `/mnt/fortress_nas/intel/attorneys/<attorney-slug>.md` | Attorney intelligence. | Locked intel layout. |
| `/mnt/fortress_nas/audits/` | Script manifests and audit output. | Used by legal ingest scripts. |
| `/mnt/fortress_nas/models/` and `/mnt/fortress_nas/nim-cache/` | Model storage/cache. | Infrastructure/model layer. |
| `/mnt/fortress_nas/legal-corpus/` and `/mnt/fortress_nas/datasets/legal-corpus/` | Courtlistener/rules/static legal corpora. | Corpus source, not case evidence source by default. |

Case source-drop authority for Wave 7 / Case I and II:

| Case slug | Source root | Include subdirs | Exclude rule |
|---|---|---|---|
| `7il-v-knight-ndga-i` | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i` | `curated`, `case-i-context` | Do not use legacy mixed dump. |
| `7il-v-knight-ndga-ii` | `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii` | `curated` | Do not use legacy mixed dump. |
| `vanderburge-v-knight-fannin` | case-specific configured row | not locked in this map | Keep untouched until scoped. |
| `fish-trap-suv2026000013` | case-specific configured row | not locked in this map | Keep untouched until scoped. |

Authoritative scoping rule: Case I and Case II ingest should walk the curated `Corporate_Legal/Business_Legal/<slug>` paths only. The legacy mixed dump `/mnt/fortress_nas/legal_vault/7il-v-knight-ndga/` must not be used as a source for rebuilding Case II.

CONFLICT: `backend/api/legal_cases.py` still has fallback/older layout logic rooted at `/mnt/fortress_nas/sectors/legal/<slug>` and expects `nas_layout` shaped as `{root, subdirs, recursive}`. `vault_ingest_legal_case.py` supports both the old shape and the newer `{primary_root, include_subdirs, exclude_subdirs}` shape. The UI/API file-browser path may not match the batch-ingest source-of-truth shape until reconciled.

CONFLICT: `legal_ediscovery.py` stores uploaded vault copies under `/mnt/fortress_nas/legal_vault`, while `LEGAL_VAULT_ROOT` in config defaults to `/mnt/fortress_nas/sectors/legal`. Treat `/mnt/fortress_nas/legal_vault` as the active process-vault-upload storage path, and treat `sectors/legal` as legacy/API fallback unless resolved.

## 5. Backend Services

Primary backend entry point:

- `fortress-guest-platform/backend/main.py` builds the FastAPI app.
- Internal Legal API prefix is `/api/internal/legal`.
- Systemd service `deploy/systemd/fortress-backend.service` starts the backend through `run-fortress-backend.sh` with env files from the app directory and `/etc/fortress/secrets` overlays.

Legal routers included by the backend include:

- `backend/api/legal_cases.py`
- `backend/api/ediscovery.py`
- `backend/api/legal_graph.py`
- `backend/api/legal_discovery.py`
- `backend/api/legal_council.py`
- `backend/api/legal_docgen.py`
- `backend/api/legal_strategy.py`
- `backend/api/legal_counsel_dispatch.py`
- `backend/api/legal_hold.py`
- `backend/api/legal_tactical.py`
- `backend/api/legal_sanctions.py`
- `backend/api/legal_deposition.py`
- `backend/api/legal_agent.py`
- `backend/api/legal_email_intake_api.py`

Important legal services and scripts:

| Service/script | Purpose | Runtime dependency |
|---|---|---|
| `backend/services/legal_ediscovery.py` | Canonical single-file vault upload, privilege classification, text extraction, chunking, embedding, Qdrant upsert. | `fortress_db` session through caller, NAS vault root, Qdrant, embedding endpoint, Ollama/SWARM classifier. |
| `backend/scripts/vault_ingest_legal_case.py` | Case-scoped batch ingest from `legal.cases.nas_layout`. | `POSTGRES_ADMIN_URI`, `fortress_prod`, `fortress_db`, Qdrant, NAS source roots, audit manifest path. |
| `backend/services/ingest_run_tracker.py` | Writes `legal.ingest_runs` lifecycle records. | Defaults to `fortress_db`; `INGEST_RUN_DB` can override. |
| `backend/services/ediscovery_agent.py` | Legal/e-discovery read surface using `LegacySession`. | Targets `fortress_db`. |
| `backend/services/legal_council.py` | Council deliberation, legal retrieval, drafting/reasoning seats. | LiteLLM aliases, Qdrant legal collections, case context. |
| `backend/services/legal_mail_ingester.py` | Multi-mailbox legal mail ingestion and bilateral mirror. | `fortress_db`, `fortress_prod`, mail credentials, legal event log. |
| `backend/services/legal_email_intake.py` | Dedicated legal email intake service. | `fortress_db` via `LegacySession`, MailPlus settings. |
| `backend/services/legal_dispatcher.py` | FLOS/legal event dispatcher. | `fortress_db` primary, `fortress_prod` mirror, optional Spark-1 mirror. |
| `backend/scripts/email_backfill_legal.py` | Email/document backfill into legal vault paths. | `POSTGRES_ADMIN_URI`, both legal DBs, process-vault-upload. |
| `backend/scripts/ocr_legal_case.py` | OCR support for legal case documents. | NAS source, OCR runtime, legal DB/Qdrant as scripted. |
| `backend/scripts/track_a_case_i_runner.py` and `case_briefing_cli.py` | Legal brief/regression generation. | Legal Qdrant alias, LiteLLM/frontier, NAS output root. |

Systemd/deploy services with runtime relevance:

- `fortress-backend.service` - FastAPI backend.
- `fortress-arq-worker.service` - async worker.
- `fortress-deadline-sweeper.service` / timer - legal deadline sweep.
- `fortress-dashboard.service` - internal dashboard/command-center surface.
- `fortress-qdrant-vrs.service` - VRS secondary Qdrant host.
- `fortress-nim-brain.service`, `fortress-nim-embed.service`, `fortress-vllm-adapter.service` - inference/embedding support.

## 6. Frontend Surfaces

Constitution and `CLAUDE.md` both require strict zone separation:

| Zone | Domain/app | Purpose | Legal rule |
|---|---|---|---|
| Zone A public | `cabin-rentals-of-georgia.com`, `apps/storefront` | Public lodging/storefront and guest booking. | Must not expose privileged legal command surfaces. |
| Zone B internal | `crog-ai.com`, `apps/command-center` | Staff, command center, AI/legal operators. | Fortress Legal should live here. |

Current Legal command-center surfaces found in `apps/command-center` include:

- `/legal`
- `/legal/cases/[slug]`
- `/legal/council`
- `/legal/email-intake`
- `/legal/war-room`
- `/legal/deposition/[targetId]/print`
- Legal components such as e-discovery dropzone, document viewer, counsel matrix, deposition war-room, discovery draft panel, graph snapshot, sanctions tripwire, hive-mind editor, inference radar, jurisprudence radar, and agent terminal.

CONFLICT / risk: `apps/storefront` contains shared legal hooks/types/tests in some places, and older `frontend-next` / legacy dashboard files contain legal discovery/damage-claim UI remnants. Treat command-center as authoritative for privileged Legal UI; audit any storefront legal imports before exposing or deploying.

## 7. Legal Ingest Flow

Canonical batch flow for a case-scoped vault ingest:

1. Operator runs `backend/scripts/vault_ingest_legal_case.py` with a `--case-slug`.
2. Script loads environment from `fortress-guest-platform/.env` if needed.
3. Script checks the case slug exists in both `fortress_prod.legal.cases` and `fortress_db.legal.cases`.
4. Script treats `fortress_prod.legal.cases.nas_layout` as the source-of-truth source layout.
5. Script verifies source directories exist and `legal.ingest_runs` is writable.
6. Script checks Qdrant collection reachability and expected vector size.
7. Script walks only the configured NAS subdirs, deduping by resolved physical path and skipping system/dot paths.
8. Script hashes each file and skips terminal statuses already in `legal.vault_documents`.
9. For each file, script calls `process_vault_upload()`.
10. `process_vault_upload()` stores/copies the file under `/mnt/fortress_nas/legal_vault/<case_slug>/` or local fallback.
11. `process_vault_upload()` inserts/updates `legal.vault_documents`.
12. Privilege classification runs before general vectorization.
13. Privileged material is logged to `legal.privilege_log`, marked `locked_privileged`, and upserted to `legal_privileged_communications`.
14. Nonprivileged material is extracted, chunked, embedded, and upserted to `legal_ediscovery` in the legacy code path.
15. Qdrant failures mark rows `qdrant_upsert_failed` instead of silently succeeding.
16. Batch script mirrors written vault rows from `fortress_db` to `fortress_prod`.
17. `IngestRunTracker` writes one `legal.ingest_runs` lifecycle record.
18. Script writes a JSON manifest under `/mnt/fortress_nas/audits/`.

Rollback behavior: `vault_ingest_legal_case.py --rollback` deletes case `legal.vault_documents` rows in both `fortress_db` and `fortress_prod`, and deletes Qdrant points whose payload `case_slug` matches. It requires explicit confirmation unless forced.

CONFLICT: the script usage example still shows legacy slug `7il-v-knight-ndga`; canonical Case I/II slugs are `7il-v-knight-ndga-i` and `7il-v-knight-ndga-ii`.

CONFLICT: v2 retrieval docs say `legal_ediscovery_active` points at `legal_ediscovery_v2`, but the single-file ingest service still writes to hardcoded `legal_ediscovery`. That may be correct during a staged v1/v2 transition, but it is an open runtime contract until documented in code.

## 8. Required Environment Variables

Do not store real secrets in repo files. The names below are runtime contract names, not values.

### Database

- `POSTGRES_API_URI`
- `POSTGRES_ADMIN_URI`
- `TEST_DATABASE_URL`
- `INGEST_RUN_DB` optional override
- `SPARK1_DATABASE_URL` optional Spark-1 mirror target
- `LEGAL_M3_SPARK1_MIRROR_ENABLED`
- `DELIBERATION_LEDGER_DATABASE_URL` or `FORTRESS_DELIBERATION_DSN` for legal deliberation ledger overrides

### Qdrant And Embeddings

- `QDRANT_URL`
- `QDRANT_API_KEY`
- `QDRANT_COLLECTION_NAME`
- `QDRANT_VRS_URL`
- `ENABLE_QDRANT_VRS_DUAL_WRITE`
- `READ_FROM_VRS_STORE`
- `EMBED_BASE_URL`
- `EMBED_MODEL`
- `EMBED_DIM`
- `RECURSIVE_EMBED_URL`

### Inference / Gateway

- `LITELLM_BASE_URL`
- `LITELLM_MASTER_KEY`
- `INTERNAL_API_BASE_URL`
- `INTERNAL_API_TOKEN`
- `SWARM_API_KEY`
- `OLLAMA_BASE_URL`
- `OLLAMA_FAST_MODEL`
- `OLLAMA_DEEP_MODEL`
- `BRAIN_BASE_URL`
- `DGX_INFERENCE_URL`
- `DGX_INFERENCE_MODEL`
- `DGX_INFERENCE_API_KEY`
- `LEGAL_DISCOVERY_CHAT_URL`
- `LEGAL_DISCOVERY_CHAT_MODEL`
- `LEGAL_DISCOVERY_API_KEY`

### Legal/NAS

- `LEGAL_VAULT_ROOT`
- `CASE_BRIEFING_OUTPUT_ROOT`
- `LEGAL_PERSONAS_DIR`
- `CONCIERGE_PERSONAS_DIR`
- `LEGAL_DISCOVERY_MAX_ITEMS`
- `LEGAL_GRAPH_MAX_NODES`
- `LEGAL_DISCOVERY_FOIA_ENABLED`
- `LEGAL_PROPORTIONALITY_MODE`
- `LEGAL_TRIPWIRE_*`
- `LEGAL_DEPOSITION_*`

### Email Intake

- `LEGAL_EMAIL_INTAKE_ENABLED`
- `LEGAL_MAILPLUS_HOST`
- `LEGAL_MAILPLUS_PORT`
- `LEGAL_MAILPLUS_USER`
- `LEGAL_MAILPLUS_PASSWORD`
- `LEGAL_MAILPLUS_FOLDER`
- `LEGAL_EMAIL_POLL_INTERVAL`
- `LEGACY_LEGAL_INTAKE_ENABLED`
- `LEGAL_MAIL_INGESTER_ENABLED`
- `LEGAL_DISPATCHER_ENABLED`
- `MAILBOXES_CONFIG`
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `IMAP_HOST`
- `IMAP_USER`
- `IMAP_APP_PASSWORD`
- `MAILPLUS_IMAP_HOST`
- `MAILPLUS_IMAP_PORT`
- `MAILPLUS_IMAP_PASSWORD`

### Auth / Security / Audit

- `JWT_RSA_PRIVATE_KEY`
- `JWT_RSA_PUBLIC_KEY`
- `JWT_SECRET_KEY` legacy fallback only
- `AUDIT_LOG_SIGNING_KEY`
- `S3_ENDPOINT_URL`
- `S3_BUCKET_NAME`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`
- `S3_PUBLIC_BASE_URL`

## 9. Known Open Questions

1. Has Fortress Legal actually cut over from Spark-2 to Spark-1, or is Spark-1 still a staged target with schema-only DBs?
2. Which live LiteLLM alias map is authoritative now: Spark-5 BRAIN-era or Spark-3+4 TP=2 Phase 9?
3. Should legal ingest write directly to `legal_ediscovery_v2` / `legal_ediscovery_active`, or is legacy `legal_ediscovery` intentionally retained as ingest source with separate reindex?
4. Are Qdrant aliases managed in code/config, or only by operator/manual Qdrant API calls?
5. Should `legal_cases.py` support the new `nas_layout` shape (`primary_root`, `include_subdirs`, `exclude_subdirs`) used by the migration and batch ingest script?
6. Should `/mnt/fortress_nas/sectors/legal` remain an active legal file root or be marked legacy-only?
7. Which DB is the legal case metadata source of truth after Spark-1 migration: `fortress_prod`, `fortress_db`, or Spark-1 `fortress_prod` mirror?
8. What is the exact production Qdrant storage path and snapshot/backup policy for privileged collections?
9. Should storefront legal hooks/types be removed, isolated, or explicitly documented as shared nonprivileged client code?
10. Are `legal_caselaw_v2` and `legal_library_v2` already cut over in all caller code, or only accepted for future caller cutover?
11. What is the retention and access-control policy for `legal_privileged_communications_v2`, given cutover was deferred but the collection exists?
12. Does `vault_ingest_legal_case.py` pass current syntax/tests after the schema reconciliation work, and are its docstring examples updated to Case I/II slugs?
13. Should `deploy/fortress-prime-compose.yaml` be updated to the current Postgres contract or explicitly moved to legacy/dev docs?

## 10. Authoritative Versus Legacy

### Authoritative Now

- Fortress Legal Constitution: `docs/architecture/FORTRESS-LEGAL-CONSTITUTION.md`.
- Internal legal UI belongs to `apps/command-center`, not public storefront.
- Current DB config contract: `POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`, `TEST_DATABASE_URL`, roles `fortress_api` / `fortress_admin`.
- Allowed DB names from config: `fortress_prod`, `fortress_shadow`, `fortress_db`, `fortress_shadow_test`.
- `legal.cases` keyed by `case_slug` with `related_matters`, `privileged_counsel_domains`, and `nas_layout`.
- `legal.ingest_runs` for ingest lifecycle tracking.
- `process_vault_upload()` as the canonical single-file vault ingestion function.
- `vault_ingest_legal_case.py` as the case-scoped batch ingest wrapper.
- Curated Case I/II source drops under `/mnt/fortress_nas/Corporate_Legal/Business_Legal/<slug>/`.
- Privileged communications must stay physically separated from ordinary e-discovery search.
- Spark-2 is the current practical operator/control-plane host until Spark-1 cutover is proven.

### Authoritative Target, Not Proven Current

- Spark-1 as single-tenant Fortress Legal app host.
- Spark-1 Postgres as legal runtime DB host.
- `legal_ediscovery_active -> legal_ediscovery_v2` as universal retrieval target for every caller.
- Spark-3+4 TP=2 as the only legal frontier endpoint.

### Legacy / Risky Until Reconciled

- `deploy/fortress-prime-compose.yaml` with `fortress_guest`, `DATABASE_URL`, and old roles.
- `/mnt/fortress_nas/sectors/legal` legal file root defaults.
- Storefront or legacy frontend legal UI fragments that could blur public/internal zones.
- Hardcoded `legal_ediscovery` writes if the retrieval world has fully moved to v2 alias.
- Older Qdrant point counts and collection-existence claims in docs predating the 2026-04-29 audit.
- Older BRAIN/Spark role docs that place services on different hosts than newer migration/Phase 9 docs.

## Operating Rule For Next Work

Before new Fortress Legal features, resolve foundation ambiguity in this order:

1. Prove live host ownership: Spark-2 current vs Spark-1 cutover state.
2. Prove DB source-of-truth contract for Legal after PR #366/#405 era changes.
3. Prove Qdrant alias/read/write contract for `legal_ediscovery_active` and v2.
4. Reconcile `nas_layout` shape across migration, batch ingest, and legal case API.
5. Re-audit frontend zone separation so privileged Legal never leaks into public storefront surfaces.
