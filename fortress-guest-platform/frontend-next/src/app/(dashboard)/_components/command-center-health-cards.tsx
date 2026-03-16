"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ServiceHealthResponse } from "@/lib/types";

interface CommandCenterHealthCardsProps {
  health?: ServiceHealthResponse;
}

const healthItems = [
  { key: "cluster", label: "Cluster Monitor", desc: "DGX nodes, thermals, and uptime checks." },
  { key: "classifier", label: "Batch Classifier", desc: "Concurrent classification service health." },
  { key: "mission", label: "Mission Control", desc: "Operator and council orchestration interface." },
  { key: "legal", label: "Legal Service", desc: "Case manager API availability." },
  { key: "grafana", label: "Grafana", desc: "Observability and dashboard availability." },
] as const;

function isUp(value: unknown): boolean {
  return value === "up";
}

export function CommandCenterHealthCards({ health }: CommandCenterHealthCardsProps) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      {healthItems.map((item) => {
        const up = isUp(health?.[item.key]);
        return (
          <Card key={item.key}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-sm">{item.label}</CardTitle>
                <Badge variant={up ? "secondary" : "destructive"}>{up ? "LIVE" : "DOWN"}</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <CardDescription>{item.desc}</CardDescription>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
