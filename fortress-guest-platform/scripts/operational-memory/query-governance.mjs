import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const registryDir = join(root, "operational-memory", "registries");
const graphDir = join(root, "operational-memory", "graph");
const queryDir = join(root, "operational-memory", "queries");
const aiRemediationDir = join(root, "operational-memory", "remediation");
const outDir = join(root, "operational-memory", "query-results");
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));

const state = readJson(join(registryDir, "operational-state.json"));
const capabilities = readJson(join(registryDir, "capability-registry.json"));
const governance = readJson(join(registryDir, "governance-registry.json"));
const evidence = readJson(join(registryDir, "evidence-registry.json"));
const remediation = readJson(join(registryDir, "remediation-registry.json"));
const ledger = readJson(join(registryDir, "reviewer-feedback-ledger.json"));
const wiki = readJson(join(registryDir, "wiki-knowledge-index.json"));
const graph = readJson(join(graphDir, "graph.json"));
const graphValidation = readJson(join(graphDir, "graph-validation-report.json"));
const taxonomy = readJson(join(queryDir, "query-taxonomy.json"));
const aiRemediationClassification = readJson(join(aiRemediationDir, "ai-remediation-classification.json"));
const aiRemediationClusters = readJson(join(aiRemediationDir, "remediation-clusters.json"));
const safeAutomationCandidates = readJson(join(aiRemediationDir, "safe-automation-candidates.json"));
const dispositionPacketIndex = readJson(join(aiRemediationDir, "disposition-packet-index.json"));
const reviewerWorkQueues = readJson(join(aiRemediationDir, "reviewer-work-queues.json"));

const command = process.argv[2] ?? "standing";
const arg = process.argv[3] ?? null;
const shouldWrite = process.argv.includes("--write");

const standingLabels = {
  ...state.standingLabels,
  counselStatus: "COUNSEL_SIGNOFF_PENDING",
  externalSubmissionAuthority: "NOT_AUTHORIZED",
  finalLegalConclusions: "NOT_CREATED",
  legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  schemaRlsPolicyMutation: "NOT_PERFORMED",
};

const negativeControls = {
  noSecrets: true,
  noConfidentialText: true,
  noCounselSignoffAuthority: true,
  noFinalLegalConclusionAuthority: true,
  noExternalSubmissionAuthority: true,
  noSourcePromotion: true,
  noSchemaRlsPolicyMutation: true,
  readOnly: true,
};

const safeNextActions = [
  {
    action: "Review autonomous rehearsal dry-run traces and replay evidence",
    reason: "Governed dry-runs now exercise hard stops, replay validation, and evidence-backed orchestration without production mutation.",
    requiredAuthority: "senior_engineer_or_governance_reviewer",
    evidenceRefs: [
      "fortress-guest-platform/docs/architecture/autonomous-rehearsal-architecture-2026-05-06.md",
      "fortress-guest-platform/docs/operational/autonomous-rehearsal-scenarios-2026-05-06.md",
      "fortress-guest-platform/docs/operational/evidence/2026-05-06-autonomous-rehearsal/",
    ],
    humanReviewRequired: true,
  },
  {
    action: "Use query outputs to scope the next controlled operational planning phase",
    reason: "Query engine can now answer blockers, safe actions, forbidden actions, and read-first context.",
    requiredAuthority: "operator_or_engineering_lead",
    evidenceRefs: ["fortress-guest-platform/operational-memory/queries/query-taxonomy.json"],
    humanReviewRequired: true,
  },
  {
    action: "Review AI remediation disposition packets without source promotion",
    reason: "232 unresolved source issues have metadata-only classifications, clusters, safe automation candidates, disposition packets, and reviewer queues.",
    requiredAuthority: "counsel_or_source_review_lead",
    evidenceRefs: [
      "fortress-guest-platform/operational-memory/remediation/ai-remediation-classification.json",
      "fortress-guest-platform/operational-memory/remediation/disposition-packet-index.json",
      "fortress-guest-platform/operational-memory/remediation/reviewer-work-queues.json",
    ],
    humanReviewRequired: true,
  },
];

