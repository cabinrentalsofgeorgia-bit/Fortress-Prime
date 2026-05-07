import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const registryDir = join(root, "operational-memory", "registries");
const graphDir = join(root, "operational-memory", "graph");
const wiki = JSON.parse(readFileSync(join(registryDir, "wiki-knowledge-index.json"), "utf8"));
const evidence = JSON.parse(readFileSync(join(registryDir, "evidence-registry.json"), "utf8"));

const base = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  standingLabels: {
    counselStatus: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
  },
  governanceBoundaries: ["path_metadata_only", "no_document_body_text", "no_auth_material"],
  validationStatus: { status: "GENERATED_GRAPH_INDEX" },
  rollbackRefs: ["delete_generated_index", "git_revert"],
  noSecrets: true,
  noConfidentialText: true,
};

const wikiGraph = {
  ...base,
  sourceRefs: ["fortress-guest-platform/operational-memory/registries/wiki-knowledge-index.json"],
  evidenceRefs: ["fortress-guest-platform/docs/architecture/wiki-evidence-graph-model-2026-05-06.md"],
  nodes: wiki.entries.map((entry, index) => ({
    id: `wiki-node:${index + 1}`,
    type: "wiki_knowledge_node",
    path: entry.path,
    category: entry.category,
    freshness: entry.freshness,
  })),
  edges: wiki.entries.map((entry, index) => ({
    id: `wiki-edge:${index + 1}`,
    type: "references",
    from: `wiki-node:${index + 1}`,
    to: "capability:operational_graph",
    category: entry.category,
  })),
};

const evidenceGraph = {
  ...base,
  sourceRefs: ["fortress-guest-platform/operational-memory/registries/evidence-registry.json"],
  evidenceRefs: ["fortress-guest-platform/docs/architecture/wiki-evidence-graph-model-2026-05-06.md"],
  nodes: evidence.evidenceDirectories.map((entry) => ({
    id: `evidence:${entry.phase}`,
    type: "evidence_bundle",
    phase: entry.phase,
    path: entry.path,
    status: entry.status,
  })),
  edges: evidence.evidenceDirectories.map((entry) => ({
    id: `evidence-edge:${entry.phase}`,
    type: "supports",
    from: `evidence:${entry.phase}`,
    to: `capability:${entry.phase}`,
    phase: entry.phase,
  })),
};

writeFileSync(join(graphDir, "wiki-graph-index.json"), `${JSON.stringify(wikiGraph, null, 2)}\n`);
writeFileSync(join(graphDir, "evidence-graph-index.json"), `${JSON.stringify(evidenceGraph, null, 2)}\n`);
console.log(JSON.stringify({
  ok: true,
  wikiNodes: wikiGraph.nodes.length,
  evidenceNodes: evidenceGraph.nodes.length,
  outputs: [
    "operational-memory/graph/wiki-graph-index.json",
    "operational-memory/graph/evidence-graph-index.json",
  ],
}, null, 2));
