import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import path from "node:path";

const require = createRequire(
  new URL("../../fortress-guest-platform/apps/command-center/package.json", import.meta.url),
);
const { chromium } = require("@playwright/test");

const storageState = process.env.CROG_AUTH_STATE
  ? path.resolve(process.env.CROG_AUTH_STATE)
  : path.resolve(process.cwd(), ".auth/crog-ai-gary.json");
const url =
  process.env.CROG_FORTRESS_URL ??
  "https://crog-ai.com/legal/cases/fortress-legal-production-review";
const includeTextSample = process.env.FORTRESS_CHECKER_INCLUDE_TEXT_SAMPLE === "1";

const executablePath =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ??
  (existsSync("/snap/bin/chromium") ? "/snap/bin/chromium" : undefined);
const browser = await chromium.launch({ headless: true, executablePath });
const context = await browser.newContext({ storageState });
const page = await context.newPage();

function sanitizeUrl(raw) {
  try {
    const parsed = new URL(raw);
    for (const key of [...parsed.searchParams.keys()]) {
      if (/token|key|auth|session|code|password|secret|signature/i.test(key)) {
        parsed.searchParams.set(key, "REDACTED");
      }
    }
    return `${parsed.origin}${parsed.pathname}${parsed.search}`;
  } catch {
    return raw.split("?")[0];
  }
}

function classifyFailure({ status, url: rawUrl, resourceType }) {
  const pathname = (() => {
    try {
      return new URL(rawUrl).pathname;
    } catch {
      return rawUrl;
    }
  })();
  if (status === 401 || status === 403) return "auth_guard";
  if (status === 404 && pathname.startsWith("/api/")) return "missing_api_route_or_manifest";
  if (status === 404 && ["script", "stylesheet", "image", "font"].includes(resourceType)) {
    return "missing_asset";
  }
  if (status === 404) return "missing_route";
  if (status >= 500 && pathname.startsWith("/api/")) return "backend_or_bff_failure";
  if (status >= 500) return "runtime_failure";
  return "http_failure";
}

const result = {
  ok: false,
  featureAlignmentOk: false,
  checkedAt: new Date().toISOString(),
  route: url,
  checks: {},
  errors: [],
  httpErrors: [],
  requestFailures: [],
  errorSummary: {},
};

page.on("console", (msg) => {
  if (msg.type() === "error") {
    result.errors.push(msg.text().slice(0, 300));
  }
});

page.on("response", (res) => {
  const status = res.status();
  if (status < 400) return;
  const request = res.request();
  const failure = {
    status,
    method: request.method(),
    resourceType: request.resourceType(),
    url: sanitizeUrl(res.url()),
    classification: classifyFailure({
      status,
      url: res.url(),
      resourceType: request.resourceType(),
    }),
  };
  result.httpErrors.push(failure);
  result.errorSummary[failure.classification] =
    (result.errorSummary[failure.classification] ?? 0) + 1;
});

page.on("requestfailed", (request) => {
  result.requestFailures.push({
    method: request.method(),
    resourceType: request.resourceType(),
    url: sanitizeUrl(request.url()),
    failure: request.failure()?.errorText?.slice(0, 200) ?? "unknown",
  });
});

const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
result.checks.httpStatus = response?.status();
result.responseUrl = response ? sanitizeUrl(response.url()) : null;
result.xRequestId = response?.headers()["x-request-id"] ?? null;
await page.waitForLoadState("load", { timeout: 15000 }).catch(() => {});
await page
  .waitForFunction(
    () => {
      const body = document.body?.innerText ?? "";
      return (
        body.includes("Fortress Legal Production Review") ||
        body.includes("COUNSEL_SIGNOFF_PENDING") ||
        body.includes("Invalid email or password")
      );
    },
    { timeout: 30000 },
  )
  .catch(() => {});

async function bodyText() {
  return await page.locator("body").innerText({ timeout: 30000 });
}

let text = await bodyText();

