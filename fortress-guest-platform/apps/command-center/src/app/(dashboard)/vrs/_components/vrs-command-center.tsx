"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  RefreshCw,
  Send,
  ShieldAlert,
  TerminalSquare,
  Waves,
} from "lucide-react";
import {
  useOverrideVrsDispatch,
  useSyncVrsLedger,
  useVrsAdjudicationDetail,
  useVrsConflictQueue,
} from "@/lib/hooks";
import type { VrsConflictQueueItem, VrsCouncilOpinion } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/lib/store";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";

function formatTimestamp(value?: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function holdReasonLabel(reason?: string): string {
  switch (reason) {
    case "below_send_threshold":
      return "Below Threshold";
    case "human_review_required":
      return "Human Review";
    case "operator_override_required":
      return "Override Required";
    case "dispatched":
      return "Dispatched";
    default:
      return "Queued";
  }
}

function seatTone(signal?: string): {
  label: "DENY" | "COMPENSATE" | "RESOLVE";
  chip: string;
  panel: string;
} {
  switch ((signal || "").toUpperCase()) {
    case "STRONG_RESOLUTION":
      return {
        label: "COMPENSATE",
        chip: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
        panel: "border-emerald-500/20 bg-emerald-500/5",
      };
    case "RESOLVE":
      return {
        label: "RESOLVE",
        chip: "border-sky-500/40 bg-sky-500/15 text-sky-300",
        panel: "border-sky-500/20 bg-sky-500/5",
      };
    case "CAUTION":
    case "CRITICAL_RISK":
    case "ERROR":
      return {
        label: "DENY",
        chip: "border-red-500/40 bg-red-500/15 text-red-300",
        panel: "border-red-500/20 bg-red-500/5",
      };
    default:
      return {
        label: "RESOLVE",
        chip: "border-indigo-500/40 bg-indigo-500/15 text-indigo-300",
        panel: "border-indigo-500/20 bg-indigo-500/5",
      };
  }
}

function QueueSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 4 }).map((_, idx) => (
        <div key={idx} className="rounded-xl border border-border/70 p-4">
          <Skeleton className="mb-3 h-4 w-28" />
          <Skeleton className="mb-2 h-5 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      ))}
    </div>
  );
}

function QueueRow({
  item,
  selected,
  onSelect,
}: {
  item: VrsConflictQueueItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-xl border p-4 text-left transition-colors",
        selected
          ? "border-primary/60 bg-primary/10"
          : "border-border/70 bg-background/60 hover:border-primary/30 hover:bg-accent/40",
      )}
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-200">
          {item.status.toUpperCase()}
        </Badge>
        <span className="text-[11px] text-muted-foreground">{formatTimestamp(item.created_at)}</span>
      </div>
      <div className="space-y-1">
        <p className="font-medium text-foreground">
          {item.guest?.full_name || "Unknown guest"}
        </p>
        <p className="text-xs text-muted-foreground">
          {item.property?.name || "Unknown property"}
          {item.reservation?.confirmation_code ? ` · ${item.reservation.confirmation_code}` : ""}
        </p>
      </div>
      <p className="mt-3 line-clamp-3 text-sm text-muted-foreground">
        {item.inbound_message || "No inbound intelligence captured on ledger."}
      </p>
      <div className="mt-3 flex items-center justify-between gap-2 text-xs">
        <span className="text-muted-foreground">{holdReasonLabel(item.hold_reason ?? undefined)}</span>
        <span className="font-medium text-foreground">
          {(item.consensus_conviction * 100).toFixed(2)}%
        </span>
      </div>
    </button>
  );
}

function SeatOpinionCard({ opinion }: { opinion: VrsCouncilOpinion }) {
  const tone = seatTone(opinion.signal);
  return (
    <div className={cn("rounded-xl border p-3", tone.panel)}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-[0.24em] text-muted-foreground">
            Seat {opinion.seat}
          </p>
          <p className="text-sm font-semibold">{opinion.persona}</p>
        </div>
        <span className={cn("rounded-full border px-2 py-1 text-[11px] font-semibold", tone.chip)}>
          {tone.label}
        </span>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">
        Signal {opinion.signal} · {(opinion.conviction * 100).toFixed(1)}%
      </p>
      <p className="text-sm leading-6 text-foreground/90">{opinion.reasoning}</p>
    </div>
  );
}

