"use client";

import {
  FlaskConical,
  Percent,
  Users,
  MousePointerClick,
  ArrowUpRight,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";

const KPI_CARDS = [
  { label: "Active Tests", value: "0", icon: FlaskConical, color: "text-emerald-400" },
  { label: "Total Impressions", value: "--", icon: Users, color: "text-blue-400" },
  { label: "Avg. CTR Lift", value: "--", icon: MousePointerClick, color: "text-amber-400" },
  { label: "Conversion Delta", value: "--", icon: Percent, color: "text-purple-400" },
] as const;

const MOCK_EXPERIMENTS = [
  {
    name: "Homepage Hero: Video vs. Static",
    status: "Draft",
    traffic: 0,
    variant_a: "Static mountain panorama",
    variant_b: "30s drone flyover",
  },
  {
    name: "CTA Button Color: Emerald vs. Gold",
    status: "Draft",
    traffic: 0,
    variant_a: "bg-emerald-600 \"Book Now\"",
    variant_b: "bg-amber-500 \"Reserve Your Cabin\"",
  },
  {
    name: "Pricing Display: Per-Night vs. Total",
    status: "Draft",
    traffic: 0,
    variant_a: "Show per-night rate",
    variant_b: "Show total stay cost",
  },
] as const;

export default function AbTestingPage() {
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

      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Experiment Queue</h2>
        <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700 gap-1.5">
          <FlaskConical className="h-3.5 w-3.5" />
          New Experiment
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {MOCK_EXPERIMENTS.map((exp) => (
          <Card key={exp.name}>
            <CardHeader className="pb-2">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm leading-tight">{exp.name}</CardTitle>
                <Badge
                  variant="outline"
                  className="bg-muted text-muted-foreground border-border shrink-0"
                >
                  {exp.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Variant A</span>
                  <span className="font-mono">50%</span>
                </div>
                <Progress value={0} className="h-1.5" />
                <p className="text-xs text-muted-foreground truncate">{exp.variant_a}</p>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Variant B</span>
                  <span className="font-mono">50%</span>
                </div>
                <Progress value={0} className="h-1.5" />
                <p className="text-xs text-muted-foreground truncate">{exp.variant_b}</p>
              </div>
              <div className="flex items-center justify-between pt-1 border-t">
                <span className="text-xs text-muted-foreground">
                  {exp.traffic.toLocaleString()} impressions
                </span>
                <Button variant="ghost" size="xs" className="gap-1 text-xs">
                  Launch <ArrowUpRight className="h-3 w-3" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Historical Results (Coming Soon)</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 rounded-md bg-muted/50 p-2.5">
                <Skeleton className="h-8 w-8 rounded-md shrink-0" />
                <div className="flex-1 space-y-1">
                  <Skeleton className="h-3 w-3/4" />
                  <Skeleton className="h-2.5 w-1/2" />
                </div>
                <Skeleton className="h-5 w-16 rounded-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