const forbiddenActions = governance.forbiddenOperations.map((operation) => ({
  action: operation,
  reason: "Forbidden by governance registry and standing labels.",
  hardStopIfAttempted: true,
}));

function capabilityList() {
  return capabilities.capabilities.map((capability) => ({
    id: capability.id,
    status: capability.status,
    maturityLevel: capability.maturityLevel,
    checkerFlag: capability.checkerFlag,
    evidencePath: capability.evidencePath,
    limitations: capability.limitations,
  }));
}

function evidenceFor(target) {
  const evidenceMatches = evidence.evidenceDirectories.filter((entry) => !target || entry.phase.includes(target) || target.includes(entry.phase));
  const capabilityMatches = capabilities.capabilities.filter((capability) => !target || capability.id.includes(target) || target.includes(capability.id));
  return {
    target: target ?? "all",
    evidenceDirectories: evidenceMatches.length ? evidenceMatches : evidence.evidenceDirectories,
    capabilities: capabilityMatches,
  };
}

function validationFor(target) {
  const matches = capabilityList().filter((capability) => !target || capability.id.includes(target) || target.includes(capability.id));
  return {
    target: target ?? "all",
    graphValidation: {
      ok: graphValidation.ok,
      nodeCount: graphValidation.nodeCount,
      edgeCount: graphValidation.edgeCount,
      noSecrets: graphValidation.noSecrets,
      noConfidentialText: graphValidation.noConfidentialText,
      governancePreserved: graphValidation.governancePreserved,
    },
    capabilities: matches,
  };
}

function agentContext() {
  return {
    canonicalRepo: "/home/admin/Fortress-Prime",
    currentWorktree: "/home/admin/Fortress-Prime-autonomous-rehearsal",
    recommendedBaseBranch: "release/fortress-legal-knowledge-graph",
    standingLabels,
    verifiedCapabilities: capabilityList().map((capability) => capability.id),
    knownBlockers: state.knownBlockers,
    safeOperatingMode: "governed_agent_orchestration_with_validation_gates",
    hardStops: governance.hardStops,
    forbiddenOperations: governance.forbiddenOperations,
    validationCommands: [
      "node fortress-guest-platform/scripts/operational-memory/validate-operational-memory.mjs",
      "node fortress-guest-platform/scripts/operational-memory/validate-knowledge-graph.mjs",
      "node fortress-guest-platform/scripts/agent-orchestration/validate-agent-orchestration.mjs",
      "node fortress-guest-platform/scripts/agent-orchestration/run-dry-run-task.mjs --category validation-only",
      "node fortress-guest-platform/scripts/agent-orchestration/summarize-dry-run.mjs",
      "node fortress-guest-platform/scripts/operational-memory/query-governance.mjs standing",
      "CROG_AUTH_STATE=/path/to/local-untracked-auth-state.json node scripts/verification/check-crog-fortress-ui.mjs",
    ],
    evidencePaths: [
      "fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-memory/",
      "fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-graph/",
      "fortress-guest-platform/docs/operational/evidence/2026-05-06-governance-query-engine/",
      "fortress-guest-platform/docs/operational/evidence/2026-05-06-agent-orchestration/",
      "fortress-guest-platform/docs/operational/evidence/2026-05-06-autonomous-rehearsal/",
    ],
    readFirst: [
      "fortress-guest-platform/docs/architecture/autonomous-rehearsal-architecture-2026-05-06.md",
      "fortress-guest-platform/docs/operational/autonomous-rehearsal-scenarios-2026-05-06.md",
      "fortress-guest-platform/operational-memory/agent-orchestration/dry-run-categories.json",
      "fortress-guest-platform/scripts/agent-orchestration/run-dry-run-task.mjs",
      "fortress-guest-platform/scripts/agent-orchestration/replay-dry-run.mjs",
      "fortress-guest-platform/docs/architecture/agent-execution-governance-architecture-2026-05-06.md",
      "fortress-guest-platform/operational-memory/agent-orchestration/registries/allowed-actions.json",
      "fortress-guest-platform/operational-memory/agent-orchestration/registries/forbidden-actions.json",
      "fortress-guest-platform/operational-memory/agent-orchestration/registries/hard-stop-policies.json",
      "fortress-guest-platform/docs/architecture/governance-query-engine-architecture-2026-05-06.md",
      "fortress-guest-platform/operational-memory/queries/query-taxonomy.json",
      "fortress-guest-platform/operational-memory/graph/graph.json",
      "fortress-guest-platform/operational-memory/registries/operational-state.json",
      "fortress-guest-platform/operational-memory/agent-context/current-agent-context.json",
    ],
    nextRecommendedPhase: "controlled_autonomous_rehearsal_review_and_dry_run_use",
    prBranchExpectations: {
      branchPrefix: "release/fortress-legal-",
      draftPrRequired: true,
      commitDiscipline: "small_focused_commits",
    },
  };
}

