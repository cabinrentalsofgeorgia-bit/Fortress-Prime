"use client";

import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  DollarSign,
  Eye,
  Flame,
  RefreshCw,
  Shield,
  ShieldCheck,
  Target,
  XCircle,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCheckoutParity } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import type { CheckoutParityAuditRow } from "@/lib/types";

function formatCurrency(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatTimestampShort(value: string | null | undefined): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function systemStatusConfig(status: string) {
  switch (status) {
    case "NOMINAL":
      return {
        label: "NOMINAL",
        tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
        bgCard: "border-emerald-500/20",
        icon: ShieldCheck,
        description: "All parity audits confirmed. Zero discrepancies detected.",
      };
    case "RECOVERING":
      return {
        label: "RECOVERING",
        tone: "border-amber-500/30 bg-amber-500/10 text-amber-200",
        bgCard: "border-amber-500/20",
        icon: Activity,
        description: "Past discrepancies detected but the system is building consecutive clean runs.",
      };
    case "ALERT":
      return {
        label: "ALERT",
        tone: "border-rose-500/30 bg-rose-500/10 text-rose-200",
        bgCard: "border-rose-500/20",
        icon: AlertTriangle,
        description: "Recent discrepancy detected. Investigate the parity breach immediately.",
      };
    default:
      return {
        label: "AWAITING DATA",
        tone: "border-zinc-700 bg-zinc-900/80 text-zinc-300",
        bgCard: "border-zinc-800",
        icon: Eye,
        description: "No checkout parity audits recorded yet. Bookings will appear as guests complete checkout.",
      };
  }
}

function GateProgressRing({ progress, consecutive, target }: { progress: number; consecutive: number; target: number }) {
  const radius = 58;
  const stroke = 6;
  const normalizedRadius = radius - stroke;
  const circumference = normalizedRadius * 2 * Math.PI;
  const strokeDashoffset = circumference - (progress / 100) * circumference;
  const isComplete = consecutive >= target;

  return (
    <div className="relative flex items-center justify-center">
      <svg height={radius * 2} width={radius * 2} className="-rotate-90">
        <circle
          stroke="currentColor"
          fill="transparent"
          strokeWidth={stroke}
          r={normalizedRadius}
          cx={radius}
          cy={radius}
          className="text-zinc-800"
        />
        <circle
          stroke="currentColor"
          fill="transparent"
          strokeWidth={stroke}
          strokeDasharray={`${circumference} ${circumference}`}
          style={{ strokeDashoffset, transition: "stroke-dashoffset 0.6s ease-in-out" }}
          strokeLinecap="round"
          r={normalizedRadius}
          cx={radius}
          cy={radius}
          className={isComplete ? "text-emerald-400" : "text-cyan-400"}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className={cn("text-3xl font-bold tabular-nums", isComplete ? "text-emerald-300" : "text-zinc-50")}>
          {consecutive}
        </span>
        <span className="text-[10px] uppercase tracking-[0.24em] text-zinc-500">/ {target}</span>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  variant = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  variant?: "default" | "success" | "warning" | "danger";
}) {
  const border =
    variant === "success"
      ? "border-emerald-500/30"
      : variant === "warning"
        ? "border-amber-500/30"
        : variant === "danger"
          ? "border-rose-500/40"
          : "border-zinc-800";
  return (
    <div className={cn("rounded-xl border bg-zinc-900/70 px-4 py-3", border)}>
      <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-50">{value}</p>
      {hint ? <p className="mt-1 text-xs text-zinc-500">{hint}</p> : null}
    </div>
  );
}

function AuditRow({ audit }: { audit: CheckoutParityAuditRow }) {
  const isClean = audit.status === "confirmed";
  return (
    <TableRow className="border-zinc-800">
      <TableCell>
        {isClean ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        ) : (
          <XCircle className="h-4 w-4 text-rose-400" />
        )}
      </TableCell>
      <TableCell className="font-mono text-xs text-zinc-300">
        {audit.confirmation_id}
      </TableCell>
      <TableCell className="text-right tabular-nums text-zinc-200">
        {formatCurrency(audit.local_total)}
      </TableCell>
      <TableCell className="text-right tabular-nums text-zinc-200">
        {formatCurrency(audit.streamline_total)}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        <span
          className={cn(
            "font-medium",
            audit.delta === 0
              ? "text-emerald-400"
              : audit.delta <= 0.01
                ? "text-zinc-400"
                : "text-rose-400",
          )}
        >
          {formatCurrency(audit.delta)}
        </span>
      </TableCell>
      <TableCell>
        <span
          className={cn(
            "inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em]",
            isClean
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
              : "border-rose-500/30 bg-rose-500/10 text-rose-200",
          )}
        >
          {audit.status}
        </span>
      </TableCell>
      <TableCell className="whitespace-nowrap text-xs text-zinc-500">
        {formatTimestampShort(audit.created_at)}
      </TableCell>
    </TableRow>
  );
}

