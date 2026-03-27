"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, RefreshCw, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  listSwarmEscalationsWithRuns,
  type SwarmEscalationListItem,
  type TrustPayload,
} from "@/lib/api/swarm-trust";

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

function formatReason(reasonCode: string): string {
  return reasonCode
    .split("_")
    .map((chunk) => chunk.slice(0, 1).toUpperCase() + chunk.slice(1))
    .join(" ");
}

function formatDollarsFromCents(amountCents: number): string {
  return currencyFormatter.format(amountCents / 100);
}

function getDebitExposure(payload: TrustPayload): number {
  if (!Array.isArray(payload.entries)) return 0;

  return payload.entries.reduce((total, entry) => {
    if (entry.entry_type !== "debit" || typeof entry.amount_cents !== "number") {
      return total;
    }
    return total + entry.amount_cents;
  }, 0);
}

function formatQueueTime(startedAt: string): string {
  const deltaMs = Date.now() - new Date(startedAt).getTime();
  const safeDeltaMs = Number.isFinite(deltaMs) ? Math.max(deltaMs, 0) : 0;
  const minutes = Math.floor(safeDeltaMs / 60_000);

  if (minutes < 1) return "<1 min";
  if (minutes < 60) return `${minutes} min`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const remainingMinutes = minutes % 60;
    return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
  }

  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours > 0 ? `${days}d ${remainingHours}h` : `${days}d`;
}

function QueueTable({ items }: { items: SwarmEscalationListItem[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow className="border-slate-800 hover:bg-transparent">
          <TableHead className="text-slate-300">Agent Name</TableHead>
          <TableHead className="text-slate-300">Trigger Source</TableHead>
          <TableHead className="text-slate-300">Escalation Reason</TableHead>
          <TableHead className="text-slate-300">Proposed Amount</TableHead>
          <TableHead className="text-slate-300">Time in Queue</TableHead>
          <TableHead className="text-right text-slate-300">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map(({ escalation, run }) => {
          const proposedAmount = getDebitExposure(escalation.proposed_payload);

          return (
            <TableRow
              key={escalation.id}
              className="border-slate-800/80 hover:bg-slate-900/70"
            >
              <TableCell className="py-4">
                <div className="space-y-1">
                  <p className="font-medium text-slate-100">{escalation.agent_name}</p>
                  <p className="font-mono text-xs text-slate-500">{run.id}</p>
                </div>
              </TableCell>
              <TableCell className="text-slate-200">{run.trigger_source}</TableCell>
              <TableCell>
                <Badge
                  variant="outline"
                  className="border-amber-500/30 bg-amber-500/10 text-amber-200"
                >
                  {formatReason(escalation.reason_code)}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-slate-100">
                {formatDollarsFromCents(proposedAmount)}
              </TableCell>
              <TableCell className="text-slate-200">{formatQueueTime(run.started_at)}</TableCell>
              <TableCell className="text-right">
                <Button asChild size="sm">
                  <Link href={`/trust-review/${escalation.id}`}>
                    Review
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

export function TrustReviewQueue() {
  const queue = useQuery({
    queryKey: ["trust-review", "queue"],
    queryFn: listSwarmEscalationsWithRuns,
    staleTime: 5_000,
    refetchInterval: 15_000,
  });

  const items = queue.data ?? [];
  const totalExposure = useMemo(
    () =>
      items.reduce(
        (sum, item) => sum + getDebitExposure(item.escalation.proposed_payload),
        0,
      ),
    [items],
  );

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_260px_260px]">
        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-slate-100">
              <ShieldAlert className="h-4 w-4 text-amber-300" />
              Trust Swarm Escalation Queue
            </CardTitle>
            <CardDescription className="text-slate-400">
              Live `crog-ai.com` HITL gate for blocked financial agent decisions.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">Pending Escalations</CardDescription>
            <CardTitle className="text-3xl text-slate-100">{items.length}</CardTitle>
          </CardHeader>
        </Card>

        <Card className="border-slate-800 bg-slate-950/70">
          <CardHeader className="pb-2">
            <CardDescription className="text-slate-400">Total Debit Exposure</CardDescription>
            <CardTitle className="text-3xl text-slate-100">
              {formatDollarsFromCents(totalExposure)}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="border-slate-800 bg-slate-950/70">
        <CardHeader className="border-b border-slate-800/80">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base text-slate-100">Blocked Trust Decisions</CardTitle>
              <CardDescription className="text-slate-400">
                Review every pending escalation before an operator override is sealed.
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
              Loading Trust Swarm escalations...
            </div>
          ) : queue.error ? (
            <div className="flex min-h-[320px] flex-col items-center justify-center gap-4 px-6 text-center">
              <AlertCircle className="h-8 w-8 text-rose-400" />
              <p className="max-w-xl text-sm text-rose-300">
                {queue.error instanceof Error
                  ? queue.error.message
                  : "Failed to load the Trust Swarm escalation queue."}
              </p>
              <Button type="button" onClick={() => queue.refetch()}>
                Retry
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div className="flex min-h-[320px] items-center justify-center px-6 text-center text-sm text-slate-400">
              No pending Trust Swarm escalations are waiting for operator review.
            </div>
          ) : (
            <QueueTable items={items} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