function reviewerContext() {
  return {
    reviewMode: "controlled_internal_review_only",
    standingLabels,
    humanReviewRequired: true,
    unresolvedSourceIssues: remediation.unresolvedSourceIssues,
    unresolvedSourceExclusionStatus: remediation.unresolvedSourceExclusionStatus,
    allowedFeedbackTypes: ledger.allowedFeedbackTypes,
    prohibitedFeedbackContent: ledger.prohibitedFeedbackContent,
    blockedActions: governance.forbiddenOperations,
  };
}

function aiRemediationSummary() {
  return {
    unresolvedIssueCount: aiRemediationClassification.unresolvedIssueCount,
    classificationSummary: aiRemediationClassification.summary,
    clusterCount: aiRemediationClusters.clusters.length,
    safeAutomationCandidateCount: safeAutomationCandidates.candidates.length,
    dispositionPacketCount: dispositionPacketIndex.packets.length,
    reviewerQueueCount: reviewerWorkQueues.queues.length,
    sourcePromotionAllowed: false,
    legalConclusion: false,
    signoffAuthority: false,
    humanReviewRequired: true,
    counselReviewRequired: true,
  };
}

function phaseRecommendation() {
  return {
    recommendedPhase: "controlled_autonomous_rehearsal_review_and_dry_run_use",
    reason: "Agent orchestration can now be exercised through non-destructive dry-runs with hard-stop enforcement, replay validation, and evidence-backed traces.",
    requiredAuthority: "operator_or_engineering_lead",
    humanReviewRequired: true,
    blockedHigherAuthorityActions: [
      "counsel_signoff",
      "external_launch",
      "final_legal_conclusions",
      "unresolved_source_promotion",
    ],
  };
}

