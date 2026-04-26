# Runbook: `email_backfill_legal`

Operator playbook for the case-aware IMAP email backfill
(`backend/scripts/email_backfill_legal.py`). Read this before running
against any case_slug, before triaging quarantined emails, and before
attempting a rollback.

Last updated: PR I (2026-04-26). Owner: Legal Platform.

---

## 1. What it is

A single command that pulls case-relevant emails from the cPanel IMAP
server (gary-gk + gary-crog mailboxes), routes each to the correct
`case_slug` via a rule-based classifier, and runs them through the
canonical `process_vault_upload()` pipeline so they land in
`legal.vault_documents` + the appropriate Qdrant collection
(`legal_ediscovery` for work product, `legal_privileged_communications`
for privileged content).

The classifier source-of-truth is the **2026-04-25b IMAP audit** at
`/mnt/fortress_nas/audits/email-coverage-inventory-20260425b.md` and
the architectural decisions in
`/mnt/fortress_nas/audits/pr-i-email-backfill-plan-20260426.md`.

---

## 2. Pre-flight gates (8 checks; failed pre-flight does not pollute the audit table)

| # | Gate | Failure mode |
| --- | --- | --- |
| 1 | `legal.cases` row exists in **both** fortress_prod and fortress_db for the target case_slug | run PR B-style insertion first |
| 2 | PostgreSQL is writable in both DBs (SELECT 1 + scratch INSERT into `legal.ingest_runs` using the real case_slug) | check `POSTGRES_ADMIN_URI` and DB up |
| 3 | PR D-pre2 schema constraints present in both DBs (FK + UNIQUE + CHECK on `legal.vault_documents`) | apply alembic `d8e3c1f5b9a6` |
| 4 | Qdrant `legal_ediscovery` and `legal_privileged_communications` both reachable, vector_size 768 | spin up Qdrant or fix `QDRANT_URL` |
| 5 | `process_vault_upload` + `LegacySession` importable | resolve the import error before retry |
| 6 | Lock file at `/tmp/email-backfill-{slug}.lock` not held by another live run | wait, or `--force` after staleness verified |
| 7 | IMAP credentials available via `pass show fortress/mailboxes/<alias>` | rotate or fix the pass entry |
| 8 | `--since` and `--until` parse as ISO dates | fix the CLI args |

Pre-flight exit code: **3**. Look for `PREFLIGHT FAILED:` on stderr.

---

## 3. Classifier rules (precedence-ordered)

The classifier returns one of: `case_slug` (string), or `None` (quarantine).
First matching rule wins.

### Rule 1 — explicit docket number in subject or body

| Pattern (case-insensitive) | Routes to |
| --- | --- |
| `2:21-cv-00226` | `7il-v-knight-ndga-i` |
| `2:26-cv-00113` | `7il-v-knight-ndga-ii` |

### Rule 2 — Vanderburge keywords in subject or body

`vanderburge`, `karen vanderburge`, `fannin county`, `easement`,
`appalachian judicial circuit` → `vanderburge-v-knight-fannin`.

### Rule 3 — 7IL-prefix keywords (date-disambiguated)

`7il properties`, `7 il properties`, `thor james`, `fish trap`,
`fish-trap`, `thatcher`, `thacker`:
- INTERNALDATE year ≥ 2026 → `7il-v-knight-ndga-ii`
- Otherwise → `7il-v-knight-ndga-i`

### Rule 4 — counsel-domain match (with cc disambiguation)

If sender or any To/Cc/Bcc address is at a counsel domain
(`mhtlegal.com`, `fgplaw.com`, `dralaw.com`, `wilsonhamilton.com`,
`wilsonpruittlaw.com`, `msp-lawfirm.com`, `masp-lawfirm.com`):

1. **Cc Frank Moore** (matches `frank moore`, `frank.moore`,
   `frankmoore`, `f.moore`, `fmoore@`) → `vanderburge-v-knight-fannin`
2. **Cc other your-side counsel** (any `fgplaw`/`mhtlegal`/`dralaw`/
   `wilsonhamilton`/`wilsonpruittlaw` not from sender):
   - 2026+ → `7il-v-knight-ndga-ii`
   - Pre-2026 → `7il-v-knight-ndga-i`
3. **Sanker (msp-lawfirm.com or masp-lawfirm.com) date fallback:**
   - 2026+ → `7il-v-knight-ndga-ii`
   - 2021-2025 → `7il-v-knight-ndga-i`
   - 2019-2020 → `None` (Vanderburge/Case-I overlap; needs human review)
   - Other / undated → `None`
4. **Other counsel domain + date in case window** → that case's slug

### Rule 5 — opposing-counsel terms

