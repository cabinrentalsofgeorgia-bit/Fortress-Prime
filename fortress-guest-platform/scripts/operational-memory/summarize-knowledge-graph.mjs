import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd().endsWith("fortress-guest-platform")
  ? process.cwd()
  : join(process.cwd(), "fortress-guest-platform");
const graph = JSON.parse(readFileSync(join(root, "operational-memory", "graph", "graph.json"), "utf8"));

function countBy(items, key) {
  return Object.fromEntries([...new Set(items.map((item) => item[key]))].sort().map((value) => [
    value,
    items.filter((item) => item[key] === value).length,
  ]));
}

const summary = {
  generatedAt: new Date().toISOString(),
  standingLabels: graph.standingLabels,
  nodeCount: graph.nodes.length,
  edgeCount: graph.edges.length,
  nodeTypes: countBy(graph.nodes, "type"),
  edgeTypes: countBy(graph.edges, "type"),
  governanceNodes: graph.nodes.filter((node) => node.type === "governance_boundary").map((node) => node.id),
  remediationNodes: graph.nodes.filter((node) => node.type === "remediation_issue" || node.type === "contradiction_cluster").map((node) => node.id),
  evidenceNodes: graph.nodes.filter((node) => node.type === "evidence_bundle").map((node) => node.id),
  deploymentNodes: graph.nodes.filter((node) => node.type === "deployment" || node.type === "rollback_event").map((node) => node.id),
  unresolvedSourceBoundaryEdges: graph.edges.filter((edge) => edge.unresolvedSourceBoundary === "EXCLUDED_FROM_RELIED_UPON_SECTIONS").map((edge) => edge.id),
  authority: {
    counselSignoff: "COUNSEL_SIGNOFF_PENDING",
    externalSubmissionAuthority: "NOT_AUTHORIZED",
    finalLegalConclusions: "NOT_CREATED",
    legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
  },
};

console.log(JSON.stringify(summary, null, 2));
