# FLOS Phase 0a — Legal Email Ingester Design

**Status:** PROPOSED — operator review pending
**Date:** 2026-04-27
**Scope:** Implementation spec for the new `legal_mail_ingester` that replaces the dead legacy multi-mailbox producer
**Parent:** [FLOS Design v1](./FLOS-design-v1.md)

This document is a **focused implementation spec**, not a strategic design. It defines what to build, where it lives, and the contracts it must honor. Expected length to implementation: ~600-1000 lines of Python plus ~50 lines of schema migration plus ~150 lines of CLI wrapper.

---

## 1. Goals

**Replace the dead legacy multi-mailbox poller** that started 2026-02-12, wrote ~50 emails/day to `email_archive` with `category='imap_gmail'` / `imap_ips_pop3_*`, then silently stopped 2026-03-25. **Five iterations of diagnostic work could not locate its source code.** It had no `ingested_from` attribution, no monitoring, no health check, no documentation, no tests, no logs we could find. When it broke, FLOS noticed only because the operator surfaced a litigation-correspondence-silence symptom 33 days later.

**The new ingester is the inverse:** observable, source-attributed, restartable, monitored, documented, testable. Every row it writes carries explicit producer attribution (`ingested_from='legal_mail_ingester:v1'`). Every patrol logs structurally. Every state change emits an event to the FLOS event bus. Every error surfaces in the operator command-bridge instead of going silent for a month.

This is not just a code rewrite — it's the **first installable piece of FLOS**. The producer-mystery experience is exactly the problem FLOS was designed to prevent: opaque pipelines that fail silently. Phase 0a is foundational; every subsequent FLOS phase assumes its source-attribution + event-emission contracts.

---

## 2. Architectural placement

### File location

```
backend/services/legal_mail_ingester.py     ← the ingester service (new)
backend/scripts/legal_mail_ingester_cli.py  ← operator CLI wrapper (new)
backend/api/legal_mail_health.py            ← health endpoint (new)
```

Single-file service following the `captain_multi_mailbox.py` pattern (~700 lines projected). CLI wrapper is small (`fgp legal mail status / pause / poll / resume`).

### Worker mechanism

**arq background task**, mirroring Captain's pattern. NOT a standalone systemd unit. Started by `fortress-arq-worker` on worker boot via `backend/core/worker.py:589` style:

```python
if settings.legal_mail_ingester_enabled:
    from backend.services.legal_mail_ingester import run_legal_mail_loop
    legal_mail_task = asyncio.create_task(run_legal_mail_loop(), name="legal_mail_ingester_task")
    ctx["legal_mail_ingester_task"] = legal_mail_task
```

Gated behind `LEGAL_MAIL_INGESTER_ENABLED` env var (default False during rollout, flipped to True after Phase 0a-3 validation).

### Spark allocation

**Spark 2 (control plane)** per ADR-002. Co-located with `fortress-arq-worker` (where Captain already runs). No new deployment target.

### Composition with existing services

