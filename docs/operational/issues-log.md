# Fortress-Prime Operational Issues Log

Running ledger of issues discovered during operations. Each entry: timestamp, discovery context, current state, remediation plan, status, ticket reference.

Status values: OPEN | IN-PROGRESS | DEFERRED | RESOLVED | DUPLICATE

---

## 2026-04-27

### Issue: GRANT drift between fortress_db and fortress_prod

- **Discovered:** during Phase 1-5 cutover Step 1 (CLI dispatcher status retry)
- **Symptom:** asyncpg.InsufficientPrivilegeError for table dispatcher_routes
- **Root cause:** f3d6a1b8c9e2 privilege reconciliation migration applied to fortress_prod hand-fix at unknown past date, never recorded in alembic_version, never applied to fortress_db
- **Remediation:** R7 applied 5-statement GRANT + ALTER DEFAULT PRIVILEGES SQL to fortress_db only (fortress_prod already correct)
- **Verified:** byte-for-byte parity on \dp output between fortress_db and fortress_prod for legal schema
- **Status:** RESOLVED
- **Ticket:** GH #258 (T2 — alembic chain reconciliation tracks the underlying tracking gap)

### Issue: /api/internal/* JWT vs static bearer middleware conflict

- **Discovered:** during Phase 1-5 cutover Step 2 (HTTP health endpoint curl)
- **Symptom:** HTTP 401 with RFC 7807 problem-details shape; global JWT middleware rejects static bearer before endpoint's _enforce_internal_auth helper at backend/api/legal_dispatcher_health.py:149-182 reached
- **Root cause:** two-layer auth conflict — global JWT middleware doesn't exempt /api/internal/* paths
- **Remediation:** deferred — Phase 1-5 cutover proceeded using CLI status as operationally equivalent validation
- **Status:** OPEN
- **Ticket:** GH #257

### Issue: MAILBOXES_CONFIG missing ingester field

- **Discovered:** during Phase 1-5 cutover Step 7 (waiting for first event)
- **Symptom:** legal_mail_ingester started with mailbox_count=0; no events flowing
- **Root cause:** Phase 0a-2 design required MAILBOXES_CONFIG entries to carry `"ingester": "legal_mail"` field; runbook omitted this prerequisite
- **Remediation:** added field to legal-cpanel entry only (other 3 mailboxes intentionally unchanged); worker re-restarted; mailbox_count=1 verified
- **Status:** RESOLVED
- **Note:** Update Phase 0a-2 runbook to include MAILBOXES_CONFIG ingester-tagging step

### Issue: Captain gary-crog mailbox unknown-8bit encoding errors

- **Discovered:** during Phase 1-5 cutover Step 5 boot log review (pre-existing condition)
- **Symptom:** captain_imap_fetch_error error='unknown encoding: unknown-8bit' on ~10 message IDs (130474, 130482-130514)
- **Root cause:** non-standard MIME charset declaration in inbound mail; Captain drops affected messages
- **Remediation:** deferred; not blocker for FLOS cutover
- **Status:** OPEN
- **Ticket:** GH #259

### Issue: Captain gary-gk SEARCH overflow

- **Discovered:** during Phase 1-5 cutover Step 5 boot log review (pre-existing condition)
- **Symptom:** captain_imap_final_failure error='command: SEARCH => got more than 1000000 bytes' on gary-gk mailbox
- **Root cause:** mailbox SEARCH result exceeds IMAP client buffer
- **Remediation:** deferred; not blocker for FLOS cutover
- **Status:** OPEN
- **Ticket:** GH #260

### Issue: Stale FORTRESS_DB_* credentials in .env

- **Discovered:** during Phase 1-6 soak script setup
- **Symptom:** psql connection as FORTRESS_DB_USER (miner_bot) fails with password authentication failed
- **Root cause:** broken-out FORTRESS_DB_USER + FORTRESS_DB_PASS keys never matched postgres state; worker uses URI-form credentials instead so runtime not affected
- **Remediation:** patched soak_check.sh to read POSTGRES_ADMIN_URI instead; .env keys themselves not modified
- **Status:** OPEN
- **Note:** File ticket T5 — either repair keys or remove them from .env

