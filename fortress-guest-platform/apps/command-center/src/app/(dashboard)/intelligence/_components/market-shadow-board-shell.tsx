"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LineChart, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useMarketShadowBoard, useMarketSnapshotLatest } from "@/lib/hooks";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

function entryId(entry: Record<string, unknown>): string {
  const id = entry.id;
  return typeof id === "string" ? id : String(id ?? "");
}

function entryStatus(entry: Record<string, unknown>): string {
  const s = entry.status;
  return typeof s === "string" ? s : "—";
}

export function MarketShadowBoardShell() {
  const qc = useQueryClient();
  const latest = useMarketSnapshotLatest();
  const board = useMarketShadowBoard(100);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const approve = useMutation({
    mutationFn: async ({ id, note }: { id: string; note?: string }) =>
      api.post(
        `/api/intelligence/market-snapshot/shadow-board/${encodeURIComponent(id)}/approve`,
        { note: note?.trim() || undefined },
      ),
    onSuccess: () => {
      toast.success("Shadow entry approved");
      void qc.invalidateQueries({ queryKey: ["intelligence-market-shadow-board"] });
    },
    onError: (err: Error) => toast.error(err.message || "Approve failed"),
  });

  const reject = useMutation({
    mutationFn: async ({ id, note }: { id: string; note: string }) =>
      api.post(`/api/intelligence/market-snapshot/shadow-board/${encodeURIComponent(id)}/reject`, {
        note,
      }),
    onSuccess: () => {
      toast.success("Shadow entry rejected");
      void qc.invalidateQueries({ queryKey: ["intelligence-market-shadow-board"] });
    },
    onError: (err: Error) => toast.error(err.message || "Reject failed"),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <LineChart className="h-7 w-7 text-primary" />
            Market Canary — Shadow Board
          </h1>
          <p className="text-muted-foreground max-w-2xl text-sm">
            Review queued shadow pricing recommendations from Gate D. Data is served from{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">
              /api/intelligence/market-snapshot/shadow-board
            </code>
            .
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={latest.isFetching || board.isFetching}
          onClick={() => {
            void latest.refetch();
            void board.refetch();
          }}
        >
          <RefreshCw
            className={`mr-2 h-4 w-4 ${latest.isFetching || board.isFetching ? "animate-spin" : ""}`}
          />
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Latest market snapshot</CardTitle>
          <CardDescription>GET /api/intelligence/market-snapshot/latest</CardDescription>
        </CardHeader>
        <CardContent className="text-sm">
          {latest.isLoading ? (
            <p className="text-muted-foreground">Loading…</p>
          ) : latest.isError ? (
            <p className="text-destructive">
              {latest.error instanceof Error ? latest.error.message : "Failed to load snapshot"}
            </p>
          ) : latest.data?.error ? (
            <div className="space-y-1">
              <p className="text-destructive font-medium">{latest.data.error}</p>
              {latest.data.detail ? (
                <p className="text-muted-foreground text-xs">{String(latest.data.detail)}</p>
              ) : null}
            </div>
          ) : (
            <dl className="grid gap-2 sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Snapshot hash</dt>
                <dd className="font-mono text-xs break-all">
                  {latest.data?.snapshot_hash ?? "—"}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Generated</dt>
                <dd>{latest.data?.generated_at ?? "—"}</dd>
              </div>
            </dl>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Shadow board queue</CardTitle>
          <CardDescription>
            {board.data
              ? `${board.data.total} total · showing ${board.data.entries.length}`
              : "—"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {board.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading board…</p>
          ) : board.isError ? (
            <p className="text-destructive text-sm">
              {board.error instanceof Error ? board.error.message : "Failed to load shadow board"}
            </p>
          ) : !board.data?.entries?.length ? (
            <p className="text-muted-foreground text-sm">No shadow board entries.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {board.data.entries.filter((e) => entryId(e)).map((entry) => {
                  const id = entryId(entry);
                  const status = entryStatus(entry);
                  const model = typeof entry.model === "string" ? entry.model : "—";
                  const pending = status === "pending_review";
                  return (
                    <TableRow key={id}>
                      <TableCell className="max-w-[120px] truncate font-mono text-xs">
                        {id}
                      </TableCell>
                      <TableCell>{status}</TableCell>
                      <TableCell className="max-w-[160px] truncate text-sm">{model}</TableCell>
                      <TableCell className="text-right">
                        {pending ? (
                          <div className="flex flex-col items-end gap-2">
                            <div className="flex flex-wrap justify-end gap-2">
                              <Button
                                type="button"
                                size="sm"
                                variant="default"
                                disabled={approve.isPending}
                                onClick={() =>
                                  approve.mutate({
                                    id,
                                    note: (rejectNotes[`approve-${id}`] ?? "").trim() || undefined,
                                  })
                                }
                              >
                                Approve
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={reject.isPending}
                                onClick={() => {
                                  const note = (rejectNotes[id] ?? "").trim();
                                  if (!note) {
                                    toast.error("Review note required to reject");
                                    return;
                                  }
                                  reject.mutate({ id, note });
                                }}
                              >
                                Reject
                              </Button>
                            </div>
                            <div className="w-full max-w-[280px] space-y-2">
                              <div className="space-y-1">
                                <Label htmlFor={`approve-note-${id}`} className="text-xs">
                                  Approve note (optional)
                                </Label>
                                <Textarea
                                  id={`approve-note-${id}`}
                                  className="min-h-[40px] text-xs"
                                  placeholder="Optional…"
                                  value={rejectNotes[`approve-${id}`] ?? ""}
                                  onChange={(e) =>
                                    setRejectNotes((prev) => ({
                                      ...prev,
                                      [`approve-${id}`]: e.target.value,
                                    }))
                                  }
                                />
                              </div>
                              <div className="space-y-1">
                                <Label htmlFor={`reject-${id}`} className="text-xs">
                                  Reject note (required)
                                </Label>
                                <Textarea
                                  id={`reject-${id}`}
                                  className="min-h-[52px] text-xs"
                                  placeholder="Required for reject…"
                                  value={rejectNotes[id] ?? ""}
                                  onChange={(e) =>
                                    setRejectNotes((prev) => ({ ...prev, [id]: e.target.value }))
                                  }
                                />
                              </div>
                            </div>
                          </div>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

    </div>
  );
}
