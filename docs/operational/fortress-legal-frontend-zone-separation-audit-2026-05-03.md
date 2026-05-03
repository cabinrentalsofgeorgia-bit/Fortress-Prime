# Fortress Legal Frontend Zone Separation Audit - 2026-05-03

Status: code + repo audit with narrow cleanup
Scope: public storefront, internal command center, legacy frontend folders, Legal hooks/types/routes/tests

## Decision

Privileged Fortress Legal UI belongs in the internal command center only:

- Authoritative internal app: `fortress-guest-platform/apps/command-center`
- Public app: `fortress-guest-platform/apps/storefront`

The public storefront must not carry active or dormant client code for privileged Legal case work, including `/api/legal` callers, `/legal/cases` routes, case-slug payloads, sanctions tripwire panels, Hive Mind/council streams, deposition/kill-sheet UI, privileged evidence views, or Legal case types.

## Findings

The internal command-center app contains the expected Legal surfaces:

- `/legal`
- `/legal/cases/[slug]`
- `/legal/council`
- `/legal/email-intake`
- Legal components for e-discovery, document viewing, counsel matrix, deposition workflows, discovery drafting, sanctions tripwire, Hive Mind editor, inference radar, and agent terminal.

The public storefront app had orphaned privileged Legal artifacts:

| Path | Finding | Runtime import status |
|---|---|---|
| `apps/storefront/src/lib/legal-hooks.ts` | Internal Legal API client hooks copied into public app. | No storefront imports found. |
| `apps/storefront/src/lib/legal-types.ts` | Internal Legal case/client types copied into public app. | No storefront imports found. |
| `apps/storefront/src/lib/use-council-stream.ts` | Legal council stream client copied into public app. | No storefront imports found. |
| `apps/storefront/e2e/legal-hivemind-telemetry.spec.ts` | Legal case/Hive Mind E2E spec in public app tree. | Not matched by current storefront Playwright `testMatch`, but still wrong-zone code. |
| `apps/storefront/e2e/legal-sanctions-tripwire.spec.ts` | Legal sanctions E2E spec in public app tree. | Not matched by current storefront Playwright `testMatch`, but still wrong-zone code. |

The cleanup removes those orphaned storefront artifacts. The matching internal command-center Legal code remains untouched.

## Guardrail Added

`apps/storefront/src/__tests__/frontend-zone-boundary.test.ts` now scans storefront `src`, `e2e`, and `tests` for privileged Legal client markers:

- `/api/legal` or `/api/internal/legal`
- `/legal/cases`
- `case_slug`
- `LegalCase`
- legal council stream markers
- sanctions/Hive Mind/deposition privileged panel markers
- forbidden copied filenames: `legal-hooks.ts`, `legal-types.ts`, `use-council-stream.ts`

The scan excludes legacy marketing content under `src/data/legacy`, where ordinary words like “legal” or “privileged” can appear in public copy and are not Fortress Legal system surfaces.

## Explicitly Not Changed

- Command-center Legal UI and tests remain authoritative.
- Storefront damage-claim hooks remain untouched. They use `/api/damage-claims/...` and are not the privileged Fortress Legal command surface.
- Public e-signature copy remains untouched; ordinary legal wording in guest/owner workflows is not Fortress Legal.
- Legacy `frontend-next` and older dashboard remnants were not cleaned in this PR; they should stay non-authoritative until a separate legacy-code retirement pass.

## Remaining Risks

1. Legacy frontend folders still contain older legal/damage-claim remnants and should not be treated as authoritative.
2. Public storefront and internal command-center still duplicate some general-purpose hooks/types; future shared packages need explicit public/internal boundaries.
3. Any future route or proxy named `/api/legal` must be rejected from `apps/storefront` and built only in `apps/command-center`.

## Next Clean Move

After this PR, the next foundation step is not more UI. The clean sequence is:

1. Keep Fortress Legal feature work paused until foundation queue is closed.
2. Continue DB/Qdrant source-of-truth hardening.
3. Create a separate legacy frontend retirement issue/PR for `frontend-next` and obsolete dashboard remnants.
