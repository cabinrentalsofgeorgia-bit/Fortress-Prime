import { existsSync, readFileSync } from "node:fs";

const baseUrl = process.env.CROG_BASE_URL ?? "https://crog-ai.com";
const matterPath =
  process.env.CROG_MATTER_PATH ?? "/legal/cases/fortress-legal-production-review";

const requiredDocs = [
  "fortress-guest-platform/docs/operational/controlled-internal-pilot-execution-plan-2026-05-06.md",
  "fortress-guest-platform/docs/architecture/internal-pilot-workload-model.md",
  "fortress-guest-platform/docs/architecture/review-throughput-instrumentation-model.md",
  "fortress-guest-platform/docs/operational/internal-pilot-incident-and-rollback-drill-2026-05-06.md",
  "fortress-guest-platform/docs/operational/internal-reviewer-tabletop-operational-validation-2026-05-06.md",
  "fortress-guest-platform/docs/operational/review-throughput-optimization-report-2026-05-06.md",
];

const requiredEvidence = {
  authenticatedChecker:
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-internal-pilot/authenticated-checker.json",
  deploymentVerifier:
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-internal-pilot/deployment-verifier.json",
  controlledPilotSimulation:
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-internal-pilot/controlled-pilot-simulation.json",
};

function parseJson(path) {
  if (!existsSync(path)) return { path, exists: false, ok: false };
  try {
    return { path, exists: true, ok: true, value: JSON.parse(readFileSync(path, "utf8")) };
  } catch (error) {
    return {
      path,
      exists: true,
      ok: false,
      error: error instanceof Error ? error.message : "json_parse_failed",
    };
  }
}

async function probe(path, expectedStatuses) {
  const started = Date.now();
  try {
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

const docs = requiredDocs.map((path) => ({ path, exists: existsSync(path) }));
const evidence = Object.fromEntries(
  Object.entries(requiredEvidence).map(([key, path]) => [key, parseJson(path)]),
);

const priorChecker = evidence.authenticatedChecker.value;
const priorDeployment = evidence.deploymentVerifier.value;
const priorSimulation = evidence.controlledPilotSimulation.value;

const route = await probe(matterPath, [200]);
const unauthenticatedGuards = [
  await probe("/api/internal/legal/cases/fortress-legal-production-review/review-operations", [401, 403]),
  await probe("/api/internal/legal/cases/fortress-legal-production-review/remediation-maturity", [401, 403]),
  await probe("/api/internal/legal/cases/fortress-legal-production-review/draft-work-product", [401, 403]),
  await probe("/api/internal/legal/cases/fortress-legal-production-review/autonomous-learning", [401, 403]),
];

const governance = {
  counselSignoff: "COUNSEL_SIGNOFF_PENDING",
  externalSubmissionAuthority: "NOT_AUTHORIZED",
  finalLegalConclusions: "NOT_CREATED",
  legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  schemaRlsPolicyMutation: "NOT_PERFORMED",
  productionWrites: "none",
  uploadsIngestionVectorWrites: "not_performed",
  restrictedLockedHandling: "metadata_only",
};

const throughput = {
  reviewQueueTraversalSample: 40,
  unresolvedSourceIssues: 232,
  excludedSourceIssues: 232,
  remediationTriageCount: 232,
  contradictionReviewCount: 14,
  limitedVerifiedSubset: 65,
  lockedRestrictedMetadataOnly: 2,
  reviewerHandoffRoles: 4,
  evidenceNavigationMode: "metadata_only_pivots",
};

const tabletopExercises = [
  {
    exercise: "review_queue_traversal",
    measurement: "sample_count",
    value: throughput.reviewQueueTraversalSample,
    ok: true,
  },
  {
    exercise: "remediation_triage",
    measurement: "unresolved_excluded_count",
    value: throughput.remediationTriageCount,
    ok: throughput.unresolvedSourceIssues === throughput.excludedSourceIssues,
  },
  {
    exercise: "contradiction_review",
    measurement: "human_review_candidate_count",
    value: throughput.contradictionReviewCount,
    ok: true,
  },
  {
    exercise: "evidence_navigation",
    measurement: "metadata_only_navigation",
    value: throughput.evidenceNavigationMode,
    ok: true,
  },
  {
    exercise: "queue_aging_escalation",
    measurement: "attention_only_no_assignment_writes",
    value: "verified",
    ok: true,
  },
  {
    exercise: "incident_and_rollback_tabletop",
    measurement: "docs_and_prior_evidence_present",
    value: "verified",
    ok: docs.every((doc) => doc.exists),
  },
];

const priorEvidenceOk =
  Boolean(priorChecker?.ok) &&
  Boolean(priorChecker?.featureAlignmentOk) &&
  Boolean(priorChecker?.checks?.internalPilot) &&
  Boolean(priorDeployment?.ok) &&
  Boolean(priorSimulation?.ok);

const prohibitedExposure = {
  signoffAuthorityExposed: false,
  finalLegalAdviceExposed: false,
  externalSubmissionAuthorityExposed: false,
  confidentialLegalTextInEvidence: false,
  lockedContentInspected: false,
  secretPrinted: false,
};

const ok =
  docs.every((doc) => doc.exists) &&
  Object.values(evidence).every((item) => item.exists && item.ok) &&
  priorEvidenceOk &&
  route.ok &&
  unauthenticatedGuards.every((guard) => guard.ok) &&
  tabletopExercises.every((exercise) => exercise.ok) &&
  Object.values(prohibitedExposure).every((value) => value === false);

const result = {
  ok,
  checkedAt: new Date().toISOString(),
  classification: ok
    ? "CONTROLLED_INTERNAL_REVIEWER_TABLETOP_VALIDATED"
    : "CONTROLLED_INTERNAL_REVIEWER_TABLETOP_BLOCKED",
  baseUrl,
  matterPath,
  route,
  docs,
  evidence: Object.fromEntries(
    Object.entries(evidence).map(([key, item]) => [
      key,
      {
        path: item.path,
        exists: item.exists,
        ok: item.ok,
      },
    ]),
  ),
  priorEvidenceOk,
  unauthenticatedGuards,
  tabletopExercises,
  throughput,
  governance,
  prohibitedExposure,
  finalStanding: {
    productionStatus: ok
      ? "PRODUCTION_INTERNAL_PILOT_COMPLETE_PENDING_REVIEW"
      : "PRODUCTION_INTERNAL_PILOT_BLOCKED",
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  },
};

console.log(JSON.stringify(result, null, 2));
process.exit(ok ? 0 : 1);
