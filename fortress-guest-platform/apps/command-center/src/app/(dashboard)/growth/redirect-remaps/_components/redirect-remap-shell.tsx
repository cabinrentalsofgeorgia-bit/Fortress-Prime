"use client";

import { useMemo, useState } from "react";
import { Check, ShieldAlert, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  useBulkApproveSeoRedirectRemaps,
  useBulkRejectSeoRedirectRemaps,
  useSeoRedirectRemapQueue,
} from "@/lib/hooks";
import type { SeoRedirectRemapQueueItem, SeoRedirectRemapStatus } from "@/lib/types";

const STATUS_BADGE: Record<SeoRedirectRemapStatus, string> = {
  proposed: "border-slate-500/20 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  promoted: "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  rejected: "border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  applied: "border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300",
  superseded: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300",
};

function formatDateTime(value: string | null): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? "");
  }
}

export function RedirectRemapShell() {
  const [status, setStatus] = useState<SeoRedirectRemapStatus | "all">("promoted");
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");

  const queue = useSeoRedirectRemapQueue({ status, limit: 200 });
  const approve = useBulkApproveSeoRedirectRemaps();
  const reject = useBulkRejectSeoRedirectRemaps();

  const items = useMemo(() => queue.data?.items ?? [], [queue.data?.items]);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) =>
      [
        item.source_path,
        item.proposed_destination_path,
        item.current_destination_path ?? "",
        item.campaign,
        item.rationale,
      ]
        .join(" ")
        .toLowerCase()
        .includes(query),
    );
  }, [items, search]);
  const active =
    filtered.find((item) => item.id === activeId) ??
    filtered[0] ??
    null;

  const handleApprove = () => {
    if (!active) return;
    approve.mutate({ ids: [active.id], note: reviewNote.trim() || undefined });
  };

  const handleReject = () => {
    if (!active || !reviewNote.trim()) return;
    reject.mutate({ ids: [active.id], note: reviewNote.trim() });
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <p className="text-2xl font-bold">{queue.data?.total ?? 0}</p>
            <p className="text-xs text-muted-foreground">Queue items in filter</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-2xl font-bold">{filtered.filter((item) => item.status === "promoted").length}</p>
            <p className="text-xs text-muted-foreground">Promoted for final seal</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <p className="text-2xl font-bold">
              {filtered.filter((item) => typeof item.grade_score === "number").length}
            </p>
            <p className="text-xs text-muted-foreground">Graded candidates</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Review Controls</CardTitle>
          <CardDescription>
            Review the God Head promoted redirect candidate and either seal it live or reject it back into quarantine.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            {(["promoted", "proposed", "applied", "rejected", "all"] as const).map((value) => (
              <Button
                key={value}
                type="button"
                variant={status === value ? "default" : "outline"}
                size="sm"
                onClick={() => setStatus(value)}
              >
                {value}
              </Button>
            ))}
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search source or destination path..."
              className="max-w-sm"
            />
          </div>
          <Textarea
            value={reviewNote}
            onChange={(event) => setReviewNote(event.target.value)}
            placeholder="Optional on approve. Required on reject."
            className="min-h-24"
          />
          <div className="flex gap-2">
            <Button type="button" disabled={!active || approve.isPending} onClick={handleApprove}>
              <Check className="mr-1.5 h-4 w-4" />
              Seal Active Candidate
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!active || !reviewNote.trim() || reject.isPending}
              onClick={handleReject}
            >
              <X className="mr-1.5 h-4 w-4" />
              Reject Active Candidate
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Queue</CardTitle>
            <CardDescription>
              Promoted candidates should be the only items that make it to final seal.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="h-[680px]">
              <Table>
                <TableHeader className="sticky top-0 bg-card">
                  <TableRow>
                    <TableHead>Source</TableHead>
                    <TableHead>Proposed Destination</TableHead>
                    <TableHead>Grade</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((item) => (
                    <TableRow
                      key={item.id}
                      className="cursor-pointer"
                      data-state={active?.id === item.id ? "selected" : undefined}
                      onClick={() => setActiveId(item.id)}
                    >
                      <TableCell className="font-mono text-xs">{item.source_path}</TableCell>
                      <TableCell className="font-mono text-xs">{item.proposed_destination_path}</TableCell>
                      <TableCell className="text-xs font-mono">
                        {typeof item.grade_score === "number" ? item.grade_score.toFixed(3) : "--"}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={STATUS_BADGE[item.status]}>
                          {item.status}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Proposal Detail</CardTitle>
            <CardDescription>
              Source evidence, rationale, entity extraction, and grader payload for the active redirect candidate.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!active ? (
              <div className="flex h-[680px] items-center justify-center text-sm text-muted-foreground">
                No remap candidate available in this filter.
              </div>
            ) : (
              <ScrollArea className="h-[680px] pr-4">
                <div className="space-y-4">
                  <div className="rounded-xl border p-4 space-y-2">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Source Path</p>
                        <p className="font-mono text-sm">{active.source_path}</p>
                      </div>
                      <Badge variant="outline" className={STATUS_BADGE[active.status]}>
                        {active.status}
                      </Badge>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Current Destination</p>
                        <p className="font-mono text-sm">{active.current_destination_path || "None"}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Proposed Destination</p>
                        <p className="font-mono text-sm">{active.proposed_destination_path}</p>
                      </div>
                    </div>
                    <div className="grid gap-3 md:grid-cols-3">
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Grade</p>
                        <p className="text-lg font-semibold">
                          {typeof active.grade_score === "number" ? active.grade_score.toFixed(3) : "--"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Campaign</p>
                        <p className="text-sm">{active.campaign}</p>
                      </div>
                      <div>
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Created</p>
                        <p className="text-sm">{formatDateTime(active.created_at)}</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-xl border p-4">
                    <div className="flex items-center gap-2">
                      <ShieldAlert className="h-4 w-4 text-amber-500" />
                      <p className="text-sm font-semibold">Swarm Rationale</p>
                    </div>
                    <p className="mt-3 text-sm text-muted-foreground">{active.rationale}</p>
                  </div>

                  <div className="rounded-xl border p-4">
                    <p className="text-sm font-semibold">Extracted Entities</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {active.extracted_entities.length > 0 ? (
                        active.extracted_entities.map((entity) => (
                          <Badge key={entity} variant="outline">
                            {entity}
                          </Badge>
                        ))
                      ) : (
                        <p className="text-sm text-muted-foreground">No entities captured.</p>
                      )}
                    </div>
                  </div>

                  <div className="rounded-xl border p-4">
                    <p className="text-sm font-semibold">Candidate Routes</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {active.route_candidates.map((route) => (
                        <Badge key={route} variant="outline" className="font-mono text-xs">
                          {route}
                        </Badge>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-xl border p-4">
                    <p className="text-sm font-semibold">Source Snapshot</p>
                    <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words text-xs leading-5">
                      {prettyJson(active.source_snapshot)}
                    </pre>
                  </div>

                  <div className="rounded-xl border p-4">
                    <p className="text-sm font-semibold">Grade Payload</p>
                    <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words text-xs leading-5">
                      {prettyJson(active.grade_payload)}
                    </pre>
                  </div>
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
