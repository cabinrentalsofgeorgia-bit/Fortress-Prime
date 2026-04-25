# Runbook: Legal Privilege Architecture

How attorney-client privileged communications are classified, stored,
retrieved, and audited across the Fortress legal stack. Read this
before adding new counsel to a case, before responding to a privilege
challenge, or before flipping any of the Council retrieval flags in
production.

Owner: Legal Platform. Last updated: PR G (2026-04-25).

---

## 1. Privilege model

**Default rule:** every communication to or from a known counsel email
domain on a case is treated as attorney-client privileged. The
privilege bar is high — `confidence >= 0.7` from the classifier (a
local Qwen2.5 inference, prompt at `legal_ediscovery.PRIVILEGE_SYSTEM_PROMPT`)
flips a vault row to `processing_status='locked_privileged'`. Lower
confidence falls through to the work-product track.

The classifier looks for:

- communications between a client and their attorney seeking or
  providing legal advice
- attorney mental impressions, strategies, or legal theories
- joint defense agreement (JDA) material

A privilege match is **deterministic across re-runs** — the document's
file_hash + chunk_index is namespaced under
`f0a17e55-7c0d-4d1f-8c5a-d3b4f0e9a200` (UUID5), so re-ingesting the same
document upserts to the same Qdrant points and never produces
duplicates. (The work-product `_upsert_to_qdrant` path still uses
`uuid4()` and is non-deterministic — Issue #207 tracks the
divergence.)

A non-attorney communication (e.g. spousal — see §6) does **not**
trigger `locked_privileged` from the counsel-domain match alone. The
classifier rule is "communication with a known *attorney* domain" — if
the sender/recipient isn't on the case's `privileged_counsel_domains`
list, the document goes through the work-product path even if it
contains personally sensitive content.

---

## 2. Two-collection architecture

Privileged content is **physically separated** from work product at the
storage layer, not just by a payload tag. This is the "no leak by
metadata error" guarantee — a misconfigured filter on the work-product
collection can never accidentally surface privileged chunks because
they aren't in that collection at all.

| Collection | Purpose | Populated by |
| --- | --- | --- |
| `legal_ediscovery` | Work product (filings, evidence, depositions, discovery responses, exhibits) | `legal_ediscovery._upsert_to_qdrant` (the default branch in `process_vault_upload`) |
| `legal_privileged_communications` | Attorney-client privileged communications, work-product memos by counsel, JDA traffic | `legal_ediscovery._upsert_to_qdrant_privileged` (the privilege-shielded branch in `process_vault_upload`) |

Both collections share the same vector dimensions (768) and distance
metric (Cosine). Both index the same `case_slug` field for filtering.
The privileged collection additionally indexes:

- `privileged=true` (sentinel; every point in this collection is true,
  but the field exists so downstream consumers can sanity-assert)
- `privileged_counsel_domain` — e.g. `mhtlegal.com`
- `role` — case-specific attorney role tag (see §7)
- `privilege_type` — `attorney_client` | `work_product` | `joint_defense`

Postgres is the source of truth for the row state; Qdrant is an
index. If the two diverge (e.g. Qdrant ahead of Postgres on a partial
upsert), the row's `processing_status` and `chunk_count` columns are
authoritative, not the Qdrant point count.

---

## 3. Council retrieval policy

Council deliberation pulls from BOTH collections by default. Two
environment variables, read **at deliberation time** (not at backend
startup) so they can be flipped without a backend restart:

| Env var | Default | When to flip false |
| --- | --- | --- |
| `COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL` | `true` | Emergency containment if a privilege issue surfaces — disables the privileged collection entirely so no FYEO chunks reach personas |
| `COUNCIL_INCLUDE_RELATED_MATTERS` | `true` | When deliberating on a single matter and you want to suppress cross-matter context (e.g. comparing two cases that share counsel but should be treated independently) |

Acceptable false values: `false`, `0`, `no`, `off`, empty string. Any
other value is treated as true.

When privileged retrieval is enabled, the frozen context for the
deliberation gets a separate section:

```
=== PRIVILEGED COMMUNICATIONS ===
[PRIVILEGED · mhtlegal.com · case_i_phase_1_filing_to_depositions] [Smith Memo.eml] ...
[PRIVILEGED · fgplaw.com · case_i_phase_2_trial_and_general_counsel] [Trial Strategy.docx] ...
```

