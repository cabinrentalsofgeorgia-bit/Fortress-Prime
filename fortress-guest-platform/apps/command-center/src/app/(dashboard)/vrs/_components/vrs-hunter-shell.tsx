"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Activity, Crosshair, Shield, Workflow } from "lucide-react";
import { useSystemHealth } from "@/lib/hooks";
import { useSystemHealthWsStore } from "@/lib/system-health-ws-store";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { HunterOpsQueue } from "./hunter-ops-queue";
import { MatrixTerminal } from "./matrix-terminal";

function clampPct(value: number): number {
  return Math.max(0, Math.min(100, value));
}

function progressTone(value: number): string {
  if (value >= 90) return "[&>[data-slot=progress-indicator]]:bg-rose-500";
  if (value >= 75) return "[&>[data-slot=progress-indicator]]:bg-amber-400";
  return "[&>[data-slot=progress-indicator]]:bg-emerald-400";
}

function progressValue(value: number | undefined): number {
  return clampPct(Number.isFinite(value) ? Number(value) : 0);
}

export function VrsHunterShell() {
  const health = useSystemHealth();
  const wsStatus = useSystemHealthWsStore((state) => state.wsStatus);
  const lastMessageAt = useSystemHealthWsStore((state) => state.lastMessageAt);
  const isConnected = wsStatus === "connected";
  const queuePanel = useMemo(() => <HunterOpsQueue />, []);
  const terminalPanel = useMemo(() => <MatrixTerminal />, []);
  const lastUpdated = useMemo(() => {
    if (lastMessageAt) return new Date(lastMessageAt).toLocaleTimeString();
    if (!health.dataUpdatedAt) return null;
    return new Date(health.dataUpdatedAt).toLocaleTimeString();
  }, [health.dataUpdatedAt, lastMessageAt]);

  const d = health.data;
  const hasHealth =
    d != null &&
    Array.isArray(d.gpus) &&
    typeof d.host_cpu_usage_pct === "number" &&
    typeof d.postgres_ok === "boolean";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <Crosshair className="h-7 w-7 text-primary" />
            Hunter Ops & Execution Terminal
          </h1>
          <p className="text-muted-foreground max-w-2xl text-sm">
            Recovery operations, AI draft review, and direct matrix dispatch converge here on the
            sovereign FastAPI Hunter and Agent routes.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={health.isFetching}
            onClick={() => {
              void health.refetch();
            }}
          >
            Refresh Health
          </Button>
        </div>
      </div>

      <div className="rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 border-b border-zinc-800 pb-2">
          <div className="flex items-center gap-2">
            <Activity className={`h-4 w-4 ${isConnected ? "text-emerald-400" : "text-rose-400"}`} />
            <h2 className="font-bold tracking-wide text-white">MATRIX TELEMETRY</h2>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={isConnected ? "text-emerald-400" : "text-rose-400"}>
              {isConnected ? "1Hz STREAM ACTIVE" : wsStatus === "connecting" ? "LINK NEGOTIATING" : "LINK SEVERED"}
            </span>
            {isConnected ? <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" /> : null}
            {lastUpdated ? <span className="text-zinc-500">LAST {lastUpdated}</span> : null}
          </div>
        </div>

        {health.isLoading ? (
          <p className="text-zinc-400">WAITING FOR HARDWARE PROBE...</p>
        ) : health.isError ? (
          <p className="text-rose-400">
            {health.error instanceof Error ? health.error.message : "System health unavailable"}
          </p>
        ) : !hasHealth ? (
          <p className="text-zinc-400">NO TELEMETRY PAYLOAD.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <div className="border border-zinc-800 bg-[#050505] p-3">
              <div className="mb-3 flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-bold text-cyan-400">{d.hostname}</p>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-500">head node</p>
                </div>
                <span
                  className={`rounded-sm px-1.5 py-0.5 text-[10px] ${
                    d.postgres_ok ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                  }`}
                >
                  {d.postgres_ok ? "POSTGRES" : "DB DOWN"}
                </span>
              </div>
              <div className="space-y-3">
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-zinc-400">
                    <span>CPU</span>
                    <span>{d.host_cpu_usage_pct.toFixed(1)}%</span>
                  </div>
                  <Progress
                    value={progressValue(d.host_cpu_usage_pct)}
                    className={`h-1 rounded-none bg-zinc-900 ${progressTone(d.host_cpu_usage_pct)}`}
                  />
                </div>
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-zinc-400">
                    <span>RAM</span>
                    <span>{d.host_ram_pct.toFixed(1)}%</span>
                  </div>
                  <Progress
                    value={progressValue(d.host_ram_pct)}
                    className={`h-1 rounded-none bg-zinc-900 ${progressTone(d.host_ram_pct)}`}
                  />
                </div>
                <div className="flex items-center justify-between text-[10px] text-zinc-500">
                  <span>pg conns</span>
                  <span>{d.database_connections}</span>
                </div>
              </div>
            </div>

            {d.gpus.length === 0 ? (
              <div className="border border-zinc-800 bg-[#050505] p-3 text-zinc-500 text-xs xl:col-span-3">
                NVML returned no GPUs (CPU-only or driver unavailable).
              </div>
            ) : (
              d.gpus.map((gpu) => {
                const vramPct =
                  gpu.memory_total_mb > 0 ? (gpu.memory_used_mb / gpu.memory_total_mb) * 100 : 0;
                return (
                  <div key={gpu.id} className="border border-zinc-800 bg-[#050505] p-3">
                    <div className="mb-3 flex items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-bold text-cyan-400">GPU {gpu.id}</p>
                        <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-500">NVML</p>
                      </div>
                      <span
                        className={`rounded-sm px-1.5 py-0.5 text-[10px] ${
                          gpu.temperature_c > 80 ? "bg-rose-500/10 text-rose-400" : "bg-emerald-500/10 text-emerald-400"
                        }`}
                      >
                        {gpu.temperature_c}°C
                      </span>
                    </div>
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <div className="flex items-center justify-between text-[10px] text-zinc-400">
                          <span>UTIL</span>
                          <span>{gpu.utilization_pct}%</span>
                        </div>
                        <Progress
                          value={progressValue(gpu.utilization_pct)}
                          className={`h-1 rounded-none bg-zinc-900 ${progressTone(gpu.utilization_pct)}`}
                        />
                      </div>
                      <div className="space-y-1">
                        <div className="flex items-center justify-between text-[10px] text-zinc-400">
                          <span>VRAM</span>
                          <span>{vramPct.toFixed(1)}%</span>
                        </div>
                        <Progress
                          value={progressValue(vramPct)}
                          className={`h-1 rounded-none bg-zinc-900 ${progressTone(vramPct)}`}
                        />
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
          <div className="mb-3 flex items-center gap-2 border-b border-zinc-800 pb-2">
            <Shield className="h-4 w-4 text-amber-400" />
            <h2 className="font-bold tracking-wide text-white">COMMAND LINKS</h2>
          </div>
          <div className="grid gap-2 text-sm">
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/vrs/quotes">
              /vrs/quotes
            </Link>
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/command/sovereign-pulse">
              /command/sovereign-pulse
            </Link>
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/guests">
              /guests
            </Link>
            <Link className="text-cyan-300 transition-colors hover:text-white" href="/messages">
              /messages
            </Link>
          </div>
          <div className="mt-4 flex items-start gap-2 border border-zinc-800 bg-[#050505] p-3 text-xs text-zinc-400">
            <Workflow className="mt-0.5 h-4 w-4 shrink-0 text-cyan-400" />
            <p>
              Queue review and direct matrix override now operate on the same authenticated FastAPI
              surfaces verified in production.
            </p>
          </div>
        </div>

        <div className="rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
          <div className="mb-3 flex items-center gap-2 border-b border-zinc-800 pb-2">
            <Shield className="h-4 w-4 text-amber-400" />
            <h2 className="font-bold tracking-wide text-white">STREAM STATUS</h2>
          </div>
          {health.isLoading ? (
            <p className="text-zinc-400">LOCKING SIGNAL...</p>
          ) : health.isError ? (
            <p className="text-rose-400">System telemetry degraded.</p>
          ) : !hasHealth ? (
            <p className="text-zinc-400">NO PAYLOAD.</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">STATUS</p>
                <p className="mt-2 text-lg font-bold text-emerald-400">{d.status}</p>
              </div>
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">SERVICE</p>
                <p className="mt-2 text-lg font-bold text-white">{d.service.toUpperCase()}</p>
              </div>
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">GPU COUNT</p>
                <p className="mt-2 text-lg font-bold text-cyan-400">{d.gpus.length}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        {queuePanel}
        {terminalPanel}
      </div>
    </div>
  );
}
