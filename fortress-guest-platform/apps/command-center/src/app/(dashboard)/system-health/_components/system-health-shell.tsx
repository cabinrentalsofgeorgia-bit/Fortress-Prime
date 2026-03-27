"use client";

import { useMemo } from "react";
import { useSystemHealth } from "@/lib/hooks";
import { useSystemHealthWsStore, type SystemHealthWsStatus } from "@/lib/system-health-ws-store";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { EmailSensorGrid } from "./email-sensor-grid";
import { StreamlineSyncButton } from "./streamline-sync-button";
import type { SystemHealthResponse, SystemHealthStatus } from "@/lib/types";
import {
  Activity,
  Cpu,
  Database,
  HardDrive,
  Network,
  Server,
  Thermometer,
  Wifi,
  WifiOff,
} from "lucide-react";

function formatBytesPerSec(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 B/s";
  if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(2)} GiB/s`;
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(2)} MiB/s`;
  if (n >= 1024) return `${(n / 1024).toFixed(2)} KiB/s`;
  return `${Math.round(n)} B/s`;
}

function statusBadgeVariant(
  s: SystemHealthStatus,
): "default" | "secondary" | "destructive" | "outline" {
  if (s === "NOMINAL") return "default";
  if (s === "WARNING") return "secondary";
  return "destructive";
}

function streamStatusLabel(wsStatus: SystemHealthWsStatus): string {
  switch (wsStatus) {
    case "connected":
      return "1 Hz stream • CONNECTED";
    case "connecting":
      return "1 Hz stream • CONNECTING";
    case "disconnected":
      return "1 Hz stream • DISCONNECTED";
    default:
      return "1 Hz stream • IDLE";
  }
}

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, v));
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-56 rounded-xl" />
        ))}
      </div>
    </div>
  );
}

function isCompletePayload(d: SystemHealthResponse | undefined): d is SystemHealthResponse {
  return (
    d != null &&
    Array.isArray(d.gpus) &&
    Array.isArray(d.network) &&
    Array.isArray(d.storage) &&
    typeof d.postgres_ok === "boolean"
  );
}

