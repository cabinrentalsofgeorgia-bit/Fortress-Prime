import { spawnSync } from "node:child_process";

const baseUrl = process.env.CROG_BASE_URL ?? "https://crog-ai.com";
const matterPath =
  process.env.CROG_MATTER_PATH ?? "/legal/cases/fortress-legal-production-review";
const authState = process.env.CROG_AUTH_STATE;

async function probe(path, expectedStatuses) {
  const url = new URL(path, baseUrl).toString();
  const started = Date.now();
  try {
    const response = await fetch(url, {
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
  } catch (error) {
    return {
      path,
      status: null,
      ok: false,
      duration_ms: Date.now() - started,
      error: error instanceof Error ? error.message.slice(0, 200) : "unknown",
    };
  }
}

function systemdActive(unit) {
  const result = spawnSync("systemctl", ["is-active", unit], {
    encoding: "utf8",
    timeout: 10_000,
  });
  return {
    unit,
    active: result.status === 0 && result.stdout.trim() === "active",
    status: result.stdout.trim() || "unknown",
  };
}

function runChecker() {
  if (!authState) {
    return {
      skipped: true,
      reason: "CROG_AUTH_STATE not set",
    };
  }
  const result = spawnSync("node", ["scripts/verification/check-crog-fortress-ui.mjs"], {
    env: {
      ...process.env,
      FORTRESS_CHECKER_INCLUDE_TEXT_SAMPLE: "0",
    },
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
    errorSummary: parsed?.errorSummary ?? null,
    httpErrors: parsed?.httpErrors ?? null,
    stderr: result.stderr ? "checker wrote stderr; inspect local sanitized logs" : "",
  };
}

const checks = {
  publicRoutes: [
    await probe("/", [200]),
    await probe(matterPath, [200]),
  ],
  unauthenticatedGuards: [
    await probe("/api/internal/legal/cases/fortress-legal-production-review/draft-work-product", [
      401,
      403,
    ]),
    await probe("/api/internal/legal/cases/fortress-legal-production-review/autonomous-learning", [
      401,
      403,
    ]),
    await probe("/api/internal/legal/cases/fortress-legal-production-review/remediation-maturity", [
      401,
      403,
    ]),
    await probe("/api/internal/legal/cases/fortress-legal-production-review/review-operations", [
      401,
      403,
    ]),
    await probe("/api/internal/legal/cases/fortress-legal-production-review/operational-memory", [
      401,
      403,
    ]),
  ],
  services: [
    systemdActive("crog-ai-frontend.service"),
    systemdActive("fortress-backend.service"),
    systemdActive("cloudflared.service"),
  ],
};

const checker = runChecker();
const checkerChecks = checker.checks ?? {};
const humanOperations = {
  visibility: Boolean(checkerChecks.humanOperations),
  feedbackCapture: Boolean(checkerChecks.feedbackCapture),
  reviewerOnboarding: Boolean(checkerChecks.reviewerOnboarding),
  governanceExceptions: Boolean(checkerChecks.governanceExceptions),
  driftDetection: Boolean(checkerChecks.driftDetection),
  humanEscalationOnly: Boolean(checkerChecks.humanEscalation),
  operationalMemory: Boolean(checkerChecks.operationalMemory),
  governanceRegistry: Boolean(checkerChecks.governanceRegistry),
  remediationRegistry: Boolean(checkerChecks.remediationRegistry),
  evidenceRegistry: Boolean(checkerChecks.evidenceRegistry),
  wikiKnowledgeIndex: Boolean(checkerChecks.wikiKnowledgeIndex),
  reviewerLedgerFoundation: Boolean(checkerChecks.reviewerLedgerFoundation),
  operationalGraph: Boolean(checkerChecks.operationalGraph),
  governanceGraph: Boolean(checkerChecks.governanceGraph),
  evidenceGraph: Boolean(checkerChecks.evidenceGraph),
  remediationGraph: Boolean(checkerChecks.remediationGraph),
  graphValidation: Boolean(checkerChecks.graphValidation),
  governanceQueryEngine: Boolean(checkerChecks.governanceQueryEngine),
  agentContext: Boolean(checkerChecks.agentContext),
  safeNextActionsVisible: Boolean(checkerChecks.safeNextActionsVisible),
  forbiddenActionsVisible: Boolean(checkerChecks.forbiddenActionsVisible),
  signoffBlockersVisible: Boolean(checkerChecks.signoffBlockersVisible),
  launchBlockersVisible: Boolean(checkerChecks.launchBlockersVisible),
  agentOrchestration: Boolean(checkerChecks.agentOrchestration),
  hardStopsVisible: Boolean(checkerChecks.hardStopsVisible),
  allowedActionsVisible: Boolean(checkerChecks.allowedActionsVisible),
  taskRiskClassifier: Boolean(checkerChecks.taskRiskClassifier),
  agentPlanGeneration: Boolean(checkerChecks.agentPlanGeneration),
  executionReportValidation: Boolean(checkerChecks.executionReportValidation),
  autonomousRehearsal: Boolean(checkerChecks.autonomousRehearsal),
  dryRunExecution: Boolean(checkerChecks.dryRunExecution),
  hardStopEnforcement: Boolean(checkerChecks.hardStopEnforcement),
  replayValidation: Boolean(checkerChecks.replayValidation),
  blockedActionHandling: Boolean(checkerChecks.blockedActionHandling),
  governanceAssertionVisibility: Boolean(checkerChecks.governanceAssertionVisibility),
};
const ok =
  checks.publicRoutes.every((item) => item.ok) &&
  checks.unauthenticatedGuards.every((item) => item.ok) &&
  checks.services.every((item) => item.active) &&
  (checker.skipped ||
    (checker.ok &&
      checker.featureAlignmentOk &&
      Object.values(humanOperations).every(Boolean)));

const result = {
  ok,
  checkedAt: new Date().toISOString(),
  baseUrl,
  matterPath,
  checks,
  authenticatedChecker: checker,
  humanOperations,
  governance: {
    counselSignoff: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  },
};

console.log(JSON.stringify(result, null, 2));
process.exit(ok ? 0 : 1);
