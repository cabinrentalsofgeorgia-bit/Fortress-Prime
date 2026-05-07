import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const registries = join(root, "operational-memory", "registries");
const readJson = (name) => JSON.parse(readFileSync(join(registries, name), "utf8"));

const state = readJson("operational-state.json");
const capabilities = readJson("capability-registry.json");
const governance = readJson("governance-registry.json");
const remediation = readJson("remediation-registry.json");
const evidence = readJson("evidence-registry.json");
const wiki = readJson("wiki-knowledge-index.json");
const ledger = readJson("reviewer-feedback-ledger.json");

const summary = {
  generatedAt: new Date().toISOString(),
  standingLabels: state.standingLabels,
  capabilityCount: capabilities.capabilities.length,
  activeCapabilityIds: capabilities.capabilities.map((capability) => capability.id),
  governanceBoundaryCount: governance.forbiddenOperations.length,
  unresolvedSourceIssues: remediation.unresolvedSourceIssues,
  unresolvedSourceExclusionStatus: remediation.unresolvedSourceExclusionStatus,
  evidenceDirectoryCount: evidence.evidenceDirectories.length,
  wikiKnowledgeEntries: wiki.entries.length,
  reviewerFeedbackEntries: ledger.entries.length,
  reviewerLedgerMode: ledger.validationStatus.status,
  blockers: state.knownBlockers,
  authority: {
    counselSignoff: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  },
};

console.log(JSON.stringify(summary, null, 2));
