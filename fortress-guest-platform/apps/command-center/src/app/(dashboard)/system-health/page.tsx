import type { Metadata } from "next";
import { SystemHealthShell } from "./_components/system-health-shell";

export const metadata: Metadata = {
  title: "System Health | Fortress Prime",
  description:
    "Sovereign bare-metal telemetry: NVML GPUs, SNMP uplinks, PostgreSQL 16 sessions, and Synology mount health.",
};

export default function SystemHealthPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">System Health</h1>
        <p className="text-muted-foreground">
          Live 1 Hz WebSocket stream from the Fortress API: NVML, IF-MIB counters, pg_stat_activity, and mount IOPS.
        </p>
      </div>
      <SystemHealthShell />
    </div>
  );
}