const queryHandlers = {
  standing: () => ({ standingLabels, validationStatus: state.validationStatus, knownBlockers: state.knownBlockers }),
  capabilities: () => ({ capabilities: capabilityList() }),
  blockers: () => ({ knownBlockers: state.knownBlockers, unresolvedSourceIssues: remediation.unresolvedSourceIssues }),
  "signoff-blockers": () => ({
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    blockers: ["counsel_signoff_pending", "232_unresolved_source_issues_excluded", "human_review_required"],
    humanReviewRequired: true,
  }),
  "launch-blockers": () => ({
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    blockers: ["public_launch_forbidden", "external_legal_operations_forbidden", "counsel_signoff_pending"],
  }),
  "safe-next-actions": () => ({ safeNextActions }),
  "forbidden-actions": () => ({ forbiddenActions, hardStops: governance.hardStops }),
  evidence: () => evidenceFor(arg),
  validation: () => validationFor(arg),
  "agent-context": () => agentContext(),
  "reviewer-context": () => reviewerContext(),
  "remediation-status": () => ({
    unresolvedSourceIssues: remediation.unresolvedSourceIssues,
    unresolvedSourceExclusionStatus: remediation.unresolvedSourceExclusionStatus,
    categories: remediation.categories,
    noAutoResolution: remediation.noAutoResolution,
    humanReviewRequired: true,
    aiRemediationExecution: aiRemediationSummary(),
  }),
  "remediation-classification": () => ({
    summary: aiRemediationClassification.summary,
    issueCount: aiRemediationClassification.unresolvedIssueCount,
    sampleIssueIds: aiRemediationClassification.issues.slice(0, 10).map((issue) => issue.issueId),
    sourcePromotionAllowed: false,
    humanReviewRequired: true,
  }),
  "remediation-clusters": () => ({
    clusterCount: aiRemediationClusters.clusters.length,
    clusters: aiRemediationClusters.clusters.map((cluster) => ({
      clusterId: cluster.clusterId,
      clusterType: cluster.clusterType,
      issueCount: cluster.issueIds.length,
      automationSafety: cluster.automationSafety,
      humanReviewRequired: cluster.humanReviewRequired,
    })),
  }),
  "safe-automation-candidates": () => ({
    candidateCount: safeAutomationCandidates.candidates.length,
    candidates: safeAutomationCandidates.candidates.map((candidate) => ({
      candidateId: candidate.candidateId,
      candidateType: candidate.candidateType,
      issueCount: candidate.issueIds.length,
      requiredHumanApproval: candidate.requiredHumanApproval,
      sourcePromotionAllowed: candidate.sourcePromotionAllowed,
      legalConclusion: candidate.legalConclusion,
      signoffAuthority: candidate.signoffAuthority,
    })),
  }),
  "disposition-packets": () => ({
    packetCount: dispositionPacketIndex.packets.length,
    packets: dispositionPacketIndex.packets,
    sourcePromotionAllowed: false,
    legalConclusion: false,
    signoffAuthority: false,
  }),
  "reviewer-work-queues": () => ({
    queueCount: reviewerWorkQueues.queues.length,
    queues: reviewerWorkQueues.queues.map((queue) => ({
      queueId: queue.queueId,
      itemCount: queue.itemCount,
      packetRefs: queue.packetRefs,
      priority: queue.priority,
      reviewRole: queue.reviewRole,
      humanReviewRequired: queue.humanReviewRequired,
      sourcePromotionAllowed: queue.sourcePromotionAllowed,
    })),
  }),
  "signoff-blocking-sources": () => ({
    unresolvedIssueCount: aiRemediationClassification.unresolvedIssueCount,
    blockerCategories: aiRemediationClassification.summary.byCategory,
    counselReviewRequired: aiRemediationClassification.summary.counselReviewRequired,
    sourcePromotionAllowed: false,
    signoffAuthority: false,
  }),
  "counsel-review-required-items": () => ({
    count: aiRemediationClassification.issues.filter((issue) => issue.counselReviewRequired).length,
    issueIds: aiRemediationClassification.issues.filter((issue) => issue.counselReviewRequired).map((issue) => issue.issueId),
    humanReviewRequired: true,
    signoffAuthority: false,
  }),
  "rollback-readiness": () => ({
    rollbackRefs: graph.rollbackRefs,
    deploymentRollbackNodes: graph.nodes.filter((node) => node.type === "rollback_event").map((node) => ({
      id: node.id,
      label: node.label,
      evidenceRefs: node.evidenceRefs,
    })),
    gitRevertable: true,
  }),
  "deployment-readiness": () => ({
    deploymentNodes: graph.nodes.filter((node) => node.type === "deployment").map((node) => ({
      id: node.id,
      label: node.label,
      validationRefs: node.validationRefs,
      evidenceRefs: node.evidenceRefs,
    })),
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  }),
  "phase-recommendation": () => phaseRecommendation(),
};

if (!(command in queryHandlers)) {
  console.error(JSON.stringify({ ok: false, error: "unknown_query", allowedQueries: Object.keys(queryHandlers) }, null, 2));
  process.exit(1);
}

const result = {
  ok: true,
  query: command,
  argument: arg,
  generatedAt: new Date().toISOString(),
  taxonomyRefs: taxonomy.queries,
  standingLabels,
  result: queryHandlers[command](),
  negativeControls,
};

if (shouldWrite) {
  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, `${command}.json`), `${JSON.stringify(result, null, 2)}\n`);
}

console.log(JSON.stringify(result, null, 2));
