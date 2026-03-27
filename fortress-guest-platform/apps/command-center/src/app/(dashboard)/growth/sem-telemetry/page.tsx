"use client";

import {
  Megaphone,
  DollarSign,
  Target,
  TrendingUp,
  BarChart3,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

const KPI_CARDS = [
  { label: "Monthly Ad Spend", value: "$--", icon: DollarSign, color: "text-emerald-400" },
  { label: "ROAS", value: "--x", icon: TrendingUp, color: "text-blue-400" },
  { label: "Conversions (30d)", value: "--", icon: Target, color: "text-amber-400" },
  { label: "Cost per Booking", value: "$--", icon: BarChart3, color: "text-purple-400" },
] as const;

const MOCK_CAMPAIGNS = [
  { name: "Blue Ridge Cabin Rentals - Brand", platform: "Google Ads", budget: "--", status: "Paused" },
  { name: "Pet Friendly Cabins GA", platform: "Google Ads", budget: "--", status: "Draft" },
  { name: "Luxury Cabin Getaway - Retarget", platform: "Meta Ads", budget: "--", status: "Draft" },
  { name: "River Cabins - Discovery", platform: "Google Ads", budget: "--", status: "Draft" },
  { name: "Corporate Retreats North GA", platform: "LinkedIn Ads", budget: "--", status: "Draft" },
] as const;

const PLATFORM_COLORS: Record<string, string> = {
  "Google Ads": "bg-blue-500/10 text-blue-500 border-blue-500/20",
  "Meta Ads": "bg-indigo-500/10 text-indigo-500 border-indigo-500/20",
  "LinkedIn Ads": "bg-sky-500/10 text-sky-500 border-sky-500/20",
};

export default function SemTelemetryPage() {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        {KPI_CARDS.map((kpi) => (
          <Card key={kpi.label}>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">{kpi.label}</p>
                <kpi.icon className={`h-3.5 w-3.5 ${kpi.color}`} />
              </div>
              <p className="text-xl font-bold font-mono">{kpi.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Spend vs. Revenue (Coming Soon)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex h-[240px] items-center justify-center rounded-lg border border-dashed bg-muted/20">
              <p className="text-sm text-muted-foreground">
                Dual-axis Recharts area chart: daily ad spend overlaid with attributed
                booking revenue.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Channel Mix</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex h-[240px] items-center justify-center rounded-lg border border-dashed bg-muted/20">
              <p className="text-sm text-muted-foreground text-center px-4">
                Recharts pie chart: Google Ads, Meta, LinkedIn, Organic share of
                bookings.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Megaphone className="h-4 w-4 text-amber-500" />
              Campaign Roster
            </CardTitle>
            <Badge variant="outline" className="bg-muted text-muted-foreground border-border">
              {MOCK_CAMPAIGNS.length} campaigns
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {MOCK_CAMPAIGNS.map((c) => (
            <div
              key={c.name}
              className="flex items-center justify-between rounded-md bg-muted/50 p-2.5"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Megaphone className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{c.name}</p>
                  <Badge
                    variant="outline"
                    className={PLATFORM_COLORS[c.platform] ?? ""}
                  >
                    {c.platform}
                  </Badge>
                </div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-xs font-mono text-muted-foreground">{c.budget}/mo</span>
                <Badge
                  variant="outline"
                  className="bg-muted text-muted-foreground border-border"
                >
                  {c.status}
                </Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Keyword Bid Intelligence (Coming Soon)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 rounded-md bg-muted/50 p-2.5">
                <Skeleton className="h-4 w-4 rounded-full shrink-0" />
                <div className="flex-1 space-y-1">
                  <Skeleton className="h-3 w-3/5" />
                  <Skeleton className="h-2.5 w-2/5" />
                </div>
                <Skeleton className="h-4 w-12" />
                <Skeleton className="h-5 w-14 rounded-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
