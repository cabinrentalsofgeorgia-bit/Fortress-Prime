import type { Metadata } from "next";
import { SystemHealthShell } from "./_components/system-health-shell";

export const metadata: Metadata = {
  title: "System Health | Fortress Prime",
  description: "Real-time DGX Spark cluster telemetry, GPU metrics, and service health.",
};

export default function SystemHealthPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">System Health</h1>
        <p className="text-muted-foreground">
          Live telemetry from the DGX Spark cluster via a 1 Hz WebSocket stream from the Fortress API.
        </p>
      </div>
      <SystemHealthShell />
    </div>
  );
}