The per-chunk `[PRIVILEGED · domain · role]` tag is intentional — both
the LLM personas and any human auditing the frozen context can tell at a
glance which chunks are privileged. The tag is preserved through every
downstream pipeline (PDF export, copy/paste, search results), so
privileged content cannot be invisibly mixed into work product.

When `COUNCIL_INCLUDE_RELATED_MATTERS=true` (the default), retrieval
expands to every slug in the case's `legal.cases.related_matters` JSONB
column. Both the work-product and privileged collections are queried
for each related slug. See §10.

---

## 4. FOR YOUR EYES ONLY warning

Whenever any privileged chunk is retrieved during a deliberation, the
output gets a hard warning. This is enforced two ways:

**Structured flag — drives the UI:**

```json
{
  "contains_privileged": true,
  "privileged_warning": "<full warning text>"
}
```

The command-center deliberation panel watches every SSE event for
`contains_privileged`. The moment it appears, the FYEO Card renders —
operators see the warning in real time, not at the end of the
deliberation. (See `apps/command-center/src/lib/use-council-stream.ts`
for the event reducer.)

**In-band text — survives downstream pipelines:**

The exact warning text is appended to `consensus_summary`:

```
⚠️ FOR YOUR EYES ONLY ⚠️
This deliberation included attorney-client privileged communications.
Do not use this output in court filings, share with opposing parties,
or quote externally without explicit privilege review. Treat as
internal work product subject to attorney-client privilege.
```

The wording is fixed (canonical source: `legal_council.FOR_YOUR_EYES_ONLY_WARNING`).
**Do not paraphrase.** If a deliberation output appears in a court
filing, opposing counsel reads the exact wording — paraphrased
variants weaken the privilege assertion. Any change here must also
update:

- `apps/command-center` deliberation-panel rendering
- This runbook
- The privilege-protocol page in the operator handbook (if separate)

---

## 5. At-issue waiver — Terry Wilson

The `wilsonhamilton.com` and `wilsonpruittlaw.com` domains are Terry
Wilson's firms — original transaction closing counsel for the Fish
Trap deal at the heart of 7IL Properties LLC v. Knight. Communications
to/from these domains are normally privileged (they're attorney-client
on the underlying real estate transaction).

**At-issue waiver applies** because Knight's defense theory in
`7il-v-knight-ndga-i` is "I relied on my closing attorney's advice."
That puts the content of the attorney's advice **into the case-in-chief**
— the privilege is waived as to communications about the closing,
specifically because Knight has elected to put them at issue.

**What this means operationally:**

- These rows are still ingested as `locked_privileged` (the default
  classifier rule based on counsel domain).
- Council retrieval still treats them as privileged by default — they
  go to `legal_privileged_communications`, not `legal_ediscovery`.
- The waiver decision is **not encoded in the schema** today. Treat the
  Wilson rows as a manual category that Gary and counsel surface
  selectively per-deposition, per-filing, per-discovery-response. Any
  systemic waiver (e.g. blanket production of all Wilson emails as
  exhibits) requires:

  1. Legal review confirming the waiver scope
  2. Move the rows from privileged to work-product collection (manual
     scroll + re-upsert; see §8 recovery procedure)
  3. UPDATE `vault_documents.processing_status='completed'` for the
     specific rows so they appear in the standard Vault panel
  4. Audit trail: `legal.privilege_log` row preserved (do not delete);
     add a `waived_at` timestamp + `waiver_basis` text in a follow-up
     schema change when the waiver process is formalized.

If Knight withdraws the at-issue defense, the privilege snaps back —
the rows must move back to `legal_privileged_communications` and the
work-product copies removed. Issue #208 tracks the formal waiver
column work.

---

## 6. Spousal communication — Lissa Knight

Lissa Knight is Gary's spouse and a co-defendant on the **Vanderburge
state case**. She is **not** a co-defendant on `7il-v-knight-ndga-i` or
`7il-v-knight-ndga-ii`. Communications between Gary and Lissa fall
under spousal privilege (where applicable jurisdictionally), **not**
attorney-client privilege.

**Critical distinction:** the classifier and the
`privileged_counsel_domains` filter only fire on attorney domains. A
Gary↔Lissa email never matches a counsel domain — so by default these
documents go through the work-product path (`legal_ediscovery`
collection) and end up in the standard Vault panel without privilege
protection.

