import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const registryRoot = join(root, "operational-memory", "agent-orchestration", "registries");
const operationalRegistryRoot = join(root, "operational-memory", "registries");
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));

const allowed = readJson(join(registryRoot, "allowed-actions.json")).actions;
const forbidden = readJson(join(registryRoot, "forbidden-actions.json")).actions;
const hardStops = readJson(join(registryRoot, "hard-stop-policies.json")).policies;
const gates = readJson(join(registryRoot, "validation-gates.json")).validationGates;
const evidenceRequirements = readJson(join(registryRoot, "evidence-requirements.json")).evidenceRequirements;
const state = readJson(join(operationalRegistryRoot, "operational-state.json"));

const taskDescription = process.argv.slice(2).join(" ").trim() || "read operational state";
const normalized = taskDescription.toLowerCase();

const forbiddenPatterns = [
  ["legal_signoff", /sign\s*off|counsel\s*signoff|approve\s*as\s*final/],
  ["final_legal_conclusion", /final\s+legal|legal\s+conclusion|final\s+advice/],
  ["external_submission", /file|serve|send|email|external\s+submission|submit\s+externally/],
  ["public_launch", /public\s+launch|enable\s+public|external\s+users?/],
  ["document_upload", /upload\s+document|new\s+document/],
  ["ingestion_rerun", /rerun\s+ingestion|intake|extract\s+all/],
  ["vector_write", /vector\s+write|qdrant|embedding\s+write/],
  ["schema_mutation", /schema|migration|alter\s+table|ddl/],
  ["rls_policy_mutation", /rls|policy\s+mutation|grant\s+privilege/],
  ["restricted_content_inspection", /locked|restricted|privileged\s+content/],
  ["confidential_text_exposure", /confidential\s+text|document\s+body|source\s+excerpt/],
  ["unresolved_source_promotion", /promote\s+unresolved|mark\s+source\s+resolved|rely\s+on\s+unresolved/],
  ["auth_bypass", /bypass\s+auth|weaken\s+auth|disable\s+auth/],
  ["secret_printing", /print\s+secret|show\s+token|show\s+cookie|auth\s+header|password/],
  ["reviewer_authority_escalation_without_approval", /grant\s+reviewer|escalate\s+reviewer|unrestricted\s+reviewer/],
];

const allowedPatterns = [
  ["run_checker", /checker|authenticated\s+check/],
  ["run_deployment_verifier", /deployment\s+verifier|verify\s+deployment/],
  ["run_pilot_simulation", /pilot\s+simulation/],
  ["run_validation", /validate|validator|test|lint|typecheck|build/],
  ["create_docs", /doc|runbook|architecture|audit/],
  ["create_evidence_summary", /evidence|summary|report/],
  ["create_read_only_ui", /read-only\s+ui|visibility|panel/],
  ["generate_context_pack", /context\s+pack|agent\s+context/],
  ["generate_plan", /plan|task\s+plan/],
  ["propose_pr", /pull\s+request|pr/],
  ["read_operational_state", /state|standing/],
  ["read_governance_registry", /governance|forbidden|allowed|hard\s+stop/],
  ["read_knowledge_graph", /graph|lineage/],
  ["summarize_evidence_refs", /evidence\s+refs?/],
  ["update_machine_readable_registry_with_nonlegal_status", /registry|machine-readable/],
];

const matchedForbidden = forbiddenPatterns
  .filter(([, pattern]) => pattern.test(normalized))
  .map(([id]) => forbidden.find((action) => action.id === id) ?? { id, riskClass: "hard_stop" });

const matchedAllowed = allowedPatterns
  .filter(([, pattern]) => pattern.test(normalized))
  .map(([id]) => allowed.find((action) => action.id === id))
  .filter(Boolean);

const uniqueAllowed = [...new Map((matchedAllowed.length ? matchedAllowed : [allowed[0]]).map((item) => [item.id, item])).values()];
const uniqueForbidden = [...new Map(matchedForbidden.map((item) => [item.id, item])).values()];

function determineRiskClass() {
  if (uniqueForbidden.length) return "hard_stop";
  const riskClasses = new Set(uniqueAllowed.map((action) => action.riskClass));
  if (riskClasses.has("requires_human_approval")) return "requires_human_approval";
  if (riskClasses.has("safe_read_only_ui")) return "safe_read_only_ui";
  if (riskClasses.has("safe_governance_update")) return "safe_governance_update";
  if (riskClasses.has("safe_docs_only")) return "safe_docs_only";
  if (riskClasses.has("safe_validation_only")) return "safe_validation_only";
  return "safe_read_only";
}

const riskClass = determineRiskClass();
const requiredValidations = gates
  .filter((gate) => gate.requiredFor.includes("all") || gate.requiredFor.includes(riskClass))
  .map((gate) => gate.id);

const result = {
  schemaVersion: "1.0.0",
  classifiedAt: new Date().toISOString(),
  taskDescription,
  riskClass,
  allowedActions: riskClass === "hard_stop" ? [] : uniqueAllowed.map((action) => action.id),
  forbiddenActions: uniqueForbidden.map((action) => action.id),
  requiredValidations,
  evidenceRequirements: evidenceRequirements.map((requirement) => requirement.id),
  rollbackRequirements: ["git_revertable_change", "evidence_refs_recorded"],
  hardStops: uniqueForbidden.length ? uniqueForbidden.map((action) => action.id) : [],
  hardStopPolicies: hardStops.map((policy) => policy.id),
  humanReviewRequired: riskClass !== "safe_read_only" && riskClass !== "safe_validation_only",
  standingLabels: state.standingLabels,
  governanceAssertions: {
    noSecrets: true,
    noConfidentialText: true,
    noLegalAuthority: true,
    noExternalAuthority: true,
    noSchemaMutation: true,
    noSourcePromotion: true,
  },
};

console.log(JSON.stringify(result, null, 2));
