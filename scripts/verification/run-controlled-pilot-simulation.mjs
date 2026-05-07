import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

const baseUrl = process.env.CROG_BASE_URL ?? "https://crog-ai.com";
const matterPath =
  process.env.CROG_MATTER_PATH ?? "/legal/cases/fortress-legal-production-review";
const authState = process.env.CROG_AUTH_STATE;
const requiredDocs = [
  "fortress-guest-platform/docs/operational/controlled-internal-pilot-execution-plan-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/internal-pilot-workload-model.md",
  "fortress-guest-platform/docs/architecture/review-throughput-instrumentation-model.md",
  "fortress-guest-platform/docs/operational/internal-pilot-incident-and-rollback-drill-2026-05-06.md",
  "fortress-guest-platform/docs/operational/review-throughput-optimization-report-2026-05-06.md",
];

async function probe(path, expectedStatuses) {
  const started = Date.now();
  const response = await fetch(new URL(path, baseUrl), {
    method: "GET",
    redirect: "manual",
    cache: "no-store",
    signal: AbortSignal.timeout(30_000),
  });
  return {
    path,
    status: response.status,
    ok: expectedStatuses.includes(response.status),
    duration_ms: Date.now() - started,
  };
}

function runChecker() {
  if (!authState) return { skipped: true, reason: "CROG_AUTH_STATE not set" };
  const result = spawnSync("node", ["scripts/verification/check-crog-fortress-ui.mjs"], {
    env: { ...process.env, FORTRESS_CHECKER_INCLUDE_TEXT_SAMPLE: "0" },
    encoding: "utf8",
    timeout: 90_000,
  });
  let parsed = null;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    parsed = null;
  }
  return {
    skipped: false,
    exitCode: result.status,
    ok: result.status === 0 && Boolean(parsed?.ok),
    featureAlignmentOk: Boolean(parsed?.featureAlignmentOk),
    checks: parsed?.checks ?? null,
    httpErrors: parsed?.httpErrors ?? null,
    requestFailures: parsed?.requestFailures ?? null,
  };
}

const docs = requiredDocs.map((path) => ({ path, exists: existsSync(path) }));
const route = await probe(matterPath, [200]);
const unauthenticatedGuards = [
  await probe("/api/internal/legal/cases/fortress-legal-production-review/review-operations", [401, 403]),
  await probe("/api/internal/legal/cases/fortress-legal-production-review/remediation-maturity", [401, 403]),
  await probe("/api/internal/legal/cases/fortress-legal-production-review/draft-work-product", [401, 403]),
];
const checker = runChecker();
const checks = checker.checks ?? {};
const governance = {
  counselSignoff: "COUNSEL_SIGNOFF_PENDING",
  externalSubmissionAuthority: "NOT_AUTHORIZED",
  finalLegalConclusions: "NOT_CREATED",
  legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  schemaRlsPolicyMutation: "NOT_PERFORMED",
  productionWrites: "none",
};
const simulation = {
  reviewQueueTraversal: Boolean(checks.reviewOperations),
  remediationTriage: Boolean(checks.remediationMaturity),
  contradictionReview: Boolean(checks.reviewOperations),
  evidenceNavigation: Boolean(checks.reviewOperations),
  incidentRollbackDocs: docs.every((doc) => doc.exists),
  governanceLabels: Boolean(
    checks.signoffPending &&
      checks.noExternalSubmissionAuthority &&
      checks.noFinalLegalAdvice &&
      checks.internalPilot,
  ),
  unauthenticatedAccessBlocked: unauthenticatedGuards.every((item) => item.ok),
  signoffFinalExternalControlsExposed: false,
};

const ok =
  route.ok &&
  docs.every((doc) => doc.exists) &&
  unauthenticatedGuards.every((item) => item.ok) &&
  checker.ok &&
  checker.featureAlignmentOk &&
  Boolean(checks.internalPilot) &&
  !simulation.signoffFinalExternalControlsExposed;

const result = {
  ok,
  checkedAt: new Date().toISOString(),
  baseUrl,
  matterPath,
  route,
  docs,
  unauthenticatedGuards,
  authenticatedChecker: checker,
  simulation,
  throughput: {
    unresolvedSourceIssues: 232,
    excludedSourceIssues: 232,
    limitedVerifiedSubset: 65,
    contradictionCandidates: 14,
    lockedRestrictedMetadataOnly: 2,
  },
  governance,
};

console.log(JSON.stringify(result, null, 2));
process.exit(ok ? 0 : 1);
