"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { OperationalHealth, OperationalHealthMetric } from "@/lib/types";
import { CreditCard, Inbox, MessageSquareText, ReceiptText, Rows3 } from "lucide-react";

function statusVariant(status?: string): "default" | "destructive" | "secondary" {
  if (status === "online") return "default";
  if (status === "degraded" || status === "offline") return "destructive";
  return "secondary";
}

function MetricRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums">{value ?? "-"}</span>
    </div>
  );
}

function OpsCard({
  title,
  metric,
  rows,
  icon: Icon,
}: {
  title: string;
  metric?: OperationalHealthMetric;
  rows: Array<[string, string]>;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold">
            <Icon className="h-4 w-4 text-primary" />
            {title}
          </CardTitle>
          <Badge variant={statusVariant(metric?.status)} className="text-[10px] uppercase">
            {metric?.status ?? "unknown"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.map(([label, key]) => (
          <MetricRow key={key} label={label} value={metric?.[key]} />
        ))}
      </CardContent>
    </Card>
  );
}

export function OperationsHealthGrid({ health }: { health?: OperationalHealth }) {
  if (!health) return null;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Rows3 className="h-4 w-4 text-primary" />
          Operating Workflows
        </h2>
        <Badge variant={statusVariant(health.status)} className="text-[10px] uppercase">
          {health.status}
        </Badge>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <OpsCard
          title="Channex"
          icon={Inbox}
          metric={health.channex}
          rows={[
            ["Pending", "pending"],
            ["Failed", "failed"],
            ["Processed 24h", "processed_24h"],
          ]}
        />
        <OpsCard
          title="Checkout Holds"
          icon={CreditCard}
          metric={health.checkout_holds}
          rows={[
            ["Active", "active"],
            ["Stale active", "stale_active"],
            ["Converted 24h", "converted_24h"],
          ]}
        />
        <OpsCard
          title="Quote Checkout"
          icon={ReceiptText}
          metric={health.quote_checkout}
          rows={[
            ["Guest pending", "guest_pending"],
            ["Taylor approval", "taylor_pending_approval"],
            ["Unresolved empty", "unresolved_empty_streamline_prices_24h"],
          ]}
        />
        <OpsCard
          title="Twilio"
          icon={MessageSquareText}
          metric={health.twilio}
          rows={[
            ["Outbound 24h", "outbound_24h"],
            ["Failed 24h", "failed_24h"],
            ["Needs review", "needs_review"],
          ]}
        />
        <OpsCard
          title="Queues"
          icon={Rows3}
          metric={health.queues}
          rows={[
            ["Queued", "queued"],
            ["Running", "running"],
            ["Failed 24h", "failed_24h"],
          ]}
        />
      </div>
    </div>
  );
}
