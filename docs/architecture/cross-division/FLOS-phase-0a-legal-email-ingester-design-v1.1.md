# FLOS Phase 0a — Legal Email Ingester Design (v1.1)

**Status:** PROPOSED — operator review pending (revision of v1)
**Date:** 2026-04-27
**Scope:** Implementation spec for the new `legal_mail_ingester` that replaces the dead legacy multi-mailbox producer
**Parent:** [FLOS Design v1](./FLOS-design-v1.md)
**Predecessor:** [FLOS Phase 0a v1](./FLOS-phase-0a-legal-email-ingester-design.md) (preserved for review history)

## Changes from v1

Operator review locked five design questions. Revision incorporates them as assertions:

- **Q1 LOCKED → §5:** two-stage privilege classifier (lightweight inbound triage + heavyweight per-document)
- **Q2 LOCKED → §3.4:** legal_mail_ingester runs alongside Captain; no replacement
- **Q3 LOCKED → §6:** forward-only backfill from 2026-03-26
- **Q5 LOCKED → §10:** bilateral mirror added to email_archive in Phase 0a-1 (not deferred)
- **(NEW) Seed data discipline → §3.3:** Phase 0a-1 includes INSERT seed for `priority_sender_rules`
- **Q-A ANSWERED → §3.5:** per-mailbox routing_tag assignments fixed (gary-gk → legal, gary-crog → legal, info-crog → executive, legal-cpanel → legal)
- **Q-B ANSWERED → §11:** 2-3 day target for Phase 0a-1 → 0a-5
- **Q4 STAYS OPEN → §12:** Phase 1 event bus mechanism (LISTEN/NOTIFY vs Redis) deferred to Phase 1 design

---

## 1. Goals

**Replace the dead legacy multi-mailbox poller** that started 2026-02-12, wrote ~50 emails/day to `email_archive` with `category='imap_gmail'` / `imap_ips_pop3_*`, then silently stopped 2026-03-25. **Five iterations of diagnostic work could not locate its source code.** It had no `ingested_from` attribution, no monitoring, no health check, no documentation, no tests. When it broke, FLOS noticed only because the operator surfaced a litigation-correspondence-silence symptom 33 days later.

**The new ingester is the inverse:** observable, source-attributed, restartable, monitored, documented, testable. Every row carries explicit producer attribution. Every patrol logs structurally. Every state change emits an event to the FLOS event bus. Every error surfaces in the operator command-bridge instead of going silent for a month.

This is **the first installable piece of FLOS.** The producer-mystery experience is exactly the failure mode FLOS exists to prevent. Phase 0a's source-attribution + event-emission contracts are foundational — every subsequent FLOS phase assumes them.

---

## 2. Architectural placement

### File location

```
backend/services/legal_mail_ingester.py     ← the ingester service (new)
backend/scripts/legal_mail_ingester_cli.py  ← operator CLI wrapper (new)
backend/api/legal_mail_health.py            ← health endpoint (new)
```

### Worker mechanism

**arq background task**, mirroring Captain's pattern. Started by `fortress-arq-worker` on worker boot via `backend/core/worker.py:589` style. Gated behind `LEGAL_MAIL_INGESTER_ENABLED` env var (default False during rollout, flipped to True after Phase 0a-3 validation).

### Spark allocation

**Spark 2 (control plane)** per ADR-002. Co-located with `fortress-arq-worker` (where Captain already runs). No new deployment target.

---

## 3. Inputs and contracts

### 3.1 MAILBOXES_CONFIG extensions

Existing 4 entries keep working. New optional fields:

```json
{
  "name": "legal-cpanel",
  "transport": "imap",
  "host": "...",
  "port": 993,
  "address": "legal@cabin-rentals-of-georgia.com",
  "credentials_ref": "...",
  "routing_tag": "legal",
  "poll_interval_sec": 120,

  // NEW (all optional, defaults shown)
  "max_messages_per_patrol": 50,
  "search_band_days": 30,
  "folder": "INBOX",
  "ingester": "legal_mail"
}
```

