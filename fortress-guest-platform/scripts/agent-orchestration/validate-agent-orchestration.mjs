import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const base = join(root, "operational-memory", "agent-orchestration");
const schemasDir = join(base, "schemas");
const registriesDir = join(base, "registries");
const plansDir = join(base, "plans");
const reportsDir = join(base, "reports");
const shouldWrite = process.argv.includes("--write");
const reportPath = join(base, "agent-orchestration-validation-report.json");

const forbiddenValuePatterns = [
  /COUNSEL_SIGNOFF_COMPLETE/i,
  /AUTHORIZED_FOR_(FILING|SERVICE|EXTERNAL|SUBMISSION)/i,
  /FINAL_LEGAL_ADVICE/i,
  /FINAL_LEGAL_CONCLUSION_CREATED/i,
  /"schemaRlsPolicyMutation"\s*:\s*"PERFORMED"/i,
  /"noLegalAuthority"\s*:\s*false/i,
  /"noExternalAuthority"\s*:\s*false/i,
  /"noSchemaMutation"\s*:\s*false/i,
  /"noSourcePromotion"\s*:\s*false/i,
];
const secretPatterns = [
  /(^|\/)\.auth(\/|$)/i,
  /crog-ai-gary/i,
  /cookie/i,
  /authorization:/i,
  /bearer\s+[a-z0-9._-]+/i,
  /password[=:]/i,
  /token[=:]/i,
  /supabase.*key/i,
  /jwt[=:]/i,
  /service[_-]?key[=:]/i,
];
const confidentialPatterns = [/document body text/i, /confidential legal text included/i, /restricted content included/i];
const errors = [];
const warnings = [];

function jsonFiles(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => join(dir, name));
}

function checkFile(path) {
  const text = readFileSync(path, "utf8");
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (error) {
    errors.push(`${path}:json_parse_failed:${error.message}`);
    return;
  }
  for (const pattern of forbiddenValuePatterns) {
    if (pattern.test(text)) errors.push(`${path}:forbidden_authority_state`);
  }
  for (const pattern of secretPatterns) {
    if (pattern.test(text)) errors.push(`${path}:secret_or_auth_marker`);
  }
  for (const pattern of confidentialPatterns) {
    if (pattern.test(text)) errors.push(`${path}:confidential_text_marker`);
  }
  const assertions = payload.governanceAssertions;
  if (assertions) {
    for (const key of ["noSecrets", "noConfidentialText", "noLegalAuthority", "noExternalAuthority", "noSchemaMutation", "noSourcePromotion"]) {
      if (assertions[key] !== true) errors.push(`${path}:governance_assertion_failed:${key}`);
    }
  }
}

const files = [
  ...jsonFiles(schemasDir),
  ...jsonFiles(registriesDir),
  ...jsonFiles(plansDir),
  ...jsonFiles(reportsDir),
];
for (const file of files) checkFile(file);

for (const required of [
  "allowed-actions.json",
  "forbidden-actions.json",
  "hard-stop-policies.json",
  "task-risk-classifications.json",
  "validation-gates.json",
  "evidence-requirements.json",
]) {
  if (!existsSync(join(registriesDir, required))) errors.push(`missing_registry:${required}`);
}
if (!existsSync(schemasDir)) errors.push("missing_schemas_dir");
if (!existsSync(registriesDir)) errors.push("missing_registries_dir");
if (!existsSync(plansDir)) warnings.push("plans_dir_empty_or_missing");
if (!existsSync(reportsDir)) warnings.push("reports_dir_empty_or_missing");

const result = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  ok: errors.length === 0,
  filesChecked: files.map((file) => file.replace(`${root}/`, "")),
  errors,
  warnings,
  standingLabels: {
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
    schemaRlsPolicyMutation: "NOT_PERFORMED",
  },
  governancePreserved: errors.length === 0,
};

if (shouldWrite) {
  writeFileSync(reportPath, `${JSON.stringify(result, null, 2)}\n`);
}

console.log(JSON.stringify(result, null, 2));
process.exit(result.ok ? 0 : 1);
