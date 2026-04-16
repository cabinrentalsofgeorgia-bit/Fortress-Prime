"use client";

import { useState } from "react";
import {
  useAdminStatements,
  useGenerateStatements,
} from "@/lib/hooks";
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
import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  Eye,
  FileText,
  Loader2,
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

// ── Main Page ─────────────────────────────────────────────────────────────────

const ALL_STATUSES: StatementPeriodStatus[] = [
  "draft", "pending_approval", "approved", "paid", "emailed", "voided",
];

export default function AdminStatementsPage() {
  const router = useRouter();
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterStart, setFilterStart] = useState("");
  const [filterEnd, setFilterEnd] = useState("");
  const [showGenerate, setShowGenerate] = useState(false);

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
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2"
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push(`/admin/statements/${row.id}`);
                        }}
                      >
                        <Eye className="h-4 w-4" />
                        <ChevronRight className="h-3 w-3 ml-0.5 text-muted-foreground" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <GenerateModal open={showGenerate} onClose={() => setShowGenerate(false)} />
    </div>
  );
}