| field | default | purpose |
|---|---|---|
| `max_messages_per_patrol` | 50 | back-pressure cap |
| `search_band_days` | 30 | IMAP `SINCE <today - N days>` — bounds result set, prevents Issue #177 overflow |
| `folder` | "INBOX" | IMAP folder to poll |
| `ingester` | "captain" | which ingester owns this mailbox |

**Both Captain AND legal_mail_ingester read MAILBOXES_CONFIG** and filter by `ingester` field (default `captain` preserves current behavior).

### 3.2 IMAP SEARCH banding (hard requirement)

**Never issue an unbounded `SEARCH UNSEEN`.** That's how gary-gk hits Issue #177's >1MB overflow. Always pair UNSEEN with a date floor:

```python
since_date = (today - timedelta(days=mailbox.search_band_days)).strftime("%d-%b-%Y")
typ, data = conn.uid("SEARCH", f"UNSEEN SINCE {since_date}")
```

For mailboxes that exceed `max_messages_per_patrol` within the band: process up to the cap, leave the rest for next patrol. UNSEEN flag remains set; no message is lost.

### 3.3 Sender-allowlist for high-priority routing — `legal.priority_sender_rules`

```sql
CREATE TABLE legal.priority_sender_rules (
    id BIGSERIAL PRIMARY KEY,
    sender_pattern TEXT NOT NULL,    -- ILIKE-matched
    priority TEXT NOT NULL,           -- 'P1' | 'P2' | 'P3'
    case_slug TEXT,                   -- optional FK to legal.cases
    rationale TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_priority CHECK (priority IN ('P1', 'P2', 'P3'))
);
```

**Phase 0a-1 includes seed INSERT** (closes the schema-without-data anti-pattern from FLOS principle 10):

```sql
-- Cross-case (court systems)
INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
  ('%@peachcourt.com',         'P1', NULL, 'Georgia court e-filing system; any inbound is procedural'),
  ('%@fanninclerk%',           'P1', NULL, 'Fannin County clerk; orders + scheduling'),
  ('%@fanninsuperior%',        'P1', NULL, 'Fannin Superior Court chambers / clerks');

-- fish-trap-suv2026000013 (Generali v CROG)
INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
  ('%@stuartattorneys.com',    'P1', 'fish-trap-suv2026000013', 'Plaintiff counsel (J. David Stuart)'),
  ('%@rtsfg.com',              'P1', 'fish-trap-suv2026000013', 'Plaintiff collections (RTS Financial / Aaron Reaney)'),
  ('%@judgesosebee.com',       'P2', 'fish-trap-suv2026000013', 'Recused judge — historical; surface but lower priority');

-- prime-trust-23-11161
INSERT INTO legal.priority_sender_rules (sender_pattern, priority, case_slug, rationale) VALUES
  ('%@wbd-us.com',             'P1', 'prime-trust-23-11161', 'Plan Administrator (Weil, Bankruptcy & Desai)'),
  ('%detweiler%',              'P1', 'prime-trust-23-11161', 'Don Detweiler — Plan Administrator');
```

Operator-editable post-deploy via direct SQL or future CLI.

### 3.4 Captain coexistence (LOCKED — no replacement)

**legal_mail_ingester runs alongside Captain.** Both poll legal-tagged mailboxes. Different contracts, different owners, different failure modes:

| pipeline | poll target | write target | failure surfacing |
|---|---|---|---|
| Captain (existing) | 4 mailboxes (current) | `llm_training_captures` (training data substrate) | journalctl, captain_patrol_report |
| legal_mail_ingester (new) | legal-tagged mailboxes (subset) | `email_archive` + `legal.event_log` (operator visibility) | CLI status, /health endpoint, structured logs, metrics |

**Acceptable trade-off:** doubled IMAP poll load on legal-tagged mailboxes. With 4 mailboxes at 120s intervals, total load is bounded (~0.5 ops/sec). Each pipeline owns its own UNSEEN cursor (Captain marks `\Seen`; legal_mail_ingester does NOT mark `\Seen` — uses BODY.PEEK[] to preserve UNSEEN for Captain). Race condition prevented because legal_mail_ingester reads with PEEK; Captain's `\Seen` write doesn't affect legal_mail_ingester's view.

### 3.5 Per-mailbox routing assignments (LOCKED Q-A)

