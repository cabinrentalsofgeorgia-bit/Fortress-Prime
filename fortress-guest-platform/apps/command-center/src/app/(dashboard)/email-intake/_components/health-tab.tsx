"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EmailIntakeHealthResponse, EmailIntakeSlaResponse } from "@/lib/types";

type Props = {
  health?: EmailIntakeHealthResponse;
  sla?: EmailIntakeSlaResponse;
  isLoading: boolean;
  onWakeSnoozed: () => void;
  onReprocess: () => void;
};

export function HealthTab({ health, sla, isLoading, onWakeSnoozed, onReprocess }: Props) {
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading health...</div>;
  if (!health) return <div className="text-sm text-muted-foreground">No health data.</div>;

  const dlqTotal = Object.values(health.dlq || {}).reduce((sum, n) => sum + n, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-2">
        <Button variant="outline" onClick={onWakeSnoozed}>
          Wake Snoozed
        </Button>
        <Button variant="outline" onClick={onReprocess}>
          Trigger Reprocess
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Ingested (Last Hour)</p>
            <p className="text-2xl font-bold">{health.ingested_last_hour}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Errors (Last Hour)</p>
            <p className="text-2xl font-bold">{health.errors_last_hour}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">DLQ Total</p>
            <p className="text-2xl font-bold">{dlqTotal}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Snoozed Active</p>
            <p className="text-2xl font-bold">{health.snoozed_active}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Snoozed Expired</p>
            <p className="text-2xl font-bold">{health.snoozed_expired}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>SLA Summary</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {Object.entries(health.sla_thresholds).map(([priority, hours]) => {
            const pending = health.escalation_pending[priority as keyof typeof health.escalation_pending] || 0;
            const breached = sla?.summary?.[priority as keyof typeof sla.summary]?.breached ?? 0;
            return (
              <div key={priority} className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{priority}</p>
                <p className="text-lg font-semibold">{pending} pending</p>
                <p className="text-xs text-muted-foreground">
                  SLA: {hours}h · Breached: {breached}
                </p>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}

