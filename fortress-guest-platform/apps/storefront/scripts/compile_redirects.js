/**
 * Build-time compiler: raw_drupal_redirects.json → src/generated/legacyRedirectMap.ts
 *
 * Next.js 16 uses src/proxy.ts (not middleware.ts) as the network boundary; the generated
 * map is imported there for O(1) legacy 301 lookups before other redirect logic.
 */

const fs = require("fs");
const path = require("path");

const RAW_PATH = path.join(__dirname, "../data/raw_drupal_redirects.json");
const OUT_PATH = path.join(__dirname, "../src/generated/legacyRedirectMap.ts");

console.log("Compiler: Forging legacy SEO redirect map...");

if (!fs.existsSync(RAW_PATH)) {
  console.error(`FATAL: Raw redirect data not found at ${RAW_PATH}`);
  process.exit(1);
}

const rawData = JSON.parse(fs.readFileSync(RAW_PATH, "utf-8"));
if (rawData === null || typeof rawData !== "object" || Array.isArray(rawData)) {
  console.error("FATAL: raw_drupal_redirects.json must be a JSON object (source → target).");
  process.exit(1);
}

const entries = Object.entries(rawData).filter(
  ([k, v]) => typeof k === "string" && typeof v === "string" && k.trim() && v.trim(),
);

entries.sort(([a], [b]) => a.localeCompare(b));

let tsContent = `// AUTO-GENERATED FILE - DO NOT EDIT MANUALLY\n`;
tsContent += `// Compiled from ${entries.length} legacy Drupal routes (see data/raw_drupal_redirects.json).\n\n`;
tsContent += `export const legacyRedirectMap: Record<string, string> = {\n`;

for (const [oldPath, newPath] of entries) {
  const cleanOld = oldPath.trim().replace(/\/$/, "") || "/";
  const cleanNew = newPath.trim();
  tsContent += `  ${JSON.stringify(cleanOld)}: ${JSON.stringify(cleanNew)},\n`;
}

tsContent += `};\n`;

const outDir = path.dirname(OUT_PATH);
if (!fs.existsSync(outDir)) {
  fs.mkdirSync(outDir, { recursive: true });
}

fs.writeFileSync(OUT_PATH, tsContent);
console.log(`Compiler: Successfully wrote ${entries.length} routes to ${OUT_PATH}`);
