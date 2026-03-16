"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SystemHealthService } from "@/lib/types";
import { Activity } from "lucide-react";

interface ServicesGridProps {
  services: SystemHealthService[];
}

export function ServicesGrid({ services }: ServicesGridProps) {
  if (!services || !Array.isArray(services)) return null;
  const onlineCount = services.filter((s) => s.status === "online").length;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            Services
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            {onlineCount}/{services.length} online
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {services.map((svc) => (
            <Badge
              key={svc.name}
              variant={svc.status === "online" ? "default" : "destructive"}
              className="text-[11px] gap-1.5"
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  svc.status === "online" ? "bg-emerald-400" : "bg-red-400"
                }`}
              />
              {svc.name}
              <span className="text-[10px] opacity-70">:{svc.port}</span>
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
