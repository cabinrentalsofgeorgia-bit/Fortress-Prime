import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const repoRoot = process.cwd().endsWith("fortress-guest-platform")
  ? join(process.cwd(), "..")
  : process.cwd();
const root = join(repoRoot, "fortress-guest-platform");
const outDir = join(root, "operational-memory", "context-packs");
const packTypes = [
  "codex-session",
  "governance-review",
  "reviewer-onboarding",
  "deployment-verification",
  "remediation-review",
  "incident-response",
  "rollback-review",
];

function query(command) {
  const run = spawnSync("node", ["fortress-guest-platform/scripts/operational-memory/query-governance.mjs", command], {
    cwd: repoRoot,
    encoding: "utf8",
    timeout: 30_000,
  });
  if (run.status !== 0) throw new Error(`query_failed:${command}`);
  return JSON.parse(run.stdout);
}

const standing = query("standing");
const blockers = query("blockers");
const safeNext = query("safe-next-actions");
const forbidden = query("forbidden-actions");
const agent = query("agent-context");
const remediation = query("remediation-status");
const rollback = query("rollback-readiness");

mkdirSync(outDir, { recursive: true });
const outputs = [];

for (const type of packTypes) {
  const pack = {
    schemaVersion: "1.0.0",
    generatedAt: new Date().toISOString(),
    contextPackType: type,
    standingLabels: standing.standingLabels,
    governanceBoundaries: ["context_pack_metadata_only", "not_legal_authority", "human_review_required"],
    noSecrets: true,
    noConfidentialText: true,
    evidenceRefs: agent.result.evidencePaths,
    readFirst: agent.result.readFirst,
    validationCommands: agent.result.validationCommands,
    safeNextActions: safeNext.result.safeNextActions,
    forbiddenActions: forbidden.result.forbiddenActions,
    blockers: blockers.result.knownBlockers,
    remediationStatus: remediation.result,
    rollbackReadiness: rollback.result,
    negativeControls: {
      noCounselSignoffAuthority: true,
      noFinalLegalConclusionAuthority: true,
      noExternalSubmissionAuthority: true,
      noSourcePromotion: true,
      readOnly: true,
    },
  };
  const filename = `${type}.json`;
  writeFileSync(join(outDir, filename), `${JSON.stringify(pack, null, 2)}\n`);
  outputs.push(`operational-memory/context-packs/${filename}`);
}

console.log(JSON.stringify({ ok: true, outputs }, null, 2));