**Operational rules:**

- **Do not** add a personal email domain (e.g. `garyknight.com`,
  `lissaknight@gmail.com`) to any case's `privileged_counsel_domains`.
  That JSONB list is for **attorney** domains only; conflating spousal
  with attorney-client weakens both privileges.
- Spousal-privilege handling for the Vanderburge co-defendant matter
  is out of scope for the Fortress vault layer today. If a Gary↔Lissa
  communication needs to be privilege-protected for the Vanderburge
  case, do it via JDA wrapping with co-defense counsel — those
  attorney-bridged emails will then carry an attorney domain and hit
  the standard privilege track automatically.
- For 7IL specifically, the privilege/non-privilege test is "did an
  attorney write or read this?" — full stop. Lissa's name on a Cc
  doesn't change a work-product document into a privileged one.

If a deliberation surfaces a Lissa-only or Gary↔Lissa email in a way
that exposes confidential marital content, that's a **policy issue**
(documents shouldn't have been ingested at all if marital confidence
matters), not a privilege issue. Recovery: rollback those specific
rows via `vault_ingest_legal_case.py --rollback` for the case.

---

## 7. Adding new privileged counsel to a case

When a case engages new counsel (or transitions phases — see
`case_phase` column), update both the schema and the code. The schema
is the runtime source of truth; the code is the role-tag lookup that
labels Qdrant payloads.

### Step 1 — Update the case row

```sql
-- Example: add fgplaw.com as new co-counsel on case II
UPDATE legal.cases
SET privileged_counsel_domains = COALESCE(privileged_counsel_domains, '[]'::jsonb)
                                 || '["fgplaw.com"]'::jsonb,
    case_phase = 'counsel_engaged'
WHERE case_slug = '7il-v-knight-ndga-ii';
```

Apply on **both** `fortress_prod` and `fortress_db` (the two-DB
distribution pattern from PR B / PR D). Verify:

```sql
SELECT case_slug, jsonb_pretty(privileged_counsel_domains)
FROM legal.cases WHERE case_slug = '7il-v-knight-ndga-ii';
```

### Step 2 — Update the role map

Edit `_DOMAIN_TO_ROLE` in
`backend/services/legal_ediscovery.py`:

```python
_DOMAIN_TO_ROLE: dict[str, str] = {
    "mhtlegal.com":        "case_i_phase_1_filing_to_depositions",
    "fgplaw.com":          "case_i_phase_2_trial_and_general_counsel",
    # ... add new entry ...
    "newcounsel.com":      "case_ii_lead_counsel",
}
```

This dict is the source of the per-chunk `role` tag in
`legal_privileged_communications` payloads. Source of truth for the
role taxonomy is `pr_f_classification_rules.md` v6/v7 — update that
first if introducing a new role category, then mirror here.

### Step 3 — Re-ingest existing files (optional)

If the case already has emails to/from this counsel in the work-product
collection (e.g. they were ingested before the domain was added),
re-classify them:

```bash
# Dry run first to inventory affected rows
python -m backend.scripts.vault_ingest_legal_case \
    --case-slug 7il-v-knight-ndga-ii --dry-run

# Then re-process — resume mode skips terminal rows. To force
# re-classification of already-completed rows, manually flip them
# back to pending first:
psql ... -c "UPDATE legal.vault_documents
             SET processing_status='pending'
             WHERE case_slug='7il-v-knight-ndga-ii'
               AND processing_status='completed'
               AND (file_name LIKE '%newcounsel%' OR ...);"

python -m backend.scripts.vault_ingest_legal_case \
    --case-slug 7il-v-knight-ndga-ii
```

The re-ingest will correctly route to `locked_privileged` for any
file whose extracted text matches the new counsel domain.

### Step 4 — Restart the backend

The role-map dict is loaded at module import. Adding a new domain
requires a backend restart for the in-memory map to update. The
schema-level `privileged_counsel_domains` column doesn't drive the
classifier today — it's metadata for the UI badges. If a future PR
adds runtime classifier reads from the column, restart will no longer
be required for the schema-level change (still required for code
edits).

---

## 8. Privilege-waiver scenarios

When a privilege determination changes (waiver, court order to
produce, defensive at-issue use), the document needs to move from the
privileged track to the work-product track. **Never delete privilege
log entries** — the audit trail must outlive the data.

