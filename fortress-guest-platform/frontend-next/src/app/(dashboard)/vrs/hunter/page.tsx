"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CalendarDays,
  Crosshair,
  Mail,
  RefreshCw,
  Search,
  Send,
  ShieldAlert,
} from "lucide-react";
import {
  useApproveHunterDraft,
  useDispatchHunterTarget,
  useEditHunterDraft,
  useRejectHunterDraft,
  useRetryHunterDraft,
  useVrsHunterQueue,
  useVrsHunterQueueStats,
  useVrsHunterTargets,
} from "@/lib/hooks";
import { api } from "@/lib/api";
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import type { VrsHunterQueueItem } from "@/lib/types";
import { toast } from "sonner";

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString();
}

function scoreTone(score: number): string {
  if (score >= 85) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  if (score >= 70) return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return "border-slate-500/40 bg-slate-500/10 text-slate-300";
}

function queueTone(status: string): string {
  switch (status) {
    case "approved":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
    case "edited":
      return "border-sky-500/30 bg-sky-500/10 text-sky-300";
    case "rejected":
      return "border-red-500/30 bg-red-500/10 text-red-300";
    case "failed":
      return "border-orange-500/30 bg-orange-500/10 text-orange-300";
    default:
      return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  }
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function HunterTableSkeleton() {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="grid grid-cols-6 gap-3">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ))}
    </div>
  );
}

function HunterDraftQueueSkeleton() {
  return (
    <div className="space-y-3 p-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="rounded-xl border p-4">
          <Skeleton className="mb-3 h-4 w-24" />
          <Skeleton className="mb-2 h-5 w-2/3" />
          <Skeleton className="h-16 w-full" />
        </div>
      ))}
    </div>
  );
}

