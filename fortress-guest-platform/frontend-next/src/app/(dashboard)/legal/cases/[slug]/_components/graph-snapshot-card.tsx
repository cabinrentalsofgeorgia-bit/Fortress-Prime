"use client";

import { Badge } from "@/components/ui/badge";

type GraphNode = {
  id: string;
  entity_type: string;
  label: string;
  node_metadata: Record<string, unknown>;
};

type GraphEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  weight: number;
  source_ref?: string | null;
};

type GraphSnapshotCardProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  isLoading: boolean;
  error: string | null;
  onNodeClick?: (node: GraphNode) => void;
};

const ENTITY_COLORS: Record<string, string> = {
  person: "text-blue-400 border-blue-500/30",
  company: "text-purple-400 border-purple-500/30",
  document: "text-emerald-400 border-emerald-500/30",
  claim: "text-red-400 border-red-500/30",
};

export function GraphSnapshotCard({ nodes, edges, isLoading, error, onNodeClick }: GraphSnapshotCardProps) {
  const nodeLabelById = new Map(nodes.map((n) => [n.id, n.label]));

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-zinc-100">Entity Graph Pressure Map</p>
        <Badge variant="outline" className="bg-blue-500/10 text-blue-400 border-blue-500/30">
          {nodes.length} {nodes.length === 1 ? "Entity" : "Entities"} &middot; {edges.length} {edges.length === 1 ? "Edge" : "Edges"}
        </Badge>
      </div>

      {isLoading && <p className="text-xs text-zinc-400">Loading graph snapshot...</p>}

      {error ? (
        <p className="text-xs text-red-400">{error}</p>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
            {nodes.map((node) => (
              <button
                key={node.id}
                type="button"
                onClick={() => onNodeClick?.(node)}
                className="rounded-md border border-zinc-800 bg-zinc-900/70 px-3 py-2 flex items-center justify-between gap-2 text-left transition hover:ring-2 hover:ring-red-500 hover:cursor-crosshair"
              >
                <span className="text-xs text-zinc-100 truncate">{node.label}</span>
                <Badge
                  variant="outline"
                  className={`text-[10px] uppercase tracking-wide ${ENTITY_COLORS[node.entity_type] ?? "text-zinc-400 border-zinc-600"}`}
                >
                  {node.entity_type}
                </Badge>
              </button>
            ))}
            {nodes.length === 0 && !isLoading && (
              <p className="text-xs text-zinc-400 col-span-full">No graph entities yet. Run &quot;Recalculate Graph Topology&quot; to extract.</p>
            )}
          </div>

          {edges.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-zinc-300">Contradiction / Edge Ledger</p>
              {edges.map((edge) => {
                const strengthClass =
                  edge.weight >= 0.85
                    ? "border-red-500/30"
                    : edge.weight >= 0.7
                      ? "border-amber-500/30"
                      : "border-zinc-800";
                return (
                  <div key={edge.id} className={`rounded-md border ${strengthClass} bg-zinc-900/60 p-2`}>
                    <p className="text-xs text-zinc-100">
                      [{nodeLabelById.get(edge.source_node_id) ?? edge.source_node_id}]
                      {" → "}
                      <span className="text-amber-300">({edge.relationship_type})</span>
                      {" → "}
                      [{nodeLabelById.get(edge.target_node_id) ?? edge.target_node_id}]
                    </p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-zinc-500">weight: {edge.weight.toFixed(2)}</span>
                      <span className="text-[10px] text-zinc-400">ref: {edge.source_ref ?? "n/a"}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