### Scenario: blanket waiver, doc category produced as exhibit

1. **Confirm with counsel.** Get a written sign-off (email, doc) on
   the scope of the waiver. Save in `Correspondence/`.

2. **Identify affected rows:**

   ```sql
   SELECT id, file_name, file_hash
   FROM legal.vault_documents
   WHERE case_slug = '7il-v-knight-ndga-i'
     AND processing_status = 'locked_privileged'
     AND file_name ILIKE '%[discriminator]%';
   ```

3. **Move chunks Qdrant-side** (manual today; tooling tracked as
   Issue #209):

   ```python
   # Pseudo: scroll privileged collection by case_slug + document_id,
   # read points, re-upsert to legal_ediscovery with payload.privileged
   # stripped, then delete from legal_privileged_communications.
   ```

4. **Update Postgres:**

   ```sql
   UPDATE legal.vault_documents
   SET processing_status = 'completed',
       error_detail = 'waived ' || NOW()::text || ' per ' || :sign_off_ref
   WHERE id = ANY(:doc_ids);
   ```

   Apply to both `fortress_prod` and `fortress_db`.

5. **Preserve `legal.privilege_log`.** Do not UPDATE or DELETE
   existing rows. The audit trail must show the document was
   classified privileged at ingest time — that's the truth at the
   time. The waiver is a later event; record it in a future
   `privilege_waivers` table, not by overwriting the original
   classification.

### Scenario: court orders production over objection

Same procedure, but counsel's sign-off is replaced by the court order
PDF in `Correspondence/`. Mark the `error_detail` with the case
caption and order date.

### Scenario: at-issue waiver (Terry Wilson — see §5)

Don't bulk-move the rows unless and until counsel decides to put a
specific email into the record. Keep them in
`legal_privileged_communications` so they aren't accidentally returned
from a Council deliberation that the privilege gates would otherwise
have suppressed. When a specific email is put at issue:

1. Move just that document to work-product (steps 3–4 above)
2. Note in the file: `at_issue_per <deposition or filing>`
3. The companion files (chains, attachments) often follow — review
   each.

---

## 9. Backward-compat alias semantics

PR G phase C renamed `7il-v-knight-ndga` to `7il-v-knight-ndga-i` and
created `7il-v-knight-ndga-ii` for the post-judgment matter. Existing
URLs (bookmarks, external links, embedded references in older
deliberation outputs) point to the old slug. The runtime resolves
those transparently:

- `legal.case_slug_aliases` table stores `(old_slug, new_slug, created_at)`
  rows.
- `_resolve_case_slug(session, slug)` in `backend/api/legal_cases.py`
  is called at the top of every case endpoint:
  - Fast path: slug exists in `legal.cases` → return unchanged
  - Else: lookup `case_slug_aliases.new_slug WHERE old_slug = slug` →
    on hit, log `case_slug_alias_hit` (for telemetry — used to decide
    when an old slug is safe to deprecate), return the new slug
  - Else: return original slug, caller proceeds and hits a normal 404

The URL **does not redirect**. `/cases/7il-v-knight-ndga` keeps that
path in the browser; the data resolves to `7il-v-knight-ndga-i`. This
preserves bookmark integrity while allowing the canonical slug to be
the new one.

**Adding an alias** when renaming a case:

```sql
INSERT INTO legal.case_slug_aliases (old_slug, new_slug)
VALUES ('legacy-slug', 'new-canonical-slug')
ON CONFLICT (old_slug) DO UPDATE SET new_slug = EXCLUDED.new_slug;
```

Apply to both `fortress_prod` and `fortress_db`.

**Coverage limitation:** 11 endpoints with `{slug}` in path do not
currently use `LegacySession` and therefore don't run alias resolution.
Tracked as Issue #210; for now, rely on the 12 covered endpoints that
do (full list in commit `f468f801b`).

**Deprecation path:** when the old-slug telemetry shows zero hits
over a quarterly window, deprecate the alias by deleting the row.
External links will start 404'ing — operators get a real signal to fix
the source.

---

## 10. Cross-matter retrieval — `related_matters`

Some cases share a factual foundation (the underlying transaction, the
same parties, the same evidence pool). Council deliberation should pull
context from related matters to avoid blind spots — e.g. discovery in
case I that's relevant to a question in case II.

**Schema:** `legal.cases.related_matters` is a JSONB array of
`case_slug` strings. The case itself is **not** included in its own
`related_matters` (avoid recursive expansion).

For 7IL today:

```
7il-v-knight-ndga-i:  related_matters = ["7il-v-knight-ndga-ii"]
7il-v-knight-ndga-ii: related_matters = ["7il-v-knight-ndga-i"]
```

Two-way reference is intentional — case I's privileged communications
are the primary attorney-client substrate (closed phase, full counsel
roster); case II is in `counsel_search` and has no counsel domains
yet, so a deliberation on case II that doesn't pull case I would miss
the entire history of attorney advice.

**How retrieval expands:**

When `COUNCIL_INCLUDE_RELATED_MATTERS=true`,
`run_council_deliberation` resolves `(case_slug + related_matters)` and
runs both `freeze_context` and `freeze_privileged_context` per
resolved slug. Results are merged into the frozen context with each
chunk's source clearly tagged.

**Disabling cross-matter expansion:** set
`COUNCIL_INCLUDE_RELATED_MATTERS=false` before invoking the
deliberation. Useful when the operator wants strictly per-case
retrieval (e.g. responding to a discovery interrogatory that asks
about case II only — pulling case I context could confuse the
response).

**Privilege carry-through:** the `[PRIVILEGED · domain · role]` tags
are preserved across matter expansion. A privileged chunk from case I
surfaced in a case II deliberation still tags as privileged and still
triggers the FYEO warning.

**Cycle protection:** `_resolve_related_matters_slugs` reads only the
direct `related_matters` column — it does not transitively expand
(case I → case II → case I…). If transitive expansion is ever needed,
the resolver must be amended to track a visited set; today's pattern
is one-hop only.

---

## 11. Common operator queries

```sql
-- 11.1  All privileged rows for a case
SELECT id, file_name, processing_status, created_at
FROM legal.vault_documents
WHERE case_slug = '7il-v-knight-ndga-i'
  AND processing_status = 'locked_privileged'
ORDER BY created_at DESC;

-- 11.2  Per-counsel-domain breakdown (parsing privilege_log)
SELECT classification->>'privilege_type' AS type,
       count(*) AS rows
FROM legal.privilege_log
WHERE case_slug = '7il-v-knight-ndga-i'
GROUP BY 1
ORDER BY rows DESC;

-- 11.3  Pending privilege classification
SELECT case_slug, count(*)
FROM legal.vault_documents
WHERE processing_status IN ('pending', 'processing', 'vectorizing')
GROUP BY case_slug;

-- 11.4  All cases with their counsel + related_matters
SELECT case_slug, case_phase,
       jsonb_array_length(privileged_counsel_domains) AS num_counsel,
       jsonb_array_length(related_matters) AS num_related
FROM legal.cases
ORDER BY case_slug;

-- 11.5  Aliases currently active
SELECT old_slug, new_slug, created_at FROM legal.case_slug_aliases ORDER BY created_at DESC;
```

---

## 12. Cross-references

- **PR G phase B** — schema migration adding `case_phase`,
  `privileged_counsel_domains`, `related_matters` JSONB columns and
  `legal.case_slug_aliases` table
- **PR G phase C** — data migration: rename + insert + Qdrant payload
  migration
- **PR G phase D file 1** — `process_vault_upload` privileged Qdrant
  path (`backend/services/legal_ediscovery.py`)
- **PR G phase D file 2** — alias resolution
  (`backend/api/legal_cases.py`)
- **PR G phase D file 3** — Council retrieval + FYEO + related_matters
  (`backend/services/legal_council.py`)
- **PR G phase E** — UI surfaces (command-center)
- **PR G phase F** — backend + UI tests (37 + 20)
- `pr_f_classification_rules.md` v6/v7 — source of truth for the
  attorney role taxonomy
- `docs/runbooks/legal-vault-documents.md` — vault row state machine
  and dedup contract (the underlying schema this layer assumes)
- `docs/runbooks/legal-vault-ingest.md` — ingestion pipeline
- Issue #207 — work-product Qdrant idempotency (UUID4 → UUID5)
- Issue #208 — formal at-issue waiver column
- Issue #209 — Qdrant collection migration tooling
  (privileged → work-product moves)
- Issue #210 — alias resolution coverage gap (11 endpoints)
