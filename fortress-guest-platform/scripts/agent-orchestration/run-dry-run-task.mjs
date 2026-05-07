import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const base = join(root, "operational-memory", "agent-orchestration");
const tracesDir = join(base, "traces");
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const categories = readJson(join(base, "dry-run-categories.json"));
const forbiddenActions = readJson(join(base, "registries", "forbidden-actions.json")).actions.map((action) => action.id);
const hardStops = readJson(join(base, "registries", "hard-stop-policies.json")).policies.map((policy) => policy.id);
const state = readJson(join(root, "operational-memory", "registries", "operational-state.json"));

const args = process.argv.slice(2);
const category = args.includes("--category") ? args[args.indexOf("--category") + 1] : "validation-only";
const planPath = args.includes("--plan") ? args[args.indexOf("--plan") + 1] : null;
const shouldWrite = args.includes("--write");
const timestamp = new Date().toISOString().replace(/[-:]/g, "").replace(".", "").replace("Z", "Z");
const safeCategory = category.replace(/[^a-z0-9_-]/gi, "-");
const dryRunId = `dry-run-${safeCategory}-${timestamp}`;
const plan = planPath ? readJson(planPath) : {
  planId: "synthetic-plan",
  taskId: `synthetic-task-${category}`,
  plannedActions: [{ actionId: "run_validation", category: "validation", executionMode: "dry_run_only" }],
  blockedActions: [],
  validationGates: ["validate_agent_orchestration", "governance_query_smoke"],
  requiredEvidence: ["execution_trace", "replay_summary"],
  rollbackPlan: "delete dry-run trace and replay artifacts; no production mutation performed.",
  standingLabels: state.standingLabels,
  humanReviewRequired: true,
};

const forbiddenCategory = categories.forbiddenCategories.includes(category);
const allowedCategory = categories.allowedCategories.includes(category);
const blockedActions = [
  ...(plan.blockedActions ?? []),
  ...plan.plannedActions
    .filter((action) => forbiddenActions.includes(action.actionId))
    .map((action) => ({ actionId: action.actionId, reason: "forbidden_action_in_plan" })),
];
const hardStopsTriggered = [
  ...(forbiddenCategory ? [`forbidden_category:${category}`] : []),
  ...blockedActions.map((action) => `blocked_action:${action.actionId}`),
];
const status = allowedCategory && hardStopsTriggered.length === 0 ? "DRY_RUN_SIMULATED_SUCCESS" : "DRY_RUN_BLOCKED";

const trace = {
  schemaVersion: "1.0.0",
  dryRunId,
  generatedAt: new Date().toISOString(),
  category,
  status,
  planId: plan.planId,
  taskId: plan.taskId,
  executionPath: [
    "load_plan",
    "load_dry_run_categories",
    "validate_allowed_category",
    "validate_forbidden_actions",
    "simulate_execution",
    "record_governance_assertions",
  ],
  decisionsTaken: [
    { decision: "category_allowed", result: allowedCategory },
    { decision: "category_forbidden", result: forbiddenCategory },
    { decision: "production_mutation", result: false },
    { decision: "legal_authority", result: false },
  ],
  simulatedStates: plan.plannedActions.map((action) => ({
    actionId: action.actionId,
    simulatedOnly: true,
    result: status === "DRY_RUN_SIMULATED_SUCCESS" ? "simulated_pass" : "not_executed_blocked",
  })),
  blockedActions,
  hardStopsTriggered,
  hardStopPolicies: hardStops,
  validationGates: plan.validationGates ?? ["validate_agent_orchestration"],
  evidenceRefs: [
    "fortress-guest-platform/docs/operational/evidence/2026-05-06-autonomous-rehearsal/",
  ],
  rollbackRefs: [plan.rollbackPlan ?? "git_revertable_trace_only"],
  standingLabels: plan.standingLabels ?? state.standingLabels,
  humanReviewRequired: true,
  governanceAssertions: {
    noSecrets: true,
    noConfidentialText: true,
    noLegalAuthority: true,
    noExternalAuthority: true,
    noSchemaMutation: true,
    noSourcePromotion: true,
    nonDestructiveDryRunOnly: true,
  },
};

if (shouldWrite) {
  mkdirSync(tracesDir, { recursive: true });
  writeFileSync(join(tracesDir, `${dryRunId}.json`), `${JSON.stringify(trace, null, 2)}\n`);
}

console.log(JSON.stringify(trace, null, 2));
process.exit(status === "DRY_RUN_BLOCKED" && forbiddenCategory ? 2 : 0);
