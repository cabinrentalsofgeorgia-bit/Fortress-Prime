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

### Issue: gh PAT cannot attach labels to issues

- **Discovered:** during T5 ticket filing verification (`gh issue view 261 --json labels`)
- **Symptom:** all 5 tickets T1–T5 (#257–#261) have empty `labels` arrays despite `gh issue create --label "..."` returning success. `gh issue edit --add-label` and `gh api POST /labels` both return HTTP 403 `Resource not accessible by personal access token`.
- **Root cause:** the active PAT (`github_pat_11B3IN7GI...`, account `cabinrentalsofgeorgia-bit`) has `issues:create` and `labels:create` scope but lacks the `addLabelsToLabelable` GraphQL mutation / REST `issues:write` scope needed to attach labels. `gh issue create --label` silently swallowed the permission failure on every create call.
- **Remediation options:** (a) attach labels manually via web UI for T1–T5 (~30s/ticket), or (b) regenerate PAT with `Issues: Read and write` scope and re-run a label-attach loop, or (c) leave unlabeled — body content is the durable record.
- **Status:** OPEN
- **Ticket:** N/A — local CLI/auth config gap, not a Fortress-Prime code issue
- **Note:** the 7 new labels created earlier in the session (`legal`, `auth`, `post-flos-cutover`, `alembic`, `imap`, `pre-existing`, `.env`) all exist on the repo — only the *attachment* failed.

---

## Tickets filed

| ID  | GH#  | Title                                              | Status      |
|-----|------|----------------------------------------------------|-------------|
| T1  | #257 | legal: /api/internal/* JWT vs static bearer        | OPEN        |
| T2  | #258 | legal: alembic chain reconciliation                | OPEN        |
| T3  | #259 | captain: gary-crog unknown-8bit encoding           | OPEN        |
| T4  | #260 | captain: gary-gk SEARCH overflow                   | OPEN        |
| T5  | #261 | legal: stale FORTRESS_DB_* keys in .env            | OPEN        |

---

## Conventions

- Append new issues to the most recent date section (newest at bottom of date)
- Use ISO date headers (## YYYY-MM-DD)
- Each issue: ### Issue: <one-line title>, then bullets for Discovered / Symptom / Root cause / Remediation / Status / Ticket
- Status transitions: OPEN → IN-PROGRESS (when work begins) → RESOLVED (verified fixed) OR DEFERRED (decision to not fix now)
- Ticket field references GH issue number once filed
- Note field captures context that doesn't fit other fields (e.g., links to design doc revisions needed)