export function VrsCommandCenter() {
  const [selectedId, setSelectedId] = useState<string>();
  const [draftState, setDraftState] = useState<{ id?: string; body: string }>({ body: "" });
  const setActiveAdjudicationContext = useAppStore((s) => s.setActiveAdjudicationContext);
  const clearActiveAdjudicationContext = useAppStore((s) => s.clearActiveAdjudicationContext);

  const queue = useVrsConflictQueue();
  const syncLedger = useSyncVrsLedger();
  const queueItems = queue.data?.items ?? [];
  const activeId = selectedId ?? queueItems[0]?.id;
  const detail = useVrsAdjudicationDetail(activeId);
  const overrideDispatch = useOverrideVrsDispatch();

  const summary = queue.data?.summary;
  const selectedQueueItem = queueItems.find((item) => item.id === activeId) ?? queueItems[0];
  const opinions = detail.data?.council?.opinions ?? [];
  const draftBody =
    draftState.id === activeId
      ? draftState.body
      : typeof detail.data?.draft_reply === "string"
        ? detail.data.draft_reply
        : "";

  const current = detail.data ?? selectedQueueItem;
  const currentInbound =
    detail.data?.inbound_message ||
    detail.data?.message?.body ||
    selectedQueueItem?.inbound_message ||
    "No inbound intelligence available for this adjudication.";

  useEffect(() => {
    if (!activeId || !current) {
      clearActiveAdjudicationContext();
      return;
    }

    setActiveAdjudicationContext({
      id: activeId,
      guestName: current.guest?.full_name || "Unknown guest",
      propertyName: current.property?.name,
      consensusSignal: current.consensus_signal,
      consensusConviction: current.consensus_conviction,
      draftBody,
    });
  }, [activeId, clearActiveAdjudicationContext, current, draftBody, setActiveAdjudicationContext]);

  useEffect(() => () => clearActiveAdjudicationContext(), [clearActiveAdjudicationContext]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">
            <TerminalSquare className="h-3.5 w-3.5" />
            VRS Conflict Review
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">Adjudication Glass</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Real-time C2 surface for HELD concierge convictions. Pull the operational
            ledger, inspect the 9-seat matrix, and push an override dispatch when the
            operator wants to close the loop.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            onClick={() => syncLedger.mutate()}
            disabled={syncLedger.isPending}
          >
            <RefreshCw className={cn("h-4 w-4", syncLedger.isPending && "animate-spin")} />
            Sync Ledger
          </Button>
          <Button
            onClick={() =>
              activeId &&
              overrideDispatch.mutate({
                id: activeId,
                body: draftBody,
                consensusConviction: detail.data?.consensus_conviction,
                minimumConviction: 0,
              })
            }
            disabled={!activeId || !draftBody.trim() || overrideDispatch.isPending}
          >
            <Send className="h-4 w-4" />
            OVERRIDE & DISPATCH
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardHeader className="pb-3">
            <CardDescription>Held Queue</CardDescription>
            <CardTitle className="text-3xl">{summary?.held ?? queueItems.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Convictions paused below autonomous send threshold.
          </CardContent>
        </Card>
        <Card className="border-blue-500/20 bg-blue-500/5">
          <CardHeader className="pb-3">
            <CardDescription>Telemetry Scan</CardDescription>
            <CardTitle className="text-3xl">{summary?.total_scanned ?? 0}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Recent conflict-resolution ledger rows scanned for this panel.
          </CardContent>
        </Card>
        <Card className="border-emerald-500/20 bg-emerald-500/5">
          <CardHeader className="pb-3">
            <CardDescription>Conviction Floor</CardDescription>
            <CardTitle className="text-3xl">80.00%</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Override path forces dispatch below the autonomous threshold.
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)_360px]">
        <Card className="min-h-[720px]">
          <CardHeader className="border-b">
            <CardTitle>HELD Queue</CardTitle>
            <CardDescription>Select a conviction probe to inspect.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="h-[640px]">
              <div className="space-y-3 p-4">
                {queue.isLoading ? (
                  <QueueSkeleton />
                ) : queueItems.length === 0 ? (
                  <div className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
                    No HELD adjudications are waiting in the ledger.
                  </div>
                ) : (
                  queueItems.map((item) => (
                    <QueueRow
                      key={item.id}
                      item={item}
                      selected={item.id === activeId}
                      onSelect={() => setSelectedId(item.id)}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card className="overflow-hidden border-slate-800 bg-slate-950 text-slate-100">
            <CardHeader className="border-b border-slate-800">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardDescription className="text-slate-400">Inbound Intelligence</CardDescription>
                  <CardTitle className="text-slate-50">
                    {current?.guest?.full_name || "Awaiting selection"}
                  </CardTitle>
                </div>
                <Badge className="border-slate-700 bg-slate-900 text-slate-200">
                  {current?.consensus_signal || "NO_SIGNAL"}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 p-6">
              {detail.isLoading && activeId ? (
                <div className="space-y-3">
                  <Skeleton className="h-5 w-40 bg-slate-800" />
                  <Skeleton className="h-28 w-full bg-slate-800" />
                </div>
              ) : (
                <>
                  <div className="rounded-lg border border-slate-800 bg-black/40 p-4 font-mono text-sm leading-6 text-emerald-300">
                    {currentInbound}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                        Reservation
                      </p>
                      <p className="mt-2 text-sm text-slate-100">
                        {current?.reservation?.confirmation_code || "Unknown"}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        {current?.property?.name || "Property unavailable"}
                      </p>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-900/70 p-4">
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                        Ledger Timestamp
                      </p>
                      <p className="mt-2 text-sm text-slate-100">
                        {formatTimestamp(current?.created_at)}
                      </p>
                      <p className="mt-1 text-xs text-slate-400">
                        Session {current?.session_id || "Unknown"}
                      </p>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b">
              <CardTitle>Dispatch Override</CardTitle>
              <CardDescription>
                Edit the outbound response before triggering the Level 3 send path.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-lg border p-3">
                  <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">
                    Conviction
                  </p>
                  <p className="mt-2 text-xl font-semibold">
                    {current ? `${(current.consensus_conviction * 100).toFixed(2)}%` : "--"}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">
                    Hold Reason
                  </p>
                  <p className="mt-2 text-sm font-medium">
                    {holdReasonLabel(current?.hold_reason ?? undefined)}
                  </p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="text-xs uppercase tracking-[0.22em] text-muted-foreground">
                    Scheduling
                  </p>
                  <p className="mt-2 text-sm font-medium">
                    {current?.corrective_scheduling || "Unavailable"}
                  </p>
                </div>
              </div>

              <Textarea
                value={draftBody}
                onChange={(event) =>
                  setDraftState({
                    id: activeId,
                    body: event.target.value,
                  })
                }
                className="min-h-36 font-mono text-sm"
                placeholder="Draft reply will populate when live triage context is available."
              />

              <div className="flex flex-wrap gap-2">
                {(detail.data?.recommended_actions || []).map((action) => (
                  <Badge key={action} variant="outline">
                    {action}
                  </Badge>
                ))}
              </div>

              <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                Override dispatch lowers the minimum conviction guard to `0.0` for this
                operator action while preserving the original conviction on the outbound audit log.
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader className="border-b">
              <CardTitle>9-Seat Matrix</CardTitle>
              <CardDescription>
                DENY is red, COMPENSATE is green, RESOLVE is blue.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-[520px]">
                <div className="space-y-3 p-4">
                  {detail.isLoading && activeId ? (
                    <QueueSkeleton />
                  ) : opinions.length === 0 ? (
                    <div className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">
                      Live seat opinions are unavailable for this case. The ledger row can
                      still be overridden and dispatched.
                    </div>
                  ) : (
                    opinions.map((opinion) => (
                      <SeatOpinionCard key={`${opinion.seat}-${opinion.slug}`} opinion={opinion} />
                    ))
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b">
              <CardTitle>Operational Ledger</CardTitle>
              <CardDescription>Conflict posture and field-reality summary.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">
                  <ShieldAlert className="h-3 w-3" />
                  {current?.complaint_legitimacy || "No legitimacy signal"}
                </Badge>
                <Badge variant="outline">
                  <Waves className="h-3 w-3" />
                  {current?.escalation_level || "No escalation"}
                </Badge>
                <Badge variant="outline">
                  <AlertTriangle className="h-3 w-3" />
                  {current?.consensus_signal || "No consensus"}
                </Badge>
              </div>

              <div className="rounded-lg border p-4">
                <p className="mb-2 text-xs uppercase tracking-[0.22em] text-muted-foreground">
                  Field Reality
                </p>
                <pre className="overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-muted-foreground">
                  {JSON.stringify(current?.field_reality || {}, null, 2)}
                </pre>
              </div>

              <div className="rounded-lg border p-4">
                <p className="mb-2 text-xs uppercase tracking-[0.22em] text-muted-foreground">
                  Message Target
                </p>
                <p className="text-sm">
                  {current?.guest?.phone_number || "No routable guest phone resolved"}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {current?.guest?.email || "No guest email on file"}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
