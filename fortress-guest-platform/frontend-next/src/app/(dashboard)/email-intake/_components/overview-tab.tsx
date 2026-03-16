"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { EmailIntakeDashboardResponse } from "@/lib/types";

const DIVISION_COLORS: Record<string, string> = {
  CABIN_VRS: "bg-orange-500/10 text-orange-600 border-orange-500/30",
  SALES_OPP: "bg-emerald-500/10 text-emerald-600 border-emerald-500/30",
  REAL_ESTATE: "bg-green-500/10 text-green-600 border-green-500/30",
  HEDGE_FUND: "bg-blue-500/10 text-blue-600 border-blue-500/30",
  LEGAL_ADMIN: "bg-rose-500/10 text-rose-600 border-rose-500/30",
  FINANCE: "bg-amber-500/10 text-amber-600 border-amber-500/30",
  UNKNOWN: "bg-slate-500/10 text-slate-500 border-slate-500/30",
};

type Props = {
  data?: EmailIntakeDashboardResponse;
  isLoading: boolean;
};

export function OverviewTab({ data, isLoading }: Props) {
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading overview...</div>;
  if (!data) return <div className="text-sm text-muted-foreground">No overview data.</div>;

  const totalEmails = data.division_distribution.reduce((sum, row) => sum + row.cnt, 0);
  const pendingEscalations = data.escalation.stats
    .filter((row) => row.status === "pending")
    .reduce((sum, row) => sum + row.cnt, 0);
  const quarantined = data.quarantine.by_status
    .filter((row) => row.status === "quarantined")
    .reduce((sum, row) => sum + row.cnt, 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Total Emails</p>
            <p className="text-2xl font-bold">{totalEmails.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Pending Escalations</p>
            <p className="text-2xl font-bold">{pendingEscalations.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Quarantined</p>
            <p className="text-2xl font-bold">{quarantined.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="text-xs text-muted-foreground">Active Routing Rules</p>
            <p className="text-2xl font-bold">{data.routing_rules.length}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Division Distribution</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {data.division_distribution.map((row) => (
            <div key={row.division} className="flex items-center justify-between rounded-md border p-2">
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={DIVISION_COLORS[row.division] ?? ""}>
                  {row.division}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  avg confidence {Math.round(row.avg_confidence ?? 0)}%
                </span>
              </div>
              <span className="font-semibold">{row.cnt.toLocaleString()}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

