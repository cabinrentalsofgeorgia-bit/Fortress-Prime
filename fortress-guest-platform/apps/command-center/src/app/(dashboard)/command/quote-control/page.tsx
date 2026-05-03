"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  CreditCard,
  LockKeyhole,
  PauseCircle,
  RefreshCw,
  ShieldCheck,
  Siren,
  StickyNote,
  Timer,
  UserCheck,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  useQuoteBookingControlAction,
  useQuoteBookingControlTower,
  type QuoteBookingRecord,
  type QuoteBookingSafeguard,
} from "@/lib/hooks";

type KindFilter = "all" | QuoteBookingRecord["kind"];
type StopFilter = "all" | QuoteBookingRecord["stop_level"];
type SafeAction = "claim" | "mark_reviewed" | "escalate" | "dismiss" | "note";
type ActionTarget = {
  record: QuoteBookingRecord;
  action: SafeAction;
};

const KIND_FILTERS: { id: KindFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "quote", label: "Quotes" },
  { id: "hold", label: "Holds" },
  { id: "reservation", label: "Reservations" },
  { id: "parity", label: "Parity" },
];

const STOP_FILTERS: { id: StopFilter; label: string }[] = [
  { id: "all", label: "All Gates" },
  { id: "stop", label: "Stops" },
  { id: "inspect", label: "Inspect" },
  { id: "clear", label: "Clear" },
];

const KIND_ICONS = {
  quote: ClipboardCheck,
  hold: Timer,
  reservation: CheckCircle2,
  parity: ShieldCheck,
} satisfies Record<QuoteBookingRecord["kind"], typeof ClipboardCheck>;

function formatMoney(value: number | null | undefined): string {
  if (value == null) return "--";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10);
  return parsed.toLocaleDateString();
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function metric(summary: Record<string, number> | undefined, key: string): number {
  return summary?.[key] ?? 0;
}

function stopTone(level: QuoteBookingRecord["stop_level"]): string {
  switch (level) {
    case "clear":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "inspect":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "stop":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
  }
}

function safeguardTone(status: QuoteBookingSafeguard["status"]): string {
  switch (status) {
    case "clear":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "locked":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "attention":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  }
}

function kindLabel(kind: QuoteBookingRecord["kind"]): string {
  switch (kind) {
    case "quote":
      return "Quote";
    case "hold":
      return "Hold";
    case "reservation":
      return "Reservation";
    case "parity":
      return "Parity";
  }
}

function actionLabel(action: SafeAction): string {
  switch (action) {
    case "claim":
      return "Claim";
    case "mark_reviewed":
      return "Reviewed";
    case "escalate":
      return "Escalate";
    case "dismiss":
      return "Dismiss";
    case "note":
      return "Note";
  }
}

function SummaryMetric({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: number;
  detail: string;
  tone?: "default" | "warning" | "danger" | "success";
}) {
  const toneClass =
    tone === "danger"
      ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
      : tone === "warning"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
        : tone === "success"
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
          : "border-zinc-800 bg-zinc-900/70 text-zinc-100";

  return (
    <div className={`rounded-lg border px-4 py-4 ${toneClass}`}>
      <p className="text-xs uppercase text-current/70">{label}</p>
      <p className="mt-2 text-3xl font-semibold">{value.toLocaleString()}</p>
      <p className="mt-1 text-xs text-current/70">{detail}</p>
    </div>
  );
}

function SafeguardRow({ safeguard }: { safeguard: QuoteBookingSafeguard }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-4 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <LockKeyhole className="h-4 w-4 text-cyan-200" />
          <p className="font-medium text-zinc-50">{safeguard.label}</p>
          <Badge className={safeguardTone(safeguard.status)}>{safeguard.status}</Badge>
        </div>
        <p className="mt-2 text-sm text-zinc-400">{safeguard.detail}</p>
      </div>
      {safeguard.href ? (
        <Button
          asChild
          variant="outline"
          size="sm"
          className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
        >
          <Link href={safeguard.href}>
            Inspect
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      ) : null}
    </div>
  );
}

