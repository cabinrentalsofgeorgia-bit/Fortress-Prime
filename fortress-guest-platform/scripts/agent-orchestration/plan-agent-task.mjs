import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const outDir = join(root, "operational-memory", "agent-orchestration", "plans");
const registryRoot = join(root, "operational-memory", "agent-orchestration", "registries");
const operationalRegistryRoot = join(root, "operational-memory", "registries");
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const shouldWrite = process.argv.includes("--write");
const taskDescription = process.argv.filter((arg) => arg !== "--write").slice(2).join(" ").trim() || "read operational state";

const state = readJson(join(operationalRegistryRoot, "operational-state.json"));
const allowed = readJson(join(registryRoot, "allowed-actions.json")).actions;
const forbidden = readJson(join(registryRoot, "forbidden-actions.json")).actions;
const evidenceRequirements = readJson(join(registryRoot, "evidence-requirements.json")).evidenceRequirements;
const classifier = spawnSync(
  "node",
  [join(root, "scripts", "agent-orchestration", "classify-task-risk.mjs"), taskDescription],
  { encoding: "utf8" },
);
if (classifier.status !== 0) {
  throw new Error("risk_classifier_failed");
}
const classification = JSON.parse(classifier.stdout);
const planId = `agent-plan-${new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z")}`;
const allowedLookup = new Map(allowed.map((action) => [action.id, action]));
const forbiddenLookup = new Map(forbidden.map((action) => [action.id, action]));

const plan = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  planId,
  taskId: `agent-task-${planId.slice("agent-plan-".length)}`,
  taskDescription,
  riskClass: classification.riskClass,
  plannedActions: classification.allowedActions.map((actionId) => ({
    actionId,
    category: allowedLookup.get(actionId)?.category ?? "unknown",
    executionMode: actionId.startsWith("run_") ? "validation_only" : "plan_or_safe_write_only",
  })),
  skippedActions: [],
  blockedActions: classification.forbiddenActions.map((actionId) => ({
    actionId,
    category: forbiddenLookup.get(actionId)?.category ?? "unknown",
    reason: "Blocked by hard-stop policy.",
  })),
  validationGates: classification.requiredValidations,
  requiredEvidence: evidenceRequirements.map((requirement) => requirement.id),
  rollbackPlan: "git revert this phase commit or delete generated plan/report artifacts; no production legal data mutation is permitted.",
  standingLabels: state.standingLabels,
  humanReviewRequired: classification.humanReviewRequired,
  governanceAssertions: classification.governanceAssertions,
};

if (shouldWrite) {
  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, `${planId}.json`), `${JSON.stringify(plan, null, 2)}\n`);
}

console.log(JSON.stringify(plan, null, 2));