| existing component | role for ingester |
|---|---|
| `MAILBOXES_CONFIG` env var | source of truth for mailbox list (extend with new optional fields — see §3) |
| `pass-store` | credential storage (already used by Captain) |
| `privilege_filter.classify_for_capture` | NOT directly applicable (it's for LLM training data); ingester implements its OWN privilege classification per ADR-002 using the existing `legal_ediscovery._classify_privilege` pipeline OR a lighter-weight rule-based classifier for inbound mail |
| `legal.case_watchdog` | rule table the ingester queries on every received email; emits `watchdog.matched` events on hits |
| `email_archive` | primary write target (with new `ingested_from` discipline) |
| `legal.event_log` (Phase 1) | event emission target; Phase 0a writes directly here as fallback if Phase 1 dispatcher not yet built |
| `legal_case_manager.py` (port 9878) | downstream consumer; preserves `file_path LIKE 'imap://%'` schema for compat with its bridge dashboard |

---

## 3. Inputs and contracts

### MAILBOXES_CONFIG extensions

Existing schema (current 4 entries: legal-cpanel, gary-crog, info-crog, gary-gk) keeps working. New optional fields:

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

  // NEW (all optional, sensible defaults)
  "max_messages_per_patrol": 50,
  "search_band_days": 30,
  "folder": "INBOX",
  "ingester": "legal_mail"
}
```

Field semantics:

| field | default | purpose |
|---|---|---|
| `max_messages_per_patrol` | 50 | back-pressure cap; prevents runaway ingestion when a backlog clears |
| `search_band_days` | 30 | IMAP SEARCH `SINCE <today - N days>` — bounds result set, prevents Issue #177 overflow |
| `folder` | "INBOX" | IMAP folder to poll |
| `ingester` | "captain" | which ingester owns this mailbox (`captain` or `legal_mail`); routing key |

**Both Captain AND legal_mail_ingester read MAILBOXES_CONFIG** — they filter by the `ingester` field to claim ownership. A mailbox without `ingester` defaults to Captain (preserves current behavior). Legal-relevant mailboxes get `ingester=legal_mail` to opt in.

### Sender-allowlist for high-priority routing

Phase 0a includes a `legal.priority_sender_rules` table (new) — small static config plus operator-editable:

```sql
CREATE TABLE legal.priority_sender_rules (
    id BIGSERIAL PRIMARY KEY,
    sender_pattern TEXT NOT NULL,    -- ILIKE-matched: "%@stuartattorneys.com", "%@judgesosebee.com"
    priority TEXT NOT NULL,           -- 'P1' | 'P2' | 'P3'
    case_slug TEXT,                   -- optional FK to legal.cases for case-specific rules
    rationale TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Seeded with current production patterns: `*@stuartattorneys.com`, `*@judgesosebee.com`, `*@fanninclerk*`, `*@peachcourt.com`, `*@rtsfg.com`, `*@wbd-us.com`, `*@detweiler*`, etc. Lookup is `ILIKE` against sender field.

### IMAP SEARCH banding

**Hard requirement: never issue an unbounded `SEARCH UNSEEN`.** That's how gary-gk hits Issue #177's >1MB overflow. Always pair UNSEEN with a date floor:

```python
since_date = (today - timedelta(days=mailbox.search_band_days)).strftime("%d-%b-%Y")
typ, data = conn.uid("SEARCH", f"UNSEEN SINCE {since_date}")
```

For mailboxes that exceed 50 unseen messages within the band: process up to `max_messages_per_patrol`, leave the rest for next patrol. UNSEEN flag remains set; no message is lost.

### Output contract to `email_archive`

Every row the ingester writes:

| column | value |
|---|---|
| `ingested_from` | `"legal_mail_ingester:v1"` (versioned for forward-compat) |
| `category` | `f"imap_{transport_kind}_{mailbox_alias}"` (preserve legacy schema for legal_case_manager.py compat — it queries `file_path LIKE 'imap://%'`) |
| `file_path` | `f"imap://{host}/{folder}/{uid}"` (deterministic, replayable) |
| `sender` | parsed From: header |
| `subject` | parsed Subject: header |
| `content` | body (plain or HTML-cleaned) |
| `sent_at` | parsed Date: header |
| `message_id` | parsed Message-ID: header |
| `to_addresses` / `cc_addresses` / `bcc_addresses` | parsed |
| (other existing columns) | best-effort populated |

Idempotency: dedup on `file_path` UNIQUE constraint (already exists on `email_archive.file_path`). Re-poll of an already-ingested message → ON CONFLICT DO NOTHING.

---

## 4. Source attribution discipline

### Schema migration (Phase 0a-1)

```sql
-- Backfill phase: fill in best-effort attribution for historical rows
-- Heuristic: file_path LIKE 'imap://%' AND id BETWEEN 166582 AND 174961
--   → ingested_from = 'legacy_imap_producer:unknown'  (the dead one)
-- For others, leave NULL and accept partial coverage.
UPDATE email_archive
   SET ingested_from = 'legacy_imap_producer:unknown'
 WHERE ingested_from IS NULL
   AND file_path LIKE 'imap://%'
   AND id BETWEEN 166582 AND 174961;

-- Then enforce going forward
ALTER TABLE email_archive
  ALTER COLUMN ingested_from SET NOT NULL,
  ADD CONSTRAINT chk_ingested_from_format
    CHECK (ingested_from ~ '^[a-z_]+:[a-z0-9_.-]+$');
```

### The architectural intent

This NOT NULL constraint is the single most important defense against future producer-mystery incidents. **Any code that writes to `email_archive` going forward MUST declare its identity.** No silent producers. No mystery columns full of unattributable rows. When the next producer breaks, the operator can `SELECT DISTINCT ingested_from FROM email_archive WHERE id > N` and see exactly which pipeline owns what.

Versioning convention: `<service_name>:v<integer>`. Bump version when output contract changes meaningfully.

---

## 5. Event emission contract

### Event type

`email.received`

### Payload schema

```json
{
  "event_type": "email.received",
  "ingester_version": "legal_mail_ingester:v1",
  "mailbox": "legal-cpanel",
  "received_at": "2026-04-27T15:30:00Z",
  "sender": "judicialstaff@judgesosebee.com",
  "subject": "Fw: Order on Recusal — SUV2026000013",
  "message_id": "<...@...>",
  "case_slug": "fish-trap-suv2026000013",   // null if no case match
  "privilege_class": "work_product",         // 'work_product' | 'privileged' | 'public'
  "watchdog_matches": [
    {"rule_id": 42, "priority": "P1", "search_term": "judgesosebee", "match_type": "sender"}
  ],
  "email_archive_id": 174962
}
```

### Emission mechanism

**Forward-compatible with Phase 1 dispatcher.** Phase 0a writes events directly to `legal.event_log` (the new audit table from FLOS Phase 1, surfaced ahead of dispatcher implementation):

```sql
INSERT INTO legal.event_log
  (event_type, case_slug, event_payload, emitted_at, emitted_by)
VALUES
  ('email.received', :case_slug, :payload::jsonb, NOW(), 'legal_mail_ingester:v1');
```

When Phase 1 dispatcher comes online, it consumes `legal.event_log` rows where `processed_at IS NULL` and routes them. **No code change needed in Phase 0a ingester** — emission contract stays the same; consumer changes.

If Phase 1 chooses Postgres `LISTEN/NOTIFY` or Redis pub/sub later, the ingester adds an additional fire-and-forget notify call alongside the table write. Backward compatibility preserved.

---

## 6. Operator interface

### CLI commands

```
fgp legal mail status
  → For each MAILBOXES_CONFIG entry where ingester=legal_mail:
      mailbox, last_patrol_at, last_success_at, last_error,
      messages_ingested_today, watchdog_matches_today

fgp legal mail pause --mailbox legal-cpanel [--reason "operator pause for X"]
  → Sets a row in `legal.mail_ingester_pause` (new small table)
    Ingester checks before each patrol; skips paused mailboxes
    Survives worker restart (table-backed, not memory)

fgp legal mail resume --mailbox legal-cpanel
  → Removes pause row

fgp legal mail poll --mailbox legal-cpanel --dry-run
  → Single-shot test; connects, fetches up to 5 messages, logs what would be inserted
    No DB writes, no event emission

fgp legal mail backfill --mailbox legal-cpanel --since 2026-03-25
  → Operator-triggered date-banded recovery for the 2026-03-25 → now silence
    Idempotent (file_path UNIQUE), safe to re-run
```

### Why CLI matters

The dead legacy producer had **no CLI**. To "check on it" the operator had to query `email_archive` and infer state from data. Phase 0a inverts this: the CLI surfaces health directly. Operator never needs to read DB rows to know if the ingester is alive.

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

Per-message error log line (when something fails partway):

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

If Prometheus exporter not available, write counters to a small `legal.mail_ingester_metrics` table (~6 columns) and surface via CLI status command.

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

### Last-known-good

Every successful patrol updates `legal.mail_ingester_state.last_success_at` per mailbox. CLI `status` and health endpoint both read from this table. Data-backed (not in-memory) so worker restart preserves it.

---

## 8. Migration plan

### Phase 0a-1 — Schema migration (single Alembic migration)

Adds:
- `legal.priority_sender_rules` (table)
- `legal.mail_ingester_pause` (table)
- `legal.mail_ingester_state` (table — last_*_at per mailbox)
- `legal.event_log` (table — Phase 1 dependency surfaced early; see FLOS §3.5 schema)
- `email_archive.ingested_from` NOT NULL after backfill + CHECK constraint
- Backfill UPDATE for legacy producer rows (id 166582-174961)

Apply via raw psql per Issue #204 chain divergence pattern (matches PR #228 Phase A.1 approach). Single PR with phase-per-commit discipline.

### Phase 0a-2 — Ingester service implementation

`backend/services/legal_mail_ingester.py` with:
- IMAP poll loop (mirroring Captain's banded SEARCH pattern)
- Per-message processing: parse → privilege classify → watchdog match → write email_archive → emit event_log row
- Idempotency via file_path UNIQUE
- Bilateral mirror discipline (per ADR-001) — write to fortress_db, mirror to fortress_prod
- Error handling: per-message try/except so one bad email doesn't abort the patrol

### Phase 0a-3 — CLI + health endpoint

`backend/scripts/legal_mail_ingester_cli.py` + `backend/api/legal_mail_health.py`. Both small (<200 lines combined). Test against staging mailbox (separate test mailbox; not production).

### Phase 0a-4 — Worker registration + cutover

Edit `backend/core/worker.py` to register the ingester behind `LEGAL_MAIL_INGESTER_ENABLED` flag. Default OFF in initial deploy. Operator flips on after Phase 0a-3 validation.

Mailbox cutover: edit MAILBOXES_CONFIG to add `ingester=legal_mail` to legal-relevant mailboxes (legal-cpanel, gary-gk if used for Sosebee chambers, etc.). Other mailboxes retain Captain ownership.

### Phase 0a-5 — Validation + 24h soak

Run for 24 hours in production. Verify:
- email_archive ingestion rate resumes (target: ≥20/day across legal mailboxes)
- ingested_from populated on every new row
- legal.event_log accumulates email.received events
- legal.mail_ingester_state shows fresh last_success_at for each legal mailbox
- No errored rate spikes
- gary-gk in particular: SEARCH banding works, no Issue #177 overflow

If validation passes, Phase 0a complete. Phase 0a-6 optional: backfill recovery for the 2026-03-25 → cutover-date silence using `fgp legal mail backfill --since 2026-03-25` per mailbox.

---

## 9. Open questions for operator

1. **Privilege classifier choice** — reuse `legal_ediscovery._classify_privilege` (heavyweight; LLM-backed) or build a lighter rule-based classifier (regex against domain + subject)? Inbound mail volume may favor lightweight; document handling will continue heavyweight.

2. **Captain coexistence** — should legal_mail_ingester completely replace Captain on legal-tagged mailboxes, or run alongside (Captain continues feeding `llm_training_captures`, ingester feeds `email_archive`)? Coexistence is safer but doubles IMAP poll load.

3. **Backfill scope** — recover the 2026-03-25 → cutover gap (~30 days) for all mailboxes, or only legal-tagged? Backfill is operator-triggered (not automatic) so this is a runbook decision, not a code decision.

4. **Phase 1 event bus mechanism** — Postgres LISTEN/NOTIFY or Redis pub/sub for the live event channel? Phase 0a writes to `legal.event_log` regardless; the live channel choice affects Phase 1 dispatcher latency.

5. **Bilateral mirror in same migration** — should email_archive itself be brought under bilateral fortress_db/fortress_prod discipline? Currently it's a single-DB table. Adding mirror is a meaningful schema-level change; may belong in a separate PR.

---

## 10. Cross-references

- [FLOS Design v1](./FLOS-design-v1.md) — parent strategic doc
- [ADR-001 (LOCKED)](../cross-division/_architectural-decisions.md) — bilateral mirror discipline
- [ADR-002 (LOCKED)](../cross-division/_architectural-decisions.md) — Captain on Spark 2 permanent; this ingester is its sibling, also Spark 2
- Issue #177 — IMAP SEARCH overflow (the bug this design defends against)
- Issue #204 — alembic chain divergence (must be honored during Phase 0a-1 schema migration)
- PR #225 (email_backfill_legal) — existing date-banded SEARCH pattern to mirror
- `/tmp/litigation-triage-20260427T074600Z.md` — operator priorities this ingester unblocks
- `/tmp/captain-restart-plan-20260427T074800Z.md` — sibling Captain reconfig (deferred per A.3 discussion)

---

**STOP per spec.** Document is on disk; no commit, no code, no migrations. Operator reviews + iterates. Phase 0a-1 (schema migration) is the next operator authorization point.