function QueueEntryButton({
  item,
  selected,
  onSelect,
  checked,
  onToggleChecked,
}: {
  item: VrsHunterQueueItem;
  selected: boolean;
  onSelect: () => void;
  checked: boolean;
  onToggleChecked: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-xl border p-4 text-left transition-colors ${
        selected
          ? "border-primary/60 bg-primary/10"
          : "border-border/70 bg-background/60 hover:border-primary/30 hover:bg-accent/40"
      }`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <Checkbox
              checked={checked}
              disabled={item.status !== "pending_review"}
              onCheckedChange={(value) => onToggleChecked(Boolean(value))}
            />
          </span>
          <Badge variant="outline" className={queueTone(item.status)}>
            {item.status.replace("_", " ").toUpperCase()}
          </Badge>
        </div>
        <span className="text-[11px] text-muted-foreground">
          {formatTimestamp(item.created_at)}
        </span>
      </div>
      <p className="font-medium text-foreground">
        {item.guest?.full_name || "Unknown guest"}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {item.property?.name || "Property unresolved"}
      </p>
      <p className="mt-3 line-clamp-4 text-sm text-muted-foreground">
        {item.final_human_message || item.original_ai_draft}
      </p>
    </button>
  );
}

type BulkActionState =
  | { kind: "dispatch" }
  | { kind: "approve"; channel: "email" | "sms" }
  | { kind: "reject" }
  | { kind: "retry"; channel: "email" | "sms" }
  | null;

export default function VrsHunterPage() {
  const targetsQuery = useVrsHunterTargets();
  const [reviewStatusFilter, setReviewStatusFilter] = useState("pending_review");
  const [reviewChannelFilter, setReviewChannelFilter] = useState("all");
  const [reviewSearch, setReviewSearch] = useState("");
  const [telemetryStatusFilter, setTelemetryStatusFilter] = useState("all");
  const [telemetryChannelFilter, setTelemetryChannelFilter] = useState("all");
  const [telemetrySearch, setTelemetrySearch] = useState("");
  const queueQuery = useVrsHunterQueue(reviewStatusFilter, 20);
  const historyQuery = useVrsHunterQueue("all", 12);
  const queueStatsQuery = useVrsHunterQueueStats();
  const dispatchTarget = useDispatchHunterTarget();
  const approveDraft = useApproveHunterDraft();
  const editDraft = useEditHunterDraft();
  const rejectDraft = useRejectHunterDraft();
  const retryDraft = useRetryHunterDraft();
  const targets = targetsQuery.data ?? [];
  const queueItems = queueQuery.data?.items ?? [];
  const historyItems = historyQuery.data?.items ?? [];
  const [selectedQueueId, setSelectedQueueId] = useState<string>();
  const [draftState, setDraftState] = useState<{ id?: string; body: string }>({ body: "" });
  const [selectedTargetIds, setSelectedTargetIds] = useState<string[]>([]);
  const [selectedQueueIds, setSelectedQueueIds] = useState<string[]>([]);
  const [selectedDeliveryIds, setSelectedDeliveryIds] = useState<string[]>([]);
  const [pendingBulkAction, setPendingBulkAction] = useState<BulkActionState>(null);
  const [isBulkDispatching, setIsBulkDispatching] = useState(false);
  const [isBulkQueueActing, setIsBulkQueueActing] = useState(false);
  const [isBulkRetrying, setIsBulkRetrying] = useState(false);

  const metrics = useMemo(() => {
    const totalLifetimeValue = targets.reduce((sum, target) => sum + target.lifetime_value, 0);
    const averageScore = targets.length
      ? Math.round(targets.reduce((sum, target) => sum + target.target_score, 0) / targets.length)
      : 0;
    const autonomousReady = targets.filter((target) => target.target_score >= 85).length;
    const maxDormancy = targets.reduce(
      (max, target) => Math.max(max, target.days_dormant),
      0,
    );

    return {
      totalLifetimeValue,
      averageScore,
      autonomousReady,
      maxDormancy,
    };
  }, [targets]);

  const filteredQueueItems = useMemo(
    () =>
      queueItems.filter((item) => {
        const channelMatches =
          reviewChannelFilter === "all" ? true : item.delivery_channel === reviewChannelFilter;
        const q = reviewSearch.trim().toLowerCase();
        if (!q) return channelMatches;
        const haystack = [
          item.guest?.full_name,
          item.guest?.email,
          item.property?.name,
          item.property?.slug,
          item.original_ai_draft,
          item.final_human_message,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return channelMatches && haystack.includes(q);
      }),
    [queueItems, reviewChannelFilter, reviewSearch],
  );
  const pendingQueueItems = useMemo(
    () => filteredQueueItems.filter((item) => item.status === "pending_review"),
    [filteredQueueItems],
  );

  useEffect(() => {
    if (!selectedQueueId && filteredQueueItems[0]?.id) {
      setSelectedQueueId(filteredQueueItems[0].id);
    }
  }, [filteredQueueItems, selectedQueueId]);

  useEffect(() => {
    if (selectedQueueId && !filteredQueueItems.some((item) => item.id === selectedQueueId)) {
      setSelectedQueueId(filteredQueueItems[0]?.id);
    }
  }, [filteredQueueItems, selectedQueueId]);

  const selectedQueueItem =
    filteredQueueItems.find((item) => item.id === selectedQueueId) ?? filteredQueueItems[0];
  const draftBody =
    draftState.id === selectedQueueItem?.id
      ? draftState.body
      : selectedQueueItem?.final_human_message || selectedQueueItem?.original_ai_draft || "";
  const queueStats = queueStatsQuery.data;
  const deliveryItems = useMemo(
    () =>
      historyItems.filter((item) => {
        const statusMatches =
          telemetryStatusFilter === "all" ? true : item.status === telemetryStatusFilter;
        const channelMatches =
          telemetryChannelFilter === "all"
            ? true
            : item.delivery_channel === telemetryChannelFilter;
        const q = telemetrySearch.trim().toLowerCase();
        const haystack = [
          item.guest?.full_name,
          item.guest?.email,
          item.property?.name,
          item.property?.slug,
          item.error_log,
          item.original_ai_draft,
          item.final_human_message,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return (
          ["delivered", "failed", "approved", "edited", "rejected"].includes(item.status) &&
          statusMatches &&
          channelMatches &&
          (!q || haystack.includes(q))
        );
      }),
    [historyItems, telemetryStatusFilter, telemetryChannelFilter, telemetrySearch],
  );
  const failedDeliveryItems = useMemo(
    () => deliveryItems.filter((item) => item.status === "failed"),
    [deliveryItems],
  );

  useEffect(() => {
    setSelectedTargetIds((current) =>
      current.filter((id) => targets.some((target) => target.guest_id === id)),
    );
  }, [targets]);

  useEffect(() => {
    setSelectedQueueIds((current) =>
      current.filter((id) => pendingQueueItems.some((item) => item.id === id)),
    );
  }, [pendingQueueItems]);

  useEffect(() => {
    setSelectedDeliveryIds((current) =>
      current.filter((id) => failedDeliveryItems.some((item) => item.id === id)),
    );
  }, [failedDeliveryItems]);

  const allTargetsSelected =
    targets.length > 0 && targets.every((target) => selectedTargetIds.includes(target.guest_id));
  const allPendingQueueSelected =
    pendingQueueItems.length > 0 &&
    pendingQueueItems.every((item) => selectedQueueIds.includes(item.id));
  const allFailedSelected =
    failedDeliveryItems.length > 0 &&
    failedDeliveryItems.every((item) => selectedDeliveryIds.includes(item.id));

  function toggleSelection(
    current: string[],
    id: string,
    checked: boolean,
    setter: (value: string[]) => void,
  ) {
    if (checked) {
      setter(current.includes(id) ? current : [...current, id]);
      return;
    }
    setter(current.filter((value) => value !== id));
  }

  async function refetchHunterState() {
    await Promise.all([
      targetsQuery.refetch(),
      queueQuery.refetch(),
      historyQuery.refetch(),
      queueStatsQuery.refetch(),
    ]);
  }

  async function bulkDispatchSelectedTargets() {
    if (selectedTargetIds.length === 0) return;
    setIsBulkDispatching(true);
    try {
      const selected = targets.filter((target) => selectedTargetIds.includes(target.guest_id));
      const results = await Promise.allSettled(
        selected.map((target) =>
          api.hunter.dispatch({
            guest_id: target.guest_id,
            full_name: target.full_name,
            target_score: target.target_score,
          }),
        ),
      );
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failureCount = results.length - successCount;
      if (successCount > 0) {
        toast.success(`Queued ${successCount} Hunter dispatch${successCount === 1 ? "" : "es"}`);
      }
      if (failureCount > 0) {
        toast.error(`${failureCount} Hunter dispatch${failureCount === 1 ? "" : "es"} failed`);
      }
      setSelectedTargetIds([]);
      await refetchHunterState();
    } finally {
      setIsBulkDispatching(false);
    }
  }

  async function bulkApproveQueue(channel: "email" | "sms") {
    if (selectedQueueIds.length === 0) return;
    setIsBulkQueueActing(true);
    try {
      const results = await Promise.allSettled(
        selectedQueueIds.map((entryId) => api.hunter.approveVia(entryId, channel)),
      );
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failureCount = results.length - successCount;
      if (successCount > 0) {
        toast.success(
          `Delivered ${successCount} queued draft${successCount === 1 ? "" : "s"} via ${channel}`,
        );
      }
      if (failureCount > 0) {
        toast.error(`${failureCount} queued draft${failureCount === 1 ? "" : "s"} failed`);
      }
      setSelectedQueueIds([]);
      await refetchHunterState();
    } finally {
      setIsBulkQueueActing(false);
    }
  }

  async function bulkRejectQueue() {
    if (selectedQueueIds.length === 0) return;
    setIsBulkQueueActing(true);
    try {
      const results = await Promise.allSettled(
        selectedQueueIds.map((entryId) =>
          api.hunter.reject(entryId, "Bulk operator rejection from Hunter Glass."),
        ),
      );
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failureCount = results.length - successCount;
      if (successCount > 0) {
        toast.success(`Rejected ${successCount} queued draft${successCount === 1 ? "" : "s"}`);
      }
      if (failureCount > 0) {
        toast.error(`${failureCount} queued reject${failureCount === 1 ? "" : "s"} failed`);
      }
      setSelectedQueueIds([]);
      await refetchHunterState();
    } finally {
      setIsBulkQueueActing(false);
    }
  }

  async function bulkRetryFailed(channel: "email" | "sms") {
    if (selectedDeliveryIds.length === 0) return;
    setIsBulkRetrying(true);
    try {
      const results = await Promise.allSettled(
        selectedDeliveryIds.map((entryId) => api.hunter.retryVia(entryId, channel)),
      );
      const successCount = results.filter((result) => result.status === "fulfilled").length;
      const failureCount = results.length - successCount;
      if (successCount > 0) {
        toast.success(
          `Retried ${successCount} failed deliver${successCount === 1 ? "y" : "ies"} via ${channel}`,
        );
      }
      if (failureCount > 0) {
        toast.error(`${failureCount} failed retr${failureCount === 1 ? "y" : "ies"} did not complete`);
      }
      setSelectedDeliveryIds([]);
      await refetchHunterState();
    } finally {
      setIsBulkRetrying(false);
    }
  }

  const bulkActionConfig = useMemo(() => {
    if (!pendingBulkAction) return null;
    switch (pendingBulkAction.kind) {
      case "dispatch":
        return {
          title: "Dispatch Selected Targets?",
          description: `Queue ${selectedTargetIds.length} dormant VIP target${selectedTargetIds.length === 1 ? "" : "s"} into the Reactivation Hunter drafting pipeline.`,
          confirmLabel: "Dispatch Selected",
          variant: "default" as const,
        };
      case "approve":
        return {
          title: `Approve Selected via ${pendingBulkAction.channel.toUpperCase()}?`,
          description: `Deliver ${selectedQueueIds.length} queued draft${selectedQueueIds.length === 1 ? "" : "s"} via ${pendingBulkAction.channel}. This will immediately move them out of review if delivery succeeds.`,
          confirmLabel:
            pendingBulkAction.channel === "sms" ? "Approve via SMS" : "Approve via Email",
          variant: "default" as const,
        };
      case "reject":
        return {
          title: "Reject Selected Drafts?",
          description: `Reject ${selectedQueueIds.length} queued Hunter draft${selectedQueueIds.length === 1 ? "" : "s"}. This cannot be undone from the current bulk action.`,
          confirmLabel: "Reject Selected",
          variant: "destructive" as const,
        };
      case "retry":
        return {
          title: `Retry Selected Failed ${pendingBulkAction.channel.toUpperCase()} Deliveries?`,
          description: `Retry ${selectedDeliveryIds.length} failed Hunter deliver${selectedDeliveryIds.length === 1 ? "y" : "ies"} via ${pendingBulkAction.channel}.`,
          confirmLabel:
            pendingBulkAction.channel === "sms" ? "Retry Selected SMS" : "Retry Selected Email",
          variant: "default" as const,
        };
      default:
        return null;
    }
  }, [pendingBulkAction, selectedDeliveryIds.length, selectedQueueIds.length, selectedTargetIds.length]);

  async function confirmBulkAction() {
    if (!pendingBulkAction) return;
    const action = pendingBulkAction;
    setPendingBulkAction(null);
    if (action.kind === "dispatch") {
      await bulkDispatchSelectedTargets();
      return;
    }
    if (action.kind === "approve") {
      await bulkApproveQueue(action.channel);
      return;
    }
    if (action.kind === "reject") {
      await bulkRejectQueue();
      return;
    }
    await bulkRetryFailed(action.channel);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">
            <Crosshair className="h-3.5 w-3.5" />
            Reactivation Hunter
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">Dormant VIP Intelligence</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Scans the guest ledger for high-value guests who have gone quiet long enough
            to justify reactivation outreach.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="outline" className="text-xs">
            Autonomous send threshold: 85+
          </Badge>
          <Button
            variant="outline"
            onClick={() => void targetsQuery.refetch()}
            disabled={targetsQuery.isFetching}
          >
            <RefreshCw
              className={`h-4 w-4 ${targetsQuery.isFetching ? "animate-spin" : ""}`}
            />
            Refresh Targets
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="border-primary/20 bg-primary/5">
          <CardHeader className="pb-3">
            <CardDescription>High-Value Dormant Assets</CardDescription>
            <CardTitle className="text-3xl">{targets.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Guests above the hunter value floor and outside the 365-day recency window.
          </CardContent>
        </Card>
        <Card className="border-emerald-500/20 bg-emerald-500/5">
          <CardHeader className="pb-3">
            <CardDescription>Review Queue</CardDescription>
            <CardTitle className="text-3xl">{queueStats?.pending_review ?? 0}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Drafted reactivation messages waiting for operator approval or edit.
          </CardContent>
        </Card>
        <Card className="border-sky-500/20 bg-sky-500/5">
          <CardHeader className="pb-3">
            <CardDescription>Total Reactivation Value</CardDescription>
            <CardTitle className="text-3xl">
              {formatCurrency(metrics.totalLifetimeValue)}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Combined lifetime value represented by the current target scan.
          </CardContent>
        </Card>
        <Card className="border-amber-500/20 bg-amber-500/5">
          <CardHeader className="pb-3">
            <CardDescription>Autonomous Ready</CardDescription>
            <CardTitle className="text-3xl">{metrics.autonomousReady}</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Targets currently scoring above the `DISPATCH AI` threshold.
          </CardContent>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="border-b">
          <CardTitle>VIP Reactivation Queue</CardTitle>
          <CardDescription>
            Strictly typed hunter targets hydrated from `/api/vrs/hunter/targets`.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b p-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox
                checked={allTargetsSelected}
                onCheckedChange={(value) =>
                  setSelectedTargetIds(Boolean(value) ? targets.map((target) => target.guest_id) : [])
                }
              />
              <span>{selectedTargetIds.length} selected</span>
            </div>
            <Button
              onClick={() => setPendingBulkAction({ kind: "dispatch" })}
              disabled={selectedTargetIds.length === 0 || isBulkDispatching}
            >
              {isBulkDispatching ? "Dispatching..." : "Dispatch Selected"}
            </Button>
          </div>
          {targetsQuery.isLoading ? (
            <HunterTableSkeleton />
          ) : targetsQuery.isError ? (
            <div className="p-6 text-sm text-destructive">
              {targetsQuery.error instanceof Error
                ? targetsQuery.error.message
                : "Failed to fetch Reactivation Hunter targets."}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <Checkbox
                      checked={allTargetsSelected}
                      onCheckedChange={(value) =>
                        setSelectedTargetIds(Boolean(value) ? targets.map((target) => target.guest_id) : [])
                      }
                    />
                  </TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Lifetime Value</TableHead>
                  <TableHead>Last Stay</TableHead>
                  <TableHead>Dormancy</TableHead>
                  <TableHead>Target Score</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-28 text-center text-muted-foreground">
                      No dormant VIP targets matched the current scan.
                    </TableCell>
                  </TableRow>
                ) : (
                  targets.map((guest) => (
                    <TableRow key={guest.guest_id}>
                      <TableCell>
                        <Checkbox
                          checked={selectedTargetIds.includes(guest.guest_id)}
                          onCheckedChange={(value) =>
                            toggleSelection(
                              selectedTargetIds,
                              guest.guest_id,
                              Boolean(value),
                              setSelectedTargetIds,
                            )
                          }
                        />
                      </TableCell>
                      <TableCell className="min-w-[260px]">
                        <div className="space-y-1">
                          <div className="font-medium text-foreground">{guest.full_name}</div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <Mail className="h-3.5 w-3.5" />
                            {guest.email}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="font-medium">
                        {formatCurrency(guest.lifetime_value)}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 text-sm">
                          <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
                          {formatDate(guest.last_stay_date)}
                        </div>
                      </TableCell>
                      <TableCell className="text-amber-300">
                        {guest.days_dormant} days
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="outline"
                          className={scoreTone(guest.target_score)}
                        >
                          {guest.target_score}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          onClick={() =>
                            dispatchTarget.mutate({
                              guestId: guest.guest_id,
                              fullName: guest.full_name,
                              targetScore: guest.target_score,
                            })
                          }
                          disabled={
                            isBulkDispatching ||
                            dispatchTarget.isPending &&
                            dispatchTarget.variables?.guestId === guest.guest_id
                          }
                        >
                          {dispatchTarget.isPending &&
                          dispatchTarget.variables?.guestId === guest.guest_id
                            ? "Queueing..."
                            : "Dispatch AI"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Hunter Review Console</CardTitle>
          <CardDescription>
            Review drafted dormant-guest outreach before it moves to the delivery layer.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="min-h-[520px]">
            <CardHeader className="border-b">
              <CardTitle>Queue Review</CardTitle>
              <CardDescription>
                {queueQuery.data?.total ?? 0} rows matched on the current queue-status filter.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <div className="flex flex-wrap gap-3 border-b p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Checkbox
                      checked={allPendingQueueSelected}
                      onCheckedChange={(value) =>
                        setSelectedQueueIds(Boolean(value) ? pendingQueueItems.map((item) => item.id) : [])
                      }
                    />
                    <span>{selectedQueueIds.length} selected</span>
                  </div>
                <div className="relative w-full min-w-[220px] flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={reviewSearch}
                    onChange={(event) => setReviewSearch(event.target.value)}
                    placeholder="Search guest, email, property, or draft..."
                    className="pl-9"
                  />
                </div>
                <Select value={reviewStatusFilter} onValueChange={setReviewStatusFilter}>
                  <SelectTrigger className="w-44">
                    <SelectValue placeholder="Queue status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="pending_review">Pending Review</SelectItem>
                    <SelectItem value="failed">Failed</SelectItem>
                    <SelectItem value="delivered">Delivered</SelectItem>
                    <SelectItem value="rejected">Rejected</SelectItem>
                    <SelectItem value="all">All Statuses</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={reviewChannelFilter} onValueChange={setReviewChannelFilter}>
                  <SelectTrigger className="w-40">
                    <SelectValue placeholder="Channel" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Channels</SelectItem>
                    <SelectItem value="email">Email</SelectItem>
                    <SelectItem value="sms">SMS</SelectItem>
                  </SelectContent>
                </Select>
              </div>
                <div className="flex flex-wrap gap-2 border-b p-4">
                  <Button
                    size="sm"
                    onClick={() => setPendingBulkAction({ kind: "approve", channel: "email" })}
                    disabled={selectedQueueIds.length === 0 || isBulkQueueActing}
                  >
                    {isBulkQueueActing ? "Working..." : "Approve Selected via Email"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPendingBulkAction({ kind: "approve", channel: "sms" })}
                    disabled={selectedQueueIds.length === 0 || isBulkQueueActing}
                  >
                    {isBulkQueueActing ? "Working..." : "Approve Selected via SMS"}
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => setPendingBulkAction({ kind: "reject" })}
                    disabled={selectedQueueIds.length === 0 || isBulkQueueActing}
                  >
                    {isBulkQueueActing ? "Working..." : "Reject Selected"}
                  </Button>
                </div>
              <ScrollArea className="h-[440px]">
                {queueQuery.isLoading ? (
                  <HunterDraftQueueSkeleton />
                ) : filteredQueueItems.length === 0 ? (
                  <div className="p-6 text-sm text-muted-foreground">
                    No Hunter drafts match the current queue filters.
                  </div>
                ) : (
                  <div className="space-y-3 p-4">
                    {filteredQueueItems.map((item) => (
                      <QueueEntryButton
                        key={item.id}
                        item={item}
                        selected={item.id === selectedQueueItem?.id}
                        onSelect={() => setSelectedQueueId(item.id)}
                        checked={selectedQueueIds.includes(item.id)}
                        onToggleChecked={(checked) =>
                          toggleSelection(selectedQueueIds, item.id, checked, setSelectedQueueIds)
                        }
                      />
                    ))}
                  </div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>

          <div className="space-y-6">
            <div className="grid gap-4 md:grid-cols-4">
              <Card className="border-amber-500/20 bg-amber-500/5">
                <CardHeader className="pb-2">
                  <CardDescription>Pending Review</CardDescription>
                  <CardTitle className="text-2xl">{queueStats?.pending_review ?? 0}</CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-emerald-500/20 bg-emerald-500/5">
                <CardHeader className="pb-2">
                  <CardDescription>Approved</CardDescription>
                  <CardTitle className="text-2xl">{queueStats?.approved ?? 0}</CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-sky-500/20 bg-sky-500/5">
                <CardHeader className="pb-2">
                  <CardDescription>Edited</CardDescription>
                  <CardTitle className="text-2xl">{queueStats?.edited ?? 0}</CardTitle>
                </CardHeader>
              </Card>
              <Card className="border-red-500/20 bg-red-500/5">
                <CardHeader className="pb-2">
                  <CardDescription>Rejected</CardDescription>
                  <CardTitle className="text-2xl">{queueStats?.rejected ?? 0}</CardTitle>
                </CardHeader>
              </Card>
            </div>

            <Card>
              <CardHeader className="border-b">
                <CardTitle>Delivery Telemetry</CardTitle>
                <CardDescription>
                  Recent Hunter outcomes across review, delivery, and failure states.
                </CardDescription>
              </CardHeader>
              <CardContent className="p-0">
                <div className="flex flex-wrap gap-3 border-b p-4">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Checkbox
                      checked={allFailedSelected}
                      onCheckedChange={(value) =>
                        setSelectedDeliveryIds(Boolean(value) ? failedDeliveryItems.map((item) => item.id) : [])
                      }
                    />
                    <span>{selectedDeliveryIds.length} selected</span>
                  </div>
                  <div className="relative w-full min-w-[220px] flex-1">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={telemetrySearch}
                      onChange={(event) => setTelemetrySearch(event.target.value)}
                      placeholder="Search guest, property, error, or draft..."
                      className="pl-9"
                    />
                  </div>
                  <Select value={telemetryStatusFilter} onValueChange={setTelemetryStatusFilter}>
                    <SelectTrigger className="w-40">
                      <SelectValue placeholder="Telemetry status" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Outcomes</SelectItem>
                      <SelectItem value="delivered">Delivered</SelectItem>
                      <SelectItem value="failed">Failed</SelectItem>
                      <SelectItem value="approved">Approved</SelectItem>
                      <SelectItem value="edited">Edited</SelectItem>
                      <SelectItem value="rejected">Rejected</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select value={telemetryChannelFilter} onValueChange={setTelemetryChannelFilter}>
                    <SelectTrigger className="w-40">
                      <SelectValue placeholder="Channel" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Channels</SelectItem>
                      <SelectItem value="email">Email</SelectItem>
                      <SelectItem value="sms">SMS</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-wrap gap-2 border-b p-4">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPendingBulkAction({ kind: "retry", channel: "email" })}
                    disabled={selectedDeliveryIds.length === 0 || isBulkRetrying}
                  >
                    {isBulkRetrying ? "Retrying..." : "Retry Selected Email"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setPendingBulkAction({ kind: "retry", channel: "sms" })}
                    disabled={selectedDeliveryIds.length === 0 || isBulkRetrying}
                  >
                    {isBulkRetrying ? "Retrying..." : "Retry Selected SMS"}
                  </Button>
                </div>
                {historyQuery.isLoading ? (
                  <HunterDraftQueueSkeleton />
                ) : deliveryItems.length === 0 ? (
                  <div className="p-6 text-sm text-muted-foreground">
                    No Hunter delivery history matches the current telemetry filters.
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12">
                          <Checkbox
                            checked={allFailedSelected}
                            onCheckedChange={(value) =>
                              setSelectedDeliveryIds(
                                Boolean(value) ? failedDeliveryItems.map((item) => item.id) : [],
                              )
                            }
                          />
                        </TableHead>
                        <TableHead>Guest</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Channel</TableHead>
                        <TableHead>Property</TableHead>
                        <TableHead>Updated</TableHead>
                        <TableHead>Signal</TableHead>
                        <TableHead className="text-right">Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {deliveryItems.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell>
                            <Checkbox
                              checked={selectedDeliveryIds.includes(item.id)}
                              disabled={item.status !== "failed"}
                              onCheckedChange={(value) =>
                                toggleSelection(
                                  selectedDeliveryIds,
                                  item.id,
                                  Boolean(value),
                                  setSelectedDeliveryIds,
                                )
                              }
                            />
                          </TableCell>
                          <TableCell className="min-w-[220px]">
                            <div className="space-y-1">
                              <div className="font-medium text-foreground">
                                {item.guest?.full_name || "Unknown guest"}
                              </div>
                              <div className="text-xs text-muted-foreground">
                                {item.guest?.email || "No email on file"}
                              </div>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className={queueTone(item.status)}>
                              {item.status.replace("_", " ").toUpperCase()}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            {item.delivery_channel ? item.delivery_channel.toUpperCase() : "UNKNOWN"}
                          </TableCell>
                          <TableCell>{item.property?.name || "Unresolved"}</TableCell>
                          <TableCell>{formatTimestamp(item.updated_at || item.created_at)}</TableCell>
                          <TableCell className="max-w-[340px]">
                            {item.status === "delivered" ? (
                              <div className="flex items-center gap-2 text-sm text-emerald-300">
                                <Send className="h-3.5 w-3.5" />
                                {item.delivery_channel === "sms"
                                  ? `Delivered via SMS${item.twilio_sid ? ` · ${item.twilio_sid}` : ""}`
                                  : "Delivered through SMTP"}
                              </div>
                            ) : item.error_log ? (
                              <div className="flex items-start gap-2 text-sm text-red-300">
                                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                                <span className="line-clamp-2">{item.error_log}</span>
                              </div>
                            ) : (
                              <span className="text-sm text-muted-foreground">
                                Awaiting next operator or delivery action
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            {item.status === "failed" ? (
                              <div className="flex justify-end gap-2">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => retryDraft.mutate({ entryId: item.id, channel: "email" })}
                                  disabled={
                                    retryDraft.isPending &&
                                    retryDraft.variables?.entryId === item.id
                                  }
                                >
                                  {retryDraft.isPending &&
                                  retryDraft.variables?.entryId === item.id &&
                                  retryDraft.variables?.channel === "email"
                                    ? "Retrying..."
                                    : "Retry Email"}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => retryDraft.mutate({ entryId: item.id, channel: "sms" })}
                                  disabled={
                                    retryDraft.isPending &&
                                    retryDraft.variables?.entryId === item.id
                                  }
                                >
                                  {retryDraft.isPending &&
                                  retryDraft.variables?.entryId === item.id &&
                                  retryDraft.variables?.channel === "sms"
                                    ? "Retrying..."
                                    : "Retry SMS"}
                                </Button>
                              </div>
                            ) : null}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="border-b">
                <CardTitle>
                  {selectedQueueItem?.guest?.full_name || "Select a queued draft"}
                </CardTitle>
                <CardDescription>
                  {selectedQueueItem?.property?.name || "No favorite property resolved"}
                  {selectedQueueItem?.guest?.email
                    ? ` · ${selectedQueueItem.guest.email}`
                    : ""}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline" className={queueTone(selectedQueueItem?.status || "")}>
                    {(selectedQueueItem?.status || "unselected").replace("_", " ").toUpperCase()}
                  </Badge>
                  {selectedQueueItem?.delivery_channel ? (
                    <Badge variant="outline">
                      Channel {selectedQueueItem.delivery_channel.toUpperCase()}
                    </Badge>
                  ) : null}
                  {selectedQueueItem?.guest?.loyalty_tier ? (
                    <Badge variant="outline">
                      Loyalty {selectedQueueItem.guest.loyalty_tier}
                    </Badge>
                  ) : null}
                  {selectedQueueItem?.guest?.lifetime_value ? (
                    <Badge variant="outline">
                      {formatCurrency(selectedQueueItem.guest.lifetime_value)}
                    </Badge>
                  ) : null}
                  {selectedQueueItem?.guest?.last_stay_date ? (
                    <Badge variant="outline">
                      Last stay {formatDate(selectedQueueItem.guest.last_stay_date)}
                    </Badge>
                  ) : null}
                </div>

                <Textarea
                  value={draftBody}
                  onChange={(event) =>
                    setDraftState({
                      id: selectedQueueItem?.id,
                      body: event.target.value,
                    })
                  }
                  className="min-h-52 font-mono text-sm"
                  placeholder="Select a Hunter draft to review or edit it."
                  disabled={!selectedQueueItem}
                />

                {selectedQueueItem?.error_log ? (
                  <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-sm text-red-200">
                    {selectedQueueItem.error_log}
                  </div>
                ) : null}

                <div className="flex flex-wrap gap-3">
                  <Button
                    onClick={() =>
                      selectedQueueItem &&
                      approveDraft.mutate({ entryId: selectedQueueItem.id, channel: "email" })
                    }
                    disabled={
                      !selectedQueueItem ||
                      selectedQueueItem.status !== "pending_review" ||
                      approveDraft.isPending ||
                      editDraft.isPending ||
                      rejectDraft.isPending
                    }
                  >
                    Approve via Email
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      selectedQueueItem &&
                      approveDraft.mutate({ entryId: selectedQueueItem.id, channel: "sms" })
                    }
                    disabled={
                      !selectedQueueItem ||
                      selectedQueueItem.status !== "pending_review" ||
                      approveDraft.isPending ||
                      editDraft.isPending ||
                      rejectDraft.isPending
                    }
                  >
                    Approve via SMS
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      selectedQueueItem &&
                      editDraft.mutate({
                        entryId: selectedQueueItem.id,
                        finalMessage: draftBody,
                        channel: "email",
                      })
                    }
                    disabled={
                      !selectedQueueItem ||
                      selectedQueueItem.status !== "pending_review" ||
                      !draftBody.trim() ||
                      approveDraft.isPending ||
                      editDraft.isPending ||
                      rejectDraft.isPending
                    }
                  >
                    Save Edit + Email
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() =>
                      selectedQueueItem &&
                      editDraft.mutate({
                        entryId: selectedQueueItem.id,
                        finalMessage: draftBody,
                        channel: "sms",
                      })
                    }
                    disabled={
                      !selectedQueueItem ||
                      selectedQueueItem.status !== "pending_review" ||
                      !draftBody.trim() ||
                      approveDraft.isPending ||
                      editDraft.isPending ||
                      rejectDraft.isPending
                    }
                  >
                    Save Edit + SMS
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() =>
                      selectedQueueItem &&
                      rejectDraft.mutate({
                        entryId: selectedQueueItem.id,
                        reason: "Operator rejected Hunter outreach draft.",
                      })
                    }
                    disabled={
                      !selectedQueueItem ||
                      selectedQueueItem.status !== "pending_review" ||
                      approveDraft.isPending ||
                      editDraft.isPending ||
                      rejectDraft.isPending
                    }
                  >
                    Reject
                  </Button>
                </div>

                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">Lifetime value ≥ $5,000</Badge>
                  <Badge variant="outline">Dormant for 365+ days</Badge>
                  <Badge variant="outline">Not blacklisted</Badge>
                  <Badge variant="outline">Not do-not-contact</Badge>
                  <Badge variant="outline">Email required</Badge>
                  <Badge variant="outline">30s live refresh</Badge>
                  <Badge variant="outline">Average score {metrics.averageScore}</Badge>
                </div>
              </CardContent>
            </Card>
          </div>
        </CardContent>
      </Card>

      <AlertDialog
        open={Boolean(pendingBulkAction)}
        onOpenChange={(open: boolean) => {
          if (!open) setPendingBulkAction(null);
        }}
      >
        <AlertDialogContent className={bulkActionConfig?.variant === "destructive" ? "border-red-500/50" : undefined}>
          <AlertDialogHeader>
            <AlertDialogTitle>{bulkActionConfig?.title || "Confirm Bulk Action"}</AlertDialogTitle>
            <AlertDialogDescription>
              {bulkActionConfig?.description ||
                "Confirm the selected bulk operation before execution."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant={bulkActionConfig?.variant === "destructive" ? "destructive" : "default"}
              onClick={() => void confirmBulkAction()}
            >
              {bulkActionConfig?.confirmLabel || "Confirm"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
