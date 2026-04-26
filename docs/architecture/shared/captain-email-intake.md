# Shared: Captain — Email Intake

Spark allocation:
- **Current:** Spark 2
- **Target:** **Spark 2 permanent** (per ADR-002 LOCKED 2026-04-26 — Captain cross-mailbox classification is its core value; centralization is correct)

Last updated: 2026-04-26

## Technical overview

Captain is the live email-capture pipeline. Connects to cPanel IMAP mailboxes, fetches new messages, runs them through the junk filter, classifies by source mailbox + division hint, persists to Postgres + writes capture rows to `public.llm_training_captures` for downstream LLM fine-tuning.

Captain only watches forward — historical backfill is the **separate** PR I tooling (`backend/scripts/email_backfill_legal.py`) which writes to legal vault, not Captain's capture stream.

## Mailboxes

| Alias | IMAP user | Pass slug |
|---|---|---|
| `gary-gk` | `gary@garyknight.com` | `fortress/mailboxes/gary-garyknight` |
| `gary-crog` | `gary@cabin-rentals-of-georgia.com` | `fortress/mailboxes/gary-crog` |
| `info-crog` | `info@cabin-rentals-of-georgia.com` | `fortress/mailboxes/info-crog` |
| `legal-cpanel` | (auth failed at last audit) | `fortress/mailboxes/legal-cpanel` |

Captain's coverage as of 2026-04-25: 5,518 captures across `gary-crog` + `info-crog` (since 2026-04-24, ~2-day window). Zero coverage of `gary-gk` (the highest-volume mailbox at ~329k INBOX). See Issue #177 — gary-gk SEARCH overflow workaround needed before Captain expands to it.

## Junk filter

PR `feat/captain-junk-filter` shipped: `backend/services/captain_junk_filter.py` filters newsletters / promotional / vendor noise before classification. Configurable via `CAPTAIN_JUNK_FILTER_ENABLED` env var.

## Classification

Each captured message is tagged with `division` (`LEGAL_ADMIN`, `REAL_ESTATE`, `HEDGE_FUND`, `CROG_OPS`, etc. per `fortress_atlas.yaml`). Routing determines which downstream consumers process the message.

## Consumers

- `public.llm_training_captures` — captures for fine-tuning corpus
- `public.email_archive` — archived correspondence (~42k rows; recency gap of ~31 days as of 2026-04-25 audit; see `email-coverage-inventory-20260425.md`)
- Division-specific routing: legal-keyword emails route through `process_vault_upload`; CROG-tagged emails go to guest CRM; finance emails get tagged for hedge-fund signal extraction
- Drafts pipeline (gmail watcher): currently failing per Issue #222 (`prompts.judge_parser` ModuleNotFoundError)

## Contract / API surface

- **No REST API** — Captain is a background service, runs as systemd unit (alias-resolution and unit name TBD)
- IMAP via `imaplib.IMAP4_SSL.select(folder, readonly=False)` for live capture (uses SELECT, not EXAMINE — Captain marks `\Seen`)
- Per Issue #177 — `gary-gk` mailbox SEARCH overflows; PR I uses date-banded `UID SEARCH SINCE/BEFORE` workaround for read-only audits
- Capture record schema (`public.llm_training_captures.capture_metadata` JSONB): `sender_email`, `source_mailbox`, `sender_domain`, `recipient_emails`, `attachment_filenames`, `routing_tag`, `transport`

## Where to read the code

- `backend/services/captain_multi_mailbox.py` — multi-mailbox poller
- `backend/services/captain_junk_filter.py` — junk filter (PR captain_junk_filter)
- `backend/services/legal_email_intake.py` — legal-side intake from Captain captures
- `deploy/secrets/install.sh` — secrets loader for IMAP creds
- `secrets.manifest` — IMAP password slug registry (4 entries)

## Open coverage gaps

Per the 2026-04-25 audit:

- gary-gk → 0 captures (SEARCH overflow on the 329k-message INBOX; Issue #177)
- legal-cpanel → 0 captures (auth failure)
- email_archive → recency gap of ~31 days (latest row 2026-03-25)
- 11 KNOWN PARTIES counsel terms have IMAP hits but **zero** rows in email_archive (massive coverage gap)

The PR I email backfill tooling addresses the legal-vault side of this (case-aware historical pull); Captain coverage of `gary-gk` is a separate forward-looking initiative.

## Cross-references

- Audit: `/mnt/fortress_nas/audits/email-coverage-inventory-20260425b.md`
- PR I plan: `/mnt/fortress_nas/audits/pr-i-email-backfill-plan-20260426.md`
- Cross-flows: [`../cross-division/email-to-legal.md`](../cross-division/email-to-legal.md), [`../cross-division/email-to-accounting.md`](../cross-division/email-to-accounting.md)
- Issue #177 — gary-gk IMAP SEARCH overflow
- Issue #222 — gmail_watcher cron broken

Last updated: 2026-04-26
