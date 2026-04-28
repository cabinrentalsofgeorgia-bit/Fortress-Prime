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