| mailbox | routing_tag | rationale |
|---|---|---|
| `legal-cpanel` | `legal` | designed-for-legal mailbox |
| `gary-gk` | `legal` | Sosebee chambers historically here; primary personal mailbox; opposing counsel may direct mail |
| `gary-crog` | `legal` | CROG operational mailbox; opposing counsel may direct mail |
| `info-crog` | `executive` | general inbox; low legal density; Captain-only |

The 3 `legal`-tagged mailboxes opt into legal_mail_ingester via `ingester=legal_mail`. `info-crog` stays Captain-exclusive.

**Also: add `legal-cpanel` to `MAILBOX_REGISTRY`** in `backend/scripts/email_backfill_legal.py:85` (currently in pass-store but not in the script-level registry; closing the gap surfaced 2026-04-26).

### 3.6 Output contract to `email_archive`

| column | value |
|---|---|
| `ingested_from` | `"legal_mail_ingester:v1"` (versioned for forward-compat) |
| `category` | `f"imap_{transport_kind}_{mailbox_alias}"` (preserves legacy schema for `legal_case_manager.py` compat — it queries `file_path LIKE 'imap://%'`) |
| `file_path` | `f"imap://{host}/{folder}/{uid}"` (deterministic, replayable, idempotent) |
| `sender` | parsed From: header |
| `subject` | parsed Subject: header |
| `content` | body (plain or HTML-cleaned) |
| `sent_at` | parsed Date: header |
| `message_id` | parsed Message-ID: header |
| `to_addresses` / `cc_addresses` / `bcc_addresses` | parsed |

Idempotency: dedup on `file_path` UNIQUE constraint (already exists). Re-poll → ON CONFLICT DO NOTHING.

---

## 4. Source attribution discipline (LOCKED)

```sql
-- Backfill: attribute legacy producer rows
UPDATE email_archive
   SET ingested_from = 'legacy_imap_producer:unknown'
 WHERE ingested_from IS NULL
   AND file_path LIKE 'imap://%'
   AND id BETWEEN 166582 AND 174961;

-- Pre-legacy historical rows (Maildir-scraped, GMAIL_ARCHIVE category, etc.)
UPDATE email_archive
   SET ingested_from = 'historical:unknown'
 WHERE ingested_from IS NULL;

-- Enforce going forward
ALTER TABLE email_archive
  ALTER COLUMN ingested_from SET NOT NULL,
  ADD CONSTRAINT chk_ingested_from_format
    CHECK (ingested_from ~ '^[a-z_]+:[a-z0-9_.-]+$');
```

**Architectural intent:** Any code writing to `email_archive` must declare itself. No silent producers. Versioning convention: `<service_name>:v<integer>`.

---

## 5. Two-stage privilege classifier (LOCKED Q1)

### Stage 1 — Lightweight inbound triage (`legal_mail_ingester`)

Fired on every inbound message during patrol. Target: ~1ms/message.

- Input: `(sender, sender_domain, subject_first_120_chars, mailbox_routing_tag)`
- Logic:
  1. ILIKE match against `legal.priority_sender_rules` (sender_pattern) → priority + case_slug if matched
  2. Heuristic regex on subject for known case identifiers (`SUV2026000013`, `23-11161`, `7il`, `vanderburge`, etc.) → case_slug if matched
  3. Mailbox routing_tag inheritance (`legal` → `work_product` default; `executive` → no default)
- Output: `(priority, case_slug, privilege_class, watchdog_matches[])`
- `privilege_class` initial values: `'work_product'` (default for legal-tagged), `'public'` (for executive-tagged), `null` (no classification yet)

This stage is deterministic. No LLM call. Persisted to `email_archive` columns + emitted in `email.received` event payload.

### Stage 2 — Heavyweight per-document classification (`legal_ediscovery._classify_privilege`)

Fired only when a message attaches to a case via correspondence record OR vault upload. Existing pipeline; reuse without change.

- Trigger: operator action OR dispatcher rule promoting an email_archive row to `legal.correspondence` or to `legal.vault_documents` via `process_vault_upload`
- Input: full message body + headers + parsed attachments
- Output: structured `PrivilegeClassification` with `is_privileged`, `confidence`, `reasoning`
- Latency: 10-100s (LLM-backed); not blocking inbound flow

