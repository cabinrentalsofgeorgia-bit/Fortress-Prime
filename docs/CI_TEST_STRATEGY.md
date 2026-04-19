# CI Test Strategy

## Overview

Tests are split into two tiers based on infrastructure requirements:

| Tier | Tag | Where it runs | Trigger |
|------|-----|--------------|---------|
| **CI-safe** | (no tag) | GitHub Actions (every PR) | Every push / PR |
| **Integration** | `@integration` | DGX cluster only | Manual: `make playwright-integration` |

## What runs on every PR (CI gate)

GitHub Actions `fortress-ci.yml` and `playwright-sovereign-gate.yml` run:

```
npx playwright test --grep-invert "@integration" --pass-with-no-tests
```

This **skips** any test tagged `@integration`. Currently all E2E tests are integration-tagged (they all require cluster services), so CI runs 0 Playwright tests and passes immediately. This is intentional — it unblocks CI while the integration test path is maintained separately.

**When to add a CI-safe test:** If you add a test that only needs the FastAPI backend (no NIM, no Qdrant, no live property data), do NOT add `@integration`. It will be picked up automatically by the CI run.

## What's tagged @integration

Any test that requires one or more of:
- Live property/reservation data in the database
- NIM inference endpoint (`http://192.168.0.104:8000` on spark-1)
- Qdrant vector store (`http://192.168.0.106:6333` on spark-4)
- Staff authentication with real credentials
- Live pricing engine results

### Currently tagged tests

| Test | File | Requires |
|------|------|---------|
| Guest booking critical path | `storefront/tests/e2e/booking.spec.ts` | Live DB (aska-escape-lodge), pricing engine |
| Sovereign concierge (storefront) | `storefront/tests/e2e/concierge.spec.ts` | NIM + Qdrant |
| Sovereign concierge (command-center) | `command-center/tests/e2e/concierge.spec.ts` | NIM + Qdrant |
| Hive Mind telemetry editor (storefront) | `storefront/e2e/legal-hivemind-telemetry.spec.ts` | Auth + live backend |
| Sanctions Tripwire Panel (storefront) | `storefront/e2e/legal-sanctions-tripwire.spec.ts` | Auth + live backend |
| Hive Mind telemetry editor (command-center) | `command-center/e2e/legal-hivemind-telemetry.spec.ts` | Auth + live backend |
| Sanctions Tripwire Panel (command-center) | `command-center/e2e/legal-sanctions-tripwire.spec.ts` | Auth + live backend |
| Legal Discovery Arsenal | `frontend-next/e2e/legal-discovery-arsenal.spec.ts` | Real login + live case |
| Legal Graph Panopticon | `frontend-next/e2e/legal-graph-panopticon.spec.ts` | Real login + live case |

## Running integration tests manually

From spark-node-2 (or any machine on the DGX LAN):

```bash
# Start the application stack first, then:
make playwright-integration

# Or run a specific test:
cd fortress-guest-platform/apps/storefront
npx playwright test --grep "@integration" tests/e2e/booking.spec.ts --reporter=list
```

Environment variables needed locally:
```
E2E_BASE_URL=http://127.0.0.1:3000   # or the storefront URL
E2E_BACKEND_URL=http://127.0.0.1:8100
```

## Nightly automation (future)

`.github/workflows/playwright-integration-nightly.yml` exists but is dispatch-only until a self-hosted GitHub Actions runner is registered on spark-node-2 with label `dgx-cluster`. Until then, integration tests run manually before releases.

## Decision tree: should my test be @integration?

```
Does the test call a real backend API?
├── No (pure UI, all network calls mocked)  →  CI-safe (no tag)
└── Yes
    ├── Does the API need NIM / Qdrant?      →  @integration
    ├── Does the API need live DB data       →  @integration
    │   (specific slugs, seeded records)?
    └── Does the API only need the schema    →  Probably CI-safe
        (no seed data required, no DGX)?        (test with CI DB)
```

## How to tag a new integration test

```typescript
test.describe("My feature", { tag: "@integration" }, () => {
  test("does something requiring cluster", async ({ page }) => {
    // ...
  });
});
```

Or at the individual test level:
```typescript
test("does something requiring cluster", { tag: "@integration" }, async ({ page }) => {
  // ...
});
```
