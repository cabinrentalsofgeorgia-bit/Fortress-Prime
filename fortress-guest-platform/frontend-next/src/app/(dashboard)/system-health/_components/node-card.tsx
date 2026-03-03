"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { NodeMetrics } from "@/lib/types";
import { Cpu, HardDrive, MemoryStick, Thermometer, Zap } from "lucide-react";

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, v));
}

function tempColor(c: number): string {
  if (c >= 80) return "text-red-500";
  if (c >= 65) return "text-amber-500";
  return "text-emerald-500";
}

function pctColor(v: number): string {
  if (v >= 90) return "text-red-500";
  if (v >= 75) return "text-amber-500";
  return "text-emerald-500";
}

function indicatorClass(v: number): string {
  if (v >= 90) return "[&>[data-slot=progress-indicator]]:bg-red-500";
  if (v >= 75) return "[&>[data-slot=progress-indicator]]:bg-amber-500";
  return "[&>[data-slot=progress-indicator]]:bg-emerald-500";
}

function Gauge({ label, icon: Icon, value, max, unit, pct }: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  value: string;
  max?: string;
  unit?: string;
  pct: number;
}) {
  const clamped = clampPct(pct);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-1 text-muted-foreground">
          <Icon className="h-3 w-3" />
          {label}
        </span>
        <span className={pctColor(clamped)}>
          {value}{max ? `/${max}` : ""} {unit ?? ""} ({clamped.toFixed(1)}%)
        </span>
      </div>
      <Progress value={clamped} className={`h-2 ${indicatorClass(clamped)}`} />
    </div>
  );
}

interface NodeCardProps {
  node: NodeMetrics;
}

export function NodeCard({ node }: NodeCardProps) {
  const vramPct = node.gpu.total_mib > 0
    ? (node.gpu.used_mib / node.gpu.total_mib) * 100
    : 0;
  const diskPct = parseFloat(node.disk.pct) || 0;

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold capitalize">
            {node.name}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge
              variant={node.online ? "default" : "destructive"}
              className="text-[10px] px-1.5 py-0"
            >
              {node.online ? "ONLINE" : "OFFLINE"}
            </Badge>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">{node.ip} &mdash; {node.role}</p>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* GPU Temperature & Power row */}
        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1 text-muted-foreground">
            <Thermometer className="h-3 w-3" />
            GPU Temp
          </span>
          <span className={tempColor(node.gpu.temp_c)}>
            {node.gpu.temp_c}&deg;C
          </span>
        </div>

        <div className="flex items-center justify-between text-xs">
          <span className="flex items-center gap-1 text-muted-foreground">
            <Zap className="h-3 w-3" />
            Power / Clock
          </span>
          <span className="text-muted-foreground">
            {node.gpu.power_w}W &bull; {node.gpu.clock_mhz}/{node.gpu.clock_max_mhz} MHz
          </span>
        </div>

        <Gauge
          label="GPU VRAM"
          icon={MemoryStick}
          value={(node.gpu.used_mib / 1024).toFixed(1)}
          max={(node.gpu.total_mib / 1024).toFixed(0)}
          unit="GB"
          pct={vramPct}
        />

        <Gauge
          label="GPU Util"
          icon={Cpu}
          value={node.gpu.util_pct.toFixed(0)}
          unit="%"
          pct={node.gpu.util_pct}
        />

        <Gauge
          label="RAM"
          icon={MemoryStick}
          value={node.ram.used_gb.toFixed(1)}
          max={node.ram.total_gb.toFixed(0)}
          unit="GB"
          pct={node.ram.pct}
        />

        <Gauge
          label="CPU"
          icon={Cpu}
          value={node.cpu.usage_pct.toFixed(1)}
          unit="%"
          pct={node.cpu.usage_pct}
        />

        <Gauge
          label="Disk"
          icon={HardDrive}
          value={node.disk.used_gb.toFixed(0)}
          max={node.disk.total_gb.toFixed(0)}
          unit="GB"
          pct={diskPct}
        />

        {/* GPU Processes */}
        {node.gpu.processes && node.gpu.processes.length > 0 && (
          <div className="pt-1 border-t space-y-1">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              GPU Processes
            </p>
            {node.gpu.processes.map((p) => (
              <div key={p.pid} className="flex items-center justify-between text-[11px]">
                <span className="text-muted-foreground truncate max-w-[60%]">{p.name}</span>
                <span className="tabular-nums">{(parseInt(p.vram_mib, 10) / 1024).toFixed(1)} GB</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