### Boundary

Stage 1 never invokes Stage 2. Stage 2 lives in the document pipeline (`legal_ediscovery`), not the inbound pipeline. **Inbound speed > inbound privilege precision.** Operator approves promotion to case attachment; that's where heavyweight classification fires.

---

## 6. Operator interface (LOCKED)

### CLI commands

```
fgp legal mail status
  → For each MAILBOXES_CONFIG entry where ingester=legal_mail:
      mailbox, last_patrol_at, last_success_at, last_error,
      messages_ingested_today, watchdog_matches_today

fgp legal mail pause --mailbox legal-cpanel [--reason "..."]
  → Sets a row in `legal.mail_ingester_pause` (table-backed, survives restart)
    Ingester checks before each patrol; skips paused mailboxes

fgp legal mail resume --mailbox legal-cpanel
  → Removes pause row

fgp legal mail poll --mailbox legal-cpanel --dry-run
  → Single-shot test; connects, fetches up to 5 messages, logs intent
    No DB writes, no event emission

fgp legal mail backfill --mailbox legal-cpanel --since 2026-03-26
  → Forward-only backfill (LOCKED Q3) — recovers the 2026-03-26 → present silence
    Idempotent (file_path UNIQUE)
    Hard floor: 2026-03-26 — backfill cannot reach pre-cliff data (legacy producer
    territory, intentionally not recovered to avoid mixing producers)
```

### Why CLI matters

The dead legacy producer had **no CLI**. To check on it, the operator queried `email_archive` and inferred state from data. Phase 0a inverts this: CLI surfaces health directly.

---

## 7. Observability

### Structured logging

Per-patrol log line:

```
2026-04-27T15:30:42Z INFO legal_mail_ingester
  mailbox=legal-cpanel patrol_id=u-abc123
  fetched=12 ingested=11 deduped=1 errored=0
  watchdog_matches=2 events_emitted=11
  duration_ms=4321 next_patrol_at=2026-04-27T15:32:42Z
```

Per-message error line:

```
2026-04-27T15:30:43Z WARN legal_mail_ingester.message_failed
  mailbox=gary-gk uid=99876 reason="parse_failed: malformed_From_header"
  message_skipped=true patrol_continues=true
```

### Metrics (Prometheus-friendly counter names)

```
legal_mail_messages_ingested_total{mailbox="<name>"}
legal_mail_messages_deduped_total{mailbox="<name>"}
legal_mail_messages_errored_total{mailbox="<name>", reason="<short>"}
legal_mail_patrol_duration_seconds{mailbox="<name>"}
legal_mail_patrol_failures_total{mailbox="<name>"}
legal_mail_watchdog_matches_total{case_slug="<slug>", priority="<p>"}
legal_mail_events_emitted_total{event_type="email.received"}
```

If Prometheus exporter not available, write counters to `legal.mail_ingester_metrics` table (~6 columns).

### Health endpoint

```
GET /api/internal/legal/mail/health

200 OK
{
  "status": "healthy",
  "ingester_version": "legal_mail_ingester:v1",
  "mailboxes": [
    {"name": "legal-cpanel", "last_patrol_at": "...", "last_success_at": "...", "paused": false},
    ...
  ]
}
```

503 if any mailbox has gone >2 patrol intervals without success.

**Phase 1+ consumer note (NEW):** the FLOS Phase 1 operator command-bridge dashboard will consume `/api/internal/legal/mail/health` + `legal.mail_ingester_state` directly — surface of mailbox health per case. Phase 0a builds the data pipe; Phase 1 builds the dashboard.

### Last-known-good

Every successful patrol updates `legal.mail_ingester_state.last_success_at` per mailbox. Data-backed (not in-memory) so worker restart preserves it.

---

## 8. Event emission contract

### Event type: `email.received`