export default function CheckoutParityPage() {
  const { data, isLoading, error, dataUpdatedAt, refetch } = useCheckoutParity();

  if (isLoading && !data) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-cyan-200">
            <Target className="h-3.5 w-3.5" />
            Step 1 — Telemetry Launch
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Checkout Parity Console</h1>
        </div>
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="pt-6 text-sm text-zinc-400">
            Arming the checkout parity audit stream from the Hermes sync worker...
          </CardContent>
        </Card>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-rose-500/30 bg-rose-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-rose-200">
            <AlertTriangle className="h-3.5 w-3.5" />
            Step 1 — Telemetry Launch
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Checkout Parity Console</h1>
        </div>
        <Card className="border-rose-500/20 bg-zinc-950/90">
          <CardContent className="space-y-3 pt-6 text-sm text-zinc-300">
            <p>{error instanceof Error ? error.message : "Checkout parity telemetry is unavailable."}</p>
            <Button
              variant="outline"
              className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-900"
              onClick={() => void refetch()}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const statusConfig = systemStatusConfig(data.system_status);
  const StatusIcon = statusConfig.icon;
  const lastRefresh = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : "--";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <Button asChild variant="ghost" size="sm" className="w-fit gap-2 text-zinc-400 hover:text-zinc-100">
            <Link href="/command">
              <ArrowLeft className="h-4 w-4" />
              Fortress Prime
            </Link>
          </Button>
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-cyan-200">
            <Target className="h-3.5 w-3.5" />
            Step 1 — Telemetry Launch
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Checkout Parity Console</h1>
          <p className="max-w-3xl text-sm text-zinc-400">
            Watching every guest checkout. Hermes runs a parity audit against Streamline on each booking.
            Target: <strong className="text-zinc-200">100 consecutive $0.00 deltas</strong> before enabling
            Self-Healing mode.
          </p>
          <p className="text-xs text-zinc-500">
            Last refresh: {lastRefresh} · Hermes mode: {data.hermes_mode} · Auto-polling 10s
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            className="border-zinc-700 bg-zinc-900 text-zinc-200"
            onClick={() => void refetch()}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh now
          </Button>
          <Button asChild variant="outline" size="sm" className="border-zinc-700 bg-zinc-900 text-zinc-200">
            <Link href="/command/parity">
              <Eye className="mr-2 h-4 w-4" />
              Shadow Parity
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_auto_1fr]">
        <Card className={cn("bg-zinc-950/90", statusConfig.bgCard)}>
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <StatusIcon className="h-5 w-5" />
              System Status
            </CardTitle>
            <CardDescription>{statusConfig.description}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 pt-6 sm:grid-cols-2">
            <Kpi
              label="Total Confirmed"
              value={data.total_confirmed}
              variant="success"
              hint="Bookings with $0.00 delta"
            />
            <Kpi
              label="Total Discrepancy"
              value={data.total_discrepancy}
              variant={data.total_discrepancy > 0 ? "danger" : "success"}
              hint="Bookings with delta > $0.01"
            />
            <div className="sm:col-span-2">
              <div className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <Zap className="h-5 w-5 text-cyan-400" />
                <div>
                  <p className="text-sm text-zinc-100">
                    Hermes Worker: <strong>{data.hermes_mode}</strong>
                  </p>
                  <p className="text-xs text-zinc-500">
                    {data.hermes_mode === "READ_ONLY"
                      ? "Auditor mode — logging parity only, no PMS corrections."
                      : "Executor mode — auto-correcting PMS discrepancies."}
                  </p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex items-center justify-center px-4">
          <div className="flex flex-col items-center gap-3">
            <GateProgressRing
              progress={data.gate_progress_pct}
              consecutive={data.consecutive_confirmed}
              target={data.target_gate}
            />
            <div className="text-center">
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-500">Gate Progress</p>
              <p className="mt-1 text-sm text-zinc-300">
                {data.consecutive_confirmed >= data.target_gate
                  ? "Gate cleared — ready for Self-Healing"
                  : `${data.target_gate - data.consecutive_confirmed} more to clear`}
              </p>
            </div>
            <span className={cn("inline-flex rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.24em]", statusConfig.tone)}>
              {statusConfig.label}
            </span>
          </div>
        </div>

        <Card className="border-violet-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <DollarSign className="h-5 w-5 text-violet-300" />
              Revenue Split
            </CardTitle>
            <CardDescription>
              Commissionable vs pass-through across recent audited bookings.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 pt-6 sm:grid-cols-2">
            <Kpi
              label="Commissionable (Rent)"
              value={formatCurrency(data.revenue_split.commissionable_total)}
              variant="success"
              hint="Owner commission base"
            />
            <Kpi
              label="Pass-Through"
              value={formatCurrency(data.revenue_split.pass_through_total)}
              hint="Cleaning + ADW + Processing + Tax"
            />
            <Kpi
              label="Lodging Taxes"
              value={formatCurrency(data.revenue_split.total_taxes)}
              hint="Fannin County + State"
            />
            <Kpi
              label="Security Deposits"
              value={formatCurrency(data.revenue_split.total_deposits)}
              hint="Refundable / exempt"
            />
          </CardContent>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-zinc-50">
                <Shield className="h-5 w-5 text-cyan-300" />
                Live Parity Audit Feed
              </CardTitle>
              <CardDescription>
                Every checkout is compared: Local Ledger total vs Streamline&apos;s
                GetReservationPrice. Newest first.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Flame className="h-4 w-4 text-cyan-400 animate-pulse" />
              <span className="text-xs text-cyan-300">Live — {data.recent_audits.length} records</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto pt-4">
          {data.recent_audits.length === 0 ? (
            <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-8 text-center text-sm text-zinc-400">
              No checkout parity audits yet. As guests book through the new checkout,
              Hermes will run the parity check after syncing each reservation to Streamline.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="w-8 text-zinc-400" />
                  <TableHead className="text-zinc-400">Confirmation</TableHead>
                  <TableHead className="text-right text-zinc-400">Local Total</TableHead>
                  <TableHead className="text-right text-zinc-400">Streamline Total</TableHead>
                  <TableHead className="text-right text-zinc-400">Delta</TableHead>
                  <TableHead className="text-zinc-400">Status</TableHead>
                  <TableHead className="text-zinc-400">Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.recent_audits.map((audit) => (
                  <AuditRow key={audit.id} audit={audit} />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="border border-dashed border-zinc-700 bg-zinc-950/50">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-300">
            <Target className="h-4 w-4" />
            Next Strike — Self-Healing Flip (Step 2)
          </CardTitle>
          <CardDescription className="text-zinc-500">
            When {data.target_gate} consecutive bookings return Delta: $0.00, Hermes will be upgraded
            from READ_ONLY auditor to EXECUTOR mode. In executor mode, if Streamline&apos;s API
            glitches (e.g., forgets a pet fee captured in our UI), Hermes will auto-inject a folio
            adjustment into Streamline to force the legacy PMS to match the Golden Ledger.
          </CardDescription>
        </CardHeader>
      </Card>

      <p className="text-xs text-zinc-600">
        Last parity audit: {formatTimestamp(data.last_audit_at)}
      </p>
    </div>
  );
}
