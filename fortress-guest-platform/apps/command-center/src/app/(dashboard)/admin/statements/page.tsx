"use client";

import { useState } from "react";
import {
  useAdminStatements,
  useApproveStatement,
  useVoidStatement,
  useMarkStatementEmailed,
  usePayOwner,
  useGenerateStatements,
} from "@/lib/hooks";
import { toast } from "sonner";
import type {
  OwnerBalancePeriod,
  StatementListFilters,
  GenerateStatementsResult,
  StatementPeriodStatus,
} from "@/lib/types";
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  CheckCircle2,
  ChevronRight,
  CreditCard,
  Download,
  Eye,
  FileText,
  Loader2,
  Mail,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function fmtCurrency(s: string | null | undefined): string {
  if (!s) return "—";
  const n = parseFloat(s);
  if (isNaN(n)) return s;
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

const STATUS_LABELS: Record<StatementPeriodStatus, string> = {
  draft: "Draft",
  pending_approval: "Pending Approval",
  approved: "Approved",
  paid: "Paid",
  emailed: "Emailed",
  voided: "Voided",
};

const STATUS_CLASSES: Record<StatementPeriodStatus, string> = {
  draft:            "bg-slate-500/10 text-slate-500 border border-slate-500/30",
  pending_approval: "bg-amber-500/10 text-amber-600 border border-amber-500/30",
  approved:         "bg-emerald-500/10 text-emerald-600 border border-emerald-500/30",
  paid:             "bg-blue-500/10 text-blue-600 border border-blue-500/30",
  emailed:          "bg-teal-500/10 text-teal-600 border border-teal-500/30",
  voided:           "bg-red-500/10 text-red-500 border border-red-500/30",
};

function StatusBadge({ status }: { status: StatementPeriodStatus }) {
  return (
    <Badge className={cn("text-xs", STATUS_CLASSES[status])}>
      {STATUS_LABELS[status]}
    </Badge>
  );
}

// ── Generate Statements Modal ─────────────────────────────────────────────────

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function firstOfMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function lastOfMonth(): string {
  const d = new Date();
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return last.toISOString().slice(0, 10);
}

interface GenerateModalProps {
  open: boolean;
  onClose: () => void;
}

function GenerateModal({ open, onClose }: GenerateModalProps) {
  const [periodStart, setPeriodStart] = useState(firstOfMonth());
  const [periodEnd, setPeriodEnd] = useState(lastOfMonth());
  const [preview, setPreview] = useState<GenerateStatementsResult | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const generate = useGenerateStatements();

  function handleReset() {
    setPreview(null);
    setShowPreview(false);
  }

  async function handlePreview() {
    const result = await generate.mutateAsync({
      period_start: periodStart,
      period_end: periodEnd,
      dry_run: true,
    });
    setPreview(result);
    setShowPreview(true);
  }

  async function handleConfirm() {
    await generate.mutateAsync({
      period_start: periodStart,
      period_end: periodEnd,
      dry_run: false,
    });
    handleReset();
    onClose();
  }

  function handleClose() {
    handleReset();
    onClose();
  }

  const canPreview = periodStart && periodEnd && periodEnd >= periodStart;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" />
            Generate Owner Statements
          </DialogTitle>
        </DialogHeader>

        {!showPreview ? (
          <div className="space-y-4 pt-2">
            <p className="text-sm text-muted-foreground">
              Generate draft statements for all enrolled owners covering a period.
              Finalized statements (approved/paid/emailed/voided) are never overwritten.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Period start</Label>
                <Input
                  type="date"
                  value={periodStart}
                  onChange={(e) => setPeriodStart(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Period end</Label>
                <Input
                  type="date"
                  value={periodEnd}
                  onChange={(e) => setPeriodEnd(e.target.value)}
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" size="sm" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={!canPreview || generate.isPending}
                onClick={handlePreview}
              >
                {generate.isPending ? (
                  <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Previewing…</>
                ) : (
                  <>Preview</>
                )}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 pt-2">
            {preview && (
              <>
                <div className="rounded-md border p-4 space-y-2 bg-muted/30">
                  <p className="text-sm font-medium">Preview results</p>
                  <p className="text-sm text-muted-foreground">
                    Period: <span className="font-medium text-foreground">{fmtDate(preview.period_start)} → {fmtDate(preview.period_end)}</span>
                  </p>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div className="text-center">
                      <div className="text-lg font-bold text-emerald-600">{preview.total_drafts_created}</div>
                      <div className="text-muted-foreground">Would create</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-muted-foreground">{preview.total_skipped}</div>
                      <div className="text-muted-foreground">Would skip</div>
                    </div>
                    <div className="text-center">
                      <div className="text-lg font-bold text-red-500">{preview.total_errors}</div>
                      <div className="text-muted-foreground">Errors</div>
                    </div>
                  </div>
                  {preview.results.filter((r) => r.outcome === "error").map((r, i) => (
                    <p key={i} className="text-xs text-red-600">
                      Error: OPA #{r.owner_payout_account_id} — {r.reason}
                    </p>
                  ))}
                </div>

                {preview.total_drafts_created === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-2">
                    No new statements to create for this period.
                  </p>
                )}

                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="outline" size="sm" onClick={() => setShowPreview(false)}>
                    Back
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleClose}>
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    disabled={preview.total_drafts_created === 0 || generate.isPending}
                    onClick={handleConfirm}
                  >
                    {generate.isPending ? (
                      <><Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> Generating…</>
                    ) : (
                      <>Confirm &amp; Generate {preview.total_drafts_created} Draft{preview.total_drafts_created !== 1 ? "s" : ""}</>
                    )}
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ── Approve Dialog ────────────────────────────────────────────────────────────

interface ApproveDialogProps { period: OwnerBalancePeriod | null; onClose: () => void; }

function ApproveDialog({ period, onClose }: ApproveDialogProps) {
  const approve = useApproveStatement();
  if (!period) return null;
  return (
    <Dialog open={!!period} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            Approve Statement
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
            <div><span className="text-muted-foreground">OPA:</span> #{period.owner_payout_account_id}</div>
            <div><span className="text-muted-foreground">Period:</span> {fmtDate(period.period_start)} → {fmtDate(period.period_end)}</div>
            <div><span className="text-muted-foreground">Opening:</span> {fmtCurrency(period.opening_balance)} → Closing: {fmtCurrency(period.closing_balance)}</div>
          </div>
          <p className="text-sm text-muted-foreground">
            Approving confirms the statement is accurate. This transitions the statement from{" "}
            <span className="font-medium text-amber-600">Pending Approval</span> to{" "}
            <span className="font-medium text-emerald-600">Approved</span>.
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onClose} disabled={approve.isPending}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={approve.isPending}
              onClick={() => approve.mutate({ periodId: period.id }, { onSuccess: onClose })}
            >
              {approve.isPending ? <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Approving…</> : "Approve"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Void Dialog ───────────────────────────────────────────────────────────────

interface VoidDialogProps { period: OwnerBalancePeriod | null; onClose: () => void; }

function VoidDialog({ period, onClose }: VoidDialogProps) {
  const [reason, setReason] = useState("");
  const voidStmt = useVoidStatement();
  if (!period) return null;

  function handleClose() { setReason(""); onClose(); }

  return (
    <Dialog open={!!period} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-red-600">
            <Ban className="h-5 w-5" />
            Void Statement
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
            <div><span className="text-muted-foreground">OPA:</span> #{period.owner_payout_account_id}</div>
            <div><span className="text-muted-foreground">Period:</span> {fmtDate(period.period_start)} → {fmtDate(period.period_end)}</div>
          </div>
          <p className="text-sm text-muted-foreground">Voiding is irreversible. Provide a reason for the audit trail.</p>
          <div className="space-y-1.5">
            <Label>Reason <span className="text-red-500">*</span></Label>
            <Textarea rows={2} maxLength={500} placeholder="Reason for voiding…"
              value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={handleClose} disabled={voidStmt.isPending}>
              Cancel
            </Button>
            <Button
              variant="destructive" size="sm"
              disabled={!reason.trim() || voidStmt.isPending}
              onClick={() => voidStmt.mutate({ periodId: period.id, reason: reason.trim() }, { onSuccess: handleClose })}
            >
              {voidStmt.isPending ? <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Voiding…</> : "Void Statement"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Mark Emailed Dialog ───────────────────────────────────────────────────────

interface MarkEmailedDialogProps { period: OwnerBalancePeriod | null; onClose: () => void; }

function MarkEmailedDialog({ period, onClose }: MarkEmailedDialogProps) {
  const markEmailed = useMarkStatementEmailed();
  if (!period) return null;
  return (
    <Dialog open={!!period} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            Mark Statement as Emailed
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
            <div><span className="text-muted-foreground">OPA:</span> #{period.owner_payout_account_id}</div>
            <div><span className="text-muted-foreground">Period:</span> {fmtDate(period.period_start)} → {fmtDate(period.period_end)}</div>
          </div>
          <p className="text-sm text-muted-foreground">
            This records the statement as emailed in the audit trail (status → Emailed).
            Actual email delivery to the owner is handled separately.
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onClose} disabled={markEmailed.isPending}>
              Cancel
            </Button>
            <Button
              size="sm" disabled={markEmailed.isPending}
              onClick={() => markEmailed.mutate({ periodId: period.id }, { onSuccess: onClose })}
            >
              {markEmailed.isPending ? <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Updating…</> : "Mark as Emailed"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Pay Dialog ────────────────────────────────────────────────────────────────

interface PayDialogProps { period: OwnerBalancePeriod | null; onClose: () => void; }

function PayDialog({ period, onClose }: PayDialogProps) {
  const payMutation = usePayOwner();
  if (!period) return null;

  const payoutAmount = parseFloat(period.closing_balance) - parseFloat(period.opening_balance);
  const canPay = period.pay_enabled && payoutAmount > 0 &&
    (period.status === "approved" || period.status === "emailed");

  return (
    <Dialog open={!!period} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-blue-600" />
            Pay Owner via Stripe
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 pt-2">
          <div className="rounded-md bg-muted/50 p-3 text-sm space-y-1">
            <div><span className="text-muted-foreground">OPA:</span> #{period.owner_payout_account_id}</div>
            <div><span className="text-muted-foreground">Period:</span> {fmtDate(period.period_start)} → {fmtDate(period.period_end)}</div>
            <div><span className="text-muted-foreground">Opening balance:</span> {fmtCurrency(period.opening_balance)}</div>
            <div><span className="text-muted-foreground">Closing balance:</span> {fmtCurrency(period.closing_balance)}</div>
            <div className="pt-1 font-semibold text-base">
              <span className="text-muted-foreground font-normal">Transfer amount: </span>
              <span className={payoutAmount > 0 ? "text-emerald-600" : "text-red-600"}>
                {fmtCurrency(payoutAmount.toFixed(2))}
              </span>
            </div>
          </div>
          {payoutAmount <= 0 && (
            <p className="text-sm text-red-600">No positive net income this period — nothing to transfer.</p>
          )}
          {payoutAmount > 0 && (
            <p className="text-sm text-muted-foreground">
              This will initiate a real Stripe Transfer to the owner&apos;s connected account.
              Idempotency key: <code className="text-xs bg-muted px-1 rounded">pay-obp-{period.id}</code>
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={onClose} disabled={payMutation.isPending}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!canPay || payMutation.isPending}
              onClick={() =>
                payMutation.mutate(
                  { periodId: period.id },
                  {
                    onSuccess: (data) => {
                      const amt = (data as { paid_amount?: string }).paid_amount;
                      toast.success(`Payment of ${fmtCurrency(amt ?? "0")} sent to OPA #${period.owner_payout_account_id}`);
                      onClose();
                    },
                    onError: (err) => {
                      toast.error(`Payment failed: ${err.message}`);
                    },
                  }
                )
              }
            >
              {payMutation.isPending ? (
                <><Loader2 className="h-4 w-4 animate-spin mr-1" /> Processing…</>
              ) : (
                <><CreditCard className="h-3.5 w-3.5 mr-1" /> Confirm Payment</>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Per-row Actions ───────────────────────────────────────────────────────────

function RowActions({
  row,
  onApprove,
  onVoid,
  onEmail,
  onPay,
}: {
  row: OwnerBalancePeriod;
  onApprove: () => void;
  onVoid: () => void;
  onEmail: () => void;
  onPay: () => void;
}) {
  const s = row.status;
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };

  const payoutAmount = parseFloat(row.closing_balance) - parseFloat(row.opening_balance);
  const payActive = row.pay_enabled && payoutAmount > 0 && (s === "approved" || s === "emailed");
  const payTitle = !row.pay_enabled
    ? "Stripe not connected (secondary OPA)"
    : payoutAmount <= 0
    ? "No net income this period"
    : "Pay owner via Stripe";

  return (
    <div className="flex items-center justify-end gap-0.5">
      {(s === "pending_approval" || s === "draft") && (
        <Button size="sm" variant="ghost" className="h-7 px-1.5 text-emerald-700 hover:text-emerald-800 hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
          onClick={stop(onApprove)} title="Approve">
          <CheckCircle2 className="h-3.5 w-3.5" />
        </Button>
      )}
      {s === "approved" && (
        <Button size="sm" variant="ghost" className="h-7 px-1.5 text-teal-700 hover:text-teal-800"
          onClick={stop(onEmail)} title="Mark Emailed">
          <Mail className="h-3.5 w-3.5" />
        </Button>
      )}
      {(s === "approved" || s === "emailed") && (
        <Button
          size="sm" variant="ghost"
          className={cn(
            "h-7 px-1.5",
            payActive
              ? "text-blue-600 hover:text-blue-700 hover:bg-blue-50 dark:hover:bg-blue-950/30"
              : "text-muted-foreground cursor-not-allowed opacity-40"
          )}
          disabled={!payActive}
          title={payTitle}
          onClick={payActive ? stop(onPay) : (e) => e.stopPropagation()}
        >
          <CreditCard className="h-3.5 w-3.5" />
        </Button>
      )}
      {s !== "voided" && s !== "paid" && (
        <Button size="sm" variant="ghost" className="h-7 px-1.5 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
          onClick={stop(onVoid)} title="Void">
          <Ban className="h-3.5 w-3.5" />
        </Button>
      )}
      <a
        href={`/api/admin/payouts/statements/${row.id}/pdf`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
      >
        <Button size="sm" variant="ghost" className="h-7 px-1.5" title="View PDF">
          <Download className="h-3.5 w-3.5" />
        </Button>
      </a>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const ALL_STATUSES: StatementPeriodStatus[] = [
  "draft", "pending_approval", "approved", "paid", "emailed", "voided",
];

export default function AdminStatementsPage() {
  const router = useRouter();
  const [filterStatus, setFilterStatus] = useState<string>("pending_approval");
  const [filterStart, setFilterStart] = useState("");
  const [filterEnd, setFilterEnd] = useState("");
  const [showGenerate, setShowGenerate] = useState(false);
  // Workflow dialog targets
  const [approveTarget, setApproveTarget] = useState<OwnerBalancePeriod | null>(null);
  const [voidTarget, setVoidTarget] = useState<OwnerBalancePeriod | null>(null);
  const [emailTarget, setEmailTarget] = useState<OwnerBalancePeriod | null>(null);
  const [payTarget, setPayTarget] = useState<OwnerBalancePeriod | null>(null);

  const filters: StatementListFilters = {
    ...(filterStatus !== "all" && { status: filterStatus }),
    ...(filterStart && { period_start: filterStart }),
    ...(filterEnd && { period_end: filterEnd }),
    limit: 50,
    offset: 0,
  };

  const { data, isLoading, isError, error, refetch } = useAdminStatements(filters);

  const rows: OwnerBalancePeriod[] = data?.statements ?? [];

  // Status counts from the full (unfiltered) query for summary cards
  const { data: allData } = useAdminStatements({ limit: 200 });
  const allRows = allData?.statements ?? [];

  function statusCount(s: StatementPeriodStatus) {
    return allRows.filter((r) => r.status === s).length;
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/admin">
            <Button variant="ghost" size="icon" className="h-8 w-8">
              <ArrowLeft className="h-4 w-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Owner Statements</h1>
            <p className="text-sm text-muted-foreground">
              Monthly statement workflow — generate, approve, and send
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isLoading}
          >
            <RefreshCw className={cn("mr-1.5 h-4 w-4", isLoading && "animate-spin")} />
            Refresh
          </Button>
          <Button size="sm" onClick={() => setShowGenerate(true)}>
            <Sparkles className="mr-1.5 h-4 w-4" />
            Generate Statements
          </Button>
        </div>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          Failed to load statements: {(error as Error)?.message ?? "Unknown error"}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-6 gap-3">
        {ALL_STATUSES.map((s) => (
          <Card
            key={s}
            className="cursor-pointer hover:ring-1 hover:ring-ring transition-all"
            onClick={() => setFilterStatus(filterStatus === s ? "all" : s)}
          >
            <CardHeader className="pb-1 pt-3 px-3">
              <CardDescription className="text-xs">{STATUS_LABELS[s]}</CardDescription>
              <CardTitle className="text-2xl">{statusCount(s)}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground whitespace-nowrap">Status</Label>
          <Select value={filterStatus} onValueChange={setFilterStatus}>
            <SelectTrigger className="h-8 w-40 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              {ALL_STATUSES.map((s) => (
                <SelectItem key={s} value={s}>{STATUS_LABELS[s]}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground">From</Label>
          <Input
            type="date"
            className="h-8 w-36 text-sm"
            value={filterStart}
            onChange={(e) => setFilterStart(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground">To</Label>
          <Input
            type="date"
            className="h-8 w-36 text-sm"
            value={filterEnd}
            onChange={(e) => setFilterEnd(e.target.value)}
          />
        </div>
        {(filterStart || filterEnd || filterStatus !== "all") && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-muted-foreground"
            onClick={() => { setFilterStart(""); setFilterEnd(""); setFilterStatus("all"); }}
          >
            Clear filters
          </Button>
        )}
      </div>

      {/* Table */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            {data?.total !== undefined
              ? `${data.total} statement${data.total !== 1 ? "s" : ""}`
              : "Statements"}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-3 text-sm text-muted-foreground">
              <FileText className="h-10 w-10 opacity-25" />
              <p>No statements yet. Generate your first batch to get started.</p>
              <Button size="sm" onClick={() => setShowGenerate(true)}>
                <Sparkles className="mr-1.5 h-4 w-4" />
                Generate Statements
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Owner Account</TableHead>
                  <TableHead>Period</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Revenue</TableHead>
                  <TableHead className="text-right">Commission</TableHead>
                  <TableHead className="text-right">Charges</TableHead>
                  <TableHead className="text-right">Closing Balance</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.id}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => router.push(`/admin/statements/${row.id}`)}
                  >
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      OPA #{row.owner_payout_account_id}
                    </TableCell>
                    <TableCell className="text-sm">
                      {fmtDate(row.period_start)} → {fmtDate(row.period_end)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <StatusBadge status={row.status} />
                        {!row.pay_enabled && (
                          <span
                            title="Statement ready to view but not payable: Stripe not connected for this property owner."
                            className="inline-flex text-amber-500"
                          >
                            <AlertTriangle className="h-3.5 w-3.5" />
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right text-sm">
                      {fmtCurrency(row.total_revenue)}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {fmtCurrency(row.total_commission)}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {fmtCurrency(row.total_charges)}
                    </TableCell>
                    <TableCell className="text-right text-sm font-medium">
                      <span
                        className={cn(
                          parseFloat(row.closing_balance) < 0
                            ? "text-red-600"
                            : "text-emerald-600"
                        )}
                      >
                        {fmtCurrency(row.closing_balance)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end">
                        <RowActions
                          row={row}
                          onApprove={() => setApproveTarget(row)}
                          onVoid={() => setVoidTarget(row)}
                          onEmail={() => setEmailTarget(row)}
                          onPay={() => setPayTarget(row)}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-1.5 ml-0.5"
                          onClick={(e) => {
                            e.stopPropagation();
                            router.push(`/admin/statements/${row.id}`);
                          }}
                          title="View detail"
                        >
                          <Eye className="h-3.5 w-3.5" />
                          <ChevronRight className="h-3 w-3 ml-0.5 text-muted-foreground" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <GenerateModal open={showGenerate} onClose={() => setShowGenerate(false)} />
      <ApproveDialog period={approveTarget} onClose={() => setApproveTarget(null)} />
      <VoidDialog period={voidTarget} onClose={() => setVoidTarget(null)} />
      <MarkEmailedDialog period={emailTarget} onClose={() => setEmailTarget(null)} />
      <PayDialog period={payTarget} onClose={() => setPayTarget(null)} />
    </div>
  );
}