export function SystemHealthShell() {
  const { data, isLoading, isError, dataUpdatedAt } = useSystemHealth();
  const wsStatus = useSystemHealthWsStore((s) => s.wsStatus);
  const lastMessageAt = useSystemHealthWsStore((s) => s.lastMessageAt);

  const metrics = useMemo(() => (isCompletePayload(data) ? data : null), [data]);

  const lastUpdated = useMemo(() => {
    if (lastMessageAt) return new Date(lastMessageAt).toLocaleTimeString();
    if (!dataUpdatedAt) return null;
    return new Date(dataUpdatedAt).toLocaleTimeString();
  }, [dataUpdatedAt, lastMessageAt]);

  if (isLoading && !metrics) return <LoadingSkeleton />;

  if (isError || !metrics) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="flex items-center gap-4 py-8 justify-center">
          <WifiOff className="h-8 w-8 text-destructive" />
          <div>
            <p className="text-sm font-semibold">Cluster unreachable</p>
            <p className="text-xs text-muted-foreground">
              Unable to reach the bare-metal health API. Confirm tunnel and staff session.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const hostOk = metrics.postgres_ok;
  const pulseUptime = metrics.pulse?.uptime;

  return (
    <div className="space-y-6 font-mono text-sm">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex flex-wrap items-center gap-3">
          <Badge variant={statusBadgeVariant(metrics.status)} className="uppercase text-[10px] tracking-widest">
            {metrics.status}
          </Badge>
          <span className="text-xs text-muted-foreground flex items-center gap-1">
            <Server className="h-3 w-3" />
            {metrics.hostname}
          </span>
          {lastUpdated ? (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Activity className="h-3 w-3" />
              {lastUpdated}
            </span>
          ) : null}
          <span className="text-[10px] text-muted-foreground">
            collect {metrics.collected_in_ms} ms · up {metrics.uptime_seconds}s
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <StreamlineSyncButton />
          <span
            className={`text-xs text-muted-foreground flex items-center gap-1 ${
              wsStatus === "connected" ? "" : "text-amber-600 dark:text-amber-400"
            }`}
          >
            <Wifi className={`h-3 w-3 ${wsStatus === "connected" ? "text-emerald-500" : "text-amber-500"}`} />
            {streamStatusLabel(wsStatus)}
          </span>
        </div>
      </div>

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-2">
              <Cpu className="h-4 w-4 text-primary" />
              Host CPU
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-2xl font-bold tabular-nums">{metrics.host_cpu_usage_pct.toFixed(1)}%</p>
            <Progress value={clampPct(metrics.host_cpu_usage_pct)} className="h-1.5" />
            <p className="text-[10px] text-muted-foreground">load1 {metrics.host_load_1m.toFixed(2)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              Host RAM
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-2xl font-bold tabular-nums">{metrics.host_ram_pct.toFixed(1)}%</p>
            <Progress value={clampPct(metrics.host_ram_pct)} className="h-1.5" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-2">
              <Database className="h-4 w-4 text-primary" />
              PostgreSQL
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-2xl font-bold tabular-nums">{metrics.database_connections}</p>
            <p className="text-[10px] text-muted-foreground">{hostOk ? "active sessions" : "probe failed"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-primary" />
              Qdrant
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-lg font-bold">{metrics.qdrant_reachable ? "REACHABLE" : "OFFLINE"}</p>
            {pulseUptime ? (
              <p className="text-[10px] text-muted-foreground">pulse uptime {pulseUptime}</p>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card className="xl:col-span-2 border-border/80 bg-card/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold tracking-widest flex items-center gap-2">
              <Cpu className="h-4 w-4 text-cyan-500" />
              DGX Spark — GPUs (NVML)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {metrics.gpus.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No NVML devices reported (CPU-only host or driver unavailable).
              </p>
            ) : (
              metrics.gpus.map((gpu) => (
                <div key={gpu.id} className="space-y-2 border-b border-border/60 pb-4 last:border-0 last:pb-0">
                  <div className="flex justify-between text-xs">
                    <span className="font-semibold">GPU {gpu.id}</span>
                    <span
                      className={
                        gpu.temperature_c > 80 ? "text-red-500" : gpu.temperature_c > 65 ? "text-amber-500" : "text-emerald-500"
                      }
                    >
                      <Thermometer className="inline h-3 w-3 mr-0.5" />
                      {gpu.temperature_c}°C
                    </span>
                  </div>
                  <div className="flex justify-between text-[10px] text-muted-foreground">
                    <span>utilization</span>
                    <span>{gpu.utilization_pct}%</span>
                  </div>
                  <Progress value={clampPct(gpu.utilization_pct)} className="h-2" />
                  <div className="text-[10px] text-muted-foreground">
                    VRAM {gpu.memory_used_mb.toLocaleString()} / {gpu.memory_total_mb.toLocaleString()} MiB
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-border/80 bg-card/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold tracking-widest flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-amber-500" />
              Sovereign storage
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {metrics.storage.length === 0 ? (
              <p className="text-xs text-muted-foreground">No mount paths returned.</p>
            ) : (
              metrics.storage.map((vol) => (
                <div key={vol.mount_path} className="space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="truncate font-medium" title={vol.mount_path}>
                      {vol.volume}
                    </span>
                    <span>{vol.capacity_pct.toFixed(1)}%</span>
                  </div>
                  <Progress
                    value={clampPct(vol.capacity_pct)}
                    className={`h-2 ${vol.capacity_pct > 90 ? "[&>[data-slot=progress-indicator]]:bg-red-500" : ""}`}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    IOPS ~{vol.iops} · {vol.mount_path}
                  </p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/80 bg-card/50">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold tracking-widest flex items-center gap-2">
            <Network className="h-4 w-4 text-violet-500" />
            Network (SNMP / IF-MIB)
          </CardTitle>
        </CardHeader>
        <CardContent>
          {metrics.network.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No SNMP interfaces configured (set SYSTEM_HEALTH_MIKROTIK_SNMP_HOST and IF indices on the API host).
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {metrics.network.map((n) => (
                <div key={n.interface} className="rounded-md border border-border/60 bg-background/40 p-3 text-xs">
                  <p className="font-semibold truncate mb-2">{n.interface}</p>
                  <p className="text-[10px] text-muted-foreground">RX {formatBytesPerSec(n.rx_bytes_sec)}</p>
                  <p className="text-[10px] text-muted-foreground">TX {formatBytesPerSec(n.tx_bytes_sec)}</p>
                  <p className="text-[10px] text-muted-foreground mt-1">drops {n.dropped_packets}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <EmailSensorGrid />
    </div>
  );
}
