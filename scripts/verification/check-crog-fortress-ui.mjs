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

const result = {
  ok: false,
  featureAlignmentOk: false,
  route: url,
  checks: {},
  errors: [],
};

page.on("console", (msg) => {
  if (msg.type() === "error") {
    result.errors.push(msg.text().slice(0, 300));
  }
});

const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
result.checks.httpStatus = response?.status();
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
          body.includes("Next-best actions"))
      );
    },
    { timeout: 20000 },
  )
  .catch(() => {});
text += "\n" + (await bodyText());

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
  result.checks.learning;

console.log(JSON.stringify(result, null, 2));

await browser.close();
process.exit(result.ok ? 0 : 1);
