"use client";

import {
  Activity,
  Bot,
  Cpu,
  Gauge,
  MailCheck,
  Scale,
  Server,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  BridgeStatusResponse,
  ClusterTelemetry,
  EmailIntakeDashboardResponse,
  LegalOverviewResponse,
  ServiceHealthResponse,
} from "@/lib/types";

interface CommandCenterKpiStripProps {
  cluster?: ClusterTelemetry;
  serviceHealth?: ServiceHealthResponse;
  bridge?: BridgeStatusResponse;
  legal?: LegalOverviewResponse;
  emailIntake?: EmailIntakeDashboardResponse;
}

function getPendingEscalations(emailIntake?: EmailIntakeDashboardResponse): number {
  if (!emailIntake?.escalation?.stats) return 0;
  return emailIntake.escalation.stats.reduce((sum, stat) => {
    return stat.status === "pending" ? sum + stat.cnt : sum;
  }, 0);
}

export function CommandCenterKpiStrip({
  cluster,
  serviceHealth,
  bridge,
  legal,
  emailIntake,
}: CommandCenterKpiStripProps) {
  const items = [
    {
      title: "Cluster Nodes",
      value: cluster ? `${cluster.nodes_online}/${cluster.nodes_total}` : "—",
      sub: "DGX nodes online",
      icon: Server,
      color: "text-cyan-500",
    },
    {
      title: "Services",
      value: serviceHealth ? `${serviceHealth.up_count}/${serviceHealth.total}` : "—",
      sub: "Core services healthy",
      icon: Activity,
      color: "text-green-500",
    },
    {
      title: "GPU Thermal",
      value: cluster?.gpu_temp_c != null ? `${cluster.gpu_temp_c}°C` : "—",
      sub: "First available node reading",
      icon: Gauge,
      color: "text-amber-500",
    },
    {
      title: "Bridge Ingest (24h)",
      value: bridge?.last_24h ?? "—",
      sub: `${bridge?.bridge_total?.toLocaleString?.() ?? 0} total ingested`,
      icon: MailCheck,
      color: "text-violet-500",
    },
    {
      title: "Legal Queue",
      value: legal?.pending_actions?.length ?? 0,
      sub: `${legal?.total_cases ?? 0} active cases`,
      icon: Scale,
      color: "text-red-500",
    },
    {
      title: "Email Intake",
      value: getPendingEscalations(emailIntake),
      sub: "Escalations pending review",
      icon: Bot,
      color: "text-indigo-500",
    },
    {
      title: "SLA Breaches",
      value: emailIntake ? Object.values(emailIntake.sla_breaches ?? {}).reduce((a, b) => a + b, 0) : 0,
      sub: "Priority breach count",
      icon: Cpu,
      color: "text-orange-500",
    },
  ];

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <Card key={item.title}>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">{item.title}</CardTitle>
            <item.icon className={`h-4 w-4 ${item.color}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{item.value}</div>
            <p className="text-xs text-muted-foreground">{item.sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
