# 7IL Properties LLC v. Knight + Thor James — `legal.cases` row insertion

**Date:** 2026-04-25
**Slug:** `7il-v-knight-ndga`
**Docket:** `2:21-CV-00226-RWS` (NDGA, Hon. Richard W. Story)
**Done by:** SQL INSERT into both `fortress_prod` and `fortress_db`. The
row + `nas_layout` JSON live in the database, not in git — this doc is
the audit artifact.

## What changed

A single `legal.cases` row was inserted into both production
databases with `nas_layout` populated to point at the case's existing
NAS folder structure under `/mnt/fortress_nas/Corporate_Legal/Business_Legal/`.

| field | value |
|---|---|
| `case_slug` | `7il-v-knight-ndga` |
| `case_number` | `2:21-CV-00226-RWS` |
| `case_name` | `7IL Properties, LLC v. Gary Knight and Thor James` |
| `court` | `U.S. District Court, Northern District of Georgia` |
| `judge` | `Hon. Richard W. Story, Senior U.S. District Judge` |
| `case_type` | `civil` |
| `our_role` | `defendant` |
| `status` | `active` |
| `opposing_counsel` | `Brian S. Goldberg, Esq., Freeman Mathis & Gary LLP, brian.goldberg@fmglaw.com` |
| `petition_date` | `2021-10-18` (extracted from `#1 Complaint.pdf` first page: "Document 1 Filed 10/18/21") |
| `risk_score` | `5` |
| `id` | `4` (in both DBs) |

## NAS layout JSON

Recursive walk over 10 logical subdir keys mapped to the case's
actual folder names. PR A's handler iterates `subdir_map.items()`
generically, so logical keys beyond the canonical six are accepted
without code change.

```json
{
  "root": "/mnt/fortress_nas/Corporate_Legal/Business_Legal",
  "recursive": true,
  "subdirs": {
    "filings_incoming":   "# Pleadings - GAND",
    "filings_outgoing":   "# Pleadings - GAND",
    "correspondence":     "Correspondence",
    "evidence":           "Discovery",
    "depositions":        "Depositions",
    "certified_mail":     "Correspondence",
    "receipts":           "attroney fees",
    "thor_james_intake":  "_INBOX_PULL_20260424",
    "trespass_evidence":  "John Thacker Lawsuit",
    "thatcher_evidence":  "THATCHER LAWSUIT"
  }
}
```

Notes on the mapping:
- `filings_incoming` and `filings_outgoing` both point at
  `# Pleadings - GAND` (case folder doesn't separate them; recursive
  walk surfaces everything).
- `certified_mail` re-uses `Correspondence` (no separate cert-mail
  folder in this case).
- The `attroney fees` typo is preserved — that's the actual folder
  name on disk.
- `_INBOX_PULL_20260424` is the Thor James 12-PDF service packet
  pulled directly from `gary@garyknight.com` on 2026-04-23.

## Live verification

After `sudo systemctl restart fortress-backend`:

- Service: `active (running)`, no errors related to `nas_layout`,
  `legal_cases`, or `legal.*` queries in the boot log.
- Ingress middleware blocks direct HTTP probes from localhost (signed
  `x-fortress-tunnel-signature` required), so verification was done
  by invoking the FastAPI handler directly:

  ```python
  from backend.api.legal_cases import list_case_files
  result = await list_case_files("7il-v-knight-ndga")
  ```

  Result:
  - `total`: **1,672**
  - subdir breakdown:
    | logical subdir | files |
    |---|---:|
    | `thor_james_intake` | 634 |
    | `evidence` | 367 |
    | `filings_incoming` | 197 |
    | `filings_outgoing` | 197 |
    | `depositions` | 147 |
    | `trespass_evidence` | 60 |
    | `thatcher_evidence` | 33 |
    | `certified_mail` | 18 |
    | `correspondence` | 18 |
    | `receipts` | 1 |

  Two logical keys map to the same physical folder
  (`filings_incoming` + `filings_outgoing` both →
  `# Pleadings - GAND`; `certified_mail` + `correspondence` both →
  `Correspondence`), so the 197 + 197 + 18 + 18 entries include 215
  duplicate-listed files. **Unique file inventory ≈ 1,457**;
  filesystem total under `Business_Legal` is 1,634 (the 177-file
  delta is `@eaDir`/dotfile filtering by `_walk_case_subdir`).

- Sanity sample (Thor James intake):
  - `INV-DF-US-ZMCUKBD2GFHR5XSCI5.pdf`
  - `HA_Audit_Combined.csv`
  - `20260417_…integrationsupport-expediagroup-com_…vrbo-listing-integration.eml`
  - …and 631 more under `thor_james_intake`.

## What still doesn't render

The `legal.cases` row makes 7IL appear in the case list and the
`/files` endpoint return the file inventory. Other panels remain
empty until subsequent PRs:

- `/cases/7il-v-knight-ndga/timeline` — empty (no rows in
  `legal.case_actions / correspondence / deadlines / case_evidence`
  for this case_id).
- `/cases/7il-v-knight-ndga/vault/documents` — empty
  (`legal.vault_documents` has no rows for this slug; population
  requires `process_vault_upload()` per file).
- Graph snapshot, sanctions alerts, deposition kill-sheets — all
  empty.

These are PR D / PR E scope.

## Issue filed for follow-up

**#186 — `2:26-CV-00113-RWS` docket clarification**

The 2026-04-24 discovery sweep surfaced this docket co-existing with
`2:21-CV-00226-RWS` in the same files (both NDGA, both Story). May be
a refile, amended caption, or separate proceeding. Defer to user
clarification before adding a second `legal.cases` row.

## Rollback

```sql
DELETE FROM legal.cases WHERE case_slug = '7il-v-knight-ndga';
-- run on both fortress_prod and fortress_db
```
Then `sudo systemctl restart fortress-backend`. The `nas_layout`
column on the table itself stays (added in PR A); only this case's
row is removed.
