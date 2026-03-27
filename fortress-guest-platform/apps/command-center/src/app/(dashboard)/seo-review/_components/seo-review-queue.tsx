"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, RefreshCw, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { listSeoQueue } from "@/lib/api/seo-queue";

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number") return "--";
  return value.toFixed(3);
}

function formatStatus(status: string): string {
  return status
    .split("_")
    .map((chunk) => chunk.slice(0, 1).toUpperCase() + chunk.slice(1))
    .join(" ");
}

export function SeoReviewQueue() {
  const searchParams = useSearchParams();
  const initialProperty = searchParams.get("property") ?? "";
  const initialStatus = searchParams.get("status") ?? "pending_human";
  const [draftPropertySlug, setDraftPropertySlug] = useState(initialProperty);
  const [activePropertySlug, setActivePropertySlug] = useState(initialProperty);
  const [activeStatus, setActiveStatus] = useState(initialStatus);

  const queue = useQuery({
    queryKey: ["seo-review-dashboard", "queue", activePropertySlug, activeStatus],
    queryFn: () =>
      listSeoQueue({
        status: activeStatus,
        propertySlug: activePropertySlug || undefined,
        limit: 100,
        offset: 0,
      }),
    refetchInterval: 15_000,
    staleTime: 5_000,
  });

  const items = useMemo(() => queue.data?.items ?? [], [queue.data?.items]);
  const averageScore = useMemo(() => {
    const scored = items.filter((item) => typeof item.godhead_score === "number");
    if (scored.length === 0) return null;
    return (
      scored.reduce((sum, item) => sum + (item.godhead_score ?? 0), 0) / scored.length
    );
  }, [items]);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px_260px]">
        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader className="pb-4">
            <CardTitle className="text-base text-slate-100">Queue Filters</CardTitle>
            <CardDescription className="text-slate-400">
              Pull live review and deploy state from the internal FastAPI strike surface.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="flex flex-col gap-3 sm:flex-row"
              onSubmit={(event) => {
                event.preventDefault();
                setActivePropertySlug(draftPropertySlug.trim());
              }}
            >
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
                <Input
                  value={draftPropertySlug}
                  onChange={(event) => setDraftPropertySlug(event.target.value)}
                  placeholder="Filter by property slug"
                  className="border-slate-800 bg-slate-900 pl-9 text-slate-100 placeholder:text-slate-500"
                />
              </div>
              <select
                value={activeStatus}
                onChange={(event) => setActiveStatus(event.target.value)}
                className="h-10 rounded-md border border-slate-800 bg-slate-900 px-3 text-sm text-slate-100"
              >
                <option value="pending_human">Pending Human</option>
                <option value="deployed">Deployed</option>
                <option value="all">All Statuses</option>
              </select>
              <Button type="submit">Apply Filter</Button>
              {activePropertySlug ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setDraftPropertySlug("");
                    setActivePropertySlug("");
                  }}
                >
                  Clear
                </Button>
              ) : null}
            </form>
          </CardContent>
        </Card>

        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">
              {activeStatus === "pending_human"
                ? "Pending Human"
                : activeStatus === "deployed"
                  ? "Deployed"
                  : "All Statuses"}
            </CardDescription>
            <CardTitle className="text-3xl text-slate-100">
              {queue.data?.total ?? 0}
            </CardTitle>
          </CardHeader>
        </Card>

        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">Average God Head Score</CardDescription>
            <CardTitle className="text-3xl text-slate-100">
              {averageScore === null ? "--" : averageScore.toFixed(3)}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="border-slate-800 bg-slate-950/70">
        <CardHeader className="border-b border-slate-800/80">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base text-slate-100">Review Queue</CardTitle>
              <CardDescription className="text-slate-400">
                Internal `crog-ai.com` HITL deployment approvals only.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              onClick={() => queue.refetch()}
              disabled={queue.isFetching}
            >
              <RefreshCw
                className={`mr-2 h-4 w-4 ${queue.isFetching ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {queue.isLoading ? (
            <div className="flex min-h-[320px] items-center justify-center text-sm text-slate-400">
              Loading SEO review queue...
            </div>
          ) : queue.error ? (
            <div className="flex min-h-[320px] flex-col items-center justify-center gap-4 px-6 text-center">
              <AlertCircle className="h-8 w-8 text-rose-400" />
              <p className="max-w-xl text-sm text-rose-300">
                {queue.error instanceof Error
                  ? queue.error.message
                  : "Failed to load the SEO review queue."}
              </p>
              <Button type="button" onClick={() => queue.refetch()}>
                Retry
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div className="flex min-h-[320px] items-center justify-center px-6 text-center text-sm text-slate-400">
              {activePropertySlug
                ? `No ${activeStatus} patches found for "${activePropertySlug}".`
                : `No ${activeStatus} patches are available.`}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-slate-800 hover:bg-transparent">
                  <TableHead className="text-slate-300">Property Name</TableHead>
                  <TableHead className="text-slate-300">God Head Score</TableHead>
                  <TableHead className="text-slate-300">Grade Attempts</TableHead>
                  <TableHead className="text-slate-300">Status</TableHead>
                  <TableHead className="text-slate-300">Deploy Strike</TableHead>
                  <TableHead className="text-right text-slate-300">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow
                    key={item.id}
                    className="border-slate-800/80 hover:bg-slate-900/70"
                  >
                    <TableCell className="py-4">
                      <div className="space-y-1">
                        <p className="font-medium text-slate-100">
                          {item.property_name ?? item.property_slug ?? item.page_path}
                        </p>
                        <p className="text-xs text-slate-500">{item.page_path}</p>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-slate-200">
                      {formatScore(item.godhead_score)}
                    </TableCell>
                    <TableCell className="text-slate-200">{item.grade_attempts}</TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className="border-amber-500/30 bg-amber-500/10 text-amber-200"
                      >
                        {formatStatus(item.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-slate-200">
                      {item.deploy_status ? formatStatus(item.deploy_status) : "--"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button asChild size="sm">
                        <Link href={`/seo-review/${item.id}`}>
                          Review
                          <ArrowRight className="ml-2 h-4 w-4" />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
