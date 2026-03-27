interface LegacyModuleHealth {
  status?: "up" | "down";
  http_status?: number | null;
  latency_ms?: number | null;
}

interface LegacyModuleMaturity {
  native_route_ready: boolean;
  native_data_live: boolean;
  maturity_reason?: string | null;
}

interface VrsLegacyGlassGridProps {
  moduleHealth: Record<string, LegacyModuleHealth>;
  moduleMaturityByPath: Record<string, LegacyModuleMaturity>;
}

const statusToneClass: Record<NonNullable<LegacyModuleHealth["status"]>, string> = {
  up: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  down: "border-red-500/30 bg-red-500/10 text-red-400",
};

export function VrsLegacyGlassGrid({
  moduleHealth,
  moduleMaturityByPath,
}: VrsLegacyGlassGridProps) {
  const modulePaths = Array.from(new Set([...Object.keys(moduleHealth), ...Object.keys(moduleMaturityByPath)])).sort();

  if (modulePaths.length === 0) {
    return <div className="p-4 text-sm text-muted-foreground">No legacy module probes have reported yet.</div>;
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {modulePaths.map((path) => {
        const health = moduleHealth[path];
        const maturity = moduleMaturityByPath[path];
        const status = health?.status ?? "down";
        const statusClass = statusToneClass[status];

        return (
          <article key={path} className="rounded-lg border bg-card p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <p className="text-sm font-semibold">{path}</p>
                <p className="text-[11px] text-muted-foreground">
                  {health?.http_status ? `HTTP ${health.http_status}` : "Probe pending"}
                  {typeof health?.latency_ms === "number" ? ` · ${health.latency_ms} ms` : ""}
                </p>
              </div>
              <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${statusClass}`}>
                {status}
              </span>
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              <span
                className={`rounded border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                  maturity?.native_route_ready
                    ? "border-sky-500/30 bg-sky-500/10 text-sky-300"
                    : "border-muted bg-muted/20 text-muted-foreground"
                }`}
              >
                {maturity?.native_route_ready ? "native route ready" : "native route pending"}
              </span>
              <span
                className={`rounded border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                  maturity?.native_data_live
                    ? "border-violet-500/30 bg-violet-500/10 text-violet-300"
                    : "border-muted bg-muted/20 text-muted-foreground"
                }`}
              >
                {maturity?.native_data_live ? "data live" : "data not live"}
              </span>
              {maturity?.maturity_reason ? (
                <span className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-amber-300">
                  {maturity.maturity_reason.replace(/_/g, " ")}
                </span>
              ) : null}
            </div>
          </article>
        );
      })}
    </div>
  );
}
