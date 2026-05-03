"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BriefcaseBusiness,
  ClipboardCheck,
  FileSearch,
  Gauge,
  Info,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateFinancialShadowDecisionRecord,
  useCreateFinancialPromotionDryRunAcceptance,
  useFinancialLatestSignals,
  useFinancialDailyCalibration,
  useFinancialPromotionGate,
  useFinancialPromotionDryRun,
  useFinancialPromotionDryRunAcceptances,
  useFinancialShadowDecisionRecords,
  useFinancialShadowReview,
  useFinancialSignalDetail,
  useFinancialSignalChart,
  useFinancialSignalTransitions,
  useFinancialWatchlistCandidates,
  useFinancialWhipsawRisk,
} from "@/lib/hooks";
import type {
  FinancialDailyCalibrationResponse,
  FinancialLatestSignal,
  FinancialPromotionDryRunAcceptance,
  FinancialPromotionDryRunAcceptanceCreate,
  FinancialPromotionDryRunApprovalStatus,
  FinancialPromotionDryRunMarketSignalRow,
  FinancialPromotionDryRunResponse,
  FinancialPromotionGateGuardrailStatus,
  FinancialPromotionGateRecommendationStatus,
  FinancialPromotionGateResponse,
  FinancialShadowReviewChecklistStatus,
  FinancialShadowReviewDecision,
  FinancialShadowReviewDecisionRecord,
  FinancialShadowReviewDecisionRecordCreate,
  FinancialShadowReviewRecommendationStatus,
  FinancialShadowReviewResponse,
  FinancialSignalChartResponse,
  FinancialSignalTransition,
  FinancialTransitionType,
  FinancialWatchlistCandidate,
  FinancialWatchlistCandidateLane,
  FinancialWhipsawRiskLevel,
  FinancialWhipsawRiskResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type ScoreBand = "all" | "bullish" | "neutral" | "risk";
type SignalModelMode = "production" | "v0_2_range";

const SCORE_BANDS: Array<{ id: ScoreBand; label: string; min?: number; max?: number }> = [
  { id: "all", label: "All" },
  { id: "bullish", label: "Bullish", min: 50 },
  { id: "neutral", label: "Neutral", min: -30, max: 30 },
  { id: "risk", label: "Risk", max: -50 },
];

const SIGNAL_MODEL_MODES: Array<{
  id: SignalModelMode;
  label: string;
  parameterSet?: string;
  badge: string;
}> = [
  {
    id: "production",
    label: "Production",
    badge: "dochia_v0_estimated",
  },
  {
    id: "v0_2_range",
    label: "v0.2 Range",
    parameterSet: "dochia_v0_2_range_daily",
    badge: "dochia_v0_2_range_daily",
  },
];

const TRANSITION_LABELS: Record<FinancialTransitionType, string> = {
  peak_to_exit: "Peak to exit",
  exit_to_reentry: "Re-entry",
  full_reversal: "Full reversal",
  breakout_bullish: "Bullish break",
  breakout_bearish: "Bearish break",
};

const EMPTY_SIGNALS: FinancialLatestSignal[] = [];
const EMPTY_TRANSITIONS: FinancialSignalTransition[] = [];
const EMPTY_LANES: FinancialWatchlistCandidateLane[] = [];

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatPrice(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return String(value);
  return numeric.toFixed(numeric >= 100 ? 2 : 4);
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatSignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(1)}%`;
}

function formatMetricNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(1);
}

function scoreTone(score: number): "green" | "red" | "amber" | "neutral" {
  if (score >= 50) return "green";
  if (score <= -50) return "red";
  if (score !== 0) return "amber";
  return "neutral";
}

function scoreClasses(score: number): string {
  const tone = scoreTone(score);
  if (tone === "green") return "text-emerald-500";
  if (tone === "red") return "text-red-500";
  if (tone === "amber") return "text-amber-500";
  return "text-muted-foreground";
}

function stateClasses(value: number): string {
  if (value > 0) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
  if (value < 0) return "border-red-500/40 bg-red-500/10 text-red-600";
  return "border-border bg-muted/30 text-muted-foreground";
}

function transitionClasses(type: FinancialTransitionType): string {
  if (type === "exit_to_reentry" || type === "breakout_bullish") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
  }
  if (type === "peak_to_exit" || type === "breakout_bearish") {
    return "border-red-500/40 bg-red-500/10 text-red-600";
  }
  return "border-amber-500/40 bg-amber-500/10 text-amber-600";
}

function whipsawRiskClasses(level: FinancialWhipsawRiskLevel): string {
  if (level === "high") return "border-red-500/40 bg-red-500/10 text-red-600";
  if (level === "elevated") return "border-amber-500/40 bg-amber-500/10 text-amber-600";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
}

function whipsawRiskLabel(level: FinancialWhipsawRiskLevel): string {
  if (level === "high") return "High";
  if (level === "elevated") return "Elevated";
  return "Quiet";
}

function promotionRecommendationClasses(status: FinancialPromotionGateRecommendationStatus): string {
  if (status === "hold") return "border-red-500/40 bg-red-500/10 text-red-600";
  if (status === "review") return "border-amber-500/40 bg-amber-500/10 text-amber-600";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
}

function promotionGuardrailClasses(status: FinancialPromotionGateGuardrailStatus): string {
  if (status === "fail") return "border-red-500/40 bg-red-500/10 text-red-600";
  if (status === "watch") return "border-amber-500/40 bg-amber-500/10 text-amber-600";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
}

function shadowReviewRecommendationClasses(status: FinancialShadowReviewRecommendationStatus): string {
  if (status === "hold") return "border-red-500/40 bg-red-500/10 text-red-600";
  if (status === "needs_review") return "border-amber-500/40 bg-amber-500/10 text-amber-600";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
}

function shadowReviewChecklistClasses(status: FinancialShadowReviewChecklistStatus): string {
  if (status === "hold" || status === "blocked") {
    return "border-red-500/40 bg-red-500/10 text-red-600";
  }
  if (status === "review") return "border-amber-500/40 bg-amber-500/10 text-amber-600";
  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
}

function shadowDecisionClasses(decision: FinancialShadowReviewDecision): string {
  if (decision === "promote_to_market_signals") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
  }
  if (decision === "continue_shadow") return "border-sky-500/40 bg-sky-500/10 text-sky-600";
  return "border-amber-500/40 bg-amber-500/10 text-amber-600";
}

function shadowDecisionLabel(decision: FinancialShadowReviewDecision): string {
  if (decision === "promote_to_market_signals") return "Promote to dry-run";
  if (decision === "continue_shadow") return "Continue shadow";
  return "Defer";
}

function promotionDryRunApprovalClasses(status: FinancialPromotionDryRunApprovalStatus): string {
  if (status === "ready_for_dry_run") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
  }
  if (status === "blocked_by_review") return "border-red-500/40 bg-red-500/10 text-red-600";
  return "border-amber-500/40 bg-amber-500/10 text-amber-600";
}

function promotionDryRunApprovalLabel(status: FinancialPromotionDryRunApprovalStatus): string {
  if (status === "ready_for_dry_run") return "Ready for dry-run";
  if (status === "blocked_by_review") return "Blocked by review";
  return "Promote decision missing";
}

function formatSignedNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}`;
}

function StatePill({ label, value }: { label: string; value: number }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 min-w-12 items-center justify-center gap-1 border px-2 font-mono text-[11px] font-semibold uppercase",
        stateClasses(value),
      )}
      title={`${label}: ${value > 0 ? "green" : value < 0 ? "red" : "neutral"}`}
    >
      {label}
      <span>{value > 0 ? "+1" : value < 0 ? "-1" : "0"}</span>
    </span>
  );
}

