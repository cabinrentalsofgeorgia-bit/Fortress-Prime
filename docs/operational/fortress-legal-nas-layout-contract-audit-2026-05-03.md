# Fortress Legal NAS Layout Contract Audit - 2026-05-03

Status: read-only live audit
Scope: `legal.cases.nas_layout`, Legal case API file browsing, and case-scoped ingest source layout
Related map: `docs/architecture/runtime-map.md`

No database rows, NAS files, services, application code, or migrations were changed during this audit.

## Summary

There are two competing `nas_layout` shapes in the repo:

1. **Legacy/API shape:** `{root, subdirs, recursive}`
2. **Wave 7 ingest shape:** `{primary_root, include_subdirs, exclude_subdirs}`

Live `fortress_prod` and `fortress_db` currently use the Wave 7 ingest shape for Case I and Case II. The batch ingest script understands that shape. The Legal case API file resolver does **not** understand it yet.

Therefore:

- Case-scoped batch ingest can interpret the new Case I/II layout shape.
- Legal Command Center file browsing/downloading through `backend/api/legal_cases.py` will not correctly list files for Case I/II from the new layout shape.
- The old `/mnt/fortress_nas/sectors/legal/<slug>` fallback does not exist for Case I/II, so fallback behavior does not rescue those matters.

## Live DB State

Read-only query against both `fortress_prod.legal.cases` and `fortress_db.legal.cases` returned matching layout rows for the known matters.

| Case slug | Live `nas_layout` shape | DBs observed | Meaning |
|---|---|---|---|
| `7il-v-knight-ndga-i` | `{primary_root, include_subdirs, exclude_subdirs}` | `fortress_prod`, `fortress_db` | New Wave 7 ingest shape. |
| `7il-v-knight-ndga-ii` | `{primary_root, include_subdirs, exclude_subdirs}` | `fortress_prod`, `fortress_db` | New Wave 7 ingest shape. |
| `vanderburge-v-knight-fannin` | `{}` | `fortress_prod`, `fortress_db` | No explicit ingest layout yet. |
| `fish-trap-suv2026000013` | `{}` | `fortress_prod`, `fortress_db` | No explicit ingest layout yet. |
| `prime-trust-23-11161` | `{}` | `fortress_prod`, `fortress_db` | No explicit ingest layout yet. |

Live Case I layout:

```json
{
  "primary_root": "/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i",
  "include_subdirs": ["curated", "case-i-context"],
  "exclude_subdirs": []
}
```

Live Case II layout:

```json
{
  "primary_root": "/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii",
  "include_subdirs": ["curated"],
  "exclude_subdirs": []
}
```

## Live NAS Path State

Read-only path existence checks found:

| Path | Status | Meaning |
|---|---|---|
| `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i` | exists | Case I root exists. |
| `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/curated` | missing | Case I declared ingest include is currently absent. |
| `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/case-i-context` | missing | Case I declared related/context include is currently absent. |
| `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii` | exists | Case II root exists. |
| `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated` | exists | Case II declared ingest include exists. |
| `/mnt/fortress_nas/sectors/legal/7il-v-knight-ndga-i` | missing | Legacy API fallback path absent for Case I. |
| `/mnt/fortress_nas/sectors/legal/7il-v-knight-ndga-ii` | missing | Legacy API fallback path absent for Case II. |

Observed Case I root subdirs:

- `filings/`
- `filings/outgoing/`

Observed Case II root subdirs include:

- `curated/`
- `curated/documents/`
- `curated/emails/`
- `filings/outgoing/`
- `incoming/`
- `incoming/dot-gnrr-records-request-20260502/`
- `incoming/wilson-pruitt-email-intake-20260503/`
- `incoming/wilson-pruitt-email-pull-20260502/`
- `operator-memos/`
- `work-product/`
- `work-product/privileged/`

## Code Contract: Batch Ingest

`fortress-guest-platform/backend/scripts/vault_ingest_legal_case.py` treats `fortress_prod.legal.cases.nas_layout` as the source of truth.

It accepts both shapes:

| Shape | Handling |
|---|---|
| `{primary_root, include_subdirs, exclude_subdirs}` | New shape. Converts includes to a logical subdir map, defaults `recursive` to true when omitted, honors excludes. |
| `{root, subdirs, recursive}` | Legacy shape. Uses explicit logical-to-physical subdir map. |
| `{}` / null | Batch ingest preflight fails. Empty layout is not accepted for case-scoped ingest. |