function RecordRow({
  record,
  onAction,
  isActionPending,
}: {
  record: QuoteBookingRecord;
  onAction: (record: QuoteBookingRecord, action: SafeAction) => void;
  isActionPending: boolean;
}) {
  const Icon = KIND_ICONS[record.kind];

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Icon className="h-4 w-4 text-cyan-200" />
            <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{kindLabel(record.kind)}</Badge>
            <Badge className={stopTone(record.stop_level)}>{record.stop_level}</Badge>
            <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">{record.status}</Badge>
            {record.assigned_to ? (
              <Badge className="border-cyan-500/30 bg-cyan-500/10 text-cyan-100">
                assigned
              </Badge>
            ) : null}
            {record.escalated ? (
              <Badge className="border-amber-500/30 bg-amber-500/10 text-amber-200">
                escalated
              </Badge>
            ) : null}
            {record.reviewed ? (
              <Badge className="border-emerald-500/30 bg-emerald-500/10 text-emerald-200">
                reviewed
              </Badge>
            ) : null}
            {record.dismissed ? (
              <Badge className="border-zinc-700 bg-zinc-950 text-zinc-300">dismissed</Badge>
            ) : null}
          </div>
          <div>
            <p className="break-words text-base font-semibold text-zinc-50">{record.title}</p>
            <p className="mt-1 text-sm text-zinc-400">{record.stop_reason}</p>
          </div>
          <div className="grid gap-2 text-sm text-zinc-300 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <p className="text-xs uppercase text-zinc-500">Property</p>
              <p className="truncate">{record.property_name || "--"}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-zinc-500">Guest</p>
              <p className="truncate">{record.guest_label || "--"}</p>
            </div>
            <div>
              <p className="text-xs uppercase text-zinc-500">Stay</p>
              <p>
                {formatDate(record.check_in)} to {formatDate(record.check_out)}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase text-zinc-500">Total</p>
              <p>{formatMoney(record.total_amount)}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-xs text-zinc-400">
            {record.payment_state ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <CreditCard className="h-3.5 w-3.5" />
                {record.payment_state}
              </span>
            ) : null}
            {record.parity_status ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                {record.parity_status}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
              <Timer className="h-3.5 w-3.5" />
              {formatTimestamp(record.created_at)}
            </span>
            {record.assigned_to ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <UserCheck className="h-3.5 w-3.5" />
                {record.assigned_to}
              </span>
            ) : null}
            {record.last_action ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-zinc-800 px-2 py-1">
                <ShieldCheck className="h-3.5 w-3.5" />
                {record.last_action} by {record.last_action_by || "staff"}
              </span>
            ) : null}
          </div>
          {record.last_note ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2 text-sm text-zinc-300">
              <span className="text-xs uppercase text-zinc-500">Latest note</span>
              <p className="mt-1">{record.last_note}</p>
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2 lg:justify-end">
          <Button
            onClick={() => onAction(record, "claim")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-cyan-500/40 bg-cyan-950/20 text-cyan-100 hover:bg-cyan-950/40"
          >
            Claim
            <UserCheck className="ml-2 h-4 w-4" />
          </Button>
          <Button
            onClick={() => onAction(record, "mark_reviewed")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-emerald-500/40 bg-emerald-950/20 text-emerald-100 hover:bg-emerald-950/40"
          >
            Reviewed
            <CheckCircle2 className="ml-2 h-4 w-4" />
          </Button>
          <Button
            onClick={() => onAction(record, "note")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            Note
            <StickyNote className="ml-2 h-4 w-4" />
          </Button>
          <Button
            asChild
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            <Link href={record.href}>
              Inspect
              <ArrowRight className="ml-2 h-4 w-4" />
            </Link>
          </Button>
          {record.stop_level !== "clear" ? (
            <Button
              onClick={() => onAction(record, "escalate")}
              disabled={isActionPending}
              variant="outline"
              size="sm"
              className="border-amber-500/40 bg-amber-950/20 text-amber-100 hover:bg-amber-950/40"
            >
              Escalate
              <AlertTriangle className="ml-2 h-4 w-4" />
            </Button>
          ) : null}
          <Button
            onClick={() => onAction(record, "dismiss")}
            disabled={isActionPending}
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            Dismiss
            <XCircle className="ml-2 h-4 w-4" />
          </Button>
        </div>
        </div>
      </div>
  );
}

export default function QuoteControlPage() {
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [stopFilter, setStopFilter] = useState<StopFilter>("all");
  const [actionTarget, setActionTarget] = useState<ActionTarget | null>(null);
  const [actionNote, setActionNote] = useState("");
  const { data, isLoading, error, refetch, isFetching } = useQuoteBookingControlTower(25);
  const actionMutation = useQuoteBookingControlAction();

  const allRecords = useMemo(
    () => [
      ...(data?.quotes ?? []),
      ...(data?.holds ?? []),
      ...(data?.reservations ?? []),
      ...(data?.parity_audits ?? []),
    ],
    [data],
  );

  const visibleRecords = allRecords.filter((record) => {
    const kindMatches = kindFilter === "all" || record.kind === kindFilter;
    const stopMatches = stopFilter === "all" || record.stop_level === stopFilter;
    return kindMatches && stopMatches;
  });

  if (isLoading && !data) {
    return (
      <div className="space-y-6">
        <div>
          <Button
            asChild
            variant="outline"
            className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
          >
            <Link href="/command">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Command
            </Link>
          </Button>
        </div>
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="flex items-center gap-3 pt-6 text-sm text-zinc-400">
            <RefreshCw className="h-4 w-4 animate-spin" />
            Loading quote-to-booking posture from local ledgers...
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="space-y-6">
        <Button
          asChild
          variant="outline"
          className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
        >
          <Link href="/command">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Command
          </Link>
        </Button>
        <Card className="border-rose-500/30 bg-rose-950/10">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-rose-100">
              <Siren className="h-5 w-5" />
              Control Tower Unavailable
            </CardTitle>
            <CardDescription className="text-rose-200/80">
              The quote-to-booking aggregate endpoint did not respond.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-rose-100">
            {error instanceof Error ? error.message : "Unknown error"}
          </CardContent>
        </Card>
      </div>
    );
  }

  const summary = data?.summary;
  const openAction = (record: QuoteBookingRecord, action: SafeAction) => {
    setActionTarget({ record, action });
    setActionNote("");
  };
  const submitAction = () => {
    if (!actionTarget) return;
    actionMutation.mutate(
      {
        kind: actionTarget.record.kind,
        id: actionTarget.record.id,
        action: actionTarget.action,
        note: actionNote.trim() || undefined,
      },
      {
        onSuccess: () => {
          setActionTarget(null);
          setActionNote("");
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <Button
          asChild
          variant="outline"
          className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
        >
          <Link href="/command">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Command
          </Link>
        </Button>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase text-cyan-100">
              <PauseCircle className="h-3.5 w-3.5" />
              Read-only control surface
            </div>
            <h1 className="mt-3 text-3xl font-semibold text-zinc-50">Quote-to-Booking Control Tower</h1>
            <p className="mt-2 max-w-4xl text-sm text-zinc-400">
              Internal visibility across guest quotes, checkout holds, Stripe handoff state,
              reservation conversion, and Streamline parity. Risky actions stay behind the
              existing approval workflows.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => refetch()}
              disabled={isFetching}
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/vrs/quotes">
                Quote Tools
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
            >
              <Link href="/command/checkout-parity">
                Parity Console
                <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-5">
        <SummaryMetric
          label="Pending Quotes"
          value={metric(summary, "pending_quotes")}
          detail="Awaiting staff or guest action"
          tone={metric(summary, "pending_quotes") > 0 ? "warning" : "success"}
        />
        <SummaryMetric
          label="Active Holds"
          value={metric(summary, "active_holds")}
          detail="Checkout locks currently active"
          tone={metric(summary, "active_holds") > 0 ? "warning" : "default"}
        />
        <SummaryMetric
          label="Converted Holds"
          value={metric(summary, "converted_holds_24h")}
          detail="Converted in the last 24 hours"
          tone="success"
        />
        <SummaryMetric
          label="Parity Drifts"
          value={metric(summary, "parity_drifts_24h")}
          detail="Streamline mismatch in last 24 hours"
          tone={metric(summary, "parity_drifts_24h") > 0 ? "danger" : "success"}
        />
        <SummaryMetric
          label="Hard Stops"
          value={metric(summary, "hard_stops")}
          detail={`${metric(summary, "inspection_items").toLocaleString()} more need inspection`}
          tone={metric(summary, "hard_stops") > 0 ? "danger" : "success"}
        />
      </div>

      <Card className="border-cyan-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <LockKeyhole className="h-5 w-5 text-cyan-300" />
            Safeguards
          </CardTitle>
          <CardDescription>
            These locks keep this build internal, inspectable, and human-approved.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-6">
          {(data?.safeguards ?? []).map((safeguard) => (
            <SafeguardRow key={safeguard.id} safeguard={safeguard} />
          ))}
        </CardContent>
      </Card>

      <Card className="border-emerald-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <ShieldCheck className="h-5 w-5 text-emerald-300" />
            Conversion Flow
          </CardTitle>
          <CardDescription>
            Quote approval to hold, payment, reservation, and Streamline parity in one view.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap gap-2">
            {KIND_FILTERS.map((filter) => (
              <Button
                key={filter.id}
                onClick={() => setKindFilter(filter.id)}
                size="sm"
                variant={kindFilter === filter.id ? "default" : "outline"}
                className={
                  kindFilter === filter.id
                    ? "bg-emerald-700 text-white hover:bg-emerald-600"
                    : "border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
                }
              >
                {filter.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {STOP_FILTERS.map((filter) => (
              <Button
                key={filter.id}
                onClick={() => setStopFilter(filter.id)}
                size="sm"
                variant={stopFilter === filter.id ? "default" : "outline"}
                className={
                  stopFilter === filter.id
                    ? "bg-cyan-700 text-white hover:bg-cyan-600"
                    : "border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
                }
              >
                {filter.label}
              </Button>
            ))}
          </div>

          {visibleRecords.length === 0 ? (
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-4 py-8 text-center text-sm text-zinc-400">
              No records match this filter.
            </div>
          ) : (
            <div className="space-y-3">
              {visibleRecords.map((record) => (
                <RecordRow
                  key={`${record.kind}-${record.id}`}
                  record={record}
                  onAction={openAction}
                  isActionPending={actionMutation.isPending}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={Boolean(actionTarget)} onOpenChange={(open) => !open && setActionTarget(null)}>
        <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-50">
          <DialogHeader>
            <DialogTitle>
              {actionTarget ? actionLabel(actionTarget.action) : "Control Action"}
            </DialogTitle>
            <DialogDescription>
              {actionTarget?.record.title || "Control Tower item"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-cyan-500/20 bg-cyan-950/20 px-3 py-3 text-sm text-cyan-100">
              Audit-only action. Source quote, booking, payment, public content, and Streamline records stay unchanged.
            </div>
            <Textarea
              value={actionNote}
              onChange={(event) => setActionNote(event.target.value)}
              placeholder="Internal note"
              className="min-h-28 border-zinc-700 bg-zinc-950 text-zinc-100"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => setActionTarget(null)}
            >
              Cancel
            </Button>
            <Button
              onClick={submitAction}
              disabled={actionMutation.isPending || (actionTarget?.action === "note" && !actionNote.trim())}
              className="bg-cyan-700 text-white hover:bg-cyan-600"
            >
              {actionMutation.isPending ? "Recording..." : "Record Action"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
