"use client";

import { useMemo } from "react";
import {
  AlertTriangle,
  Archive,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useHistoricalRecoverySummary, useShadowSummary } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function money(value: number) {
  return `$${value.toFixed(2)}`;
}

function driftTone(value: number) {
  if (value >= 5) return "bg-red-500";
  if (value >= 1) return "bg-amber-500";
  return "bg-emerald-500";
}

function HistoricalHealthPanel() {
  const { data, isLoading, isError } = useHistoricalRecoverySummary();

  if (isLoading) {
    return <Skeleton className="h-72 rounded-xl" />;
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg border border-amber-500/40 p-4">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <p className="text-sm font-semibold">Historical Recovery Unavailable</p>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Recovery telemetry is temporarily unavailable, so the resurrection ledger cannot be summarized right now.
        </p>
      </div>
    );
  }

  const signatureProgress = Math.min(Math.max(data.signature_health_pct, 0), 100);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Total Resurrections</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{data.total_resurrections}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Restored or cache-hit archive recoveries in the last {data.window_hours}h
          </p>
        </div>

        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Soft-Landed Losses</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{data.soft_landed_losses}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Legacy URLs with no valid source record in the scanned window
          </p>
        </div>

        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Signature Health</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{data.signature_health_pct.toFixed(1)}%</p>
          <div className="mt-3 space-y-2">
            <Progress value={signatureProgress} />
            <p className="text-[11px] text-muted-foreground">
              {data.valid_signature_count}/{data.total_events} events verified against the sovereign archive signature
            </p>
          </div>
        </div>

        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Events Scanned</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{data.total_events}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Audit rows tagged as `historical_archive`
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border p-4">
          <div className="flex items-center gap-2">
            <Archive className="h-4 w-4 text-primary" />
            <div>
              <p className="text-sm font-semibold">Top Recovered Slugs</p>
              <p className="text-xs text-muted-foreground">
                Highest-volume archive recoveries in the active window
              </p>
            </div>
          </div>

          <div className="mt-4 space-y-2">
            {data.top_recovered_slugs.length === 0 ? (
              <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                No historical recoveries were recorded in this window.
              </div>
            ) : (
              data.top_recovered_slugs.map((item) => (
                <div
                  key={item.slug}
                  className="flex items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <p className="truncate text-sm font-medium">{item.slug}</p>
                  <Badge variant="outline" className="tabular-nums">
                    {item.count}
                  </Badge>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-lg border p-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <div>
              <p className="text-sm font-semibold">Orphan Leaderboard</p>
              <p className="text-xs text-muted-foreground">
                Slugs most often soft-landed because the source record is still missing
              </p>
            </div>
          </div>

          <div className="mt-4 space-y-2">
            {data.top_soft_landed_slugs.length === 0 ? (
              <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                No dead-air slugs were observed in this window.
              </div>
            ) : (
              data.top_soft_landed_slugs.map((item) => (
                <div
                  key={item.slug}
                  className="flex items-center justify-between gap-3 rounded-lg border p-3"
                >
                  <p className="truncate text-sm font-medium">{item.slug}</p>
                  <Badge variant="secondary" className="tabular-nums">
                    {item.count}
                  </Badge>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function LiveShadowPanel() {
  const { data, isLoading, isError } = useShadowSummary();

  const maxRecentDrift = useMemo(() => {
    if (!data?.recent_traces?.length) return 0;
    return Math.max(...data.recent_traces.map((trace) => trace.total_drift_pct));
  }, [data]);

  if (isLoading) {
    return <Skeleton className="h-80 rounded-xl" />;
  }

  if (isError || !data) {
    return (
      <Card className="border-amber-500/40">
        <CardContent className="flex items-center gap-3 py-6">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <div>
            <p className="text-sm font-semibold">Shadow Monitor Unavailable</p>
            <p className="text-xs text-muted-foreground">
              Unable to read structured shadow telemetry right now.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const gatePct = data.gate_target > 0 ? (data.gate_completed / data.gate_target) * 100 : 0;
  const avgBaseDriftPct = data.avg_base_drift_pct;
  const killSwitch = data.kill_switch_armed || maxRecentDrift > 5;

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold">Live Shadow</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            Live vs. sovereign quote telemetry for the 100-quote no-harm gate.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={data.spark_node_2_status === "online" ? "default" : "secondary"}>
            Spark Node 2 {data.spark_node_2_status}
          </Badge>
          <Badge variant={killSwitch ? "destructive" : "outline"}>
            {killSwitch ? "Kill Switch Watch" : data.status}
          </Badge>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Gate Tracker</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{data.gate_progress}</p>
          <div className="mt-3 space-y-2">
            <Progress value={gatePct} />
            <p className="text-[11px] text-muted-foreground">
              {gatePct.toFixed(0)}% of the live shadow gate completed
            </p>
          </div>
        </div>

        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Exact Match Rate</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{pct(data.accuracy_rate)}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Strict `MATCH` traces across the latest {data.gate_completed || 0} audits
          </p>
        </div>

        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Tax Match Rate</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{pct(data.tax_accuracy_rate)}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Deterministic Fannin County tax parity
          </p>
        </div>

        <div className="rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">Critical Mismatches</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{data.critical_mismatch_count}</p>
          <p className="mt-3 text-[11px] text-muted-foreground">
            Amber review required when drift exceeds hard guardrails
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <div className="rounded-lg border p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">Drift Gauge</p>
              <p className="text-xs text-muted-foreground">
                Average base-rate drift vs. 5% kill-switch threshold
              </p>
            </div>
            <p className="text-lg font-bold tabular-nums">{avgBaseDriftPct.toFixed(4)}%</p>
          </div>

          <div className="mt-4 space-y-3">
            <div className="h-3 overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all ${driftTone(avgBaseDriftPct)}`}
                style={{ width: `${Math.min((avgBaseDriftPct / 5) * 100, 100)}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[11px] text-muted-foreground">
              <span>0%</span>
              <span>1% review band</span>
              <span>5% kill switch</span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Max recent total drift: {maxRecentDrift.toFixed(4)}%
            </p>
          </div>
        </div>

        <div className={`rounded-lg border p-4 ${killSwitch ? "border-amber-500/60 bg-amber-500/5" : ""}`}>
          <div className="flex items-center gap-2">
            {killSwitch ? (
              <ShieldAlert className="h-4 w-4 text-amber-500" />
            ) : (
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
            )}
            <p className="text-sm font-semibold">Kill Switch Alert</p>
          </div>
          <p className="mt-2 text-sm">
            {killSwitch
              ? "A critical mismatch or >5% drift was detected. Manual signed-trace review is required."
              : "No kill-switch events detected in the latest shadow telemetry."}
          </p>
          <p className="mt-3 text-xs text-muted-foreground">
            Trigger conditions: `CRITICAL_MISMATCH` or total drift above 5%.
          </p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">Recent Traces</p>
            <p className="text-xs text-muted-foreground">
              Last 10 signed shadow audits for manual inspection
            </p>
          </div>
        </div>

        <div className="space-y-2">
          {data.recent_traces.length === 0 ? (
            <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              No shadow traces yet. The gate will populate as live quotes arrive.
            </div>
          ) : (
            data.recent_traces.map((trace) => (
              <div
                key={trace.trace_id}
                className="grid gap-3 rounded-lg border p-3 md:grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr]"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{trace.trace_id}</p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    Quote {trace.quote_id ?? "unknown"} • {new Date(trace.created_at).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] text-muted-foreground">Legacy / Shadow</p>
                  <p className="text-sm font-medium tabular-nums">
                    {money(trace.legacy_total)} / {money(trace.sovereign_total)}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] text-muted-foreground">Drift</p>
                  <p className="text-sm font-medium tabular-nums">{trace.total_drift_pct.toFixed(4)}%</p>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <Badge
                    variant={
                      trace.drift_status === "CRITICAL_MISMATCH"
                        ? "destructive"
                        : trace.drift_status === "MINOR_DRIFT"
                          ? "secondary"
                          : "outline"
                    }
                  >
                    {trace.drift_status}
                  </Badge>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export function ShadowMonitorCard() {
  return (
    <Card>
      <CardContent className="space-y-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-semibold">Sovereign Glass</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Toggle between the live quote safety gate and historical recovery health without leaving the command view.
            </p>
          </div>
        </div>

        <Tabs defaultValue="live-shadow" className="w-full">
          <TabsList className="grid w-full grid-cols-2 md:w-[360px]">
            <TabsTrigger value="live-shadow">Live Shadow</TabsTrigger>
            <TabsTrigger value="historical-health">Historical Health</TabsTrigger>
          </TabsList>

          <TabsContent value="live-shadow" className="mt-5">
            <LiveShadowPanel />
          </TabsContent>

          <TabsContent value="historical-health" className="mt-5">
            <HistoricalHealthPanel />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