result.checks.authenticatedMatter = text.includes("Fortress Legal Production Review");
result.checks.signoffPending = text.includes("COUNSEL_SIGNOFF_PENDING");
result.checks.validationVisible = text.includes("Counsel Validation") || text.includes("Validation");
result.checks.lockedVisible = text.includes("Locked");

await page
  .waitForFunction(
    () => {
      const body = document.body?.innerText ?? "";
      return (
        (body.includes("Draft Work Product") ||
          body.includes("Draft Internal Memo") ||
          body.includes("Draft Statement of Facts")) &&
        (body.includes("Autonomous Learning") ||
          body.includes("Learning signals") ||
          body.includes("Next-best actions")) &&
        (body.includes("Remediation Maturity") ||
          body.includes("Review Confidence") ||
          body.includes("Evidence Lineage")) &&
        (body.includes("Controlled Review Operations") ||
          body.includes("Review Queue Operations") ||
          body.includes("Controlled Pilot Readiness")) &&
        (body.includes("Reviewer Assignment") ||
          body.includes("Workload Balancing") ||
          body.includes("Queue Aging / SLA")) &&
        (body.includes("Operational Readiness Certification") ||
          body.includes("Governance Enforcement Verification") ||
          body.includes("Operational Safety Certification")) &&
        (body.includes("Controlled Internal Pilot Operations") ||
      body.includes("Pilot Throughput Metrics") ||
          body.includes("Forbidden Pilot Actions") ||
          body.includes("Controlled Human Operations") ||
          body.includes("Operational Feedback Capture") ||
          body.includes("Operational Memory / Machine-Readable Cognition") ||
          body.includes("Operational Knowledge Graph / Queryable Governance"))
      );
    },
    { timeout: 20000 },
  )
  .catch(() => {});
text += "\n" + (await bodyText());
const lowerText = text.toLowerCase();

result.checks.authenticatedMatter = text.includes("Fortress Legal Production Review");
result.checks.signoffPending = text.includes("COUNSEL_SIGNOFF_PENDING");
result.checks.validationVisible = text.includes("Counsel Validation") || text.includes("Validation");
result.checks.lockedVisible = text.includes("Locked");
result.checks.documents = text.includes("Documents") || text.includes("Vault");
result.checks.completed = text.includes("Completed") || text.includes("78");
result.checks.workbench =
  text.includes("Counsel Review Workbench") ||
  text.includes("Workbench") ||
  text.includes("Issue Matrix") ||
  text.includes("Evidence Binders");
result.checks.draftWorkProduct =
  text.includes("Draft Work Product") ||
  text.includes("Draft Internal Memo") ||
  text.includes("Draft Statement of Facts");
result.checks.learning =
  text.includes("Autonomous Learning") ||
  text.includes("Learning signals") ||
  text.includes("Next-best actions");
result.checks.remediationMaturity =
  text.includes("Remediation Maturity") &&
  text.includes("Review Confidence") &&
  text.includes("Evidence Lineage") &&
  text.includes("excluded from relied-upon sections");
result.checks.reviewOperations =
  text.includes("Controlled Review Operations") &&
  text.includes("Review Queue Operations") &&
  text.includes("Contradiction Review") &&
  text.includes("Evidence Navigator") &&
  text.includes("Review Analytics") &&
  text.includes("Controlled Pilot Readiness") &&
  text.includes("excluded from relied-upon sections");
result.checks.reviewScaling =
  text.includes("Reviewer Assignment") &&
  text.includes("Workload Balancing") &&
  text.includes("Queue Aging / SLA") &&
  text.includes("Escalation & Incident Readiness") &&
  text.includes("forbidden counsel signoff") &&
  text.includes("forbidden external submission authority");
result.checks.operationalCertification =
  text.includes("Operational Readiness Certification") &&
  text.includes("Pilot Governance") &&
  text.includes("Reviewer Onboarding Governance") &&
  text.includes("Rollback Certification") &&
  text.includes("Governance Enforcement Verification") &&
  text.includes("Operational Safety Certification") &&
  text.includes("limit no public launch") &&
  text.includes("forbidden auto signoff");
