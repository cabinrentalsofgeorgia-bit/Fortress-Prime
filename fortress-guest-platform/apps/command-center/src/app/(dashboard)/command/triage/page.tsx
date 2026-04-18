"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BookOpen,
  Calendar,
  CheckCircle2,
  CreditCard,
  Loader2,
  Mail,
  Scale,
  Shield,
  User,
} from "lucide-react";

import {
  usePendingApprovals,
  useExecuteApproval,
  type PendingApproval,
} from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Badge } from "@/components/ui/badge";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}$${(abs / 100).toFixed(2)}`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

function deltaTone(deltaCents: number): string {
  const abs = Math.abs(deltaCents);
  if (abs >= 5000) return "border-rose-500/40 bg-rose-950/30 text-rose-100";
  if (abs >= 1000) return "border-amber-500/40 bg-amber-950/30 text-amber-100";
  return "border-yellow-500/40 bg-yellow-950/30 text-yellow-100";
}

function deltaIcon(deltaCents: number) {
  return deltaCents > 0 ? (
    <ArrowUpRight className="h-5 w-5 text-rose-400" />
  ) : (
    <ArrowDownRight className="h-5 w-5 text-emerald-400" />
  );
}

// ---------------------------------------------------------------------------
// Diff line-item types
// ---------------------------------------------------------------------------

interface DiffLineItem {
  label: string;
  local_cents: number | null;
  streamline_cents: number | null;
  delta_cents: number;
  status: "match" | "added" | "removed" | "changed";
}

function parseDiffFromPayload(payload: Record<string, unknown>): DiffLineItem[] {
  const diff = payload.diff as DiffLineItem[] | undefined;
  if (Array.isArray(diff) && diff.length > 0) return diff;

  const autoRes = payload.auto_resolution as Record<string, unknown> | undefined;
  if (autoRes) {
    const innerDiff = autoRes.diff as DiffLineItem[] | undefined;
    if (Array.isArray(innerDiff) && innerDiff.length > 0) return innerDiff;
  }

  const items: DiffLineItem[] = [];
  const localBreakdown = payload.local_breakdown as Record<string, number> | undefined;
  const streamlineBreakdown = payload.streamline_breakdown as Record<string, number> | undefined;

  if (localBreakdown || streamlineBreakdown) {
    const keys = new Set([
      ...Object.keys(localBreakdown || {}),
      ...Object.keys(streamlineBreakdown || {}),
    ]);
    for (const key of keys) {
      const local = localBreakdown?.[key] ?? null;
      const slTotal = streamlineBreakdown?.[key] ?? null;
      const d = (slTotal ?? 0) - (local ?? 0);
      let status: DiffLineItem["status"] = "match";
      if (local === null) status = "added";
      else if (slTotal === null) status = "removed";
      else if (d !== 0) status = "changed";
      items.push({ label: key, local_cents: local, streamline_cents: slTotal, delta_cents: d, status });
    }
    return items;
  }

  return [];
}

// ---------------------------------------------------------------------------
// Diff Visualizer
// ---------------------------------------------------------------------------

function DiffVisualizer({ items }: { items: DiffLineItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-700 bg-zinc-900/50 px-4 py-6 text-center text-sm text-zinc-500">
        No structured diff available in context_payload.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-700/60">
      <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-1 bg-zinc-900/80 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.3em] text-zinc-500">
        <span>Line Item</span>
        <span className="w-28 text-right">Local</span>
        <span className="w-28 text-right">Streamline</span>
        <span className="w-24 text-right">Delta</span>
      </div>
      {items.map((item, idx) => {
        const isAnomaly = item.status === "added" || item.status === "changed";
        const rowBg = isAnomaly
          ? "bg-amber-500/[0.06]"
          : idx % 2 === 0
            ? "bg-zinc-900/40"
            : "bg-zinc-900/20";
        const leftBorder = isAnomaly ? "border-l-2 border-l-amber-500" : "border-l-2 border-l-transparent";

        return (
          <div
            key={`${item.label}-${idx}`}
            className={`grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-1 px-4 py-2.5 ${rowBg} ${leftBorder}`}
          >
            <div className="flex items-center gap-2">
              <span className="text-sm text-zinc-200">{item.label}</span>
              {item.status === "added" && (
                <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
                  new
                </span>
              )}
              {item.status === "removed" && (
                <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-rose-300">
                  missing
                </span>
              )}
            </div>
            <span className="w-28 text-right font-mono text-sm text-zinc-300">
              {item.local_cents !== null ? formatCents(item.local_cents) : "--"}
            </span>
            <span
              className={`w-28 text-right font-mono text-sm ${
                isAnomaly ? "font-semibold text-amber-200" : "text-zinc-300"
              }`}
            >
              {item.streamline_cents !== null ? formatCents(item.streamline_cents) : "--"}
            </span>
            <span
              className={`w-24 text-right font-mono text-sm ${
                item.delta_cents === 0
                  ? "text-zinc-500"
                  : item.delta_cents > 0
                    ? "text-rose-400"
                    : "text-emerald-400"
              }`}
            >
              {item.delta_cents === 0 ? "--" : formatCents(item.delta_cents)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Triage Card
// ---------------------------------------------------------------------------

function TriageCard({
  approval,
  onExecute,
  executingId,
}: {
  approval: PendingApproval;
  onExecute: (id: string, strategy: "absorb" | "invoice") => void;
  executingId: string | null;
}) {
  const res = approval.reservation;
  const diffItems = parseDiffFromPayload(approval.context_payload);
  const isExecuting = executingId === approval.id;
  const absDelta = Math.abs(approval.delta_cents);

  return (
    <Card className={`transition-all duration-300 ${deltaTone(approval.delta_cents)} bg-zinc-950/90`}>
      {/* --- Header --- */}
      <CardHeader className="border-b border-zinc-800/60 pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-lg text-zinc-50">
                {res?.confirmation_code || approval.reservation_id}
              </CardTitle>
              <Badge
                className="border-amber-500/30 bg-amber-500/10 text-amber-200"
                variant="outline"
              >
                {approval.discrepancy_type.replaceAll("_", " ")}
              </Badge>
            </div>
            <CardDescription className="flex flex-wrap items-center gap-3 text-zinc-400">
              {res?.guest_name && (
                <span className="inline-flex items-center gap-1">
                  <User className="h-3.5 w-3.5" />
                  {res.guest_name}
                </span>
              )}
              {res?.check_in && res?.check_out && (
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {formatDate(res.check_in)} &ndash; {formatDate(res.check_out)}
                </span>
              )}
              <span className="inline-flex items-center gap-1 text-xs text-zinc-500">
                Detected {formatTimestamp(approval.created_at)}
              </span>
            </CardDescription>
          </div>

          {/* Delta callout */}
          <div className="flex items-center gap-2 rounded-xl border border-zinc-700/50 bg-zinc-900/70 px-4 py-2.5">
            {deltaIcon(approval.delta_cents)}
            <div className="text-right">
              <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-zinc-500">
                Discrepancy
              </p>
              <p className="text-xl font-bold tabular-nums tracking-tight text-zinc-50">
                {formatCents(absDelta)}
              </p>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-5 pt-5">
        {/* --- Side-by-side totals --- */}
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-zinc-500">
              Local Ledger
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-zinc-100">
              {formatCents(approval.local_total_cents)}
            </p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-zinc-500">
              Streamline Folio
            </p>
            <p className="mt-1 text-lg font-semibold tabular-nums text-zinc-100">
              {formatCents(approval.streamline_total_cents)}
            </p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.3em] text-zinc-500">
              Source
            </p>
            <p className="mt-1 text-sm font-medium text-zinc-300">
              {res?.booking_source || "unknown"}
            </p>
          </div>
        </div>

        {/* --- Diff table --- */}
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.3em] text-zinc-500">
            Line-Item Diff — Local vs Streamline
          </p>
          <DiffVisualizer items={diffItems} />
        </div>

        {/* --- Action bar --- */}
        <div className="flex flex-wrap items-center gap-3 border-t border-zinc-800/60 pt-4">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  disabled={isExecuting}
                  onClick={() => onExecute(approval.id, "absorb")}
                  className="border-zinc-600 bg-zinc-900 text-zinc-200 hover:border-zinc-500 hover:bg-zinc-800 disabled:opacity-50"
                >
                  {isExecuting && executingId === approval.id ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Scale className="mr-2 h-4 w-4" />
                  )}
                  Absorb Variance
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Balance books internally. Guest is not charged.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  disabled={isExecuting}
                  onClick={() => onExecute(approval.id, "invoice")}
                  className="bg-[#635BFF] text-white shadow-lg shadow-[#635BFF]/20 hover:bg-[#7A73FF] disabled:opacity-50"
                >
                  {isExecuting && executingId === approval.id ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <CreditCard className="mr-2 h-4 w-4" />
                  )}
                  Issue Stripe Invoice
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                Bill guest for the difference via Stripe.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          {res?.guest_email && (
            <span className="ml-auto flex items-center gap-1.5 text-xs text-zinc-500">
              <Mail className="h-3.5 w-3.5" />
              {res.guest_email}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function NemoTriagePage() {
  const { data: approvals, isLoading, error } = usePendingApprovals();
  const executeApproval = useExecuteApproval();
  const [executingId, setExecutingId] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  function handleExecute(id: string, strategy: "absorb" | "invoice") {
    setExecutingId(id);
    executeApproval.mutate(
      { approvalId: id, strategy },
      {
        onSettled: () => setExecutingId(null),
        onSuccess: () => {
          setDismissed((prev) => new Set(prev).add(id));
        },
      },
    );
  }

  const visible = (approvals || []).filter((a) => !dismissed.has(a.id));

  return (
    <div className="space-y-6">
      {/* --- Page Header --- */}
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-amber-200">
          <Shield className="h-3.5 w-3.5" />
          NeMo Triage
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">
              Financial Approval Queue
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-zinc-400">
              Pending parity discrepancies between the sovereign ledger and Streamline.
              Review the diff, then absorb internally or invoice the guest.
            </p>
          </div>
          {visible.length > 0 && (
            <div className="flex items-center gap-2 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              <span className="text-sm font-medium text-zinc-200">
                {visible.length} pending
              </span>
            </div>
          )}
        </div>
      </div>

      {/* --- Loading --- */}
      {isLoading && !approvals && (
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="flex items-center gap-3 pt-6 text-sm text-zinc-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading pending approvals from the sovereign queue...
          </CardContent>
        </Card>
      )}

      {/* --- Error --- */}
      {error && (
        <Card className="border-rose-500/20 bg-zinc-950/90">
          <CardContent className="pt-6 text-sm text-rose-300">
            {error instanceof Error ? error.message : "Failed to load financial approvals."}
          </CardContent>
        </Card>
      )}

      {/* --- Empty state --- */}
      {!isLoading && !error && visible.length === 0 && (
        <Card className="border-emerald-500/20 bg-zinc-950/90">
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <CheckCircle2 className="h-10 w-10 text-emerald-400" />
            <p className="text-lg font-medium text-zinc-200">Queue Clear</p>
            <p className="max-w-md text-sm text-zinc-400">
              No pending parity discrepancies. The sovereign ledger and Streamline
              are in harmony.
            </p>
          </CardContent>
        </Card>
      )}

      {/* --- Triage Card Stack --- */}
      <div className="space-y-4">
        {visible.map((approval) => (
          <TriageCard
            key={approval.id}
            approval={approval}
            onExecute={handleExecute}
            executingId={executingId}
          />
        ))}
      </div>
    </div>
  );
}
