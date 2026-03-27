#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_OUTPUT_DIR = path.resolve(__dirname, "../artifacts/ota-probes");

function parseArgs(argv) {
  const args = {
    input: "",
    outputDir: DEFAULT_OUTPUT_DIR,
    headless: true,
    checkIn: "",
    checkOut: "",
    adults: 2,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--input") {
      args.input = String(argv[index + 1] || "");
      index += 1;
    } else if (value === "--output-dir") {
      args.outputDir = String(argv[index + 1] || "");
      index += 1;
    } else if (value === "--check-in") {
      args.checkIn = String(argv[index + 1] || "");
      index += 1;
    } else if (value === "--check-out") {
      args.checkOut = String(argv[index + 1] || "");
      index += 1;
    } else if (value === "--adults") {
      args.adults = Number.parseInt(String(argv[index + 1] || "2"), 10) || 2;
      index += 1;
    } else if (value === "--headed") {
      args.headless = false;
    }
  }

  if (!args.input || !args.checkIn || !args.checkOut) {
    throw new Error(
      "Usage: probe_ota_checkout.mjs --input <targets.json> --check-in YYYY-MM-DD --check-out YYYY-MM-DD [--adults 2] [--output-dir dir] [--headed]",
    );
  }
  return args;
}

async function ensureDir(targetPath) {
  await fs.mkdir(targetPath, { recursive: true });
}

async function readTargets(inputPath) {
  const raw = await fs.readFile(inputPath, "utf8");
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error("Input JSON must be an array");
  }
  return parsed;
}

function buildProbeUrl(provider, rawUrl, checkIn, checkOut, adults) {
  const url = new URL(rawUrl);
  if (provider === "airbnb") {
    url.searchParams.set("check_in", checkIn);
    url.searchParams.set("check_out", checkOut);
    url.searchParams.set("adults", String(adults));
    url.searchParams.set("guests", String(adults));
  }
  if (provider === "vrbo") {
    url.searchParams.set("chkin", checkIn);
    url.searchParams.set("chkout", checkOut);
    url.searchParams.set("adultsCount", String(adults));
    url.searchParams.set("childrenCount", "0");
  }
  if (provider === "booking_com") {
    url.searchParams.set("checkin", checkIn);
    url.searchParams.set("checkout", checkOut);
    url.searchParams.set("group_adults", String(adults));
    url.searchParams.set("no_rooms", "1");
  }
  return url.toString();
}

async function dismissCommonOverlays(page) {
  const labels = [
    /accept/i,
    /agree/i,
    /got it/i,
    /close/i,
    /continue/i,
    /dismiss/i,
  ];
  for (const label of labels) {
    const button = page.getByRole("button", { name: label }).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click({ timeout: 2000 }).catch(() => {});
    }
  }
}

async function collectPriceSignals(page) {
  return await page.evaluate(() => {
    const moneyPattern = /\$\s?\d[\d,]*(?:\.\d{2})?/;
    const keywordPattern = /(total|nightly|night|cleaning|service fee|tax|fees|price|pay|reserve)/i;
    const elements = Array.from(document.querySelectorAll("body *"));
    const signals = [];
    for (const element of elements) {
      const text = (element.textContent || "").replace(/\s+/g, " ").trim();
      if (!text || text.length > 200) {
        continue;
      }
      if (!moneyPattern.test(text) && !keywordPattern.test(text)) {
        continue;
      }
      if (!signals.includes(text)) {
        signals.push(text);
      }
      if (signals.length >= 40) {
        break;
      }
    }
    return signals;
  });
}

async function probeUrl(page, { slug, provider, url, checkIn, checkOut, adults, outputDir }) {
  const probeUrl = buildProbeUrl(provider, url, checkIn, checkOut, adults);
  const startedAt = new Date().toISOString();
  let navigateError = null;

  try {
    await page.goto(probeUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(5000);
    await dismissCommonOverlays(page);
    await page.waitForTimeout(1000);
  } catch (error) {
    navigateError = String(error);
  }

  const pageTitle = await page.title().catch(() => "");
  const currentUrl = page.url();
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const priceSignals = await collectPriceSignals(page).catch(() => []);

  const artifactBase = `${slug}-${provider}`;
  const screenshotPath = path.join(outputDir, `${artifactBase}.png`);
  const htmlPath = path.join(outputDir, `${artifactBase}.html`);

  await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
  await fs.writeFile(htmlPath, await page.content().catch(() => ""), "utf8");

  return {
    slug,
    provider,
    source_url: url,
    probe_url: probeUrl,
    started_at: startedAt,
    final_url: currentUrl,
    title: pageTitle,
    navigate_error: navigateError,
    visible_total_detected: priceSignals.some((line) => /total/i.test(line) && /\$/.test(line)),
    price_signals: priceSignals,
    body_excerpt: bodyText.slice(0, 2000),
    screenshot_path: screenshotPath,
    html_path: htmlPath,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const outputDir = path.resolve(args.outputDir);
  await ensureDir(outputDir);

  const browser = await chromium.launch({ headless: args.headless });
  const context = await browser.newContext({
    locale: "en-US",
    timezoneId: "America/New_York",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    viewport: { width: 1440, height: 2200 },
  });

  try {
    const targets = await readTargets(path.resolve(args.input));
    const results = [];
    for (const target of targets) {
      const slug = String(target.slug || "").trim();
      for (const provider of ["airbnb", "vrbo", "booking_com"]) {
        const url = String(target[`${provider}_url`] || "").trim();
        if (!slug || !url) {
          continue;
        }
        const page = await context.newPage();
        try {
          results.push(
            await probeUrl(page, {
              slug,
              provider,
              url,
              checkIn: args.checkIn,
              checkOut: args.checkOut,
              adults: args.adults,
              outputDir,
            }),
          );
        } finally {
          await page.close();
        }
      }
    }

    console.log(JSON.stringify({ results }, null, 2));
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
