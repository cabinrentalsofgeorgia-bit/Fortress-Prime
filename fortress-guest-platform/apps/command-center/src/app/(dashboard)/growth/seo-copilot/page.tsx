"use client";

import { useState, useEffect } from "react";
import {
  Brain,
  Send,
  TrendingUp,
  FileText,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

interface PipelineStats {
  drafts_created: number;
  pending_review: number;
  deployed_count: number;
  properties_without_draft: number;
  total_active_properties: number;
  avg_godhead_score: number | null;
  active_rubrics: number;
}

function usePipelineStats() {
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/seo/pipeline-stats")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) setStats(data as PipelineStats);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return { stats, loading };
}

export default function SeoCopilotPage() {
  const [message, setMessage] = useState("");
  const { stats, loading } = usePipelineStats();

  const kpiCards = [
    {
      label: "Drafts Created",
      value: loading ? null : (stats?.drafts_created ?? 0),
      icon: FileText,
      color: "text-blue-400",
    },
    {
      label: "Pending Review",
      value: loading ? null : (stats?.pending_review ?? 0),
      icon: AlertCircle,
      color: "text-amber-400",
    },
    {
      label: "Deployed",
      value: loading ? null : (stats?.deployed_count ?? 0),
      icon: CheckCircle,
      color: "text-emerald-400",
    },
    {
      label: "Properties Uncovered",
      value: loading
        ? null
        : stats
        ? `${stats.properties_without_draft}/${stats.total_active_properties}`
        : "--",
      icon: TrendingUp,
      color: "text-purple-400",
    },
  ] as const;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        {kpiCards.map((kpi) => (
          <Card key={kpi.label}>
            <CardContent className="pt-4 pb-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">{kpi.label}</p>
                <kpi.icon className={`h-3.5 w-3.5 ${kpi.color}`} />
              </div>
              {loading ? (
                <Skeleton className="h-7 w-16 mt-1" />
              ) : (
                <p className="text-xl font-bold font-mono">
                  {kpi.value ?? "--"}
                </p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Brain className="h-4 w-4 text-emerald-500" />
              SEO Co-Pilot
              <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 ml-auto">
                Teacher / Student
              </Badge>
              {stats && (
                <Badge variant="outline" className="text-xs font-mono">
                  {stats.active_rubrics} rubric{stats.active_rubrics !== 1 ? "s" : ""} active
                </Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex h-[360px] flex-col rounded-lg border bg-muted/30">
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                <div className="flex gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-500/10">
                    <Brain className="h-4 w-4 text-emerald-500" />
                  </div>
                  <div className="rounded-lg bg-card border p-3 text-sm max-w-[80%]">
                    <p className="text-muted-foreground">
                      I&apos;m your SEO Co-Pilot. Ask me to audit a page, suggest meta
                      tags, analyze keyword gaps, or review your sitemap coverage. What
                      would you like to optimize today?
                    </p>
                  </div>
                </div>
                <Skeleton className="h-12 w-3/4 ml-11" />
                <Skeleton className="h-8 w-1/2 ml-11" />
              </div>
              <div className="border-t p-3">
                <form
                  className="flex gap-2"
                  onSubmit={(e) => { e.preventDefault(); setMessage(""); }}
                >
                  <Input
                    placeholder="Ask the Co-Pilot to audit a URL, suggest titles..."
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    className="text-sm"
                  />
                  <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700">
                    <Send className="h-4 w-4" />
                  </Button>
                </form>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Optimization Queue</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {loading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-2 rounded-md bg-muted/50 p-2.5">
                    <Skeleton className="h-4 w-4 rounded-full shrink-0" />
                    <div className="flex-1 space-y-1">
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-2.5 w-2/3" />
                    </div>
                    <Skeleton className="h-5 w-14 rounded-full" />
                  </div>
                ))
              : stats && stats.pending_review > 0
              ? (
                  <div className="flex flex-col items-center justify-center h-24 gap-2">
                    <p className="text-sm font-semibold text-amber-500">{stats.pending_review} patch{stats.pending_review !== 1 ? "es" : ""} pending review</p>
                    <a
                      href="/growth/seo-approval"
                      className="text-xs text-blue-400 underline underline-offset-2"
                    >
                      Open approval queue →
                    </a>
                  </div>
                )
              : (
                  <div className="flex flex-col items-center justify-center h-24 gap-1">
                    <CheckCircle className="h-6 w-6 text-emerald-500" />
                    <p className="text-sm text-muted-foreground">Queue is clear</p>
                  </div>
                )
            }
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Keyword Performance
            {stats?.avg_godhead_score != null && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                Avg God Head score: <span className="font-mono text-emerald-400">{stats.avg_godhead_score.toFixed(2)}</span>
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-[200px] items-center justify-center rounded-lg border border-dashed bg-muted/20">
            <p className="text-sm text-muted-foreground">
              Recharts keyword ranking timeline will render here once Search Console data is connected.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
