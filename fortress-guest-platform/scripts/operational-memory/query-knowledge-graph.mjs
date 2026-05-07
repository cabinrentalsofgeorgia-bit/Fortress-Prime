import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const graph = JSON.parse(readFileSync(join(root, "operational-memory", "graph", "graph.json"), "utf8"));
const query = process.argv[2] ?? "governance";

const byId = new Map(graph.nodes.map((node) => [node.id, node]));
const redactNode = (node) => ({
  id: node.id,
  type: node.type,
  label: node.label,
  governanceBoundaries: node.governanceBoundaries,
  evidenceRefs: node.evidenceRefs,
  humanReviewRequired: Boolean(node.humanReviewRequired),
  unresolvedSourceBoundary: node.unresolvedSourceBoundary ?? null,
});
const redactEdge = (edge) => ({
  id: edge.id,
  type: edge.type,
  from: edge.from,
  to: edge.to,
  fromType: byId.get(edge.from)?.type ?? null,
  toType: byId.get(edge.to)?.type ?? null,
  label: edge.label,
  governanceBoundaries: edge.governanceBoundaries,
  evidenceRefs: edge.evidenceRefs,
  humanReviewRequired: Boolean(edge.humanReviewRequired),
  unresolvedSourceBoundary: edge.unresolvedSourceBoundary ?? null,
});

const filters = {
  governance: {
    nodes: graph.nodes.filter((node) => node.type === "governance_boundary"),
    edges: graph.edges.filter((edge) => edge.type === "governed_by" || edge.type === "excluded_by"),
  },
  remediation: {
    nodes: graph.nodes.filter((node) => ["remediation_issue", "contradiction_cluster", "review_queue"].includes(node.type)),
    edges: graph.edges.filter((edge) => ["blocks", "excluded_by", "escalated_to"].includes(edge.type)),
  },
  evidence: {
    nodes: graph.nodes.filter((node) => node.type === "evidence_bundle" || node.type === "validation_run" || node.type === "checker_run"),
    edges: graph.edges.filter((edge) => edge.type === "validated_by" || edge.type === "references"),
  },
  deployment: {
    nodes: graph.nodes.filter((node) => node.type === "deployment" || node.type === "rollback_event"),
    edges: graph.edges.filter((edge) => edge.type === "mitigated_by" || edge.from.startsWith("deployment:")),
  },
  operational_state: {
    nodes: graph.nodes.filter((node) => node.type === "operational_state" || node.type === "operational_phase" || node.type === "capability"),
    edges: graph.edges.filter((edge) => edge.from === "state:production" || edge.to === "state:production" || edge.from === "phase:operational_graph"),
  },
};

if (!(query in filters)) {
  console.error(JSON.stringify({ ok: false, error: "unknown_query", allowedQueries: Object.keys(filters) }, null, 2));
  process.exit(1);
}

const result = {
  ok: true,
  query,
  generatedAt: new Date().toISOString(),
  standingLabels: graph.standingLabels,
  nodes: filters[query].nodes.map(redactNode),
  edges: filters[query].edges.map(redactEdge),
  negativeControls: {
    noSecrets: true,
    noConfidentialText: true,
    noCounselSignoffAuthority: true,
    noFinalLegalConclusionAuthority: true,
    noExternalSubmissionAuthority: true,
    noSourcePromotion: true,
  },
};

console.log(JSON.stringify(result, null, 2));