result.checks.internalPilot =
  text.includes("Controlled Internal Pilot Operations") &&
  text.includes("Allowed Pilot Exercises") &&
  text.includes("Forbidden Pilot Actions") &&
  text.includes("Pilot Throughput Metrics") &&
  text.includes("Pilot Simulation / Drills") &&
  text.includes("production writes none") &&
  text.includes("forbidden legal signoff") &&
  text.includes("forbidden external submission");
result.checks.humanOperations =
  text.includes("Controlled Human Operations") &&
  text.includes("Reviewer Onboarding Governance") &&
  text.includes("Operational Feedback Capture") &&
  text.includes("Governance Exception Handling") &&
  text.includes("Operational Drift Detection") &&
  text.includes("Human Incident Rehearsal");
result.checks.feedbackCapture =
  text.includes("Operational Feedback Capture") &&
  text.includes("confidential document text") &&
  text.includes("auth or secret values");
result.checks.reviewerOnboarding =
  text.includes("Reviewer Onboarding Governance") &&
  text.includes("acknowledge COUNSEL SIGNOFF PENDING") &&
  text.includes("acknowledge NOT AUTHORIZED") &&
  text.includes("acknowledge NOT FINAL LEGAL ADVICE");
result.checks.governanceExceptions =
  text.includes("Governance Exception Handling") &&
  text.includes("halt restricted content boundary uncertain") &&
  text.includes("halt unauthorized access detected");
result.checks.driftDetection =
  text.includes("Operational Drift Detection") &&
  text.includes("queue depth drift");
result.checks.humanEscalation =
  text.includes("Human Incident Rehearsal") &&
  text.includes("reviewer confusion escalation") &&
  text.includes("tabletop ready");
result.checks.operationalMemory =
  text.includes("Operational Memory / Machine-Readable Cognition") &&
  text.includes("registry-as-operational-memory") &&
  text.includes("Governance Registry") &&
  text.includes("Remediation Registry") &&
  text.includes("Evidence Registry") &&
  text.includes("Capability Registry") &&
  text.includes("Wiki / App / Evidence Knowledge Index") &&
  text.includes("Reviewer Feedback Ledger Foundation");
result.checks.governanceRegistry =
  text.includes("Governance Registry") &&
  text.includes("forbidden auto signoff") &&
  text.includes("forbidden final legal conclusion") &&
  text.includes("forbidden filing service email external submission");
result.checks.remediationRegistry =
  text.includes("Remediation Registry") &&
  text.includes("EXCLUDED FROM RELIED UPON SECTIONS") &&
  text.includes("no auto resolution true");
result.checks.evidenceRegistry =
  text.includes("Evidence Registry") &&
  text.includes("capability audit");
result.checks.wikiKnowledgeIndex =
  text.includes("Wiki / App / Evidence Knowledge Index") &&
  text.includes("current operational index");
result.checks.reviewerLedgerFoundation =
  text.includes("Reviewer Feedback Ledger Foundation") &&
  text.includes("EMPTY LEDGER FOUNDATION") &&
  text.includes("no freeform legal text true");
result.checks.operationalGraph =
  text.includes("Operational Knowledge Graph / Queryable Governance") &&
  text.includes("operationalGraph true") &&
  text.includes("graph-as-operational-cognition, not legal authority") &&
  text.includes("Graph Entities") &&
  text.includes("Graph Relationships");
result.checks.governanceGraph =
  lowerText.includes("governance graph");
result.checks.evidenceGraph =
  lowerText.includes("evidence graph");
result.checks.remediationGraph =
  lowerText.includes("remediation graph");
result.checks.graphValidation =
  text.includes("operationalGraph true") &&
  text.includes("graph-as-operational-cognition, not legal authority");
result.checks.governanceQueryEngine =
  text.includes("Governance Query Engine / Agent Operating Context") &&
  text.includes("governanceQueryEngine true") &&
  text.includes("query-engine-as-operational-guidance, not legal authority");
