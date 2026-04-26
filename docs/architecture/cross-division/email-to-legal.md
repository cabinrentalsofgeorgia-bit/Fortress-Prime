# Cross-Division Flow: Email → Legal

Last updated: 2026-04-26

## Summary

Inbound email reaches Fortress via Captain (live capture, future-only) or PR I email backfill (historical, case-aware). Once an email is identified as legal-relevant — by sender domain, subject keyword, or KNOWN PARTIES match — it lands in `legal.vault_documents` via `process_vault_upload()` and gets routed (work-product or privileged) into the appropriate Qdrant collection.

## Path

```
[ IMAP cPanel ]                 [ Captain (live) ]                  [ Legal Vault ]
   │                                 │                                    │
   ├─ gary-gk          ───►  capture + classify  ───►   process_vault_upload()
   ├─ gary-crog                                            │
   ├─ info-crog                                            ├─► legal.vault_documents
   └─ legal-cpanel                                         │   (status pending → completed
                                                           │                  / locked_privileged
                                                           │                  / ocr_failed
                                                           │                  / failed)
                                                           │
                                                           ├─► legal_ediscovery (work product)
                                                           │   OR
                                                           └─► legal_privileged_communications
                                                               (deterministic UUID5 IDs)

[ IMAP cPanel ]                 [ PR I email_backfill_legal.py (historical) ]
   │                                 │
   ├─ gary-gk          ───►  classify_email() ───►  case_slug + privileged flag
   └─ gary-crog                       │
                                       └─► same process_vault_upload()
```

## Trigger

- **Live (Captain):** poll-driven, runs as background daemon. New IMAP messages get fetched, classified, captured.
- **Historical (PR I):** explicit operator command per `case_slug`. Pre-flight checks (8 gates), date-banded UID SEARCH, per-email `process_vault_upload()`.

## Steps

1. IMAP `EXAMINE` (read-only — no `\Seen` mutation in PR I; Captain uses `SELECT` for live capture)
2. UID SEARCH per date band (PR I) or polling for new UIDs (Captain)
3. FETCH headers + body
4. **Classify** — KNOWN PARTIES match against sender/recipient/subject/body
5. **Route** — case_slug decision (Case I / Case II / Vanderburge / quarantine)
6. Write `.eml` bytes through `process_vault_upload(mime_type='message/rfc822')`:
   - Privilege classifier (Qwen2.5 ≥ 0.7 confidence) decides privileged vs work-product
   - File hashes via SHA-256 (or Message-Id-derived for emails)
   - Composite UNIQUE `(case_slug, file_hash)` enforces dedup
   - Qdrant upsert: privileged collection (UUID5 IDs) or work-product (UUID4 today; UUID5 per Issue #210)
7. Mirror row from `fortress_db` to `fortress_prod` (PR D dual-DB pattern)
8. Audit row in `legal.ingest_runs` (PR D-pre1)

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| IMAP SEARCH overflow on gary-gk | timeout or empty results despite known traffic | date-banded SEARCH (PR I workaround for Issue #177) |
| Classifier ambiguous (Sanker 2019-2020) | `case_slug=None` from `classify_email()` | quarantine (manifest entry; `--include-quarantine` to opt in) |
| Privilege classifier low confidence | `< 0.7` or `is_privileged=false` | falls through to work-product track (safe default) |
| `vault_documents` UNIQUE violation | `INSERT … ON CONFLICT DO NOTHING RETURNING id` returns no row | NFS file deleted, status='duplicate' returned |
| Qdrant upsert fails | `vectors_indexed=0` despite chunks | row stays `completed` (Issue #201 proposes `qdrant_pending` status) |
| Pre-process exception | `process_vault_upload` raises before INSERT | quarantine to manifest only — no row created (Issue #198 proposes a sentinel `failed` row) |

## Authoritative source-of-truth

- Schema: [`../../runbooks/legal-vault-documents.md`](../../runbooks/legal-vault-documents.md)
- Classifier rules: [`../../runbooks/legal-email-backfill.md`](../../runbooks/legal-email-backfill.md) §3
- Privilege track architecture: [`../../runbooks/legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md)

## Cross-references

- Source: [`../shared/captain-email-intake.md`](../shared/captain-email-intake.md)
- Target division: [`../divisions/fortress-legal.md`](../divisions/fortress-legal.md)
- Code (live): `backend/services/legal_email_intake.py`
- Code (historical): `backend/scripts/email_backfill_legal.py` (PR I / #225)

Last updated: 2026-04-26
