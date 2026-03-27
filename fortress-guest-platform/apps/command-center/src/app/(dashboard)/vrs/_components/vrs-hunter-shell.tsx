"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Activity, Crosshair, Shield, Workflow } from "lucide-react";
import { useSystemHealth } from "@/lib/hooks";
import { useSystemHealthWsStore } from "@/lib/system-health-ws-store";
import type { NodeMetrics } from "@/lib/types";
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
  const nodes = useMemo<NodeMetrics[]>(() => Object.values(health.data?.nodes ?? {}), [health.data?.nodes]);
  const queuePanel = useMemo(() => <HunterOpsQueue />, []);
  const terminalPanel = useMemo(() => <MatrixTerminal />, []);
  const lastUpdated = useMemo(() => {
    if (lastMessageAt) return new Date(lastMessageAt).toLocaleTimeString();
    if (!health.dataUpdatedAt) return null;
    return new Date(health.dataUpdatedAt).toLocaleTimeString();
  }, [health.dataUpdatedAt, lastMessageAt]);

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
        ) : nodes.length === 0 ? (
          <p className="text-zinc-400">NO NODE METRICS RETURNED.</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {nodes.map((node) => {
              const cpuPct = progressValue(node.cpu?.usage_pct);
              const ramPct = progressValue(node.ram?.pct);
              const vramPct =
                node.gpu?.total_mib > 0 ? progressValue((node.gpu.used_mib / node.gpu.total_mib) * 100) : 0;

              return (
                <div key={node.ip} className="border border-zinc-800 bg-[#050505] p-3">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-bold text-cyan-400">{node.ip}</p>
                      <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-500">{node.name}</p>
                    </div>
                    <span
                      className={`rounded-sm px-1.5 py-0.5 text-[10px] ${
                        node.online ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"
                      }`}
                    >
                      {node.online ? "ONLINE" : "OFFLINE"}
                    </span>
                  </div>

                  <div className="space-y-3">
                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-zinc-400">
                        <span>CPU</span>
                        <span>{cpuPct.toFixed(1)}%</span>
                      </div>
                      <Progress value={cpuPct} className={`h-1 rounded-none bg-zinc-900 ${progressTone(cpuPct)}`} />
                    </div>

                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-zinc-400">
                        <span>RAM</span>
                        <span>{ramPct.toFixed(1)}%</span>
                      </div>
                      <Progress value={ramPct} className={`h-1 rounded-none bg-zinc-900 ${progressTone(ramPct)}`} />
                    </div>

                    <div className="space-y-1">
                      <div className="flex items-center justify-between text-[10px] text-zinc-400">
                        <span>VRAM</span>
                        <span>{vramPct.toFixed(1)}%</span>
                      </div>
                      <Progress value={vramPct} className={`h-1 rounded-none bg-zinc-900 ${progressTone(vramPct)}`} />
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-zinc-500">
                      <span>{node.role}</span>
                      <span>{node.gpu.temp_c}C GPU</span>
                    </div>
                  </div>
                </div>
              );
            })}
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
          ) : (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">CLUSTER</p>
                <p className="mt-2 text-lg font-bold text-emerald-400">{health.data?.status?.toUpperCase()}</p>
              </div>
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">SERVICE</p>
                <p className="mt-2 text-lg font-bold text-white">{health.data?.service?.toUpperCase()}</p>
              </div>
              <div className="border border-zinc-800 bg-[#050505] p-3">
                <p className="text-[11px] tracking-[0.24em] text-zinc-500">NODES</p>
                <p className="mt-2 text-lg font-bold text-cyan-400">{nodes.filter((node) => node.online).length}</p>
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
