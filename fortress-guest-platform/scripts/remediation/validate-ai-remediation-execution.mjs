import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const remediationDir = join(root, "operational-memory", "remediation");
const packetDir = join(remediationDir, "disposition-packets");

const errors = [];
const warnings = [];

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    errors.push(`json_parse_failed:${path}:${error instanceof Error ? error.message : "unknown"}`);
    return null;
  }
}

function assert(condition, message) {
  if (!condition) errors.push(message);
}

function containsForbiddenText(path) {
  const text = readFileSync(path, "utf8");
  const patterns = [
    /(^|\/)\.auth(\/|$)/i,
    /crog-ai-gary\.json/i,
    /cookie/i,
    /authorization/i,
    /bearer\s+[a-z0-9._-]+/i,
    /password/i,
    /supabase.*(?:key|secret|token|jwt)/i,
    /secret[_-]?key/i,
    /service[_-]?role/i,
    /BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY/i,
    /confidential legal text/i,
    /document body text/i,
    /restricted content body/i,
    /locked document content/i,
    /sourcePromotionAllowed"\s*:\s*true/i,
    /legalConclusion"\s*:\s*true/i,
    /signoffAuthority"\s*:\s*true/i,
    /externalAuthority"\s*:\s*true/i,
    /schemaRlsPolicyMutation"\s*:\s*"(?!NOT_PERFORMED)/i,
  ];
  return patterns.filter((pattern) => pattern.test(text)).map(String);
}

function validateStandingLabels(name, payload) {
  const labels = payload?.standingLabels ?? {};
  assert(labels.counselStatus === "COUNSEL_SIGNOFF_PENDING", `${name}:counsel_status_not_pending`);
  assert(labels.externalSubmissionAuthority === "NOT_AUTHORIZED", `${name}:external_authority_not_blocked`);
  assert(labels.finalLegalConclusions === "NOT_CREATED", `${name}:final_legal_conclusions_not_blocked`);
  assert(labels.legalAdviceStatus === "NOT FINAL LEGAL ADVICE", `${name}:legal_advice_status_not_draft`);
  assert(labels.schemaRlsPolicyMutation === "NOT_PERFORMED", `${name}:schema_rls_status_not_preserved`);
}

function validateBoundaryBooleans(name, payload) {
  assert(payload?.noSecrets === true, `${name}:no_secrets_not_true`);
  assert(payload?.noConfidentialText === true, `${name}:no_confidential_text_not_true`);
  validateStandingLabels(name, payload);
}

const classificationPath = join(remediationDir, "ai-remediation-classification.json");
const clustersPath = join(remediationDir, "remediation-clusters.json");
const candidatesPath = join(remediationDir, "safe-automation-candidates.json");
const packetIndexPath = join(remediationDir, "disposition-packet-index.json");
const queuesPath = join(remediationDir, "reviewer-work-queues.json");

const classification = readJson(classificationPath);
const clusters = readJson(clustersPath);
const candidates = readJson(candidatesPath);
const packetIndex = readJson(packetIndexPath);
const queues = readJson(queuesPath);

for (const [name, payload] of Object.entries({ classification, clusters, candidates, packetIndex, queues })) {
  if (payload) validateBoundaryBooleans(name, payload);
}

const issues = classification?.issues ?? [];
assert(classification?.unresolvedIssueCount === 232, "classification:unresolved_issue_count_not_232");
assert(issues.length === 232, "classification:issue_array_count_not_232");
assert(classification?.sourcePromotionAllowed === false, "classification:source_promotion_not_false");
assert(classification?.legalConclusion === false, "classification:legal_conclusion_not_false");
assert(classification?.signoffAuthority === false, "classification:signoff_authority_not_false");
assert(classification?.summary?.counselReviewRequired === 232, "classification:counsel_review_count_not_232");
assert(classification?.summary?.restrictedMetadataOnly === 2, "classification:restricted_metadata_count_not_2");

for (const issue of issues) {
  assert(issue.sourcePromotionAllowed === false, `issue:${issue.issueId}:source_promotion_not_false`);
  assert(issue.legalConclusion === false, `issue:${issue.issueId}:legal_conclusion_not_false`);
  assert(issue.signoffAuthority === false, `issue:${issue.issueId}:signoff_authority_not_false`);
  assert(issue.humanReviewRequired === true, `issue:${issue.issueId}:human_review_not_true`);
  assert(issue.counselReviewRequired === true, `issue:${issue.issueId}:counsel_review_not_true`);
  assert(Array.isArray(issue.sourceRefs), `issue:${issue.issueId}:source_refs_not_array`);
}

