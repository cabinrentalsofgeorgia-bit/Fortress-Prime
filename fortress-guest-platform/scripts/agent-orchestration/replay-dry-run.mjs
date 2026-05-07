import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, basename } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const base = join(root, "operational-memory", "agent-orchestration");
const replaysDir = join(base, "replays");
const tracePath = process.argv[2];
const shouldWrite = process.argv.includes("--write");
if (!tracePath || tracePath.startsWith("--")) {
  throw new Error("trace_path_required");
}
const trace = JSON.parse(readFileSync(tracePath, "utf8"));
const replayId = `replay-${basename(tracePath, ".json")}`;
const assertions = trace.governanceAssertions ?? {};
const errors = [];
for (const key of ["noSecrets", "noConfidentialText", "noLegalAuthority", "noExternalAuthority", "noSchemaMutation", "noSourcePromotion", "nonDestructiveDryRunOnly"]) {
  if (assertions[key] !== true) errors.push(`assertion_failed:${key}`);
}
if (!Array.isArray(trace.hardStopsTriggered)) errors.push("hard_stops_missing");
if (!Array.isArray(trace.validationGates) || trace.validationGates.length === 0) errors.push("validation_gates_missing");
if (!Array.isArray(trace.rollbackRefs) || trace.rollbackRefs.length === 0) errors.push("rollback_refs_missing");
if (trace.standingLabels?.counselStatus !== "COUNSEL_SIGNOFF_PENDING") errors.push("counsel_status_not_pending");
if (trace.standingLabels?.externalSubmissionAuthority !== "NOT_AUTHORIZED") errors.push("external_authority_not_blocked");

const replay = {
  schemaVersion: "1.0.0",
  replayId,
  generatedAt: new Date().toISOString(),
  traceRef: tracePath.replace(`${root}/`, ""),
  dryRunId: trace.dryRunId,
  status: errors.length === 0 ? "REPLAY_VALIDATED" : "REPLAY_REVIEW_REQUIRED",
  errors,
  hardStopsRechecked: true,
  governanceAssertionsRechecked: true,
  destructiveOperationsExecuted: false,
  standingLabels: trace.standingLabels,
  governanceAssertions: assertions,
};

if (shouldWrite) {
  mkdirSync(replaysDir, { recursive: true });
  writeFileSync(join(replaysDir, `${replayId}.json`), `${JSON.stringify(replay, null, 2)}\n`);
}
console.log(JSON.stringify(replay, null, 2));
process.exit(errors.length === 0 ? 0 : 1);