`fmglaw.com`, `goldberg`, `brian goldberg` (in subject/body or any address)
→ Case I or Case II depending on which case's opposing-counsel list
matches first. Always **work-product track** (not privileged).

`frank moore` (Vanderburge opposing) → Vanderburge. Bare `moore` is
**intentionally excluded** here — too FP-prone (Roy Moore newsletters,
real estate Moore listings, etc.). Surfaces only when paired with
counsel-domain context (Rule 4 cc analysis).

### Rule 6 — username/name terms with date window

`podesta`, `frank podesta`, `argo`, `alicia argo`, `terry wilson`,
`twilson` (in subject/body) + INTERNALDATE within the case's date window:

| Term cluster | Case | Date window |
| --- | --- | --- |
| podesta, argo, terry wilson, twilson | `7il-v-knight-ndga-i` | 2018-01-01 → 2025-12-31 |
| sanker, jsank, jsanker | `7il-v-knight-ndga-ii` | 2026-01-01 → forever |
| sanker, jsank, jsanker | `vanderburge-v-knight-fannin` | 2019-01-01 → 2021-12-31 |

### Rule 7 — fallback

No match → `None` → quarantine.

---

## 4. Cross-case disambiguation (the Sanker problem)

Sanker (`msp-lawfirm.com`, ~1,500 audit hits) is your-side trial
cocounsel for Case I AND defense counsel for Vanderburge. The
disambiguation algorithm is encoded in Rule 4 above, but for operator
reference:

```
Sanker email arrives
  │
  ├─ Subject/body has "2:21-cv-00226" → Case I
  ├─ Subject/body has "2:26-cv-00113" → Case II
  ├─ Subject/body has "vanderburge"/"easement"/"fannin county" → Vanderburge
  ├─ Cc Frank Moore (any pattern) → Vanderburge
  ├─ Cc other your-side counsel (Podesta, etc.) → Case I (pre-2026) or Case II (2026+)
  ├─ INTERNALDATE 2026+ no other signal → Case II
  ├─ INTERNALDATE 2021-2025 no other signal → Case I
  ├─ INTERNALDATE 2019-2020 no other signal → QUARANTINE (ambiguous)
  └─ Otherwise → QUARANTINE
```

Quarantine volume estimate: ~450 emails of the ~1,500 Sanker hits will
land in quarantine for human review.

---

## 5. Privilege routing

The classifier's `privileged: bool` flag is **informational**. The actual
routing decision (work-product vs privileged Qdrant collection) is made
inside `process_vault_upload()` by its own privilege classifier
(Qwen2.5 with confidence ≥ 0.7 threshold).

This is intentional: backfill emails go through the same privilege
classifier as live-ingested emails, so the two sources produce identical
artifacts. PR I doesn't bypass or override that decision.

If `privileged_counsel_domains` for the target case includes the email's
domain match, the classifier is more likely to flag it privileged
(matches the email parsing path in `_derive_privileged_counsel_domain`).
PR I doesn't need to do anything special here.

---

## 6. CLI usage

```bash
python -m backend.scripts.email_backfill_legal \
    --case-slug 7il-v-knight-ndga-i \
    --mailbox gary-gk,gary-crog \
    --since 2018-01-01 --until 2025-12-31

# Smoke before production
python -m backend.scripts.email_backfill_legal \
    --case-slug 7il-v-knight-ndga-i \
    --dry-run --limit 10

# Resume from state
python -m backend.scripts.email_backfill_legal \
    --case-slug 7il-v-knight-ndga-i --resume

# Include emails that classify to None (quarantine flow)
python -m backend.scripts.email_backfill_legal \
    --case-slug 7il-v-knight-ndga-i --include-quarantine

# Rollback (deletes vault_documents .eml rows + Qdrant points; confirmation
# required unless --force)
python -m backend.scripts.email_backfill_legal \
    --case-slug 7il-v-knight-ndga-i --rollback
```

`--case-slug` is a positive selector: only emails classified to that
exact slug are ingested. Emails classified to a different case are
**skipped**; emails classified to `None` are **skipped** unless
`--include-quarantine` is set (in which case they're skipped with a
"quarantined" status entry in the manifest).

---

## 7. Manifest schema

Every successful run writes
`/mnt/fortress_nas/audits/email-backfill-{case_slug}-{ts}.json`:

