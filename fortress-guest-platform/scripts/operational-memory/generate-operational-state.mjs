import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const evidenceRoot = join(root, "docs", "operational", "evidence", "2026-05-06-operational-memory");
const output = join(root, "operational-memory", "registries", "operational-state.generated.json");

function readEvidence(name) {
  const path = join(evidenceRoot, name);
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

const checker = readEvidence("authenticated-checker.json");
const deployment = readEvidence("deployment-verifier.json");
const simulation = readEvidence("pilot-simulation.json");

const registry = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: [
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-capability-audit/authenticated-checker.json",
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-capability-audit/deployment-verifier.json",
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-capability-audit/pilot-simulation.json",
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-memory/authenticated-checker.json",
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-memory/deployment-verifier.json",
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-memory/pilot-simulation.json",
  ],
  standingLabels: {
    productionStatus: "PRODUCTION_OPERATIONAL_MEMORY_COMPLETE_PENDING_REVIEW",
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  },
  governanceBoundaries: ["generated_state_never_infers_signoff", "generated_state_never_infers_final_readiness"],
  evidenceRefs: [`fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-memory/`],
  validationStatus: {
    authenticatedChecker: checker?.ok === true ? "PASS" : "UNKNOWN",
    deploymentVerifier: deployment?.ok === true ? "PASS" : "UNKNOWN",
    pilotSimulation: simulation?.ok === true ? "PASS" : "UNKNOWN",
    featureAlignmentOk: checker?.featureAlignmentOk === true,
    humanOperations: checker?.checks?.humanOperations === true,
    operationalMemory: checker?.checks?.operationalMemory === true,
  },
  rollbackRefs: ["delete_generated_preview", "git_revert"],
  noSecrets: true,
  noConfidentialText: true,
  knownBlockers: [
    "232_unresolved_source_issues_excluded",
    "counsel_signoff_pending",
    "persistent_reviewer_assignment_writes_deferred",
  ],
  hardStops: ["registry_legal_authority_risk", "secret_exposure_risk", "schema_rls_policy_mutation_required"],
};

writeFileSync(output, `${JSON.stringify(registry, null, 2)}\n`);
console.log(JSON.stringify({ ok: true, output: "operational-memory/registries/operational-state.generated.json" }, null, 2));
