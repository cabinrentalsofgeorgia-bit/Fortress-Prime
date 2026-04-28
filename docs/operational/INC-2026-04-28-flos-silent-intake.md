# INC-2026-04-28-flos-silent-intake

**Status:** RESOLVED 2026-04-28
**Severity:** P0 — production legal mail intake silently dropping all messages for 38 days
**Discovered:** 2026-04-28 ~14:30 UTC
**Resolved:** 2026-04-28 ~21:34 UTC
**Operator:** Gary Knight
**Author:** Claude (assistant) + Claude Code on Opus

---

## TL;DR

The legal mail ingester pipeline was silently dropping every legal correspondence message between 2026-03-21 and 2026-04-28 (38 days). On the day of discovery, `legal.event_log` contained zero rows for its entire history. Five separate compounding bugs converged to produce the silent failure. All five are now fixed and production has been verified writing legal correspondence into `email_archive` and `legal.event_log` with watchdog matches firing.

This incident matters beyond the silent intake itself: it exposed structural gaps in privilege grants, schema migrations, role identity, and connection-level diagnostics that would have bitten the broader Fortress Legal stack on the next high-stakes drop. The post-mortem actions are designed to make every one of these failures impossible (or self-detecting) in the future.

---

## Timeline

| UTC | Event |
|---|---|
| 2026-03-21 | Last successful write from `legacy_imap_producer` to `email_archive` (legacy producer dies silently — separate, prior incident not covered here) |
| 2026-04-?? | FLOS Phase 0a-2 (`legal_mail_ingester`) deployed, replacing legacy producer. Designed to coexist with Captain. |
| 2026-04-?? | FLOS Phase 1 dispatcher cutover (`LEGAL_DISPATCHER_ENABLED=true`). |
| 2026-04-28 ~14:30 | Operator notices `legal.event_log` is empty when checking dispatcher posture. |
| 2026-04-28 ~14:45 | Diagnostic confirms silent intake — `email_archive` has zero rows from `legal_mail_ingester:v1`, `legal.event_log` has zero rows total, `legal.mail_ingester_state` empty. |
| 2026-04-28 ~15:30 | Bug #1 identified (UNSEEN SINCE design defect). |
| 2026-04-28 ~16:00 | Schema migration `s4d5e6f7g8h9_flos_phase_0a_7_uid_watermark.py` written. |
| 2026-04-28 ~16:15 | Migration applied directly via `psql` against `fortress_db` and `fortress_prod` (alembic chain divergent per Issue #204). |
| 2026-04-28 ~17:30 | PR #271 (UID-watermark code change) drafted and handed off to Claude Code on Opus. |
| 2026-04-28 ~20:48 | PR #271 merged after rebase to single-commit. |
| 2026-04-28 ~20:50 | First post-merge worker restart: 5 fetched, 5 errored. tz-naive bug + permission errors surface. |
| 2026-04-28 ~21:00 | Bug #2 identified (tz-naive vs tz-aware datetime). Patched in place. |
| 2026-04-28 ~21:10 | Bugs #3 + #4 identified (wrong role granted; missing grants on `email_archive` and sequences in `fortress_db`). |
| 2026-04-28 ~21:33 | Final patrol succeeds: `fetched=5 ingested=5 errored=0 events_emitted=5 watchdog_matches=2`. |
| 2026-04-28 ~21:34 | INC marked RESOLVED. PR #272 opened to commit tz-naive patch. |

---

## The five compounding bugs

### Bug #1 — UNSEEN SINCE design defect (PR #271)

**Where:** `backend/services/legal_mail_ingester.py::_fetch_with`

**What:** SEARCH predicate was `UNSEEN SINCE <date>`. UNSEEN matches only messages without the `\Seen` IMAP flag.

**Why it broke:** The legal mailbox is read by humans (webmail), by Captain (parallel ingester), and by the operator on phone/desktop. Any one of these marks `\Seen` on read. After any read, the message becomes invisible to the legal_mail_ingester forever. Per design v1.1 §3.4 the ingester deliberately does not mutate `\Seen` (Captain coexistence rule), so it can never recover messages once read.

**Production impact:** ALL inbound legal correspondence missed since deploy. Verified by raw IMAP probe — `INBOX` had 5 messages, all SEEN, all therefore invisible to the ingester.

**Fix:** Replace UNSEEN-based SEARCH with UID watermark. New schema column `legal.mail_ingester_state.last_seen_uid` tracks the highest UID processed. Bootstrap path (NULL watermark): `SEARCH SINCE <date>`, no UNSEEN — captures all messages in band regardless of read state. Steady state: `SEARCH UID <last+1>:*`. Filter for IMAP UID quirk where `<next>:*` returns at least one UID even if no messages have UID >= next.

**Schema migration:** `s4d5e6f7g8h9_flos_phase_0a_7_uid_watermark.py` (committed in PR #271).

**Code change:** 5 spot edits in `legal_mail_ingester.py` (PR #271). 5 new tests covering bootstrap, steady-state, UID quirk, no-new, invalid-watermark fallback. Zero regressions vs clean tree.

---

### Bug #2 — tz-aware sent_at vs naive TIMESTAMP column (PR #272)

**Where:** `backend/services/legal_mail_ingester.py::parse_message`

**What:** `parsedate_to_datetime(date_header)` from Python's `email.utils` returns a tz-aware `datetime` whenever the email's Date header contains a timezone offset (every RFC 2822 date header from IMAP does, e.g. `Tue, 28 Apr 2026 09:22:54 -0400`). The destination column `email_archive.sent_at` is `TIMESTAMP WITHOUT TIME ZONE`.

**Why it broke:** asyncpg refuses to coerce a tz-aware datetime into a naive TIMESTAMP column. It raises:

> `asyncpg.exceptions.DataError: invalid input for query argument $6: ... can't subtract offset-naive and offset-aware datetimes`

**Production impact:** 4 of 5 messages on the first post-PR-271 patrol failed to insert with this error. (The 5th hit Bug #4 — see below.)

**Fix:** Convert to UTC then strip tzinfo before storing:

```python
if parsed_dt is not None and parsed_dt.tzinfo is not None:
    parsed_dt = parsed_dt.astimezone(timezone.utc).replace(tzinfo=None)
```

UTC chosen so stored timestamps compare consistently regardless of server local time. The original sender's local TZ is preserved in the raw message body if needed.

**Code change:** PR #272 (10 insertions, 1 deletion).

---

### Bug #3 — Wrong role granted (5 hours of debug)

**Where:** privilege grants applied during incident response.

**What:** Operator and assistant repeatedly granted privileges to role `fgp_app` based on `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://fgp_app:...@localhost:5432/fortress_guest
```

**Why it was wrong:** `backend/core/config.settings.database_url` does NOT read from `.env`'s `DATABASE_URL`. It reads from `POSTGRES_API_URI` instead:

```
POSTGRES_API_URI=postgresql+asyncpg://fortress_api:...@127.0.0.1:5432/fortress_shadow
```

The actual role used by `LegacySession` for legal mail writes is `fortress_api`, not `fgp_app`.

**Why it took 5 hours to find:** Three layers of indirection:
1. `.env` has multiple DB URL variables (`DATABASE_URL`, `POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`, etc.) and not obvious which one actually wins.
2. `backend/core/config.py` uses Pydantic settings with field aliases — what looks like `database_url` in code maps to `POSTGRES_API_URI` from environment.
3. `backend/services/ediscovery_agent.py::_LEGACY_DB_URL` then transforms that URL by replacing `/fortress_shadow` → `/fortress_db`. The role stays the same; only the DB name changes.

So the actual connection is `fortress_api@fortress_db`, not `fgp_app@fortress_guest` (which `.env`'s `DATABASE_URL` suggests).

**Detection:** `pg_stat_activity` query showed `fortress_api` connecting to `fortress_db`, while `fgp_app` was only on `fortress_guest`. Caught after several rounds of granting fgp_app and seeing zero behavior change.

**Fix:** Re-grant on `fortress_api` instead. (See Bug #4 for the actual grant set.)

---

### Bug #4 — Missing privileges on email_archive in fortress_db

**Where:** Postgres role grants on `fortress_db`.

**What:** Role `fortress_api` had only `SELECT` on `public.email_archive` in `fortress_db`. The FLOS Phase 0a-1 migration granted full INSERT/UPDATE/DELETE on the new `legal.*` tables but did not extend grants to the existing `email_archive` table that the ingester writes to.

**Why it broke:** After Bug #1 fix, the patrol fetched 5 messages and attempted to write them. Without INSERT privilege, asyncpg raised:

> `asyncpg.exceptions.InsufficientPrivilegeError: permission denied for table email_archive`

**Production impact:** Even with the UNSEEN bug fixed and the tz bug fixed, every message would have failed to insert.

**Fix:** Granted the full write set in fortress_db:

```sql
GRANT INSERT, UPDATE, DELETE ON public.email_archive TO fortress_api;
GRANT USAGE, SELECT ON SEQUENCE public.email_archive_id_seq TO fortress_api;
```

In fortress_prod, fortress_api already had these — no change needed.

---

### Bug #5 — Missing sequence UPDATE grant on legal.event_log_id_seq in fortress_prod

**Where:** Postgres role grants on `fortress_prod` (and, as it turned out, `fortress_db` as well — see "Correction" below).

**What:** After Bug #4 fix, the canonical write to `fortress_db` succeeded for all 5 messages. The mirror write to `fortress_prod` (via `ProdSession`) succeeded the INSERT but failed the subsequent `setval()` call on `legal.event_log_id_seq`:

> `asyncpg.exceptions.InsufficientPrivilegeError: permission denied for sequence event_log_id_seq`

**Production impact:** Mirror drift on every event. `fortress_db` is canonical; `fortress_prod` mirror falls behind. Logged via `legal_mail_event_log_prod_mirror_failed` and recoverable by dispatcher reconciliation.

**Correction (post-runtime-patch, captured here for the durable record):** The fix originally documented below granted only `USAGE, SELECT` on the sequences. That was insufficient. PostgreSQL's `setval()` — which the bilateral mirror writer calls to align `fortress_prod`'s sequence with the source row's id — requires the **`UPDATE`** privilege on the sequence object, not `USAGE` (which governs `nextval()`/`currval()`). Without `UPDATE`, the mirror writer continued to fail with `permission denied for sequence event_log_id_seq` even after the runtime patch. We discovered this when restarting the worker on the `docs/INC-2026-04-28-flos-silent-intake-and-grants` branch and seeing the mirror fail again. The migration (`t6e7f8g9h0a1_flos_phase_0a_8_role_grants.py`) and the apply SQL (`docs/operational/apply-flos-phase-0a-8-grants.sql`) both grant `USAGE, SELECT, UPDATE`.

**Status:** Fixed durably in PR #273 — the migration grants `USAGE, SELECT, UPDATE` on `public.email_archive_id_seq` and on every sequence in schema `legal`, plus matching `ALTER DEFAULT PRIVILEGES` for future sequences. Applied to both `fortress_db` and `fortress_prod` via the apply SQL after merge.

**Fix (durable, applied):**

```sql
-- in BOTH fortress_db AND fortress_prod
GRANT USAGE, SELECT, UPDATE ON SEQUENCE public.email_archive_id_seq TO fortress_api;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA legal TO fortress_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA legal GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO fortress_api;
```

The `ALTER DEFAULT PRIVILEGES` clause covers any future sequences added to the schema.

---

## What we got right

- **Diagnostic discipline:** every diagnosis based on log evidence, never on guesses. When a guess proved wrong (Bug #3), evidence (`pg_stat_activity`) corrected it.
- **Tested raw IMAP path before blaming code:** the manual IMAP probe in incident response confirmed the IMAP path was healthy and SEARCH found all 5 messages, before suspecting code.
- **Operator-merge gate honored:** PR #271 was opened by Claude Code on Opus but rebased and merged manually after the operator reviewed the diff. No auto-merge despite the urgency.
- **Schema migration created as durable record:** even though we applied it via raw psql due to alembic chain divergence (Issue #204), the migration file was committed so future restores reapply automatically.
- **Bilateral mirror discipline maintained:** schema applied to both `fortress_db` and `fortress_prod` per ADR-001.

## What we got wrong

- **Started granting before identifying the role.** Five hours of guessing on `fgp_app` could have been avoided by running `pg_stat_activity` first to see the actual connection identity.
- **Did not grep `.env` exhaustively for DB URL variables.** Had we noticed `POSTGRES_API_URI` early, the role would have been obvious.
- **Did not commit the tz patch immediately after applying it.** The fix lived only on disk for ~30 minutes during incident response. PR #272 closes that window now but the gap was real — a process restart or rollback during that window would have lost the fix.
- **No incident doc until end of incident.** Should have started this doc at minute 5, not minute 380.

## Why none of this is allowed to happen again

### Defense layer 1 — `pg_stat_activity` is the first stop on any privilege incident

Going forward, on any "permission denied" error from asyncpg or sqlalchemy, the first diagnostic command is:

```sql
SELECT pid, usename, datname, application_name, query
FROM pg_stat_activity
WHERE state != 'idle' AND datname IS NOT NULL;
```

Identifies the actual connecting role immediately. Captured in the runbook (see follow-up actions).

### Defense layer 2 — Single source of truth for DB roles per service

Add to `docs/operational/database-roles.md` (forthcoming): a table mapping every service to its Postgres role(s) and DB(s). When a new service ships, the table is updated. Reviewing the table tells the operator at a glance who-connects-where without grepping config.

### Defense layer 3 — Migration includes grants

All new FLOS migrations (and any migration creating tables) MUST include a GRANT statement for the relevant role at the bottom of `upgrade()`. Pattern:

```python
op.execute("""
    GRANT SELECT, INSERT, UPDATE, DELETE ON legal.<new_table> TO fortress_api;
    GRANT USAGE, SELECT, UPDATE ON SEQUENCE legal.<new_table>_id_seq TO fortress_api;
""")
```

`UPDATE` on the sequence is required for `setval()`, which the bilateral mirror writer calls to align `fortress_prod`'s sequences with `fortress_db`. Omitting `UPDATE` was Bug #5's root cause; copying the pattern above without it would reproduce the bug.

This makes the grant part of the schema's durable record. Restoring from a fresh DB applies grants automatically. Closes the gap that caused Bug #4 and Bug #5.

### Defense layer 4 — Health endpoint surfaces silent failure

The `/health/legal-mail-ingester` endpoint (FLOS Phase 1-4) now needs an additional check: if `legal.event_log` has zero rows AND any `legal.mail_ingester_state.last_success_at` is older than 24 hours, the health check goes red. Silent intake fails the health check immediately. Tomorrow's follow-up.

### Defense layer 5 — Smoke test on every worker startup

Worker startup runs a single dummy upsert against `legal.mail_ingester_state` (insert + immediate delete) as a privilege probe. If it fails, worker fails-fast at boot, not silently after a patrol. Tomorrow's follow-up.

### Defense layer 6 — Operator runbook entry

`docs/operational/runbooks/legal-mail-intake-silent.md` (forthcoming) — concise runbook the operator (or future Claude session) follows when this class of failure recurs. Order: pg_stat_activity → grants check → schema check → URL check → code path. The five-bug-five-hour debugging session is the canonical example.

---

## Verification of resolution

Final patrol at 2026-04-28 21:33:44 UTC:

```
legal_mail_patrol_report
  duration_ms=1033
  errored=0
  events_emitted=5
  fetched=5
  ingested=5
  mailbox=legal-cpanel
  watchdog_matches=2
```

Database state in `fortress_db` post-resolution:

```
SELECT mailbox_alias, last_seen_uid, messages_ingested_total,
       messages_errored_total, last_error
FROM legal.mail_ingester_state WHERE mailbox_alias='legal-cpanel';

mailbox_alias | last_seen_uid | messages_ingested_total | messages_errored_total | last_error
--------------+---------------+-------------------------+------------------------+-----------
legal-cpanel  |             5 |                       5 |                      0 | (null)

SELECT COUNT(*) FROM email_archive WHERE ingested_from='legal_mail_ingester:v1';
count
-----
    5

SELECT COUNT(*) FROM legal.event_log;
count
-----
    5
```

Production legal mail intake is operational. New legal correspondence will flow into `email_archive` and `legal.event_log` going forward.

---

## Open follow-ups (in priority order)

1. ~~**Bug #5 fix** — grant sequence USAGE on `legal.*` in `fortress_prod` (one psql command).~~ **Done.** Closed by PR #273 with `USAGE, SELECT, UPDATE` (USAGE alone was insufficient — see Bug #5 "Correction" above).
2. ~~**Migration follow-up** — convert tonight's runtime grants into a versioned migration so a fresh DB restore reapplies them.~~ **Done.** Migration file: `t6e7f8g9h0a1_flos_phase_0a_8_role_grants.py` (PR #273).
3. ~~**PR #272** — tz-naive patch.~~ **Merged 2026-04-28** as commit `7b0aa8a21`, with regression test added in commit `e11f01882`.
4. **Health endpoint enhancement** — add silent-intake detection per Defense layer 4.
5. **Worker boot smoke test** — privilege probe per Defense layer 5.
6. **Runbook** — `legal-mail-intake-silent.md` per Defense layer 6.
7. **Database roles doc** — `database-roles.md` per Defense layer 2.
8. **Tag gary-gk and gary-crog with `ingester=legal_mail`** in MAILBOXES_CONFIG so real Case I/II correspondence flows through the new ingester (separate config-only PR — pending operator decision).
9. **ADR amendment** — update ADR-001 (one-spark-per-division) and ADR-002/003 to reflect the production reality of multi-DB role identity and the patterns this incident exposed.

---

## Cross-references

- PR #271 — FLOS Phase 0a-7 UID watermark code change (merged 2026-04-28 20:48 UTC)
- PR #272 — tz-naive sent_at fix (open)
- Issue #204 — alembic chain divergence (existing; explains why migration applied via raw psql)
- `docs/architecture/cross-division/FLOS-phase-0a-legal-email-ingester-design-v1.1.md` — design doc that introduced the UNSEEN SINCE pattern (now superseded for legal mailbox; Captain coexistence rule preserved by the UID watermark approach)
- `docs/priorities/fortress-legal-case-i-ii-priorities-v2.md` — Fortress Legal master plan (PR #270)

---

End of incident document.
