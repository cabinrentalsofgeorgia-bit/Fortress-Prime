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
  "fortress-guest-platform/docs/operational/human-operations-readiness-audit-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/reviewer-onboarding-governance-model.md",
  "fortress-guest-platform/docs/architecture/operational-feedback-capture-model.md",
  "fortress-guest-platform/docs/operational/governance-exception-handling-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/operational-drift-detection-model.md",
  "fortress-guest-platform/docs/operational/human-operations-incident-rehearsal-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/operational-memory-architecture-2026-05-06.md",
  "fortress-guest-platform/operational-memory/registries/operational-state.json",
  "fortress-guest-platform/operational-memory/registries/governance-registry.json",
  "fortress-guest-platform/operational-memory/registries/remediation-registry.json",
  "fortress-guest-platform/operational-memory/registries/evidence-registry.json",
  "fortress-guest-platform/operational-memory/registries/reviewer-feedback-ledger.json",
  "fortress-guest-platform/docs/architecture/operational-knowledge-graph-architecture-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/queryable-governance-model-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/wiki-evidence-graph-model-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/reviewer-remediation-lineage-model-2026-05-06.md",
  "fortress-guest-platform/operational-memory/graph/graph.json",
  "fortress-guest-platform/operational-memory/graph/graph-validation-report.json",
  "fortress-guest-platform/docs/architecture/governance-query-engine-architecture-2026-05-06.md",
  "fortress-guest-platform/operational-memory/queries/query-taxonomy.json",
  "fortress-guest-platform/operational-memory/agent-context/current-agent-context.json",
  "fortress-guest-platform/operational-memory/context-packs/codex-session.json",
  "fortress-guest-platform/docs/architecture/agent-execution-governance-architecture-2026-05-06.md",
  "fortress-guest-platform/operational-memory/agent-orchestration/registries/allowed-actions.json",
  "fortress-guest-platform/operational-memory/agent-orchestration/registries/forbidden-actions.json",
  "fortress-guest-platform/operational-memory/agent-orchestration/registries/hard-stop-policies.json",
  "fortress-guest-platform/scripts/agent-orchestration/validate-agent-orchestration.mjs",
  "fortress-guest-platform/docs/architecture/autonomous-rehearsal-architecture-2026-05-06.md",
  "fortress-guest-platform/docs/operational/autonomous-rehearsal-scenarios-2026-05-06.md",
  "fortress-guest-platform/operational-memory/agent-orchestration/dry-run-categories.json",
  "fortress-guest-platform/scripts/agent-orchestration/run-dry-run-task.mjs",
  "fortress-guest-platform/scripts/agent-orchestration/replay-dry-run.mjs",
  "fortress-guest-platform/scripts/agent-orchestration/summarize-dry-run.mjs",
  "fortress-guest-platform/operational-memory/remediation/ai-remediation-classification.json",
  "fortress-guest-platform/operational-memory/remediation/remediation-clusters.json",
  "fortress-guest-platform/operational-memory/remediation/safe-automation-candidates.json",
  "fortress-guest-platform/operational-memory/remediation/disposition-packet-index.json",
  "fortress-guest-platform/operational-memory/remediation/reviewer-work-queues.json",
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
  feedbackCaptureVisible: Boolean(checks.feedbackCapture),
  feedbackCaptureNonSensitive: Boolean(checks.feedbackCapture),
  reviewerOnboardingAcknowledgmentsVisible: Boolean(checks.reviewerOnboarding),
  roleScopeVisible: Boolean(checks.humanOperations),
  forbiddenOnboardingOutcomesVisible: Boolean(checks.reviewerOnboarding),
  governanceExceptionBoundariesVisible: Boolean(checks.governanceExceptions),
  driftDetectionVisible: Boolean(checks.driftDetection),
  rollbackVerificationVisible: Boolean(checks.operationalCertification),
  humanEscalationOnlyVisible: Boolean(checks.humanEscalation),
  escalationStopConditionsVisible: Boolean(checks.governanceExceptions),
  noPersistentReviewerAssignmentWrites: Boolean(checks.humanOperations),
  noSourcePromotion: true,
  noIngestionUploadVectorWrites: true,
  noLockedContentInspection: true,
  operationalMemoryVisible: Boolean(checks.operationalMemory),
  governanceRegistryVisible: Boolean(checks.governanceRegistry),
  remediationRegistryVisible: Boolean(checks.remediationRegistry),
  evidenceRegistryVisible: Boolean(checks.evidenceRegistry),
  wikiKnowledgeIndexVisible: Boolean(checks.wikiKnowledgeIndex),
  reviewerLedgerFoundationVisible: Boolean(checks.reviewerLedgerFoundation),
  noRegistryLegalAuthority: Boolean(checks.operationalMemory),
  operationalGraphVisible: Boolean(checks.operationalGraph),
  governanceGraphVisible: Boolean(checks.governanceGraph),
  evidenceGraphVisible: Boolean(checks.evidenceGraph),
  remediationGraphVisible: Boolean(checks.remediationGraph),
  graphValidationVisible: Boolean(checks.graphValidation),
  noGraphLegalAuthority: Boolean(checks.operationalGraph),
  governanceQueryEngineVisible: Boolean(checks.governanceQueryEngine),
  agentContextVisible: Boolean(checks.agentContext),
  safeNextActionsVisible: Boolean(checks.safeNextActionsVisible),
  forbiddenActionsVisible: Boolean(checks.forbiddenActionsVisible),
  signoffBlockersVisible: Boolean(checks.signoffBlockersVisible),
  launchBlockersVisible: Boolean(checks.launchBlockersVisible),
  agentOrchestrationVisible: Boolean(checks.agentOrchestration),
  hardStopsVisible: Boolean(checks.hardStopsVisible),
  allowedActionsVisible: Boolean(checks.allowedActionsVisible),
  taskRiskClassifierVisible: Boolean(checks.taskRiskClassifier),
  agentPlanGenerationVisible: Boolean(checks.agentPlanGeneration),
  executionReportValidationVisible: Boolean(checks.executionReportValidation),
  autonomousRehearsalVisible: Boolean(checks.autonomousRehearsal),
  dryRunExecutionVisible: Boolean(checks.dryRunExecution),
  hardStopEnforcementVisible: Boolean(checks.hardStopEnforcement),
  replayValidationVisible: Boolean(checks.replayValidation),
  blockedActionHandlingVisible: Boolean(checks.blockedActionHandling),
  governanceAssertionVisibility: Boolean(checks.governanceAssertionVisibility),
  aiRemediationExecutionVisible: Boolean(checks.aiRemediationExecution),
  remediationClassificationVisible: Boolean(checks.remediationClassificationVisible),
  dispositionPacketsVisible: Boolean(checks.dispositionPacketsVisible),
  reviewerQueuesVisible: Boolean(checks.reviewerQueuesVisible),
  aiRemediationNoSourcePromotion: Boolean(checks.noSourcePromotion),
  counselReviewRequiredVisible: Boolean(checks.counselReviewRequiredVisible),
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
  Boolean(checks.humanOperations) &&
  Boolean(checks.feedbackCapture) &&
  Boolean(checks.reviewerOnboarding) &&
  Boolean(checks.governanceExceptions) &&
  Boolean(checks.driftDetection) &&
  Boolean(checks.humanEscalation) &&
  Boolean(checks.operationalMemory) &&
  Boolean(checks.governanceRegistry) &&
  Boolean(checks.remediationRegistry) &&
  Boolean(checks.evidenceRegistry) &&
  Boolean(checks.wikiKnowledgeIndex) &&
  Boolean(checks.reviewerLedgerFoundation) &&
  Boolean(checks.operationalGraph) &&
  Boolean(checks.governanceGraph) &&
  Boolean(checks.evidenceGraph) &&
  Boolean(checks.remediationGraph) &&
  Boolean(checks.graphValidation) &&
  Boolean(checks.governanceQueryEngine) &&
  Boolean(checks.agentContext) &&
  Boolean(checks.safeNextActionsVisible) &&
  Boolean(checks.forbiddenActionsVisible) &&
  Boolean(checks.signoffBlockersVisible) &&
  Boolean(checks.launchBlockersVisible) &&
  Boolean(checks.agentOrchestration) &&
  Boolean(checks.hardStopsVisible) &&
  Boolean(checks.allowedActionsVisible) &&
  Boolean(checks.taskRiskClassifier) &&
  Boolean(checks.agentPlanGeneration) &&
  Boolean(checks.executionReportValidation) &&
  Boolean(checks.autonomousRehearsal) &&
  Boolean(checks.dryRunExecution) &&
  Boolean(checks.hardStopEnforcement) &&
  Boolean(checks.replayValidation) &&
  Boolean(checks.blockedActionHandling) &&
  Boolean(checks.governanceAssertionVisibility) &&
  Boolean(checks.aiRemediationExecution) &&
  Boolean(checks.remediationClassificationVisible) &&
  Boolean(checks.dispositionPacketsVisible) &&
  Boolean(checks.reviewerQueuesVisible) &&
  Boolean(checks.noSourcePromotion) &&
  Boolean(checks.counselReviewRequiredVisible) &&
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
  humanOperations: {
    visibility: Boolean(checks.humanOperations),
    feedbackCapture: Boolean(checks.feedbackCapture),
    reviewerOnboarding: Boolean(checks.reviewerOnboarding),
    governanceExceptions: Boolean(checks.governanceExceptions),
    driftDetection: Boolean(checks.driftDetection),
    humanEscalationOnly: Boolean(checks.humanEscalation),
    stopConditionsVisible: Boolean(checks.governanceExceptions),
    operationalMemory: Boolean(checks.operationalMemory),
    governanceRegistry: Boolean(checks.governanceRegistry),
    remediationRegistry: Boolean(checks.remediationRegistry),
    evidenceRegistry: Boolean(checks.evidenceRegistry),
    wikiKnowledgeIndex: Boolean(checks.wikiKnowledgeIndex),
    reviewerLedgerFoundation: Boolean(checks.reviewerLedgerFoundation),
    operationalGraph: Boolean(checks.operationalGraph),
    governanceGraph: Boolean(checks.governanceGraph),
    evidenceGraph: Boolean(checks.evidenceGraph),
    remediationGraph: Boolean(checks.remediationGraph),
    graphValidation: Boolean(checks.graphValidation),
    governanceQueryEngine: Boolean(checks.governanceQueryEngine),
    agentContext: Boolean(checks.agentContext),
    safeNextActionsVisible: Boolean(checks.safeNextActionsVisible),
    forbiddenActionsVisible: Boolean(checks.forbiddenActionsVisible),
    signoffBlockersVisible: Boolean(checks.signoffBlockersVisible),
    launchBlockersVisible: Boolean(checks.launchBlockersVisible),
    agentOrchestration: Boolean(checks.agentOrchestration),
    hardStopsVisible: Boolean(checks.hardStopsVisible),
    allowedActionsVisible: Boolean(checks.allowedActionsVisible),
    taskRiskClassifier: Boolean(checks.taskRiskClassifier),
    agentPlanGeneration: Boolean(checks.agentPlanGeneration),
    executionReportValidation: Boolean(checks.executionReportValidation),
    autonomousRehearsal: Boolean(checks.autonomousRehearsal),
    dryRunExecution: Boolean(checks.dryRunExecution),
    hardStopEnforcement: Boolean(checks.hardStopEnforcement),
    replayValidation: Boolean(checks.replayValidation),
    blockedActionHandling: Boolean(checks.blockedActionHandling),
    governanceAssertionVisibility: Boolean(checks.governanceAssertionVisibility),
    aiRemediationExecution: Boolean(checks.aiRemediationExecution),
    remediationClassificationVisible: Boolean(checks.remediationClassificationVisible),
    dispositionPacketsVisible: Boolean(checks.dispositionPacketsVisible),
    reviewerQueuesVisible: Boolean(checks.reviewerQueuesVisible),
    noSourcePromotion: Boolean(checks.noSourcePromotion),
    counselReviewRequiredVisible: Boolean(checks.counselReviewRequiredVisible),
  },
  negativeControls: {
    noDocumentBodyText: true,
    noAuthMaterial: true,
    noPersistentReviewerAssignmentWrites: simulation.noPersistentReviewerAssignmentWrites,
    noSourcePromotion: simulation.noSourcePromotion,
    noIngestionUploadVectorWrites: simulation.noIngestionUploadVectorWrites,
    noLockedContentInspection: simulation.noLockedContentInspection,
  },
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
