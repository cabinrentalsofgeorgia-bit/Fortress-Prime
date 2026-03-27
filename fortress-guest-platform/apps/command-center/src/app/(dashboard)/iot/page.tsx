import { DigitalTwinGrid } from "./_components/digital-twin-grid";

export default function IoTDashboardPage() {
  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">Physical Operations</h2>
      </div>
      <p className="text-muted-foreground font-mono text-sm mb-6">
        FORTRESS PROTOCOL: Zero-Latency Digital Twin Telemetry
      </p>
      <DigitalTwinGrid />
    </div>
  );
}