For Case II, the current layout should walk `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated` recursively.

For Case I, the current layout would fail path preflight because declared includes `curated` and `case-i-context` are absent.

## Code Contract: Legal Case API

`fortress-guest-platform/backend/api/legal_cases.py` currently resolves files as follows:

| Input | API behavior |
|---|---|
| `nas_layout` null or `{}` | Falls back to `/mnt/fortress_nas/sectors/legal/<slug>` and the six-subdir legacy tree. |
| `{root, subdirs, recursive}` | Uses configured `root`, configured `subdirs`, and optional `recursive`. |
| `{primary_root, include_subdirs, exclude_subdirs}` | Not supported. `root` becomes empty, `subdirs` becomes empty, so listing returns no files. |

Affected API endpoints:

- `GET /api/internal/legal/cases/{slug}/files`
- `GET /api/internal/legal/cases/{slug}/download/{filename}`

Because Case I/II live DB rows use the new shape and `/mnt/fortress_nas/sectors/legal/<slug>` is absent for both slugs, the Legal Command Center file browser/download surface is expected to be wrong or empty for Case I/II until the API resolver is updated.

## Migration History

| Migration | Layout contract |
|---|---|
| `e7f9a3c2d8b1_add_legal_cases_nas_layout.py` | Introduced old/API shape: `{root, subdirs, recursive}` with `/mnt/fortress_nas/sectors/legal/<slug>` fallback. |
| `u7a8b9c0d1e2_reconcile_legal_cases_ingest_runs.py` | Seeded Case I/II with new Wave 7 ingest shape: `{primary_root, include_subdirs, exclude_subdirs}`. |

The newer migration reflects the curated Case I/II source-scoping decision, but one API resolver still reflects the older migration comment/shape.

## Current Contract Decision

Until a code PR reconciles the resolver, treat this as the current safe contract:

| Surface | Authoritative layout contract today | Notes |
|---|---|---|
| Case II batch ingest | `{primary_root, include_subdirs, exclude_subdirs}` | Use `Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated`. |
| Case I batch ingest | Declared new shape, but current NAS paths are missing | Do not run Case I batch ingest without fixing or updating includes. |
| Legal Command Center file browsing | Legacy `{root, subdirs, recursive}` only | Does not yet support Case I/II live layout. |
| Non-7IL batch ingest | Not explicitly scoped | `{}` rows will fail batch-ingest preflight. |
| Non-7IL API file browsing | Legacy fallback | Uses `/mnt/fortress_nas/sectors/legal/<slug>` if present. |

## Open Risks

1. Case II source-of-truth layout is correct for ingest but not for UI/API file browsing.
2. Case I source-of-truth layout points to missing `curated` and `case-i-context` folders.
3. `{}` means different things in different callers: batch ingest treats it as invalid; API treats it as fallback.
4. The newer `exclude_subdirs` field is honored by batch ingest but ignored by the API resolver.
5. The newer `include_subdirs` field defaults to recursive true in batch ingest; the old API shape defaults recursive false unless explicitly set.
6. Download-by-filename may be ambiguous in recursive layouts because nested relative paths are not part of the download route.
7. The old `/mnt/fortress_nas/sectors/legal` fallback is still in code but is not valid for Case I/II.

## Recommended Next Move

Do **not** change NAS files, DB rows, or runtime services in this docs PR.

The next implementation PR should be a narrow resolver reconciliation:

1. Add a shared layout normalization helper that accepts both shapes and returns one normalized form: `{root, subdirs, recursive, exclude_subdirs}`.
2. Use that helper in both `vault_ingest_legal_case.py` and `backend/api/legal_cases.py`.
3. Preserve legacy `{root, subdirs, recursive}` behavior for non-7IL cases.
4. Preserve `{}` API fallback behavior only where intended.
5. Add tests proving Case II new-shape layout lists files from `curated/` recursively.
6. Add tests proving batch ingest still rejects `{}` for case-scoped ingest.
7. Decide separately whether to create Case I `curated` / `case-i-context` folders or update its DB layout to current real paths.

Given active Case II priority, the lowest-risk implementation target is to make the API resolver support the new shape without changing DB values or NAS structure.
