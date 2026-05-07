import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const planPath = process.argv[2];
const shouldWrite = process.argv.includes("--write");
const reportDir = join(root, "operational-memory", "agent-orchestration", "reports");
const state = JSON.parse(readFileSync(join(root, "operational-memory", "registries", "operational-state.json"), "utf8"));
const plan = planPath && !planPath.startsWith("--")
  ? JSON.parse(readFileSync(planPath, "utf8"))
  : {
      planId: "plan-not-provided",
      taskId: "task-not-provided",
      plannedActions: [],
      blockedActions: [],
      validationGates: ["validate_agent_orchestration"],
      requiredEvidence: ["execution_report"],
      humanReviewRequired: true,
    };
const reportId = `agent-execution-report-${new Date().toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z")}`;

const report = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  reportId,
  taskId: plan.taskId,
  planId: plan.planId,
  actionsAttempted: plan.plannedActions.map((action) => ({
    actionId: action.actionId,
    result: "not_executed_by_report_generator",
    note: "Execution reporter records outcomes only; it does not perform risky actions.",
  })),
  actionsSkipped: plan.blockedActions ?? [],
  hardStopsEncountered: (plan.blockedActions ?? []).map((action) => action.actionId),
  validationResults: plan.validationGates.map((gate) => ({
    gate,
    status: "pending_or_recorded_externally",
  })),
  evidenceRefs: plan.requiredEvidence ?? [],
  rollbackRefs: [plan.rollbackPlan ?? "git_revertable"],
  standingLabels: plan.standingLabels ?? state.standingLabels,
  humanReviewRequired: plan.humanReviewRequired ?? true,
  governanceAssertions: plan.governanceAssertions ?? {
    noSecrets: true,
    noConfidentialText: true,
    noLegalAuthority: true,
    noExternalAuthority: true,
    noSchemaMutation: true,
    noSourcePromotion: true,
  },
};

if (shouldWrite) {
  mkdirSync(reportDir, { recursive: true });
  writeFileSync(join(reportDir, `${reportId}.json`), `${JSON.stringify(report, null, 2)}\n`);
}

console.log(JSON.stringify(report, null, 2));
