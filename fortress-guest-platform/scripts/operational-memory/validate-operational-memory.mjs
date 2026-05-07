import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const registriesDir = join(root, "operational-memory", "registries");
const reportPath = join(root, "operational-memory", "registries", "validation-report.json");

const requiredBaseFields = [
  "schemaVersion",
  "generatedAt",
  "sourceRefs",
  "standingLabels",
  "governanceBoundaries",
  "evidenceRefs",
  "validationStatus",
  "rollbackRefs",
  "noSecrets",
  "noConfidentialText",
];

const forbiddenValuePatterns = [
  /(^|\/)\.auth(\/|$)/i,
  /bearer\s+[a-z0-9._-]+/i,
  /authorization:\s*/i,
  /service[_-]?role/i,
  /supabase.*key/i,
  /postgres(ql)?:\/\/[^"\s]+/i,
  /cookie\s*[:=]/i,
  /password\s*[:=]/i,
  /jwt\s*[:=]/i,
  /confidential document text/i,
  /privileged document content/i,
  /locked restricted content body/i,
];

const forbiddenAuthorityValues = new Set([
  "COUNSEL_SIGNOFF_COMPLETE",
  "COUNSEL_SIGNOFF_RECORDED_FOR_APPROVED_REVIEW_SCOPE",
  "AUTHORIZED_FOR_FILING",
  "AUTHORIZED_FOR_SERVICE",
  "AUTHORIZED_FOR_EXTERNAL_SUBMISSION",
  "FINAL_LEGAL_CONCLUSION",
  "FINAL_LEGAL_ADVICE",
  "SCHEMA_RLS_POLICY_MUTATED",
]);

function flatten(value, path = "$", out = []) {
  if (value === null || value === undefined) return out;
  if (typeof value !== "object") {
    out.push([path, String(value)]);
    return out;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => flatten(item, `${path}[${index}]`, out));
    return out;
  }
  for (const [key, nested] of Object.entries(value)) {
    flatten(nested, `${path}.${key}`, out);
  }
  return out;
}

function validateRegistry(filename) {
  const errors = [];
  const warnings = [];
  const fullPath = join(registriesDir, filename);
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(fullPath, "utf8"));
  } catch (error) {
    return { filename, errors: [`invalid_json:${error.message}`], warnings: [] };
  }

  for (const field of requiredBaseFields) {
    if (!(field in parsed)) errors.push(`missing_field:${field}`);
  }
  if (parsed.noSecrets !== true) errors.push("noSecrets_not_true");
  if (parsed.noConfidentialText !== true) errors.push("noConfidentialText_not_true");

  const labels = parsed.standingLabels ?? {};
  const labelText = JSON.stringify(labels);
  if (!labelText.includes("COUNSEL_SIGNOFF_PENDING")) warnings.push("standing_label_counsel_pending_not_explicit");
  if (labelText.includes("AUTHORIZED_FOR_EXTERNAL_SUBMISSION")) errors.push("external_authority_present");
  if (labelText.includes("FINAL_LEGAL_CONCLUSION")) errors.push("final_legal_conclusion_present");

  for (const [path, text] of flatten(parsed)) {
    for (const pattern of forbiddenValuePatterns) {
      if (pattern.test(text)) errors.push(`forbidden_value:${path}`);
    }
    if (forbiddenAuthorityValues.has(text)) errors.push(`forbidden_authority:${path}:${text}`);
  }

  if (filename === "remediation-registry.json") {
    if (parsed.unresolvedSourceIssues !== 232) errors.push("unresolved_source_count_not_232");
    if (parsed.noAutoResolution !== true) errors.push("noAutoResolution_not_true");
  }

  if (filename === "reviewer-feedback-ledger.json") {
    if (parsed.noFreeformLegalText !== true) errors.push("noFreeformLegalText_not_true");
    if (!Array.isArray(parsed.entries)) errors.push("entries_not_array");
    if ((parsed.entries ?? []).length > 0) warnings.push("ledger_has_entries_review_manually");
  }

  return { filename, errors, warnings };
}

const registryFiles = readdirSync(registriesDir)
  .filter((name) => name.endsWith(".json") && name !== "validation-report.json")
  .sort();
const results = registryFiles.map(validateRegistry);
const errors = results.flatMap((result) => result.errors.map((error) => `${result.filename}:${error}`));
const warnings = results.flatMap((result) => result.warnings.map((warning) => `${result.filename}:${warning}`));

const report = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  ok: errors.length === 0,
  registriesChecked: registryFiles.map((name) => relative(root, join(registriesDir, name))),
  errors,
  warnings,
  standingLabels: {
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  },
  noSecrets: errors.every((error) => !error.includes("forbidden_value")),
  noConfidentialText: errors.every((error) => !error.includes("confidential")),
};

writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report, null, 2));
process.exit(report.ok ? 0 : 1);