```json
{
  "case_slug":            "...",
  "started_at":           "...",
  "finished_at":          "...",
  "runtime_seconds":      ...,
  "args":                 {...},
  "host":                 "...",
  "pid":                  ...,
  "ingest_run_id":        "uuid",
  "mailboxes":            ["gary-gk", "gary-crog"],
  "total_uids":           N,
  "ingested":             N,
  "duplicate":            N,
  "quarantined":          N,
  "failed":               N,
  "skipped":              N,
  "by_classification":    {...},
  "quarantine_log":       [{"uid": "...", "reason": "..."}, ...],
  "errors":               [{"uid": "...", "error": "..."}]
}
```

Quick triage:
- `failed == 0` and `ingested ≈ expected per audit` → clean run
- `quarantined > 0` → operator triages each entry; either re-run with
  explicit case_slug after manual decision, or accept the quarantine
- `failed > 0` → see `errors[]` — each entry has the UID, mailbox,
  folder, error string

---

## 8. Recovery procedures

### 8.1  Ctrl-C / SIGTERM

State file at `/tmp/email-backfill-{case_slug}.state.json` checkpoints
completed UIDs. Re-run with `--resume`; previously-completed UIDs are
skipped. In-flight UIDs may have left vault_documents rows in `pending`
or `vectorizing` — those are also caught by `--resume` since the
existence-check at the start of each email path catches terminal-status
rows.

### 8.2  Lock file left behind

```bash
cat /tmp/email-backfill-{slug}.lock
ps -p <pid_from_lock>
```

If the PID is gone, delete the lock manually OR pass `--force` (the
script auto-overrides locks > 6 h old).

### 8.3  IMAP connection drop

The script retries up to 3 times per band with exponential backoff
(2/8/20s). On exhaustion, the term is marked errored in the manifest
and the sweep continues.

### 8.4  Quarantine triage

For each `quarantine_log` entry, the operator decides which case the
email belongs to. After that decision, run:

```bash
python -m backend.scripts.email_backfill_legal \
    --case-slug <chosen-case> \
    --include-quarantine \
    --limit 1
```

(Targeted re-classification scoped to one email is a future enhancement;
today the operator may need to process all quarantined emails per
chosen case via re-run.)

---

## 9. Rollback

`--rollback` deletes all `legal.vault_documents` rows where:
- `case_slug` matches AND
- `file_name` ends in `.eml`

…on **both** `fortress_prod` and `fortress_db`, plus Qdrant points
across both `legal_ediscovery` and `legal_privileged_communications`
collections where `payload.case_slug` matches.

It does **not** touch:
- NAS files (vault NFS copies)
- `legal.cases` row
- `legal.privilege_log` (audit trail must outlive the data)
- vault_documents rows that came from non-email ingestion paths
  (the `.eml` filename suffix scopes the delete)

```bash
python -m backend.scripts.email_backfill_legal \
    --case-slug 7il-v-knight-ndga-i --rollback
```

You'll be prompted to type the case_slug back. Pass `--force` to skip
the prompt.

Rollback writes a separate manifest at
`/mnt/fortress_nas/audits/email-backfill-rollback-{slug}-{ts}.json`.

---

## 10. Common operator queries

```sql
-- 10.1  Email backfill rows per case
SELECT case_slug, count(*) AS email_rows
FROM legal.vault_documents
WHERE file_name LIKE '%.eml'
GROUP BY case_slug
ORDER BY case_slug;

-- 10.2  Quarantine log review (run-by-run; not a persistent table today)
-- Read the manifest's quarantine_log section directly:
--   /mnt/fortress_nas/audits/email-backfill-{case_slug}-{ts}.json

-- 10.3  Email-rows per processing_status (cross-cutting)
SELECT processing_status, count(*)
FROM legal.vault_documents
WHERE file_name LIKE '%.eml'
GROUP BY processing_status
ORDER BY processing_status;

-- 10.4  Recent ingest_runs for email backfill
SELECT id, case_slug, status, processed, errored, skipped, started_at
FROM legal.ingest_runs
WHERE script_name = 'email_backfill_legal'
ORDER BY started_at DESC LIMIT 20;
```

---

## 11. Cross-references

- Plan: `/mnt/fortress_nas/audits/pr-i-email-backfill-plan-20260426.md`
- Audit: `/mnt/fortress_nas/audits/email-coverage-inventory-20260425b.md`
- Existing pipeline: `backend/services/legal_ediscovery.py::process_vault_upload`
- Privilege architecture: `docs/runbooks/legal-privilege-architecture.md`
- Vault documents schema: `docs/runbooks/legal-vault-documents.md`
- Vault ingest (PR D pattern, the basis for this script): `docs/runbooks/legal-vault-ingest.md`
- IMAP audit script (the one that produced the classifier source data): `/tmp/imap_party_audit.py`
- Issue #209 — `legal.ingest_runs` row CASCADE on case_slug rename
- Issue #218 — pre-2018 archive optimization
