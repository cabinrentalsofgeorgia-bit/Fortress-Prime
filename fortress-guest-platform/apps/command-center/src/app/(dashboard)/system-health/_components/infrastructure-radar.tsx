import type { NodeMetrics } from "@/lib/types";

export function InfrastructureRadar({ nodes: _nodes }: { nodes: NodeMetrics[] }) {
  return <div className="p-4 text-sm text-muted-foreground">Infrastructure radar unavailable in this branch snapshot.</div>;
}
