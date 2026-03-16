"use client";

import { useEffect, useState } from "react";

interface GraphNode {
  id: string;
  entity_name: string;
  entity_type: string;
  pressure_score: number;
}

interface GraphEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  confidence_weight: number;
}

export function GraphSnapshotCard({ caseSlug }: { caseSlug: string }) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchSnapshot = async () => {
    try {
      const res = await fetch(`/api/legal/cases/${caseSlug}/graph/snapshot`);
      if (!res.ok) throw new Error("Failed to fetch graph snapshot");
      const data = await res.json();
      setNodes(Array.isArray(data?.nodes) ? data.nodes : []);
      setEdges(Array.isArray(data?.edges) ? data.edges : []);
    } catch (error) {
      console.error("[GRAPH] Snapshot sync failed:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchSnapshot();
  }, [caseSlug]);

  const triggerRefresh = async () => {
    setIsRefreshing(true);
    try {
      await fetch(`/api/legal/cases/${caseSlug}/graph/refresh`, { method: "POST" });
      // For MVP: simple delayed pull after refresh request.
      setTimeout(() => {
        void fetchSnapshot();
      }, 2000);
    } catch (error) {
      console.error("[GRAPH] Refresh trigger failed:", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  if (isLoading) {
    return <div className="text-gray-400 font-mono text-sm animate-pulse">Rendering Tactical Map...</div>;
  }

  const topTargets = [...nodes].sort((a, b) => b.pressure_score - a.pressure_score);

  return (
    <div className="bg-gray-900 border border-blue-900/50 rounded-lg p-6 mt-6">
      <div className="flex justify-between items-center mb-6 border-b border-gray-800 pb-2">
        <h3 className="text-blue-500 font-bold uppercase tracking-widest flex items-center gap-2">
          Entity Graph Snapshot
        </h3>
        <button
          onClick={triggerRefresh}
          disabled={isRefreshing}
          className="bg-blue-900/50 hover:bg-blue-800 text-blue-200 text-xs font-mono py-1 px-3 rounded transition-colors disabled:opacity-50"
        >
          {isRefreshing ? "Swarm Rebuilding..." : "Force Map Refresh"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h4 className="text-gray-400 font-bold text-xs uppercase mb-3">Identified Targets</h4>
          <div className="space-y-2">
            {topTargets.map((node) => (
              <div key={node.id} className="bg-gray-800 p-3 rounded border border-gray-700 flex justify-between items-center">
                <div>
                  <div className="text-gray-200 text-sm font-bold">{node.entity_name}</div>
                  <div className="text-gray-500 text-xs font-mono uppercase">{node.entity_type}</div>
                </div>
                <div className="text-right">
                  <div className={`text-xl font-bold ${node.pressure_score > 70 ? "text-red-500" : "text-blue-400"}`}>
                    {node.pressure_score}
                  </div>
                  <div className="text-gray-600 text-[10px] uppercase font-mono">Pressure</div>
                </div>
              </div>
            ))}
            {nodes.length === 0 && <div className="text-gray-600 text-sm font-mono">No entities mapped.</div>}
          </div>
        </div>

        <div>
          <h4 className="text-gray-400 font-bold text-xs uppercase mb-3">Tactical Relationships</h4>
          <div className="space-y-2">
            {edges.map((edge) => {
              const source = nodes.find((n) => n.id === edge.source_node_id)?.entity_name || "Unknown";
              const target = nodes.find((n) => n.id === edge.target_node_id)?.entity_name || "Unknown";
              return (
                <div key={edge.id} className="bg-gray-800/50 p-2 rounded border border-gray-700/50 text-sm">
                  <span className="text-blue-300">{source}</span>
                  <span className="text-gray-500 mx-2 text-xs font-mono">[{edge.relationship_type}]</span>
                  <span className="text-amber-500">{target}</span>
                </div>
              );
            })}
            {edges.length === 0 && <div className="text-gray-600 text-sm font-mono">No relationships established.</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