for (const cluster of clusters?.clusters ?? []) {
  assert(cluster.humanReviewRequired === true, `cluster:${cluster.clusterId}:human_review_not_true`);
  assert(cluster.automationSafety !== "auto_resolution", `cluster:${cluster.clusterId}:unsafe_automation_safety`);
}

for (const candidate of candidates?.candidates ?? []) {
  assert(candidate.requiredHumanApproval === true, `candidate:${candidate.candidateId}:human_approval_not_true`);
  assert(candidate.sourcePromotionAllowed === false, `candidate:${candidate.candidateId}:source_promotion_not_false`);
  assert(Array.isArray(candidate.forbiddenActions), `candidate:${candidate.candidateId}:forbidden_actions_missing`);
  assert(candidate.forbiddenActions.includes("source_promotion"), `candidate:${candidate.candidateId}:source_promotion_not_forbidden`);
}

const packetFiles = readdirSync(packetDir).filter((name) => name.endsWith(".json")).sort();
assert(packetFiles.length === (packetIndex?.packets ?? []).length, "packet_index:file_count_mismatch");
for (const packetRef of packetIndex?.packets ?? []) {
  assert(packetRef.sourcePromotionAllowed === false, `packet_index:${packetRef.packetId}:source_promotion_not_false`);
  assert(packetRef.humanReviewRequired === true, `packet_index:${packetRef.packetId}:human_review_not_true`);
  assert(packetRef.counselReviewRequired === true, `packet_index:${packetRef.packetId}:counsel_review_not_true`);
}
for (const packetFile of packetFiles) {
  const packetPath = join(packetDir, packetFile);
  const packet = readJson(packetPath);
  if (!packet) continue;
  validateBoundaryBooleans(`packet:${packetFile}`, packet);
  assert(packet.sourcePromotionAllowed === false, `packet:${packetFile}:source_promotion_not_false`);
  assert(packet.legalConclusion === false, `packet:${packetFile}:legal_conclusion_not_false`);
  assert(packet.signoffAuthority === false, `packet:${packetFile}:signoff_authority_not_false`);
  assert(packet.humanReviewRequired === true, `packet:${packetFile}:human_review_not_true`);
  assert(packet.counselReviewRequired === true, `packet:${packetFile}:counsel_review_not_true`);
}

for (const queue of queues?.queues ?? []) {
  assert(queue.humanReviewRequired === true, `queue:${queue.queueId}:human_review_not_true`);
  assert(queue.sourcePromotionAllowed === false, `queue:${queue.queueId}:source_promotion_not_false`);
  assert(queue.prohibitedAction?.includes("source_promotion"), `queue:${queue.queueId}:source_promotion_not_forbidden`);
}

const filesToScan = [
  classificationPath,
  clustersPath,
  candidatesPath,
  packetIndexPath,
  queuesPath,
  ...packetFiles.map((packetFile) => join(packetDir, packetFile)),
];
for (const path of filesToScan) {
  const matches = containsForbiddenText(path);
  if (matches.length) errors.push(`forbidden_text:${path}:${matches.join(",")}`);
}

const result = {
  ok: errors.length === 0,
  checkedAt: new Date().toISOString(),
  filesChecked: filesToScan.length,
  unresolvedIssueCount: classification?.unresolvedIssueCount ?? null,
  issueCount: issues.length,
  clusterCount: clusters?.clusters?.length ?? 0,
  candidateCount: candidates?.candidates?.length ?? 0,
  packetCount: packetIndex?.packets?.length ?? 0,
  queueCount: queues?.queues?.length ?? 0,
  restrictedMetadataOnly: classification?.summary?.restrictedMetadataOnly ?? null,
  counselReviewRequired: classification?.summary?.counselReviewRequired ?? null,
  sourcePromotionAllowed: false,
  legalConclusion: false,
  signoffAuthority: false,
  governance: {
    counselSignoff: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  },
  warnings,
  errors,
};

console.log(JSON.stringify(result, null, 2));
process.exit(result.ok ? 0 : 1);
