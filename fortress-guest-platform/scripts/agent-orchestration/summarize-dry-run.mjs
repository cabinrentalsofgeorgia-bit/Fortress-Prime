import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const base = join(root, "operational-memory", "agent-orchestration");
const tracesDir = join(base, "traces");
const replaysDir = join(base, "replays");
const readAll = (dir) =>
  existsSync(dir)
    ? readdirSync(dir)
        .filter((name) => name.endsWith(".json"))
        .map((name) => JSON.parse(readFileSync(join(dir, name), "utf8")))
    : [];
const traces = readAll(tracesDir);
const replays = readAll(replaysDir);
const summary = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  traceCount: traces.length,
  replayCount: replays.length,
  blockedActionCount: traces.reduce((sum, trace) => sum + (trace.blockedActions?.length ?? 0), 0),
  hardStopCount: traces.reduce((sum, trace) => sum + (trace.hardStopsTriggered?.length ?? 0), 0),
  categories: [...new Set(traces.map((trace) => trace.category))].sort(),
  allReplaysValidated: replays.every((replay) => replay.status === "REPLAY_VALIDATED"),
  noSecrets: traces.every((trace) => trace.governanceAssertions?.noSecrets === true),
  noConfidentialText: traces.every((trace) => trace.governanceAssertions?.noConfidentialText === true),
  noLegalAuthority: traces.every((trace) => trace.governanceAssertions?.noLegalAuthority === true),
  noExternalAuthority: traces.every((trace) => trace.governanceAssertions?.noExternalAuthority === true),
  nonDestructiveDryRunOnly: traces.every((trace) => trace.governanceAssertions?.nonDestructiveDryRunOnly === true),
};
console.log(JSON.stringify(summary, null, 2));
