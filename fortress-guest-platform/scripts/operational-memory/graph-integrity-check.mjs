import { spawnSync } from "node:child_process";

const checks = [
  ["validate-knowledge-graph", ["node", "fortress-guest-platform/scripts/operational-memory/validate-knowledge-graph.mjs"]],
  ["summarize-knowledge-graph", ["node", "fortress-guest-platform/scripts/operational-memory/summarize-knowledge-graph.mjs"]],
  ["query-governance", ["node", "fortress-guest-platform/scripts/operational-memory/query-knowledge-graph.mjs", "governance"]],
  ["query-remediation", ["node", "fortress-guest-platform/scripts/operational-memory/query-knowledge-graph.mjs", "remediation"]],
  ["query-evidence", ["node", "fortress-guest-platform/scripts/operational-memory/query-knowledge-graph.mjs", "evidence"]],
  ["query-deployment", ["node", "fortress-guest-platform/scripts/operational-memory/query-knowledge-graph.mjs", "deployment"]],
  ["query-operational-state", ["node", "fortress-guest-platform/scripts/operational-memory/query-knowledge-graph.mjs", "operational_state"]],
];

const results = checks.map(([name, command]) => {
  const run = spawnSync(command[0], command.slice(1), {
    encoding: "utf8",
    timeout: 30_000,
  });
  return {
    name,
    exitCode: run.status,
    ok: run.status === 0,
  };
});

const report = {
  ok: results.every((result) => result.ok),
  generatedAt: new Date().toISOString(),
  results,
  standingLabels: {
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  },
};

console.log(JSON.stringify(report, null, 2));
process.exit(report.ok ? 0 : 1);
