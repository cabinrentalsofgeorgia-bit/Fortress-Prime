import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const repoRoot = process.cwd().endsWith("fortress-guest-platform")
  ? join(process.cwd(), "..")
  : process.cwd();
const platformRoot = join(repoRoot, "fortress-guest-platform");
const outputPath = join(platformRoot, "operational-memory", "registries", "wiki-knowledge-index.generated.json");
const roots = [
  join(platformRoot, "docs", "architecture"),
  join(platformRoot, "docs", "operational"),
  "/home/admin/fortress-legal-production-work/fortress-legal-wiki/wiki",
].filter(existsSync);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.name === ".git" || entry.name === "node_modules") continue;
    if (entry.isDirectory()) walk(full, out);
    else if (entry.isFile() && entry.name.endsWith(".md")) out.push(full);
  }
  return out;
}

function categoryFor(path) {
  if (path.includes("/evidence/")) return "evidence_summary";
  if (path.includes("/architecture/")) return "architecture";
  if (path.includes("/operational/")) return "operational";
  if (path.includes("/audits/")) return "wiki_audit";
  if (path.includes("/decisions/")) return "wiki_decision";
  if (path.includes("/runbooks/")) return "wiki_runbook";
  if (path.includes("/context-packs/")) return "wiki_context_pack";
  return "knowledge";
}

function titleFor(path) {
  const text = readFileSync(path, "utf8").split(/\r?\n/).slice(0, 8);
  const heading = text.find((line) => /^#\s+/.test(line));
  return heading ? heading.replace(/^#\s+/, "").slice(0, 160) : path.split("/").pop();
}

const entries = roots.flatMap((root) => walk(root)).map((path) => ({
  path: path.startsWith(repoRoot) ? relative(repoRoot, path) : path.replace("/home/admin/fortress-legal-production-work/fortress-legal-wiki/", ""),
  title: titleFor(path),
  category: categoryFor(path),
  freshness: path.includes("2026-05-06") || path.includes("2026-05-07") ? "current_or_recent" : "historical_or_needs_review",
}));

const registry = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  sourceRefs: roots.map((root) => root.replace(`${repoRoot}/`, "")),
  standingLabels: {
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
  },
  governanceBoundaries: ["index_paths_titles_categories_only", "no_document_body_text"],
  evidenceRefs: ["fortress-guest-platform/docs/operational/evidence/2026-05-06-capability-audit/summary.md"],
  validationStatus: { status: "GENERATED_INDEX_PREVIEW" },
  rollbackRefs: ["delete_generated_preview"],
  noSecrets: true,
  noConfidentialText: true,
  entries,
};

writeFileSync(outputPath, `${JSON.stringify(registry, null, 2)}\n`);
console.log(JSON.stringify({ ok: true, outputPath: relative(repoRoot, outputPath), entries: entries.length }, null, 2));