### Issue: soak_check.sh initial credential bug

- **Discovered:** during Phase 1-6 soak script +0h baseline run
- **Symptom:** BLOCKED state logged with UNKNOWN-DB-ERROR; soak_alert.flag created
- **Root cause:** script wired to FORTRESS_DB_* keys (see above)
- **Remediation:** patched script to use POSTGRES_ADMIN_URI; timers stopped + re-armed; +0h baseline re-run
- **Status:** RESOLVED
- **Note:** see "Stale FORTRESS_DB_* credentials" above for underlying issue

### Issue: running fortress-backend lacks FLOS endpoints (Gap A)

- **Discovered:** during command-center ↔ FLOS pipeline audit (2026-04-27 evening)
- **Symptom:** `curl http://127.0.0.1:8000/openapi.json` → 0 FLOS endpoints registered (no dispatcher_*, mail/health, event_log, case_posture, legal_mail_*, legal_dispatcher_*). 80 legacy `/api/internal/legal/*` endpoints (cases, deadlines, council, etc.) are registered.
- **Root cause:** `fortress-backend.service` started Sun 2026-04-26 21:07 EDT against `main` HEAD `b458d8867`, which predates today's FLOS Phase 1-3 / 1-4 / 1-5 work. Today's PRs are on `feat/flos-phase-1-*` branches and have not merged to main. uvicorn caches imports at startup; the source files exist on the working tree (feat branch checkout) but the running process never imported them.
- **Remediation options:** (A1) merge FLOS feat branches to main and restart `fortress-backend`; (A2) restart against current feat-branch working tree without merge; (A3) defer until Phase 1-6 soak completes.
- **Recommended:** A1 after Phase 1-6 soak validates end-to-end flow.
- **Status:** OPEN
- **Ticket:** N/A (operational/deployment state, not a code defect)
- **Note:** Gap B (#257 JWT/static-bearer) is moot until this is resolved — the endpoint must be registered before middleware order matters.

### Issue: command-center has zero FLOS UI surface (Gap C)

- **Discovered:** during command-center ↔ FLOS pipeline audit
- **Symptom:** `grep -rnE '/api/internal/legal/(dispatcher|mail)/' apps/command-center/src/` returns 0 hits. None of the 8 FLOS surfaces (event_log, case_posture, dispatcher_routes, dispatcher_event_attempts, dispatcher_dead_letter, dispatcher_pause, legal_mail_ingester health, legal_dispatcher health) have a UI consumer.
- **Root cause:** today's work was scoped backend-only. UI not in Phase 1-x design.
- **Remediation options:** (G1) add `/legal/flos` page consuming dispatcher/mail health + dead-letter + posture endpoints (~1-2 days, requires Gap A + B closed); (G2) defer UI for now, observe via psql/CLI/soak log only; (G3) add minimal ops widget to existing `/legal` dashboard.
- **Recommended:** G2 through Phase 1-6 soak window; revisit G1 vs G3 after soak completes.
- **Status:** DEFERRED
- **Ticket:** N/A (deferred sprint item)

### Issue: crog-ai-backend README claims Vercel hosting but reality is self-hosted

- **Discovered:** during command-center ↔ FLOS pipeline audit
- **Symptom:** `crog-ai-backend/README.md` describes "Vercel (React frontend at crog-ai.com)". Reality: crog-ai.com is served by self-hosted Next.js 16 standalone build on spark-2 port 3005 via Cloudflare Tunnel. Confirmed via `ss -tlnp`, `/proc/<pid>/cwd`, and `/etc/cloudflared/config.yml`.
- **Root cause:** doc drift — README never updated when hosting model migrated from Vercel to self-hosted.
- **Remediation:** update `crog-ai-backend/README.md` in next docs sweep to describe Cloudflare Tunnel + self-hosted Next.js architecture.
- **Status:** OPEN
- **Ticket:** N/A — defer to docs sweep; low priority.

### Issue: command-center has `pg` runtime dep + DATABASE_URL — potential CLAUDE.md violation

- **Discovered:** during command-center ↔ FLOS pipeline audit
- **Symptom:** `apps/command-center/package.json` lists `"pg": "^8.20.0"` as runtime dep. `apps/command-center/.env.local` has `DATABASE_URL`, `POSTGRES_ADMIN_URI`, `POSTGRES_API_URI`. CLAUDE.md says "the frontend must never import `pg`, `asyncpg`, `psycopg2`, or any database driver."
- **Root cause:** unknown without trace. Possibilities: (i) genuine violation — server components or BFF routes connect directly to postgres; (ii) server-side-only utility (e.g., a build script in `scripts/`) uses pg and got hoisted to the package; (iii) historical artifact, no longer imported.
- **Remediation:** trace `grep -rn "from 'pg'\\|require('pg')" apps/command-center/src/` to find live importers. If none in src, audit `apps/command-center/scripts/`. If unused, remove from dependencies.
- **Status:** OPEN
- **Ticket:** N/A — investigation needed before deciding repair vs remove.
- **Note:** if direct DB access from command-center is real, this also violates the CLAUDE.md "only authorized data path" rule (Next.js → Cloudflare Tunnel → FastAPI → Postgres).

### Issue: gh PAT cannot attach labels to issues

- **Discovered:** during T5 ticket filing verification (`gh issue view 261 --json labels`)
- **Symptom:** all 5 tickets T1–T5 (#257–#261) have empty `labels` arrays despite `gh issue create --label "..."` returning success. `gh issue edit --add-label` and `gh api POST /labels` both return HTTP 403 `Resource not accessible by personal access token`.
- **Root cause:** the active PAT (`github_pat_11B3IN7GI...`, account `cabinrentalsofgeorgia-bit`) has `issues:create` and `labels:create` scope but lacks the `addLabelsToLabelable` GraphQL mutation / REST `issues:write` scope needed to attach labels. `gh issue create --label` silently swallowed the permission failure on every create call.
- **Remediation options:** (a) attach labels manually via web UI for T1–T5 (~30s/ticket), or (b) regenerate PAT with `Issues: Read and write` scope and re-run a label-attach loop, or (c) leave unlabeled — body content is the durable record.
- **Status:** OPEN
- **Ticket:** N/A — local CLI/auth config gap, not a Fortress-Prime code issue
- **Note:** the 7 new labels created earlier in the session (`legal`, `auth`, `post-flos-cutover`, `alembic`, `imap`, `pre-existing`, `.env`) all exist on the repo — only the *attachment* failed.

### Issue: legal.cases.opposing_counsel stale for 7il-v-knight-ndga-ii

- **Discovered:** during Case II complaint extraction from Thor James inbox dump
- **Symptom:** `legal.cases.opposing_counsel` for `7il-v-knight-ndga-ii` says "Brian S. Goldberg, Esq., Freeman Mathis & Gary LLP, brian.goldberg@fmglaw.com"
- **Reality:** Complaint signature (Document 1, p.18, filed 2026-04-15) shows Buchalter LLP, 3475 Piedmont Rd NE, Suite 1100, Atlanta GA 30305, bgoldberg@buchalter.com, GA Bar 128007. Andrew Pinter co-counsel.
- **Root cause:** DB row prepared from outdated info or early-research guess; never reconciled when the operative complaint arrived from Thor James on 2026-04-23.
- **Remediation:** UPDATE legal.cases SET opposing_counsel = '<corrected JSONB>' WHERE case_slug = '7il-v-knight-ndga-ii'. Operator authorizes when ready (proposed statement in curation manifest / inline in audit response).
- **Status:** OPEN (deferred until JSONB schema migration scheduled)
- **Ticket:** GH #262
- **Note:** this drift compromises (a) the brief generator (would print wrong firm in the brief) and (b) Captain's domain-allowlist for legal-track classification (would whitelist fmglaw.com instead of buchalter.com, missing real opposing-counsel emails). Two-part fix: Part 1 schema migration text→JSONB, Part 2 data correction + audit pass across all active cases.

## 2026-04-28

### Issue: PR G phase F backend tests broke after upstream `_upsert_to_qdrant_privileged` return-shape change

- **Discovered:** re-running PR G phase F backend test suite at the start of phase G work
- **Symptom:** 3 of 37 backend tests fail (`test_upsert_to_qdrant_privileged_uses_uuid5_deterministic_ids`, `test_privileged_collection_payload_dual_field_chunk_num_and_chunk_index`, `test_process_vault_upload_routes_privileged_to_separate_collection`, `test_process_vault_upload_non_privileged_uses_work_product_collection`). All assertions about the privileged-upsert return value fail because the function now returns `tuple[list[str], Optional[dict]]` instead of `int`.
- **Root cause:** an upstream edit to `backend/services/legal_ediscovery.py` (referenced as Issue #228 in the file's comment block) changed `_upsert_to_qdrant_privileged` to return `(successful_uuids, batch_failure_descriptor)` so partial-failure retries can replay only the failed batch instead of re-uploading the whole document. The phase F tests were written against the original `int` return.
- **Remediation:** update the 3 affected tests to (a) unpack the tuple, (b) assert on `len(successful_ids)` instead of the bare int, (c) update mocks of `_upsert_to_qdrant_privileged` in pipeline tests to return a tuple. UI tests (20) are unaffected and still pass.
- **Status:** RESOLVED (3 tests adapted to new tuple return; 37/37 backend tests + 20/20 UI tests green)
- **Ticket:** N/A — phase F test maintenance, not a code defect
- **Note:** also noticed the `_DOMAIN_TO_ROLE` Sanker entry was corrected from `masp-lawfirm.com` → `msp-lawfirm.com`. The `test_role_for_counsel_domain_maps_correctly` test iterates the live dict so it auto-adapts. The `/tmp/pr_f_classification_rules.md` draft still has the old spelling — separate cleanup, no test impact. Fix mechanics: (1) unpack the tuple `(successful, failure)`, assert `len(successful) == N` + `failure is None`; (2) update pipeline-test mocks to return `(["uuid-list"], None)` instead of `int`; (3) the deterministic-UUID test's `_FakeResp` now provides a `.json()` returning the Qdrant `{"status":"ok","result":{"status":"completed",...}}` shape that `_batch_upsert_with_verification` now requires.

---

## Tickets filed

| ID  | GH#  | Title                                              | Status      |
|-----|------|----------------------------------------------------|-------------|
| T1  | #257 | legal: /api/internal/* JWT vs static bearer        | OPEN        |
| T2  | #258 | legal: alembic chain reconciliation                | OPEN        |
| T3  | #259 | captain: gary-crog unknown-8bit encoding           | OPEN        |
| T4  | #260 | captain: gary-gk SEARCH overflow                   | OPEN        |
| T5  | #261 | legal: stale FORTRESS_DB_* keys in .env            | OPEN        |
| T8  | #262 | legal: opposing_counsel stale + needs JSONB migration | OPEN (deferred) |

---

## Conventions

- Append new issues to the most recent date section (newest at bottom of date)
- Use ISO date headers (## YYYY-MM-DD)
- Each issue: ### Issue: <one-line title>, then bullets for Discovered / Symptom / Root cause / Remediation / Status / Ticket
- Status transitions: OPEN → IN-PROGRESS (when work begins) → RESOLVED (verified fixed) OR DEFERRED (decision to not fix now)
- Ticket field references GH issue number once filed
- Note field captures context that doesn't fit other fields (e.g., links to design doc revisions needed)

---

## 2026-04-28 — Fortress Legal migration to spark-1 (issues surfaced during M1/M2 prep)

### M-001 — fortress-brain.service had hardcoded venv path

**Severity:** medium  
**Surfaced:** M1-1 (rename of `~/Fortress-Prime` → `~/Fortress-Prime.legacy`)  
**Effect:** systemd unit ExecStart pointed at `/home/admin/Fortress-Prime/venv/bin/streamlit`; rename broke the path; unit failed 5x and went into permanent failed state.  
**Root cause:** Python venv shebangs hardcode the venv's parent path at venv creation time. Renaming any directory above a venv breaks every wrapper script in `venv/bin/`.  
**Fix applied:** Recovery R1-R10. Symlink restore (`~/Fortress-Prime` → `~/Fortress-Prime.legacy`) + drop-in override at `/etc/systemd/system/fortress-brain.service.d/10-legacy-path.conf`.  
**Long-term:** Recreate venvs after migration completes (M5 followup). Audit all systemd units for hardcoded repo paths before any future rename.  
**Open work:** drop-in cleanup post-M5.

### M-002 — needrestart triggered cascade restart attempts during apt install

**Severity:** low  
**Surfaced:** M1-2 (apt install postgresql-16 + redis + deps)  
**Effect:** needrestart's auto-restart hook surfaced fortress-brain in its restart list while the unit was already failed from M-001, creating ambiguous interaction.  
**Fix applied:** `/etc/needrestart/conf.d/99-fortress-quiet.conf` set `$nrconf{restart} = 'l';` for migration window.  
**Open work:** remove post-M5.

### M-003 — GitHub deploy key required for spark-1 git access

**Severity:** low (process, not technical)  
**Surfaced:** M1-4 (clone Fortress-Prime fresh)  
**Effect:** SSH auth failed at clone — spark-1's ed25519 pubkey was not in repo's Deploy Keys.  
**Fix applied:** Operator added pubkey via GitHub UI with write access. Fingerprint `SHA256:P532moZ/del210PNnn5RTZ0B4qNXrWKj4H46W0sl7WY` recorded in spark-1-legal-migration-runbook.md.  
**Long-term:** Document deploy-key provisioning as standard step in any future cross-spark migration runbook.

### M-004 — fortress-guest-platform missing pyproject.toml + alembic in deps

**Severity:** high (blocking M2-5)  
**Surfaced:** M2-5-FIX (alembic upgrade head on spark-1)  
**Effect:** `uv pip install -e .` fails — no `pyproject.toml`, no `setup.py`, no `setup.cfg` in `~/Fortress-Prime/fortress-guest-platform/`. `alembic` is not in `backend/requirements.txt`. Production schema migrations have shipped via this repo (#245-#256) so an install path exists; it's undocumented.  
**Status:** M2-INVESTIGATE phase running to surface canonical install ritual (Docker? install script? venv on spark-2?).  
**Fix path TBD:** depends on investigation outcome. Likely needs a separate PR adding `pyproject.toml` + alembic to deps, or a documented install script.  
**Blocks:** M2-5 → M3 → M4 → M5 → Phase 1-6 soak.

### M-005 — Hardcoded postgres credential in labeling_pipeline.py

**Severity:** medium (security)  
**Surfaced:** M2-INVESTIGATE  
**Effect:** `backend/services/labeling_pipeline.py` contains literal `postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow`. The password is the placeholder string `fortress`, suggesting either dev-mode legacy or a never-rotated default.  
**Status:** logged, not touched during migration.  
**Fix path:** separate PR — replace with env-var read, rotate any production deployment that uses this string.  
**Risk if ignored:** if production fortress_admin's password ever became `fortress`, this would be a credential leak in source. If not, low immediate risk but will fail at M3 dual-write.

### M-006 — Query A name-collision noise (86% noise, surnames matching non-counsel)

**Severity:** medium (operator-time waste, not data integrity)  
**Surfaced:** Track B Case II privilege review  
**Effect:** SQL substring match on counsel surnames against `email_archive.sender` returned 30/37 rows that are HR/employee correspondence (River Underwood at gmail, etc.) rather than legal counsel.  
**Root cause:** No counsel registry table; queries use surname substring instead of authorized counsel email/domain.  
**Fix applied (today):** Pivoted to LLM-based bulk classification (qwen2.5:7b on Ollama) — produced section-7-source-manifest.md with 42 entries from union of (Query A v2, vanderburge-misroute folder, additional ILIKE matches).  
**Long-term:** Build `legal.counsel_registry` table seeded from operative pleadings + LOAs. Captain classifier consults registry during Stage 1 triage. Filed as B-track work; not started.

### M-007 — 147 vanderburge-misroute emails contain Case I + Case II counsel correspondence

**Severity:** medium (data quality)  
**Surfaced:** vanderburge-misroute LLM probe (2026-04-28)  
**Effect:** Captain classifier originally tagged 147 emails as `case_slug='vanderburge-v-knight-fannin'`. LLM probe surfaced these include the missing MHT Legal correspondence (Ethan Underwood 2021-06-09, Stanton Kincaid 2022-03-10) — the defense counsel mail that v2/v3 SQL queries against email_archive could not locate.  
**Status:** misroute folder treated as logical re-route via section-7-source-manifest.md; .eml files NOT physically moved.  
**Fix path:** maps to B2 (cross-case email link table) in case-briefing-build-plan.md. Captain classifier needs to emit multiple links per email, not single classification.  
**Blocks:** comprehensive privilege review for any future case will hit the same pattern.

### M-008 — alembic missing from backend/requirements.txt despite being a runtime dependency

**Severity:** medium (process, blocks migration to new hosts)
**Surfaced:** M2-INVESTIGATE on spark-1 (2026-04-28)
**Effect:** Production deployments use alembic for schema migrations (PRs #245-#256 all required it). Spark-2's venv has alembic installed but it's not in `backend/requirements.txt`. Any new host installation has to discover this gap by failing first, then mirror the installed version off spark-2 manually.
**Root cause:** alembic was installed ad-hoc on spark-2 at some point and never added to `requirements.txt`. The next host repeats the discovery.
**Fix path:** Separate PR — `pip freeze | grep alembic` on spark-2 to get the canonical version, add to `backend/requirements.txt`, merge.
**Workaround applied:** spark-1 M2-INSTALL pins alembic to spark-2's installed version.
**Open work:** upstream `requirements.txt` fix.

### M-009 — backend/requirements.txt has Python 3.12-incompatible inference pins

**Severity:** medium (blocks fresh installs, requires hermes-style filter)
**Surfaced:** M2-INSTALL on spark-1 (2026-04-28)
**Effect:** `ray[default]==2.10.0`, `ray[serve]==2.10.0`, `vllm==0.4.0` are pinned to versions that don't publish cp312 wheels. Spark-2 has them installed because the original install was on Python 3.11 (or sourced ray from elsewhere). On Ubuntu 24.04 (Python 3.12 only), uv hard-fails dependency resolution.
**Root cause:** Pins predate Python 3.12 wheel availability for those packages. Inference deps are co-mingled in `backend/requirements.txt` with Alembic/SQLAlchemy/asyncpg, even though they're only needed by the AI inference path — not by migrations or the guest-platform backend itself.
**Existing precedent:** `deploy/hermes/Dockerfile` already filters these three pins out before `pip install` for the same reason.
**Fix applied (today):** spark-1 M2-INSTALL filters `ray[default]==`, `ray[serve]==`, `vllm==` from requirements.txt before install (matching hermes pattern).
**Long-term:** split `backend/requirements.txt` into `requirements-base.txt` (universal) + `requirements-inference.txt` (ray/vllm path only). Install-time selects which to apply.
**Open work:** upstream split + documentation.
