import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const APP_ROOT = process.cwd();
const SCAN_ROOTS = ["src", "e2e", "tests"];
const TEXT_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"]);
const EXCLUDED_SEGMENTS = new Set([
  "node_modules",
  ".next",
  "playwright-report",
  "test-results",
]);

const FORBIDDEN_FILENAMES = new Set([
  "legal-hooks.ts",
  "legal-types.ts",
  "use-council-stream.ts",
]);

const FORBIDDEN_CONTENT = [
  { label: "Legal API route", pattern: /\/api\/(?:internal\/)?legal\b/ },
  { label: "Internal Legal case route", pattern: /\/legal\/cases\b/ },
  { label: "Legal case payload field", pattern: /\bcase_slug\b/ },
  { label: "Legal case client type", pattern: /\bLegalCase\b/ },
  { label: "Legal counsel/council stream", pattern: /legal\/council|useCouncilStream|council-stream/i },
  { label: "Privileged Legal panel text", pattern: /Sanctions Tripwire|Hive Mind|Hivemind|deposition\/kill/i },
];

function shouldSkip(fullPath: string): boolean {
  const relative = path.relative(APP_ROOT, fullPath);
  const parts = relative.split(path.sep);
  if (parts.some((part) => EXCLUDED_SEGMENTS.has(part))) {
    return true;
  }
  if (relative === path.join("src", "__tests__", "frontend-zone-boundary.test.ts")) {
    return true;
  }
  return relative.startsWith(path.join("src", "data", "legacy"));
}

function collectFiles(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir) || shouldSkip(dir)) {
    return out;
  }
  for (const entry of readdirSync(dir)) {
    const fullPath = path.join(dir, entry);
    if (shouldSkip(fullPath)) {
      continue;
    }
    const stats = statSync(fullPath);
    if (stats.isDirectory()) {
      collectFiles(fullPath, out);
      continue;
    }
    if (stats.isFile() && TEXT_EXTENSIONS.has(path.extname(fullPath))) {
      out.push(fullPath);
    }
  }
  return out;
}

describe("storefront frontend zone boundary", () => {
  it("does not carry privileged Fortress Legal client code", () => {
    const scannedFiles = SCAN_ROOTS.flatMap((scanRoot) =>
      collectFiles(path.join(APP_ROOT, scanRoot)),
    );

    const violations: string[] = [];
    for (const fullPath of scannedFiles) {
      const relative = path.relative(APP_ROOT, fullPath);
      const basename = path.basename(fullPath);
      if (FORBIDDEN_FILENAMES.has(basename)) {
        violations.push(`${relative}: forbidden internal Legal client filename`);
        continue;
      }

      const content = readFileSync(fullPath, "utf8");
      for (const rule of FORBIDDEN_CONTENT) {
        if (rule.pattern.test(content)) {
          violations.push(`${relative}: ${rule.label}`);
        }
      }
    }

    expect(violations).toEqual([]);
  });
});
