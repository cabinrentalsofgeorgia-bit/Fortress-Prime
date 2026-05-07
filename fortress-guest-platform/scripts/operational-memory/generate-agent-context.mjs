import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const repoRoot = process.cwd().endsWith("fortress-guest-platform")
  ? join(process.cwd(), "..")
  : process.cwd();
const root = join(repoRoot, "fortress-guest-platform");
const outDir = join(root, "operational-memory", "agent-context");
const query = spawnSync("node", ["fortress-guest-platform/scripts/operational-memory/query-governance.mjs", "agent-context"], {
  cwd: repoRoot,
  encoding: "utf8",
  timeout: 30_000,
});

if (query.status !== 0) {
  console.error(query.stderr || query.stdout);
  process.exit(query.status ?? 1);
}

const parsed = JSON.parse(query.stdout);
const context = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: [
    "fortress-guest-platform/scripts/operational-memory/query-governance.mjs",
    "fortress-guest-platform/operational-memory/queries/query-taxonomy.json",
  ],
  standingLabels: parsed.standingLabels,
  governanceBoundaries: ["agent_context_not_legal_authority", "human_review_required"],
  evidenceRefs: parsed.result.evidencePaths,
  validationStatus: { status: "GENERATED_FROM_GOVERNANCE_QUERY_ENGINE" },
  rollbackRefs: ["delete_generated_context", "git_revert"],
  noSecrets: true,
  noConfidentialText: true,
  ...parsed.result,
  negativeControls: parsed.negativeControls,
};

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, "current-agent-context.json"), `${JSON.stringify(context, null, 2)}\n`);
console.log(JSON.stringify({ ok: true, output: "operational-memory/agent-context/current-agent-context.json" }, null, 2));