function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub: string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "green" | "red" | "amber" | "neutral";
}) {
  const toneClass =
    tone === "green"
      ? "text-emerald-500"
      : tone === "red"
        ? "text-red-500"
        : tone === "amber"
          ? "text-amber-500"
          : "text-primary";

  return (
    <Card>
      <CardContent className="flex min-h-24 items-center gap-4 px-5 py-4">
        <div className={cn("border border-border bg-muted/30 p-2.5", toneClass)}>
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-xl font-bold tabular-nums">{value}</p>
          <p className="truncate text-[11px] text-muted-foreground">{sub}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function ScoreDistribution({ signals }: { signals: FinancialLatestSignal[] }) {
  const buckets = useMemo(
    () => [
      { label: "+80", count: signals.filter((item) => item.composite_score === 80).length, className: "bg-emerald-500" },
      { label: "+50/+30", count: signals.filter((item) => item.composite_score > 0 && item.composite_score < 80).length, className: "bg-sky-500" },
      { label: "0", count: signals.filter((item) => item.composite_score === 0).length, className: "bg-muted-foreground" },
      { label: "-30/-50", count: signals.filter((item) => item.composite_score < 0 && item.composite_score > -80).length, className: "bg-amber-500" },
      { label: "-80", count: signals.filter((item) => item.composite_score === -80).length, className: "bg-red-500" },
    ],
    [signals],
  );
  const total = Math.max(1, signals.length);

  return (
    <div className="space-y-3">
      {buckets.map((bucket) => (
        <div key={bucket.label} className="grid grid-cols-[72px_minmax(0,1fr)_40px] items-center gap-3">
          <span className="font-mono text-[11px] text-muted-foreground">{bucket.label}</span>
          <div className="h-2 overflow-hidden bg-muted">
            <div
              className={cn("h-full", bucket.className)}
              style={{ width: `${(bucket.count / total) * 100}%` }}
            />
          </div>
          <span className="text-right font-mono text-[11px] tabular-nums text-muted-foreground">
            {bucket.count}
          </span>
        </div>
      ))}
    </div>
  );
}

function TransitionBadge({ type }: { type: FinancialTransitionType }) {
  return (
    <Badge variant="outline" className={cn("font-medium", transitionClasses(type))}>
      {TRANSITION_LABELS[type]}
    </Badge>
  );
}

function SignalTable({
  signals,
  selectedTicker,
  onSelect,
}: {
  signals: FinancialLatestSignal[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Ticker</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead>Triangles</TableHead>
            <TableHead>Daily Channel</TableHead>
            <TableHead>As Of</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {signals.map((signal) => {
            const selected = selectedTicker === signal.ticker;
            return (
              <TableRow
                key={signal.ticker}
                className={cn("cursor-pointer", selected && "bg-muted/60")}
                onClick={() => onSelect(signal.ticker)}
              >
                <TableCell className="font-mono font-semibold">{signal.ticker}</TableCell>
                <TableCell className={cn("text-right font-mono text-lg font-bold", scoreClasses(signal.composite_score))}>
                  {signal.composite_score > 0 ? "+" : ""}
                  {signal.composite_score}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1.5">
                    <StatePill label="M" value={signal.monthly_state} />
                    <StatePill label="W" value={signal.weekly_state} />
                    <StatePill label="D" value={signal.daily_state} />
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {formatPrice(signal.daily_channel_low)} / {formatPrice(signal.daily_channel_high)}
                </TableCell>
                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {formatDate(signal.bar_date)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function AlertFeed({ transitions }: { transitions: FinancialSignalTransition[] }) {
  if (!transitions.length) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No recent signal transitions.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {transitions.slice(0, 14).map((item) => (
        <div
          key={item.id}
          className="grid gap-3 border border-border p-3 sm:grid-cols-[92px_minmax(0,1fr)_88px]"
        >
          <div>
            <p className="font-mono text-sm font-semibold">{item.ticker}</p>
            <p className="text-xs text-muted-foreground">{formatDate(item.to_bar_date)}</p>
          </div>
          <div className="min-w-0 space-y-1">
            <TransitionBadge type={item.transition_type} />
            <p className="truncate text-xs text-muted-foreground">{item.notes ?? "—"}</p>
          </div>
          <div className="text-right font-mono text-sm font-semibold">
            <span className={scoreClasses(item.from_score)}>
              {item.from_score > 0 ? "+" : ""}
              {item.from_score}
            </span>
            <span className="px-1 text-muted-foreground">→</span>
            <span className={scoreClasses(item.to_score)}>
              {item.to_score > 0 ? "+" : ""}
              {item.to_score}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function legacyActionClasses(action?: string | null): string {
  const normalized = action?.toUpperCase();
  if (normalized === "BUY") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-600";
  if (normalized === "SELL") return "border-red-500/40 bg-red-500/10 text-red-600";
  if (normalized === "WATCH") return "border-sky-500/40 bg-sky-500/10 text-sky-600";
  return "border-border bg-muted/30 text-muted-foreground";
}

function CandidateRow({
  candidate,
  onSelect,
}: {
  candidate: FinancialWatchlistCandidate;
  onSelect: (ticker: string) => void;
}) {
  return (
    <button
      type="button"
      className="w-full border border-border p-3 text-left transition-colors hover:bg-muted/50"
      onClick={() => onSelect(candidate.ticker)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold">{candidate.ticker}</p>
          <p className="truncate text-xs text-muted-foreground">
            {candidate.sector ?? candidate.parameter_set_name}
          </p>
        </div>
        <div className={cn("font-mono text-lg font-bold", scoreClasses(candidate.composite_score))}>
          {candidate.composite_score > 0 ? "+" : ""}
          {candidate.composite_score}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <StatePill label="M" value={candidate.monthly_state} />
        <StatePill label="W" value={candidate.weekly_state} />
        <StatePill label="D" value={candidate.daily_state} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="outline" className={cn("font-medium", legacyActionClasses(candidate.legacy_action))}>
          {candidate.legacy_action ?? "No legacy action"}
        </Badge>
        {candidate.latest_transition_type ? (
          <TransitionBadge type={candidate.latest_transition_type} />
        ) : null}
        <span className="text-muted-foreground">
          Watchlist {candidate.watchlist_signal_count ?? 0}
        </span>
      </div>
    </button>
  );
}

function WatchlistLanes({
  lanes,
  loading,
  error,
  onSelect,
}: {
  lanes: FinancialWatchlistCandidateLane[];
  loading: boolean;
  error: boolean;
  onSelect: (ticker: string) => void;
}) {
  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Portfolio lens unavailable.
      </div>
    );
  }

  if (loading) {
    return <div className="py-8 text-sm text-muted-foreground">Loading portfolio lens…</div>;
  }

  return (
    <div className="grid gap-4 xl:grid-cols-4">
      {lanes.map((lane) => (
        <div key={lane.id} className="space-y-3 border border-border p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold">{lane.label}</h2>
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{lane.description}</p>
            </div>
            <Badge variant="outline">{lane.candidates.length}</Badge>
          </div>
          <div className="space-y-2">
            {lane.candidates.length ? (
              lane.candidates.slice(0, 4).map((candidate) => (
                <CandidateRow
                  key={`${lane.id}-${candidate.ticker}`}
                  candidate={candidate}
                  onSelect={onSelect}
                />
              ))
            ) : (
              <div className="border border-dashed border-border p-3 text-xs text-muted-foreground">
                No candidates.
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function CalibrationPanel({
  calibration,
  loading,
  error,
}: {
  calibration: FinancialDailyCalibrationResponse | null;
  loading: boolean;
  error: boolean;
}) {
  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Calibration baseline unavailable.
      </div>
    );
  }

  if (loading && !calibration) {
    return <div className="py-8 text-sm text-muted-foreground">Loading calibration baseline…</div>;
  }

  if (!calibration) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No calibration baseline.
      </div>
    );
  }

  const confusion = calibration.confusion;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,0.75fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Carried State Match</p>
          <p className="mt-1 font-mono text-2xl font-bold">
            {formatPercent(calibration.accuracy)}
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Exact Alert Match</p>
          <p className="mt-1 font-mono text-2xl font-bold">
            {formatPercent(calibration.exact_event_accuracy)}
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">
            ±{calibration.event_window_days}d Alert Match
          </p>
          <p className="mt-1 font-mono text-2xl font-bold">
            {formatPercent(calibration.window_event_accuracy)}
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Coverage</p>
          <p className="mt-1 font-mono text-2xl font-bold">
            {formatPercent(calibration.coverage_rate)}
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Score MAE</p>
          <p className="mt-1 font-mono text-2xl font-bold">
            {formatMetricNumber(calibration.score_mae)}
          </p>
        </div>
      </div>
      <div className="border border-border p-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Daily Confusion</h2>
          <span className="text-xs text-muted-foreground">
            {calibration.covered_observations.toLocaleString()} covered
          </span>
        </div>
        <div className="mt-4 grid grid-cols-[72px_repeat(4,minmax(0,1fr))] gap-2 text-xs">
          <span />
          {["green", "red", "neutral", "missing"].map((label) => (
            <span key={label} className="text-center text-muted-foreground">
              {label}
            </span>
          ))}
          {(["green", "red"] as const).map((actual) => (
            <div key={actual} className="contents">
              <span className="font-medium capitalize">{actual}</span>
              {(["green", "red", "neutral", "missing"] as const).map((generated) => (
                <span key={generated} className="bg-muted/50 py-2 text-center font-mono">
                  {confusion[actual][generated].toLocaleString()}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="border border-border p-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold">Largest Samples</h2>
          <span className="text-xs text-muted-foreground">{calibration.parameter_set_name}</span>
        </div>
        <div className="mt-3 space-y-2">
          {calibration.top_tickers.slice(0, 5).map((item) => (
            <div
              key={item.ticker}
              className="grid grid-cols-[64px_minmax(0,1fr)_64px] items-center gap-3 text-xs"
            >
              <span className="font-mono font-semibold">{item.ticker}</span>
              <div className="h-2 overflow-hidden bg-muted">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${Math.max(0, Math.min(100, (item.accuracy ?? 0) * 100))}%` }}
                />
              </div>
              <span className="text-right font-mono text-muted-foreground">
                {formatPercent(item.accuracy)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function numericValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function triangleDotColor(state: string): string {
  if (state === "green") return "hsl(142, 71%, 45%)";
  if (state === "red") return "hsl(0, 84%, 60%)";
  return "hsl(var(--muted-foreground))";
}

function triangleDotRadius(timeframe: string): number {
  if (timeframe === "monthly") return 6;
  if (timeframe === "weekly") return 5;
  return 4;
}

function SignalChart({
  chart,
  loading,
  error,
}: {
  chart: FinancialSignalChartResponse | null;
  loading: boolean;
  error: boolean;
}) {
  const chartRows = useMemo(
    () =>
      chart?.bars.map((bar) => ({
        date: bar.bar_date,
        close: numericValue(bar.close),
        dailyHigh: numericValue(bar.daily_channel_high),
        dailyLow: numericValue(bar.daily_channel_low),
        weeklyHigh: numericValue(bar.weekly_channel_high),
        weeklyLow: numericValue(bar.weekly_channel_low),
      })) ?? [],
    [chart],
  );

  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Chart overlay unavailable.
      </div>
    );
  }

  if (loading && !chart) {
    return <div className="py-8 text-sm text-muted-foreground">Loading chart overlay…</div>;
  }

  if (!chart || chartRows.length === 0) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No chart data.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="h-72 min-h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartRows} margin={{ top: 12, right: 14, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis
              dataKey="date"
              minTickGap={28}
              tickFormatter={(value) => String(value).slice(5)}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value) => formatPrice(value)}
              tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              formatter={(value, name) => [formatPrice(value as number), String(name)]}
              labelFormatter={(label) => formatDate(String(label))}
            />
            <Line
              type="monotone"
              dataKey="close"
              name="Close"
              stroke="hsl(var(--primary))"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="dailyHigh"
              name="Daily High"
              stroke="hsl(142, 71%, 45%)"
              strokeDasharray="4 4"
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="dailyLow"
              name="Daily Low"
              stroke="hsl(0, 84%, 60%)"
              strokeDasharray="4 4"
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="weeklyHigh"
              name="Weekly High"
              stroke="hsl(217, 91%, 60%)"
              strokeDasharray="2 5"
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="weeklyLow"
              name="Weekly Low"
              stroke="hsl(280, 67%, 55%)"
              strokeDasharray="2 5"
              strokeWidth={1}
              dot={false}
              isAnimationActive={false}
            />
            {chart.events.slice(-40).map((event) => (
              <ReferenceDot
                key={`${event.timeframe}-${event.state}-${event.bar_date}-${event.trigger_price}`}
                x={event.bar_date}
                y={numericValue(event.trigger_price) ?? 0}
                r={triangleDotRadius(event.timeframe)}
                fill={triangleDotColor(event.state)}
                stroke="hsl(var(--background))"
                strokeWidth={2}
                ifOverflow="extendDomain"
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{chart.sessions} sessions</span>
        <span>{chart.events.length} triangle events</span>
      </div>
    </div>
  );
}

function WhipsawRiskPanel({
  risk,
  loading,
  error,
}: {
  risk: FinancialWhipsawRiskResponse | null;
  loading: boolean;
  error: boolean;
}) {
  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Whipsaw risk unavailable.
      </div>
    );
  }

  if (loading && !risk) {
    return <div className="py-8 text-sm text-muted-foreground">Loading whipsaw risk…</div>;
  }

  if (!risk) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No whipsaw risk data.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Risk</p>
          <div className="mt-2 flex items-center gap-2">
            <Badge variant="outline" className={cn("font-medium", whipsawRiskClasses(risk.risk_level))}>
              {whipsawRiskLabel(risk.risk_level)}
            </Badge>
            <span className="font-mono text-sm font-semibold">{risk.risk_score}</span>
          </div>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Whipsaws</p>
          <p className="mt-1 font-mono text-xl font-bold">
            {risk.whipsaw_count}
            <span className="text-xs font-normal text-muted-foreground"> / {risk.event_count}</span>
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">
            {risk.outcome_horizon_sessions}d Win
          </p>
          <p className="mt-1 font-mono text-xl font-bold">
            {formatPercent(risk.outcome.win_rate)}
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">
            Avg {risk.outcome_horizon_sessions}d
          </p>
          <p
            className={cn(
              "mt-1 font-mono text-xl font-bold",
              (risk.outcome.average_directional_return ?? 0) >= 0
                ? "text-emerald-500"
                : "text-red-500",
            )}
          >
            {formatSignedPercent(risk.outcome.average_directional_return)}
          </p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.75fr)_minmax(0,1fr)]">
        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Backtest</h2>
            <span className="text-xs text-muted-foreground">
              {risk.outcome.evaluated_events} events
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div className="bg-muted/40 p-2">
              <span className="text-muted-foreground">Median</span>
              <p className="mt-1 font-mono font-semibold">
                {formatSignedPercent(risk.outcome.median_directional_return)}
              </p>
            </div>
            <div className="bg-muted/40 p-2">
              <span className="text-muted-foreground">Whipsaw Rate</span>
              <p className="mt-1 font-mono font-semibold">{formatPercent(risk.whipsaw_rate)}</p>
            </div>
            <div className="bg-muted/40 p-2">
              <span className="text-muted-foreground">P25</span>
              <p className="mt-1 font-mono font-semibold">
                {formatSignedPercent(risk.outcome.p25_directional_return)}
              </p>
            </div>
            <div className="bg-muted/40 p-2">
              <span className="text-muted-foreground">P75</span>
              <p className="mt-1 font-mono font-semibold">
                {formatSignedPercent(risk.outcome.p75_directional_return)}
              </p>
            </div>
          </div>
        </div>

        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Recent Daily Events</h2>
            <span className="text-xs text-muted-foreground">
              {risk.daily_trigger_mode} · {risk.sessions} sessions
            </span>
          </div>
          <div className="mt-3 space-y-2">
            {risk.recent_events.length ? (
              risk.recent_events.slice(0, 5).map((event) => (
                <div
                  key={`${event.event_date}-${event.state}`}
                  className="grid grid-cols-[82px_72px_minmax(0,1fr)_68px] items-center gap-2 text-xs"
                >
                  <span className="font-mono text-muted-foreground">{formatDate(event.event_date)}</span>
                  <Badge variant="outline" className={cn("justify-center", stateClasses(event.state === "green" ? 1 : -1))}>
                    {event.state}
                  </Badge>
                  <span className="truncate text-muted-foreground">
                    {event.is_whipsaw ? "Flip" : "Trend"} ·{" "}
                    {event.sessions_since_previous ?? "—"} sessions
                  </span>
                  <span className="text-right font-mono font-semibold">
                    {formatSignedPercent(event.directional_return)}
                  </span>
                </div>
              ))
            ) : (
              <div className="border border-dashed border-border p-3 text-xs text-muted-foreground">
                No recent daily events.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function PromotionGatePanel({
  gate,
  loading,
  error,
}: {
  gate: FinancialPromotionGateResponse | null;
  loading: boolean;
  error: boolean;
}) {
  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Promotion gate unavailable.
      </div>
    );
  }

  if (loading && !gate) {
    return <div className="py-8 text-sm text-muted-foreground">Loading promotion gate…</div>;
  }

  if (!gate) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No promotion-gate data.
      </div>
    );
  }

  const metricRows = [
    {
      label: "± Window Match",
      production: formatPercent(gate.production.calibration.window_event_accuracy),
      candidate: formatPercent(gate.candidate.calibration.window_event_accuracy),
      delta: formatSignedPercent(gate.deltas.window_event_accuracy),
    },
    {
      label: "Exact Alert Match",
      production: formatPercent(gate.production.calibration.exact_event_accuracy),
      candidate: formatPercent(gate.candidate.calibration.exact_event_accuracy),
      delta: formatSignedPercent(gate.deltas.exact_event_accuracy),
    },
    {
      label: "Coverage",
      production: formatPercent(gate.production.calibration.coverage_rate),
      candidate: formatPercent(gate.candidate.calibration.coverage_rate),
      delta: formatSignedPercent(gate.deltas.coverage_rate),
    },
    {
      label: "Score MAE",
      production: formatMetricNumber(gate.production.calibration.score_mae),
      candidate: formatMetricNumber(gate.candidate.calibration.score_mae),
      delta: formatSignedNumber(gate.deltas.score_mae, 1),
    },
    {
      label: "Signals",
      production: gate.production.signal_count.toLocaleString(),
      candidate: gate.candidate.signal_count.toLocaleString(),
      delta: formatSignedNumber(gate.deltas.signal_count),
    },
    {
      label: "Re-entry",
      production: gate.production.reentry_count.toLocaleString(),
      candidate: gate.candidate.reentry_count.toLocaleString(),
      delta: formatSignedNumber(gate.deltas.reentry_count),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Production vs v0.2 Range</p>
          <p className="text-xs text-muted-foreground">
            {gate.baseline_parameter_set} → {gate.candidate_parameter_set}
          </p>
        </div>
        <Badge
          variant="outline"
          className={cn("font-medium", promotionRecommendationClasses(gate.recommendation.status))}
        >
          {gate.recommendation.label}
        </Badge>
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
        <div className="overflow-hidden border border-border">
          <div className="grid grid-cols-[minmax(120px,1fr)_repeat(3,minmax(92px,0.7fr))] border-b border-border bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground">
            <span>Metric</span>
            <span className="text-right">{gate.production.label}</span>
            <span className="text-right">{gate.candidate.label}</span>
            <span className="text-right">Delta</span>
          </div>
          {metricRows.map((row) => (
            <div
              key={row.label}
              className="grid grid-cols-[minmax(120px,1fr)_repeat(3,minmax(92px,0.7fr))] border-b border-border px-3 py-2 text-xs last:border-b-0"
            >
              <span className="font-medium">{row.label}</span>
              <span className="text-right font-mono text-muted-foreground">{row.production}</span>
              <span className="text-right font-mono font-semibold">{row.candidate}</span>
              <span className="text-right font-mono text-muted-foreground">{row.delta}</span>
            </div>
          ))}
        </div>

        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Guardrails</h2>
            <span className="text-xs text-muted-foreground">{formatDate(gate.generated_at)}</span>
          </div>
          <div className="mt-3 space-y-2">
            {gate.guardrails.map((guardrail) => (
              <div key={guardrail.id} className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 truncate">{guardrail.label}</span>
                <Badge
                  variant="outline"
                  className={cn("shrink-0 font-medium", promotionGuardrailClasses(guardrail.status))}
                >
                  {guardrail.status}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">{gate.recommendation.rationale}</p>
    </div>
  );
}

function ShadowReviewPanel({
  review,
  loading,
  error,
  decisionRecords,
  decisionRecordsLoading,
  onSubmitDecision,
  submittingDecision,
}: {
  review: FinancialShadowReviewResponse | null;
  loading: boolean;
  error: boolean;
  decisionRecords: FinancialShadowReviewDecisionRecord[];
  decisionRecordsLoading: boolean;
  onSubmitDecision: (payload: FinancialShadowReviewDecisionRecordCreate) => Promise<void>;
  submittingDecision: boolean;
}) {
  const [decision, setDecision] = useState<FinancialShadowReviewDecision>("continue_shadow");
  const [reviewer, setReviewer] = useState("Gary Knight");
  const [rationale, setRationale] = useState("");
  const [rollbackCriteria, setRollbackCriteria] = useState("");
  const [reviewedTickers, setReviewedTickers] = useState("");
  const [notes, setNotes] = useState("");

  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Shadow review unavailable.
      </div>
    );
  }

  if (loading && !review) {
    return <div className="py-8 text-sm text-muted-foreground">Loading shadow review…</div>;
  }

  if (!review) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No shadow-review data.
      </div>
    );
  }

  const highestChurn = [...review.lane_reviews].sort((a, b) => b.churn_rate - a.churn_rate)[0];
  const activeReview = review;
  const topPressure = review.transition_pressure.slice(0, 5);
  const topWhipsaws = review.whipsaw_reviews.slice(0, 5);
  const canSubmitDecision =
    reviewer.trim().length >= 2 &&
    rationale.trim().length >= 12 &&
    rollbackCriteria.trim().length >= 12;

  async function handleDecisionSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmitDecision) return;
    const tickers = reviewedTickers
      .split(/[\s,]+/)
      .map((ticker) => ticker.trim().toUpperCase())
      .filter(Boolean);
    try {
      await onSubmitDecision({
        candidate_parameter_set: activeReview.candidate_parameter_set,
        decision,
        reviewer,
        rationale,
        rollback_criteria: rollbackCriteria,
        reviewed_tickers: Array.from(new Set(tickers)),
        notes: notes.trim() || null,
        lookback_days: activeReview.lookback_days,
        review_limit: activeReview.review_limit,
        whipsaw_window_sessions: 5,
        outcome_horizon_sessions: 5,
      });
      setRationale("");
      setRollbackCriteria("");
      setNotes("");
    } catch {
      // The mutation hook owns the operator-facing error toast.
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Supervised Shadow Review</p>
          <p className="text-xs text-muted-foreground">
            {review.baseline_parameter_set} → {review.candidate_parameter_set}
          </p>
        </div>
        <Badge
          variant="outline"
          className={cn("font-medium", shadowReviewRecommendationClasses(review.recommendation.status))}
        >
          {review.recommendation.label}
        </Badge>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        {review.checklist.map((item) => (
          <div key={item.id} className="border border-border p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-xs font-medium">{item.label}</p>
              <Badge
                variant="outline"
                className={cn("shrink-0 text-[10px]", shadowReviewChecklistClasses(item.status))}
              >
                {item.status}
              </Badge>
            </div>
            <p className="mt-2 line-clamp-2 text-[11px] text-muted-foreground">{item.detail}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Lane Churn</h2>
            <span className="font-mono text-xs text-muted-foreground">
              {highestChurn ? formatPercent(highestChurn.churn_rate) : "—"}
            </span>
          </div>
          <div className="mt-3 space-y-2">
            {review.lane_reviews.map((lane) => (
              <div key={lane.lane_id} className="grid grid-cols-[minmax(0,1fr)_56px_56px] gap-2 text-xs">
                <span className="truncate font-medium">{lane.label}</span>
                <span className="text-right font-mono text-emerald-600">+{lane.added_tickers.length}</span>
                <span className="text-right font-mono text-red-600">-{lane.removed_tickers.length}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Transition Pressure</h2>
            <span className="text-xs text-muted-foreground">{review.lookback_days}d</span>
          </div>
          <div className="mt-3 space-y-2">
            {topPressure.length ? (
              topPressure.map((item) => (
                <div key={item.ticker} className="grid grid-cols-[56px_minmax(0,1fr)_52px] items-center gap-2 text-xs">
                  <span className="font-mono font-semibold">{item.ticker}</span>
                  <span className="truncate text-muted-foreground">
                    {item.latest_candidate_transition_type
                      ? TRANSITION_LABELS[item.latest_candidate_transition_type]
                      : "—"}
                  </span>
                  <span className="text-right font-mono">
                    {item.candidate_transition_count}
                    <span className="text-muted-foreground">({formatSignedNumber(item.delta)})</span>
                  </span>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">No transition pressure.</p>
            )}
          </div>
        </div>

        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Whipsaw Review</h2>
            <span className="text-xs text-muted-foreground">{topWhipsaws.length} tickers</span>
          </div>
          <div className="mt-3 space-y-2">
            {topWhipsaws.length ? (
              topWhipsaws.map((item) => (
                <div key={item.ticker} className="grid grid-cols-[56px_minmax(0,1fr)_52px] items-center gap-2 text-xs">
                  <span className="font-mono font-semibold">{item.ticker}</span>
                  <Badge
                    variant="outline"
                    className={cn("justify-center", whipsawRiskClasses(item.risk_level))}
                  >
                    {whipsawRiskLabel(item.risk_level)}
                  </Badge>
                  <span className="text-right font-mono">{item.risk_score}</span>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">No whipsaw pressure.</p>
            )}
          </div>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">{review.recommendation.rationale}</p>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <form className="border border-border p-3" onSubmit={(event) => void handleDecisionSubmit(event)}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Decision Record</h2>
            <Badge variant="outline" className={cn("font-medium", shadowDecisionClasses(decision))}>
              {shadowDecisionLabel(decision)}
            </Badge>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {(["defer", "continue_shadow", "promote_to_market_signals"] as const).map((option) => (
              <Button
                key={option}
                type="button"
                variant={decision === option ? "default" : "outline"}
                size="sm"
                className="justify-center"
                onClick={() => setDecision(option)}
                aria-pressed={decision === option}
              >
                {shadowDecisionLabel(option)}
              </Button>
            ))}
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-xs font-medium">
              Reviewer
              <Input
                value={reviewer}
                onChange={(event) => setReviewer(event.target.value)}
                className="h-9"
              />
            </label>
            <label className="space-y-1 text-xs font-medium">
              Reviewed Tickers
              <Input
                value={reviewedTickers}
                onChange={(event) => setReviewedTickers(event.target.value)}
                placeholder="AA, BTU"
                className="h-9 font-mono"
              />
            </label>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-xs font-medium">
              Rationale
              <textarea
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                className="min-h-24 w-full resize-y border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
            <label className="space-y-1 text-xs font-medium">
              Rollback Criteria
              <textarea
                value={rollbackCriteria}
                onChange={(event) => setRollbackCriteria(event.target.value)}
                className="min-h-24 w-full resize-y border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
          </div>

          <label className="mt-3 block space-y-1 text-xs font-medium">
            Notes
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              className="min-h-16 w-full resize-y border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />
          </label>

          <div className="mt-3 flex justify-end">
            <Button type="submit" disabled={!canSubmitDecision || submittingDecision}>
              {submittingDecision ? "Saving…" : "Record Decision"}
            </Button>
          </div>
        </form>

        <div className="border border-border p-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Decision Records</h2>
            <span className="text-xs text-muted-foreground">
              {decisionRecordsLoading ? "Loading" : `${decisionRecords.length} shown`}
            </span>
          </div>
          <div className="mt-3 space-y-2">
            {decisionRecords.length ? (
              decisionRecords.map((record) => (
                <div key={record.id} className="border border-border/70 p-2 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Badge
                      variant="outline"
                      className={cn("font-medium", shadowDecisionClasses(record.decision))}
                    >
                      {shadowDecisionLabel(record.decision)}
                    </Badge>
                    <span className="text-muted-foreground">{formatDate(record.created_at)}</span>
                  </div>
                  <p className="mt-2 font-medium">{record.reviewer}</p>
                  <p className="mt-1 line-clamp-2 text-muted-foreground">{record.rationale}</p>
                  {record.reviewed_tickers.length ? (
                    <p className="mt-2 font-mono text-[11px] text-muted-foreground">
                      {record.reviewed_tickers.join(", ")}
                    </p>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">No decision records yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function PromotionDryRunRow({ row }: { row: FinancialPromotionDryRunMarketSignalRow }) {
  return (
    <div className="grid gap-2 border-b border-border px-3 py-3 text-xs last:border-b-0 lg:grid-cols-[70px_76px_64px_88px_98px_minmax(0,1fr)]">
      <span className="font-mono font-semibold">{row.ticker}</span>
      <span>
        <Badge variant="outline" className={cn("font-medium", legacyActionClasses(row.action))}>
          {row.action}
        </Badge>
      </span>
      <span className={cn("font-mono font-semibold", scoreClasses(row.composite_score))}>
        {row.composite_score > 0 ? "+" : ""}
        {row.composite_score}
      </span>
      <span className="font-mono text-muted-foreground">{row.confidence_score}</span>
      <span className="text-muted-foreground">{formatDate(row.candidate_bar_date)}</span>
      <span className="min-w-0 truncate font-mono text-[11px] text-muted-foreground">
        {row.lineage.rollback_marker}
      </span>
    </div>
  );
}

function PromotionDryRunPanel({
  dryRun,
  loading,
  error,
  acceptances,
  acceptancesLoading,
  onSubmitAcceptance,
  submittingAcceptance,
}: {
  dryRun: FinancialPromotionDryRunResponse | null;
  loading: boolean;
  error: boolean;
  acceptances: FinancialPromotionDryRunAcceptance[];
  acceptancesLoading: boolean;
  onSubmitAcceptance: (payload: FinancialPromotionDryRunAcceptanceCreate) => Promise<void>;
  submittingAcceptance: boolean;
}) {
  const [acceptedBy, setAcceptedBy] = useState("Gary Knight");
  const [acceptanceRationale, setAcceptanceRationale] = useState("");

  if (error) {
    return (
      <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertTriangle className="h-4 w-4" />
        Promotion dry-run unavailable.
      </div>
    );
  }

  if (loading && !dryRun) {
    return <div className="py-8 text-sm text-muted-foreground">Loading promotion dry-run…</div>;
  }

  if (!dryRun) {
    return (
      <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
        No promotion dry-run data.
      </div>
    );
  }

  const activeDryRun = dryRun;
  const summary = activeDryRun.summary;
  const previewRows = activeDryRun.proposed_rows.slice(0, 8);
  const canAccept =
    activeDryRun.approval.status === "ready_for_dry_run" &&
    summary.proposed_insert_count > 0 &&
    acceptedBy.trim().length >= 2 &&
    acceptanceRationale.trim().length >= 12;

  async function handleAcceptanceSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canAccept) return;
    try {
      await onSubmitAcceptance({
        candidate_parameter_set: activeDryRun.candidate_parameter_set,
        decision_id: activeDryRun.approval.decision_id,
        accepted_by: acceptedBy,
        acceptance_rationale: acceptanceRationale,
        limit: 500,
        min_abs_score: summary.min_abs_score,
      });
      setAcceptanceRationale("");
    } catch {
      // The mutation hook owns the operator-facing error toast.
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">market_signals Preview</p>
          <p className="text-xs text-muted-foreground">
            {activeDryRun.baseline_parameter_set} → {activeDryRun.candidate_parameter_set}
          </p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Badge
            variant="outline"
            className={cn("font-medium", promotionDryRunApprovalClasses(activeDryRun.approval.status))}
          >
            {promotionDryRunApprovalLabel(activeDryRun.approval.status)}
          </Badge>
          <Badge variant="outline" className="border-sky-500/40 bg-sky-500/10 text-sky-600">
            Writes locked
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Proposed Rows</p>
          <p className="mt-1 font-mono text-2xl font-bold">{summary.proposed_insert_count}</p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Bullish</p>
          <p className="mt-1 font-mono text-2xl font-bold text-emerald-500">
            {summary.bullish_count}
          </p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Risk</p>
          <p className="mt-1 font-mono text-2xl font-bold text-red-500">{summary.risk_count}</p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Neutral Skipped</p>
          <p className="mt-1 font-mono text-2xl font-bold">{summary.skipped_neutral_count}</p>
        </div>
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Target</p>
          <p className="mt-1 truncate font-mono text-sm font-semibold">{summary.target_table}</p>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="overflow-hidden border border-border">
          <div className="hidden border-b border-border bg-muted/40 px-3 py-2 text-xs font-medium text-muted-foreground lg:grid lg:grid-cols-[70px_76px_64px_88px_98px_minmax(0,1fr)]">
            <span>Ticker</span>
            <span>Action</span>
            <span>Score</span>
            <span>Confidence</span>
            <span>Bar</span>
            <span>Rollback Marker</span>
          </div>
          {previewRows.length ? (
            previewRows.map((row) => <PromotionDryRunRow key={row.lineage.rollback_marker} row={row} />)
          ) : (
            <div className="p-4 text-sm text-muted-foreground">No proposed rows clear the threshold.</div>
          )}
        </div>

        <div className="space-y-3">
          <div className="border border-border p-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">Approval</h2>
              <span className="text-xs text-muted-foreground">{formatDate(activeDryRun.generated_at)}</span>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">{activeDryRun.approval.detail}</p>
            <div className="mt-3 space-y-2 text-xs">
              <div className="grid grid-cols-[86px_minmax(0,1fr)] gap-2">
                <span className="text-muted-foreground">Reviewer</span>
                <span className="truncate font-medium">{activeDryRun.approval.reviewer ?? "—"}</span>
              </div>
              <div className="grid grid-cols-[86px_minmax(0,1fr)] gap-2">
                <span className="text-muted-foreground">Decision</span>
                <span className="truncate font-mono">{activeDryRun.approval.decision_id ?? "—"}</span>
              </div>
              <div className="grid grid-cols-[86px_minmax(0,1fr)] gap-2">
                <span className="text-muted-foreground">Columns</span>
                <span className="truncate font-mono">{summary.target_columns.length}</span>
              </div>
            </div>
          </div>

          <form className="border border-border p-3" onSubmit={(event) => void handleAcceptanceSubmit(event)}>
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold">Dry-Run Acceptance</h2>
              <Badge variant="outline">
                {acceptancesLoading ? "Loading" : `${acceptances.length} saved`}
              </Badge>
            </div>
            <label className="mt-3 block space-y-1 text-xs font-medium">
              Accepted By
              <Input
                value={acceptedBy}
                onChange={(event) => setAcceptedBy(event.target.value)}
                className="h-9"
              />
            </label>
            <label className="mt-3 block space-y-1 text-xs font-medium">
              Acceptance Rationale
              <textarea
                value={acceptanceRationale}
                onChange={(event) => setAcceptanceRationale(event.target.value)}
                className="min-h-20 w-full resize-y border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
            </label>
            <div className="mt-3 flex justify-end">
              <Button type="submit" disabled={!canAccept || submittingAcceptance}>
                {submittingAcceptance ? "Saving…" : "Accept Dry-Run"}
              </Button>
            </div>

            {acceptances.length ? (
              <div className="mt-3 space-y-2">
                {acceptances.slice(0, 2).map((acceptance) => (
                  <div key={acceptance.id} className="border border-border/70 p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{acceptance.accepted_by}</span>
                      <span className="text-muted-foreground">{formatDate(acceptance.created_at)}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-muted-foreground">
                      {acceptance.acceptance_rationale}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
          </form>
        </div>
      </div>
  </div>
  );
}

function SymbolPanel({
  signal,
  transitions,
  loading,
  chart,
  chartLoading,
  chartError,
  whipsawRisk,
  whipsawLoading,
  whipsawError,
}: {
  signal: FinancialLatestSignal | null;
  transitions: FinancialSignalTransition[];
  loading: boolean;
  chart: FinancialSignalChartResponse | null;
  chartLoading: boolean;
  chartError: boolean;
  whipsawRisk: FinancialWhipsawRiskResponse | null;
  whipsawLoading: boolean;
  whipsawError: boolean;
}) {
  if (loading && !signal) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">Loading symbol detail…</CardContent>
      </Card>
    );
  }

  if (!signal) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">Select a ticker.</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="font-mono text-2xl">{signal.ticker}</CardTitle>
            <p className="text-sm text-muted-foreground">{signal.parameter_set_name}</p>
          </div>
          <div className={cn("font-mono text-3xl font-bold", scoreClasses(signal.composite_score))}>
            {signal.composite_score > 0 ? "+" : ""}
            {signal.composite_score}
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <StatePill label="M" value={signal.monthly_state} />
          <StatePill label="W" value={signal.weekly_state} />
          <StatePill label="D" value={signal.daily_state} />
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Chart Overlay</h2>
            <span className="text-xs text-muted-foreground">
              {chart?.daily_trigger_mode === "range" ? "range daily" : "close daily"} ·{" "}
              {chart?.sessions ?? 0} sessions
            </span>
          </div>
          <SignalChart chart={chart} loading={chartLoading} error={chartError} />
        </div>

        <div className="grid gap-3 text-sm sm:grid-cols-3">
          <div className="border border-border p-3">
            <p className="text-xs text-muted-foreground">Monthly Channel</p>
            <p className="mt-1 font-mono">
              {formatPrice(signal.monthly_channel_low)} / {formatPrice(signal.monthly_channel_high)}
            </p>
          </div>
          <div className="border border-border p-3">
            <p className="text-xs text-muted-foreground">Weekly Channel</p>
            <p className="mt-1 font-mono">
              {formatPrice(signal.weekly_channel_low)} / {formatPrice(signal.weekly_channel_high)}
            </p>
          </div>
          <div className="border border-border p-3">
            <p className="text-xs text-muted-foreground">Daily Channel</p>
            <p className="mt-1 font-mono">
              {formatPrice(signal.daily_channel_low)} / {formatPrice(signal.daily_channel_high)}
            </p>
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Whipsaw Risk / Backtest</h2>
            <span className="text-xs text-muted-foreground">
              {formatDate(whipsawRisk?.as_of)}
            </span>
          </div>
          <WhipsawRiskPanel
            risk={whipsawRisk}
            loading={whipsawLoading}
            error={whipsawError}
          />
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">Recent Transitions</h2>
            <span className="text-xs text-muted-foreground">{formatDate(signal.bar_date)}</span>
          </div>
          <AlertFeed transitions={transitions.slice(0, 5)} />
        </div>
      </CardContent>
    </Card>
  );
}

export function HedgeFundSignalsShell() {
  const [tickerInput, setTickerInput] = useState("");
  const [scoreBand, setScoreBand] = useState<ScoreBand>("all");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [signalModelMode, setSignalModelMode] = useState<SignalModelMode>("production");

  const activeBand = SCORE_BANDS.find((band) => band.id === scoreBand) ?? SCORE_BANDS[0];
  const activeSignalMode =
    SIGNAL_MODEL_MODES.find((mode) => mode.id === signalModelMode) ?? SIGNAL_MODEL_MODES[0];
  const activeParameterSet = activeSignalMode.parameterSet;
  const tickerQuery = tickerInput.trim().toUpperCase() || undefined;
  const latestParams = useMemo(
    () => ({
      limit: tickerQuery ? 1 : 120,
      ticker: tickerQuery,
      min_score: activeBand.min,
      max_score: activeBand.max,
      parameter_set: activeParameterSet,
    }),
    [activeBand.max, activeBand.min, activeParameterSet, tickerQuery],
  );

  const latest = useFinancialLatestSignals(latestParams);
  const transitions = useFinancialSignalTransitions({
    limit: 120,
    lookback_days: 30,
    parameter_set: activeParameterSet,
  });
  const watchlistCandidates = useFinancialWatchlistCandidates({
    limit: 8,
    parameter_set: activeParameterSet,
  });
  const dailyCalibration = useFinancialDailyCalibration({ top_tickers: 8 });
  const promotionGate = useFinancialPromotionGate({
    candidate_parameter_set: "dochia_v0_2_range_daily",
    top_tickers: 8,
  });
  const shadowReview = useFinancialShadowReview({
    candidate_parameter_set: "dochia_v0_2_range_daily",
    lookback_days: 30,
    review_limit: 8,
    whipsaw_window_sessions: 5,
    outcome_horizon_sessions: 5,
  });
  const shadowDecisionRecords = useFinancialShadowDecisionRecords({
    candidate_parameter_set: "dochia_v0_2_range_daily",
    limit: 5,
  });
  const promotionDryRun = useFinancialPromotionDryRun({
    candidate_parameter_set: "dochia_v0_2_range_daily",
    limit: 25,
    min_abs_score: 50,
  });
  const promotionDryRunAcceptances = useFinancialPromotionDryRunAcceptances({
    candidate_parameter_set: "dochia_v0_2_range_daily",
    limit: 3,
  });
  const createShadowDecisionRecord = useCreateFinancialShadowDecisionRecord();
  const createPromotionDryRunAcceptance = useCreateFinancialPromotionDryRunAcceptance();
  const signals = latest.data ?? EMPTY_SIGNALS;
  const alertRows = transitions.data ?? EMPTY_TRANSITIONS;
  const watchlistLanes = watchlistCandidates.data?.lanes ?? EMPTY_LANES;
  const activeTicker = selectedTicker ?? signals[0]?.ticker ?? null;
  const detail = useFinancialSignalDetail(activeTicker, {
    transition_limit: 12,
    lookback_days: 30,
    parameter_set: activeParameterSet,
  });
  const chart = useFinancialSignalChart(activeTicker, {
    sessions: 180,
    parameter_set: activeParameterSet,
  });
  const whipsawRisk = useFinancialWhipsawRisk(activeTicker, {
    sessions: 260,
    parameter_set: activeParameterSet,
    whipsaw_window_sessions: 5,
    outcome_horizon_sessions: 5,
  });

  const selectedSignal =
    detail.data?.latest ?? signals.find((signal) => signal.ticker === activeTicker) ?? null;
  const selectedTransitions =
    detail.data?.recent_transitions ??
    alertRows.filter((item) => item.ticker === activeTicker).slice(0, 12);

  const metrics = useMemo(() => {
    const bullish = signals.filter((item) => item.composite_score >= 50).length;
    const bearish = signals.filter((item) => item.composite_score <= -50).length;
    const reentries = alertRows.filter((item) => item.transition_type === "exit_to_reentry").length;
    const latestDate = signals[0]?.bar_date ?? null;
    return { bullish, bearish, reentries, latestDate };
  }, [alertRows, signals]);

  const isRefreshing =
    latest.isFetching ||
    transitions.isFetching ||
    detail.isFetching ||
    chart.isFetching ||
    whipsawRisk.isFetching ||
    watchlistCandidates.isFetching ||
    dailyCalibration.isFetching ||
    promotionGate.isFetching ||
    shadowReview.isFetching ||
    shadowDecisionRecords.isFetching ||
    promotionDryRun.isFetching ||
    promotionDryRunAcceptances.isFetching;

  async function handleShadowDecisionSubmit(payload: FinancialShadowReviewDecisionRecordCreate) {
    await createShadowDecisionRecord.mutateAsync(payload);
    void shadowDecisionRecords.refetch();
  }

  async function handlePromotionDryRunAcceptanceSubmit(
    payload: FinancialPromotionDryRunAcceptanceCreate,
  ) {
    await createPromotionDryRunAcceptance.mutateAsync(payload);
    void promotionDryRunAcceptances.refetch();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">Hedge Fund Signals</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Dochia v0 daily, weekly, and monthly signal cockpit.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <div className="flex h-10 items-center gap-1 border border-border bg-background p-1">
            {SIGNAL_MODEL_MODES.map((mode) => (
              <Button
                key={mode.id}
                type="button"
                size="sm"
                variant={signalModelMode === mode.id ? "default" : "ghost"}
                className="h-8 px-3"
                onClick={() => {
                  setSignalModelMode(mode.id);
                  setSelectedTicker(null);
                }}
                aria-pressed={signalModelMode === mode.id}
              >
                {mode.label}
              </Button>
            ))}
          </div>
          <Badge variant="outline" className="font-mono">
            {activeSignalMode.badge}
          </Badge>
          <Badge variant="outline" className="gap-1 border-amber-500/40 bg-amber-500/10 text-amber-600">
            <Info className="h-3 w-3" />
            Calibration pending
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="icon"
            onClick={() => {
              void latest.refetch();
              void transitions.refetch();
              void detail.refetch();
              void chart.refetch();
              void whipsawRisk.refetch();
              void watchlistCandidates.refetch();
              void dailyCalibration.refetch();
              void promotionGate.refetch();
              void shadowReview.refetch();
              void shadowDecisionRecords.refetch();
              void promotionDryRun.refetch();
              void promotionDryRunAcceptances.refetch();
            }}
            disabled={isRefreshing}
            aria-label="Refresh hedge fund signals"
          >
            <RefreshCw className={cn("h-4 w-4", isRefreshing && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Visible Tickers"
          value={String(signals.length)}
          sub={metrics.latestDate ? `Latest ${formatDate(metrics.latestDate)}` : "No score rows"}
          icon={Activity}
        />
        <KpiCard
          label="Bullish Alignment"
          value={String(metrics.bullish)}
          sub="Composite score +50 or higher"
          icon={ArrowUpRight}
          tone="green"
        />
        <KpiCard
          label="Risk Alignment"
          value={String(metrics.bearish)}
          sub="Composite score -50 or lower"
          icon={ArrowDownRight}
          tone="red"
        />
        <KpiCard
          label="Re-entry Alerts"
          value={String(metrics.reentries)}
          sub="Recent transition window"
          icon={ShieldAlert}
          tone="amber"
        />
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <BriefcaseBusiness className="h-5 w-5 text-primary" />
            <CardTitle>Portfolio Lens</CardTitle>
          </div>
          <Badge variant="outline">
            {watchlistCandidates.data ? formatDate(watchlistCandidates.data.generated_at) : "—"}
          </Badge>
        </CardHeader>
        <CardContent>
          <WatchlistLanes
            lanes={watchlistLanes}
            loading={watchlistCandidates.isLoading}
            error={watchlistCandidates.isError}
            onSelect={setSelectedTicker}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Gauge className="h-5 w-5 text-primary" />
            <CardTitle>Calibration Baseline</CardTitle>
          </div>
          <Badge variant="outline">
            {dailyCalibration.data ? formatDate(dailyCalibration.data.generated_at) : "—"}
          </Badge>
        </CardHeader>
        <CardContent>
          <CalibrationPanel
            calibration={dailyCalibration.data ?? null}
            loading={dailyCalibration.isLoading}
            error={dailyCalibration.isError}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-primary" />
            <CardTitle>Promotion Gate</CardTitle>
          </div>
          <Badge variant="outline">
            {promotionGate.data ? formatDate(promotionGate.data.generated_at) : "—"}
          </Badge>
        </CardHeader>
        <CardContent>
          <PromotionGatePanel
            gate={promotionGate.data ?? null}
            loading={promotionGate.isLoading}
            error={promotionGate.isError}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-5 w-5 text-primary" />
            <CardTitle>Shadow Review</CardTitle>
          </div>
          <Badge variant="outline">
            {shadowReview.data ? formatDate(shadowReview.data.generated_at) : "—"}
          </Badge>
        </CardHeader>
        <CardContent>
          <ShadowReviewPanel
            review={shadowReview.data ?? null}
            loading={shadowReview.isLoading}
            error={shadowReview.isError}
            decisionRecords={shadowDecisionRecords.data ?? []}
            decisionRecordsLoading={shadowDecisionRecords.isLoading}
            onSubmitDecision={handleShadowDecisionSubmit}
            submittingDecision={createShadowDecisionRecord.isPending}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <FileSearch className="h-5 w-5 text-primary" />
            <CardTitle>Promotion Dry-Run</CardTitle>
          </div>
          <Badge variant="outline">
            {promotionDryRun.data ? formatDate(promotionDryRun.data.generated_at) : "—"}
          </Badge>
        </CardHeader>
        <CardContent>
          <PromotionDryRunPanel
            dryRun={promotionDryRun.data ?? null}
            loading={promotionDryRun.isLoading}
            error={promotionDryRun.isError}
            acceptances={promotionDryRunAcceptances.data ?? []}
            acceptancesLoading={promotionDryRunAcceptances.isLoading}
            onSubmitAcceptance={handlePromotionDryRunAcceptanceSubmit}
            submittingAcceptance={createPromotionDryRunAcceptance.isPending}
          />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(360px,0.8fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle>Signal Scanner</CardTitle>
                <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
                  <div className="relative sm:w-56">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={tickerInput}
                      onChange={(event) => {
                        setTickerInput(event.target.value);
                        setSelectedTicker(null);
                      }}
                      className="pl-9 font-mono uppercase"
                      placeholder="Ticker"
                    />
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {SCORE_BANDS.map((band) => (
                      <Button
                        key={band.id}
                        type="button"
                        size="sm"
                        variant={scoreBand === band.id ? "default" : "outline"}
                        onClick={() => {
                          setScoreBand(band.id);
                          setSelectedTicker(null);
                        }}
                      >
                        {band.label}
                      </Button>
                    ))}
                  </div>
                </div>
              </div>
              {latest.isError ? (
                <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertTriangle className="h-4 w-4" />
                  Signal scanner unavailable.
                </div>
              ) : null}
            </CardHeader>
            <CardContent>
              {latest.isLoading ? (
                <div className="py-10 text-sm text-muted-foreground">Loading scanner…</div>
              ) : signals.length ? (
                <SignalTable
                  signals={signals}
                  selectedTicker={activeTicker}
                  onSelect={setSelectedTicker}
                />
              ) : (
                <div className="border border-dashed border-border p-5 text-sm text-muted-foreground">
                  No signal rows match the current filter.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Score Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <ScoreDistribution signals={signals} />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <SymbolPanel
            signal={selectedSignal}
            transitions={selectedTransitions}
            loading={detail.isLoading}
            chart={chart.data ?? null}
            chartLoading={chart.isLoading}
            chartError={chart.isError}
            whipsawRisk={whipsawRisk.data ?? null}
            whipsawLoading={whipsawRisk.isLoading}
            whipsawError={whipsawRisk.isError}
          />

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle>Alert Feed</CardTitle>
              <Badge variant="outline">{alertRows.length}</Badge>
            </CardHeader>
            <CardContent>
              {transitions.isError ? (
                <div className="flex items-center gap-2 border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertTriangle className="h-4 w-4" />
                  Transition feed unavailable.
                </div>
              ) : transitions.isLoading ? (
                <div className="py-8 text-sm text-muted-foreground">Loading alerts…</div>
              ) : (
                <AlertFeed transitions={alertRows} />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
