# Fortress Legal NAS Layout Contract Audit - 2026-05-03

Status: read-only live audit; amended after PR #410 code reconciliation
Scope: `legal.cases.nas_layout`, Legal case API file browsing, and case-scoped ingest source layout
Related map: `docs/architecture/runtime-map.md`

No database rows, NAS files, services, application code, or migrations were changed during this audit. Post-audit application code reconciliation landed separately in PR #410.

## Summary

At audit time, there were two competing `nas_layout` shapes in the repo:

1. **Legacy/API shape:** `{root, subdirs, recursive}`
2. **Wave 7 ingest shape:** `{primary_root, include_subdirs, exclude_subdirs}`

Live `fortress_prod` and `fortress_db` currently use the Wave 7 ingest shape for Case I and Case II. The batch ingest script already understood that shape at audit time. The Legal case API file resolver did not understand it yet.

Post-audit update:

- PR #410 added `backend/services/legal/nas_layout.py` as the shared normalizer.
- Case-scoped batch ingest and Legal Command Center file browsing now interpret both supported shapes.
- The old `/mnt/fortress_nas/sectors/legal/<slug>` fallback still does not exist for Case I/II, so those matters must continue to use the curated `Corporate_Legal/Business_Legal/<slug>` layout rows.

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

Post-audit, PR #410 changed `fortress-guest-platform/backend/api/legal_cases.py` to use the shared normalizer in `backend/services/legal/nas_layout.py`.

| Input | API behavior after PR #410 |
|---|---|
| `nas_layout` null or `{}` | Falls back to `/mnt/fortress_nas/sectors/legal/<slug>` and the six-subdir legacy tree. |
| `{root, subdirs, recursive}` | Uses configured `root`, configured `subdirs`, and optional `recursive`. |
| `{primary_root, include_subdirs, exclude_subdirs}` | Uses `primary_root`, maps each included subdir to itself, defaults recursive to true when omitted, and honors excludes. |

Affected API endpoints now share the reconciled layout interpretation:

- `GET /api/internal/legal/cases/{slug}/files`
- `GET /api/internal/legal/cases/{slug}/download/{filename}`

Post-audit update: download URLs now include `subdir` and `relative_path` query parameters for stable recursive addressing; filename-only downloads remain backward compatible for unique matches and fail with conflict when ambiguous.

## Migration History

| Migration | Layout contract |
|---|---|
| `e7f9a3c2d8b1_add_legal_cases_nas_layout.py` | Introduced old/API shape: `{root, subdirs, recursive}` with `/mnt/fortress_nas/sectors/legal/<slug>` fallback. |
| `u7a8b9c0d1e2_reconcile_legal_cases_ingest_runs.py` | Seeded Case I/II with new Wave 7 ingest shape: `{primary_root, include_subdirs, exclude_subdirs}`. |

The newer migration reflects the curated Case I/II source-scoping decision, but one API resolver still reflects the older migration comment/shape.

## Current Contract Decision

After PR #410, treat this as the current safe contract:

| Surface | Authoritative layout contract today | Notes |
|---|---|---|
| Case II batch ingest | `{primary_root, include_subdirs, exclude_subdirs}` | Use `Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated`. |
| Case I batch ingest | Declared new shape, but current NAS paths are missing | Do not run Case I batch ingest without fixing or updating includes. |
| Legal Command Center file browsing | Shared normalizer accepts both legacy and Wave 7 shapes | Case I/II no longer depend on the absent `/sectors/legal/<slug>` fallback. |
| Non-7IL batch ingest | Not explicitly scoped | `{}` rows will fail batch-ingest preflight. |
| Non-7IL API file browsing | Legacy fallback | Uses `/mnt/fortress_nas/sectors/legal/<slug>` if present. |

## Open Risks

1. Case I source-of-truth layout points to missing `curated` and `case-i-context` folders.
2. `{}` intentionally means different things in different callers: batch ingest treats it as invalid; API treats it as fallback.
3. Filename-only manual downloads can still be ambiguous in recursive layouts, but now fail with conflict instead of choosing an arbitrary match.
4. The old `/mnt/fortress_nas/sectors/legal` fallback is still in code but is not valid for Case I/II.

## Recommended Next Move

Do **not** change NAS files, DB rows, or runtime services in this docs PR.

The narrow resolver reconciliation recommended by this audit landed in PR #410. The next clean moves are:

1. Keep Case II on the curated `Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated` source path.
2. Decide separately whether to create Case I `curated` / `case-i-context` folders or update its DB layout to current real paths.
3. Consider a future document-id based download route if the UI needs immutable links independent of NAS path changes.
4. Leave non-7IL `{}` batch-ingest rows untouched until each matter receives explicit scoping.
