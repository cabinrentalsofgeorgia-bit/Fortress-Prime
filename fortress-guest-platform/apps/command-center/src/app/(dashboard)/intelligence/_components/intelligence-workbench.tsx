"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Bot,
  Brain,
  LineChart,
  Radar,
  Sparkles,
} from "lucide-react";
import { useMarketSnapshotLatest } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const LINKS: { href: string; label: string; description: string; icon: typeof Sparkles }[] = [
  {
    href: "/intelligence/market-shadow",
    label: "Market Canary",
    description: "Shadow board + latest Gate D snapshot",
    icon: LineChart,
  },
  {
    href: "/command/parity",
    label: "Shadow Parallel",
    description: "SEO parity dashboard and recovery drafts",
    icon: Radar,
  },
  {
    href: "/growth/seo-copilot",
    label: "SEO Copilot",
    description: "Growth lane — copilot workflows",
    icon: Sparkles,
  },
  {
    href: "/ai-engine",
    label: "AI Engine",
    description: "Review queue and messaging automation",
    icon: Brain,
  },
  {
    href: "/automations",
    label: "Automations",
    description: "VRS rule engine console",
    icon: Bot,
  },
];

export function IntelligenceWorkbench() {
  const latest = useMarketSnapshotLatest();

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">Intelligence</h1>
        <p className="text-muted-foreground max-w-2xl text-sm">
          Sovereign analytics, shadow parity, and AI ops. Each tile opens a live dashboard backed by
          FastAPI routes on the DGX cluster.
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle className="text-base">Latest market snapshot</CardTitle>
            <CardDescription>
              <code className="rounded bg-muted px-1 py-0.5 text-xs">
                GET /api/intelligence/market-snapshot/latest
              </code>
            </CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" asChild>
            <Link href="/intelligence/market-shadow">
              Open shadow board
              <ArrowUpRight className="ml-1 h-4 w-4" />
            </Link>
          </Button>
        </CardHeader>
        <CardContent className="text-sm">
          {latest.isLoading ? (
            <p className="text-muted-foreground">Loading snapshot…</p>
          ) : latest.isError ? (
            <p className="text-destructive">
              {latest.error instanceof Error ? latest.error.message : "Snapshot request failed"}
            </p>
          ) : latest.data?.error ? (
            <p className="text-destructive">{latest.data.error}</p>
          ) : (
            <dl className="grid gap-3 sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground text-xs uppercase tracking-wide">Hash</dt>
                <dd className="font-mono text-xs break-all">
                  {latest.data?.snapshot_hash ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs uppercase tracking-wide">
                  Generated
                </dt>
                <dd>{latest.data?.generated_at ?? "—"}</dd>
              </div>
              {latest.data?.summary && typeof latest.data.summary === "object" ? (
                <div className="sm:col-span-2">
                  <dt className="text-muted-foreground mb-1 text-xs uppercase tracking-wide">
                    Summary (excerpt)
                  </dt>
                  <dd>
                    <pre className="bg-muted max-h-40 overflow-auto rounded-md p-3 text-xs">
                      {JSON.stringify(latest.data.summary, null, 2)}
                    </pre>
                  </dd>
                </div>
              ) : null}
            </dl>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {LINKS.map((item) => (
          <Card key={item.href} className="flex flex-col">
            <CardHeader>
              <div className="flex items-center gap-2">
                <item.icon className="h-5 w-5 text-primary" />
                <CardTitle className="text-base">{item.label}</CardTitle>
              </div>
              <CardDescription>{item.description}</CardDescription>
            </CardHeader>
            <CardContent className="mt-auto">
              <Button variant="secondary" size="sm" asChild className="w-full">
                <Link href={item.href}>
                  Open
                  <ArrowUpRight className="ml-2 h-4 w-4" />
                </Link>
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
