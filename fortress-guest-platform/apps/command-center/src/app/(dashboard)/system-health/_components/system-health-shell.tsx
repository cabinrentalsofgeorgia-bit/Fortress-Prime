"use client";

import { useMemo } from "react";
import { useSystemHealth } from "@/lib/hooks";
import { useSystemHealthWsStore, type SystemHealthWsStatus } from "@/lib/system-health-ws-store";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { NodeCard } from "./node-card";
import { ServicesGrid } from "./services-grid";
import { DatabaseStats } from "./database-stats";
import { EmailSensorGrid } from "./email-sensor-grid";
import { StreamlineSyncButton } from "./streamline-sync-button";
import { OperationsHealthGrid } from "./operations-health-grid";
import { InfrastructureRadar } from "./infrastructure-radar";
import {
  Activity,
  AlertTriangle,
  Clock,
  Cpu,
  MemoryStick,
  Server,
  Thermometer,
  Wifi,
  WifiOff,
} from "lucide-react";
import type { NodeMetrics } from "@/lib/types";

function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  variant = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ComponentType<{ className?: string }>;
  variant?: "default" | "success" | "warning" | "danger";
}) {
  const colorMap = {
    default: "text-primary",
    success: "text-emerald-500",
    warning: "text-amber-500",
    danger: "text-red-500",
  };
  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-4 px-5">
        <div className={`rounded-lg bg-accent p-2.5 ${colorMap[variant]}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-lg font-bold tabular-nums leading-tight">{value}</p>
          {sub && <p className="text-[10px] text-muted-foreground truncate">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-64 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-32 rounded-xl" />
    </div>
  );
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

export function SystemHealthShell() {
  const { data, isLoading, isError, dataUpdatedAt } = useSystemHealth();
  const wsStatus = useSystemHealthWsStore((s) => s.wsStatus);
  const lastMessageAt = useSystemHealthWsStore((s) => s.lastMessageAt);

  const nodes = useMemo<NodeMetrics[]>(() => {
    if (!data?.nodes) return [];
    return Object.values(data.nodes);
  }, [data]);

  const kpis = useMemo(() => {
    if (!nodes.length)
      return { nodesOnline: 0, nodesTotal: 0, avgTemp: 0, totalVram: 0, usedVram: 0, avgRam: 0 };
    const online = nodes.filter((n) => n.online);
    const avgTemp =
      online.length > 0
        ? online.reduce((s, n) => s + (n.gpu?.temp_c ?? 0), 0) / online.length
        : 0;
    const totalVram = nodes.reduce((s, n) => s + (n.gpu?.total_mib ?? 0), 0);
    const usedVram = nodes.reduce((s, n) => s + (n.gpu?.used_mib ?? 0), 0);
    const avgRam =
      online.length > 0
        ? online.reduce((s, n) => s + (n.ram?.pct ?? 0), 0) / online.length
        : 0;
    return {
      nodesOnline: online.length,
      nodesTotal: nodes.length,
      avgTemp: Math.round(avgTemp),
      totalVram,
      usedVram,
      avgRam: Math.round(avgRam),
    };
  }, [nodes]);

  const lastUpdated = useMemo(() => {
    if (lastMessageAt) return new Date(lastMessageAt).toLocaleTimeString();
    if (!dataUpdatedAt) return null;
    return new Date(dataUpdatedAt).toLocaleTimeString();
  }, [dataUpdatedAt, lastMessageAt]);

  if (isLoading) return <LoadingSkeleton />;

  if (isError || !data) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="flex items-center gap-4 py-8 justify-center">
          <WifiOff className="h-8 w-8 text-destructive" />
          <div>
            <p className="text-sm font-semibold">Cluster Unreachable</p>
            <p className="text-xs text-muted-foreground">
              Unable to reach the bare-metal health API. Retrying every 10 seconds.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const tempVariant =
    kpis.avgTemp >= 80 ? "danger" : kpis.avgTemp >= 65 ? "warning" : "success";
  const vramPct = kpis.totalVram > 0 ? (kpis.usedVram / kpis.totalVram) * 100 : 0;

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Badge variant={data?.status === "healthy" ? "default" : "destructive"} className="uppercase text-[10px]">
            {data?.status ?? "unknown"}
          </Badge>
          {lastUpdated && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {lastUpdated}
            </span>
          )}
          {data.collected_in_ms && (
            <span className="text-[10px] text-muted-foreground">
              ({(data.collected_in_ms / 1000).toFixed(1)}s collection)
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <StreamlineSyncButton health={data.integrations?.streamline_sync} />
          <span
            className={`text-xs text-muted-foreground flex items-center gap-1 ${
              wsStatus === "connected" ? "" : "text-amber-600 dark:text-amber-400"
            }`}
          >
            <Wifi
              className={`h-3 w-3 ${wsStatus === "connected" ? "text-emerald-500" : "text-amber-500"}`}
            />
            Live &bull; {streamStatusLabel(wsStatus)}
          </span>
        </div>
      </div>

      {/* KPI Strip */}
      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Nodes Online"
          value={`${kpis.nodesOnline}/${kpis.nodesTotal}`}
          sub="DGX Spark cluster"
          icon={kpis.nodesOnline === kpis.nodesTotal ? Server : AlertTriangle}
          variant={kpis.nodesOnline === kpis.nodesTotal ? "success" : "danger"}
        />
        <KpiCard
          label="Avg GPU Temp"
          value={`${kpis.avgTemp}\u00B0C`}
          sub="Across online nodes"
          icon={Thermometer}
          variant={tempVariant}
        />
        <KpiCard
          label="Total VRAM"
          value={`${(kpis.usedVram / 1024).toFixed(0)}/${(kpis.totalVram / 1024).toFixed(0)} GB`}
          sub={`${vramPct.toFixed(1)}% allocated`}
          icon={MemoryStick}
          variant={vramPct >= 90 ? "danger" : vramPct >= 75 ? "warning" : "default"}
        />
        <KpiCard
          label="Avg RAM Usage"
          value={`${kpis.avgRam}%`}
          sub="Across online nodes"
          icon={Cpu}
          variant={kpis.avgRam >= 90 ? "danger" : kpis.avgRam >= 75 ? "warning" : "default"}
        />
      </div>

      {/* Node cards -- 2x2 grid */}
      <div>
        <h2 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          DGX Spark Nodes
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {nodes.map((node) => (
            <NodeCard key={node.name} node={node} />
          ))}
        </div>
      </div>

      {/* Services */}
      {data.services && <ServicesGrid services={data.services} />}

      <OperationsHealthGrid health={data.integrations?.operations} />

      {/* Databases */}
      {data.databases && <DatabaseStats databases={data.databases} />}

      {/* Infrastructure Radar */}
      <InfrastructureRadar nodes={nodes} />

      {/* Iron Dome Email Sensor Grid */}
      <EmailSensorGrid />
    </div>
  );
}