```json
{
  "event_type": "email.received",
  "ingester_version": "legal_mail_ingester:v1",
  "mailbox": "legal-cpanel",
  "received_at": "2026-04-27T15:30:00Z",
  "sender": "judicialstaff@judgesosebee.com",
  "subject": "Fw: Order on Recusal — SUV2026000013",
  "message_id": "<...@...>",
  "case_slug": "fish-trap-suv2026000013",
  "privilege_class": "work_product",
  "watchdog_matches": [
    {"rule_id": 42, "priority": "P1", "search_term": "judgesosebee", "match_type": "sender"}
  ],
  "email_archive_id": 174962
}
```

### Emission mechanism

Phase 0a writes events directly to `legal.event_log`:

```sql
INSERT INTO legal.event_log
  (event_type, case_slug, event_payload, emitted_at, emitted_by)
VALUES
  ('email.received', :case_slug, :payload::jsonb, NOW(), 'legal_mail_ingester:v1');
```

When Phase 1 dispatcher comes online, it consumes `legal.event_log` rows where `processed_at IS NULL` and routes them. **Phase 0a ingester unchanged.** Phase 1 mechanism choice (LISTEN/NOTIFY vs Redis) doesn't gate Phase 0a.

**Phase 2/3 consumer note (NEW):** the watchdog-match alert routing UI will consume these events from Phase 2+ onward. Phase 0a ingester emits the events; UI surfaces them later.

---

## 9. Schema additions in Phase 0a-1 migration

Single Alembic migration adds:

| object | purpose |
|---|---|
| `legal.priority_sender_rules` (table) | sender-priority routing rules + case-specific |
| `legal.mail_ingester_pause` (table) | operator-controlled pause per mailbox |
| `legal.mail_ingester_state` (table) | last_patrol_at, last_success_at, last_error per mailbox |
| `legal.mail_ingester_metrics` (table) | counter store if Prometheus not available |
| `legal.event_log` (table) | append-only audit + Phase 1 dispatcher source |
| `email_archive.ingested_from` NOT NULL + CHECK | source attribution discipline |
| `priority_sender_rules` SEED ROWS | 8+ INSERT rows for cross-case + per-case patterns |
| Bilateral mirror trigger / replication | see §10 |

Apply via raw psql per Issue #204 chain divergence pattern. Single PR with phase-per-commit discipline (matches PR #228 Phase A.1 approach).

---

## 10. Bilateral mirror discipline for `email_archive` (LOCKED Q5)

`email_archive` joins the bilateral-mirror club per ADR-001. Currently single-DB. Phase 0a-1 brings it under discipline:

```sql
-- On fortress_db:
-- (existing email_archive table; production data lives here today)

-- On fortress_prod:
-- Mirror table created with same schema; populated by ingester writes
CREATE TABLE email_archive (
    -- same columns as fortress_db.email_archive
    -- + ingested_from NOT NULL + CHECK constraint
);
```

**Ingester write pattern** (mirroring PR D / PR I bilateral discipline):

```python
async def _write_with_mirror(row: dict) -> int:
    # 1. Write to fortress_db (LegacySession)
    async with LegacySession() as db:
        result = await db.execute(text("INSERT INTO email_archive (...) VALUES (...) RETURNING id"), row)
        new_id = result.fetchone().id
        await db.commit()

    # 2. Mirror to fortress_prod
    async with AsyncSessionLocal() as prod:
        await prod.execute(text("INSERT INTO email_archive (id, ...) VALUES (:id, ...)"), {"id": new_id, **row})
        await prod.commit()

    return new_id
```

Idempotency on each side via `file_path` UNIQUE.

**Existing 174,961 rows:** Phase 0a-1 does NOT bulk-copy historical rows to fortress_prod (would be a massive data-replication operation outside PR scope). Mirror discipline applies forward-only. This is acceptable because:
- legal_case_manager.py reads from fortress_db (the historical store remains intact)
- New ingester writes to both DBs going forward
- Operator can choose to one-time-bulk-mirror historical data later if needed

If operator decides historical bulk-mirror is needed, that's a separate sub-task (Phase 0a-1b) with its own runbook.

---

## 11. Migration plan — 2-3 day target (LOCKED Q-B)

### Day 1 (Phase 0a-1) — Schema migration