result.checks.agentContext =
  text.includes("Agent Operating Context") &&
  text.includes("read only governance query engine and agent context");
result.checks.safeNextActionsVisible = text.includes("Safe Next Actions");
result.checks.forbiddenActionsVisible = text.includes("Forbidden Actions");
result.checks.signoffBlockersVisible = lowerText.includes("signoff blockers");
result.checks.launchBlockersVisible = lowerText.includes("launch blockers");
result.checks.agentOrchestration =
  text.includes("Agent Execution Governance / Safe Task Orchestration") &&
  text.includes("agentOrchestration true") &&
  text.includes("governed operations, not legal authority");
result.checks.hardStopsVisible =
  text.includes("Hard Stop Policies") &&
  lowerText.includes("secrets exposure") &&
  lowerText.includes("legal authority");
result.checks.allowedActionsVisible =
  text.includes("Allowed Agent Actions") &&
  lowerText.includes("read operational state");
result.checks.taskRiskClassifier =
  text.includes("Task Risk Classifier / Plan Validation") &&
  lowerText.includes("safe read only");
result.checks.agentPlanGeneration = text.includes("Latest Agent Plans");
result.checks.executionReportValidation = text.includes("Execution Reports");
result.checks.noLoginError = !text.includes("Invalid email or password");
result.checks.noExternalSubmissionAuthority =
  !text.includes("AUTHORIZED_FOR_FILING") &&
  !text.includes("AUTHORIZED_FOR_SERVICE") &&
  !text.includes("AUTHORIZED_FOR_EXTERNAL_SUBMISSION");
result.checks.noFinalLegalAdvice =
  !text.includes("FINAL_LEGAL_CONCLUSION") &&
  !text.includes("FINAL_LEGAL_ADVICE") &&
  !text.includes("AUTHORIZED_FINAL_LEGAL_CONCLUSION");

if (includeTextSample) {
  result.visibleTextSample = text.slice(0, 2500);
}

result.ok =
  result.checks.httpStatus === 200 &&
  result.checks.authenticatedMatter &&
  result.checks.signoffPending &&
  result.checks.noLoginError &&
  result.checks.noExternalSubmissionAuthority &&
  result.checks.noFinalLegalAdvice;

result.featureAlignmentOk =
  result.ok &&
  result.checks.validationVisible &&
  result.checks.workbench &&
  result.checks.draftWorkProduct &&
  result.checks.learning &&
  result.checks.remediationMaturity &&
  result.checks.reviewOperations &&
  result.checks.reviewScaling &&
  result.checks.operationalCertification &&
  result.checks.internalPilot &&
  result.checks.humanOperations &&
  result.checks.feedbackCapture &&
  result.checks.reviewerOnboarding &&
  result.checks.governanceExceptions &&
  result.checks.driftDetection &&
  result.checks.humanEscalation &&
  result.checks.operationalMemory &&
  result.checks.governanceRegistry &&
  result.checks.remediationRegistry &&
  result.checks.evidenceRegistry &&
  result.checks.wikiKnowledgeIndex &&
  result.checks.reviewerLedgerFoundation &&
  result.checks.operationalGraph &&
  result.checks.governanceGraph &&
  result.checks.evidenceGraph &&
  result.checks.remediationGraph &&
  result.checks.graphValidation &&
  result.checks.governanceQueryEngine &&
  result.checks.agentContext &&
  result.checks.safeNextActionsVisible &&
  result.checks.forbiddenActionsVisible &&
  result.checks.signoffBlockersVisible &&
  result.checks.launchBlockersVisible &&
  result.checks.agentOrchestration &&
  result.checks.hardStopsVisible &&
  result.checks.allowedActionsVisible &&
  result.checks.taskRiskClassifier &&
  result.checks.agentPlanGeneration &&
  result.checks.executionReportValidation;

console.log(JSON.stringify(result, null, 2));

await browser.close();
process.exit(result.ok ? 0 : 1);
