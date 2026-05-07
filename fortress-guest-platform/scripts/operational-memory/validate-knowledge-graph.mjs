import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const graphDir = join(root, "operational-memory", "graph");
const graphPath = join(graphDir, "graph.json");
const reportPath = join(graphDir, "graph-validation-report.json");

const allowedNodeTypes = new Set(JSON.parse(readFileSync(join(graphDir, "entity.schema.json"), "utf8")).allowedNodeTypes);
const relationshipSchema = JSON.parse(readFileSync(join(graphDir, "relationship.schema.json"), "utf8"));
const allowedEdgeTypes = new Set(relationshipSchema.allowedEdgeTypes);
const forbiddenEdgeTypes = new Set(relationshipSchema.forbiddenEdgeTypes);
const requiredNodeFields = JSON.parse(readFileSync(join(graphDir, "entity.schema.json"), "utf8")).requiredFields;
const requiredEdgeFields = relationshipSchema.requiredFields;

const forbiddenPatterns = [
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
  /restricted content body/i,
  /locked restricted content body/i,
];

const forbiddenAuthorityValues = new Set([
  "COUNSEL_SIGNOFF_COMPLETE",
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
  for (const [key, nested] of Object.entries(value)) flatten(nested, `${path}.${key}`, out);
  return out;
}

const graph = JSON.parse(readFileSync(graphPath, "utf8"));
const errors = [];
const warnings = [];

for (const field of ["schemaVersion", "generatedAt", "standingLabels", "nodes", "edges", "governanceBoundaries", "validationStatus", "rollbackRefs", "noSecrets", "noConfidentialText"]) {
  if (!(field in graph)) errors.push(`graph_missing_field:${field}`);
}
if (graph.noSecrets !== true) errors.push("graph_noSecrets_not_true");
if (graph.noConfidentialText !== true) errors.push("graph_noConfidentialText_not_true");

const nodes = Array.isArray(graph.nodes) ? graph.nodes : [];
const edges = Array.isArray(graph.edges) ? graph.edges : [];
const nodeIds = new Set();

for (const node of nodes) {
  for (const field of requiredNodeFields) if (!(field in node)) errors.push(`node_missing_field:${node.id ?? "unknown"}:${field}`);
  if (!allowedNodeTypes.has(node.type)) errors.push(`node_forbidden_type:${node.id}:${node.type}`);
  if (nodeIds.has(node.id)) errors.push(`node_duplicate_id:${node.id}`);
  nodeIds.add(node.id);
  if (node.noSecrets !== true) errors.push(`node_noSecrets_not_true:${node.id}`);
  if (node.noConfidentialText !== true) errors.push(`node_noConfidentialText_not_true:${node.id}`);
}

for (const edge of edges) {
  for (const field of requiredEdgeFields) if (!(field in edge)) errors.push(`edge_missing_field:${edge.id ?? "unknown"}:${field}`);
  if (!allowedEdgeTypes.has(edge.type)) errors.push(`edge_type_not_allowed:${edge.id}:${edge.type}`);
  if (forbiddenEdgeTypes.has(edge.type)) errors.push(`edge_type_forbidden:${edge.id}:${edge.type}`);
  if (!nodeIds.has(edge.from)) errors.push(`edge_missing_from_node:${edge.id}:${edge.from}`);
  if (!nodeIds.has(edge.to)) errors.push(`edge_missing_to_node:${edge.id}:${edge.to}`);
  if (edge.noSecrets !== true) errors.push(`edge_noSecrets_not_true:${edge.id}`);
  if (edge.noConfidentialText !== true) errors.push(`edge_noConfidentialText_not_true:${edge.id}`);
  if (edge.type === "excluded_by" && edge.unresolvedSourceBoundary !== "EXCLUDED_FROM_RELIED_UPON_SECTIONS") {
    errors.push(`edge_unresolved_boundary_missing:${edge.id}`);
  }
}

const textItems = flatten(graph);
for (const [path, text] of textItems) {
  for (const pattern of forbiddenPatterns) {
    if (pattern.test(text)) errors.push(`forbidden_value:${path}`);
  }
  if (forbiddenAuthorityValues.has(text)) errors.push(`forbidden_authority:${path}:${text}`);
}

if (!nodes.some((node) => node.type === "governance_boundary")) errors.push("missing_governance_nodes");
if (!edges.some((edge) => edge.type === "governed_by")) errors.push("missing_governed_by_edges");
if (!edges.some((edge) => edge.type === "excluded_by")) errors.push("missing_unresolved_source_exclusion_edge");
if (nodes.length < 10) warnings.push("low_node_count_review_scope");
if (edges.length < 10) warnings.push("low_edge_count_review_scope");

const schemaFiles = readdirSync(graphDir).filter((name) => name.endsWith(".schema.json")).sort();
const report = {
  schemaVersion: "1.0.0",
  generatedAt: new Date().toISOString(),
  ok: errors.length === 0,
  graphPath: "operational-memory/graph/graph.json",
  schemaFiles: schemaFiles.map((name) => `operational-memory/graph/${name}`),
  nodeCount: nodes.length,
  edgeCount: edges.length,
  nodeTypes: Object.fromEntries([...new Set(nodes.map((node) => node.type))].sort().map((type) => [type, nodes.filter((node) => node.type === type).length])),
  edgeTypes: Object.fromEntries([...new Set(edges.map((edge) => edge.type))].sort().map((type) => [type, edges.filter((edge) => edge.type === type).length])),
  standingLabels: graph.standingLabels,
  errors,
  warnings,
  noSecrets: errors.every((error) => !error.includes("forbidden_value")),
  noConfidentialText: errors.every((error) => !error.includes("confidential") && !error.includes("privileged")),
  governancePreserved: errors.every((error) => !error.includes("forbidden_authority")),
};

writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report, null, 2));
process.exit(report.ok ? 0 : 1);