Single Alembic migration with all schema additions + seed data + bilateral mirror setup. Apply via raw psql to fortress_db, fortress_prod, fortress_shadow_test (skip fortress_shadow per Issue #204). PR phase-per-commit; surface for operator review before each apply.

**Exit:** all 5 new tables exist with seed data; `email_archive.ingested_from` NOT NULL enforced; backfill of historical attribution complete.

### Day 1 (Phase 0a-2) — Ingester service

`backend/services/legal_mail_ingester.py` implementation:
- IMAP poll loop (mirroring Captain's banded SEARCH pattern)
- Per-message processing: parse → Stage 1 privilege classify → watchdog match → write email_archive bilaterally → emit event_log row
- Idempotency via file_path UNIQUE
- Per-message try/except (one bad email doesn't abort patrol)
- Structured logging + metrics emission

PR phase-per-commit. Surface diff for operator review before commit. ~700 lines.

### Day 2 (Phase 0a-3) — CLI + health endpoint

`backend/scripts/legal_mail_ingester_cli.py` + `backend/api/legal_mail_health.py`. Combined ~250 lines. Test against staging mailbox (separate test mailbox; not production).

### Day 2 (Phase 0a-4) — Worker registration + cutover

Edit `backend/core/worker.py` to register the ingester behind `LEGAL_MAIL_INGESTER_ENABLED` flag (default OFF). Edit MAILBOXES_CONFIG to add `ingester=legal_mail` to legal-tagged mailboxes per §3.5. Operator flips flag ON after Phase 0a-3 validation. Add `legal-cpanel` to `MAILBOX_REGISTRY` per §3.5.

### Day 2-3 (Phase 0a-5) — 24h soak

Verify:
- email_archive ingestion rate resumes (target: ≥20/day across 3 legal mailboxes)
- ingested_from populated on every new row
- legal.event_log accumulates email.received events
- legal.mail_ingester_state shows fresh last_success_at for each legal mailbox
- No errored rate spikes
- gary-gk: SEARCH banding works, no Issue #177 overflow
- Bilateral mirror parity: fortress_db row count = fortress_prod row count (for new rows only)

### Optional Day 3+ (Phase 0a-6) — Forward-only backfill

`fgp legal mail backfill --since 2026-03-26 --mailbox legal-cpanel` and similar for gary-gk + gary-crog. Recovers the 2026-03-26 → cutover-date silence. Per LOCKED Q3, **does not backfill pre-2026-02-12 historical data** — that territory belongs to the legacy producer and isn't recovered to avoid mixing producer attribution.

---

## 12. Open questions remaining

Only Q4 stays open:

**Q4 (deferred to Phase 1):** Phase 1 event bus mechanism — Postgres `LISTEN/NOTIFY` or Redis pub/sub for the live event channel? Phase 0a writes to `legal.event_log` regardless. Live channel choice affects Phase 1 dispatcher latency, not Phase 0a.

All other v1 open questions (Q1, Q2, Q3, Q5, Q-A, Q-B) closed by operator review.

---

## 13. Cross-references

- [FLOS Design v1](./FLOS-design-v1.md) — parent strategic doc
- [FLOS Phase 0a v1](./FLOS-phase-0a-legal-email-ingester-design.md) — predecessor revision (preserved for review history)
- [ADR-001 (LOCKED)](../cross-division/_architectural-decisions.md) — bilateral mirror discipline
- [ADR-002 (LOCKED)](../cross-division/_architectural-decisions.md) — Captain on Spark 2 permanent; this ingester is its sibling, also Spark 2
- Issue #177 — IMAP SEARCH overflow (the bug this design defends against)
- Issue #204 — alembic chain divergence (must be honored during Phase 0a-1 schema migration)
- PR #225 (email_backfill_legal) — existing date-banded SEARCH pattern to mirror
- PR #228 / Phase A.1 — phase-per-commit migration discipline precedent
- `/tmp/litigation-triage-20260427T074600Z.md` — operator priorities this ingester unblocks
- `/tmp/captain-restart-plan-20260427T074800Z.md` — sibling Captain reconfig (deferred)
- `tools/legal_case_manager.py:1994` — downstream consumer that depends on `file_path LIKE 'imap://%'` schema

---

**STOP per spec.** Document is on disk; no commit, no code, no migrations. Operator reviews v1.1, signs off, then **Phase 0a-1 schema migration authorization is the next operator move.**
