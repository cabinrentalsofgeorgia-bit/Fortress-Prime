"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BriefcaseBusiness,
  Gauge,
  Info,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";

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
  useFinancialLatestSignals,
  useFinancialDailyCalibration,
  useFinancialSignalDetail,
  useFinancialSignalTransitions,
  useFinancialWatchlistCandidates,
} from "@/lib/hooks";
import type {
  FinancialDailyCalibrationResponse,
  FinancialLatestSignal,
  FinancialSignalTransition,
  FinancialTransitionType,
  FinancialWatchlistCandidate,
  FinancialWatchlistCandidateLane,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type ScoreBand = "all" | "bullish" | "neutral" | "risk";

const SCORE_BANDS: Array<{ id: ScoreBand; label: string; min?: number; max?: number }> = [
  { id: "all", label: "All" },
  { id: "bullish", label: "Bullish", min: 50 },
  { id: "neutral", label: "Neutral", min: -30, max: 30 },
  { id: "risk", label: "Risk", max: -50 },
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
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
        <div className="border border-border p-3">
          <p className="text-xs text-muted-foreground">Daily Color Accuracy</p>
          <p className="mt-1 font-mono text-2xl font-bold">
            {formatPercent(calibration.accuracy)}
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

function SymbolPanel({
  signal,
  transitions,
  loading,
}: {
  signal: FinancialLatestSignal | null;
  transitions: FinancialSignalTransition[];
  loading: boolean;
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

  const activeBand = SCORE_BANDS.find((band) => band.id === scoreBand) ?? SCORE_BANDS[0];
  const tickerQuery = tickerInput.trim().toUpperCase() || undefined;
  const latestParams = useMemo(
    () => ({
      limit: tickerQuery ? 1 : 120,
      ticker: tickerQuery,
      min_score: activeBand.min,
      max_score: activeBand.max,
    }),
    [activeBand.max, activeBand.min, tickerQuery],
  );

  const latest = useFinancialLatestSignals(latestParams);
  const transitions = useFinancialSignalTransitions({ limit: 120, lookback_days: 30 });
  const watchlistCandidates = useFinancialWatchlistCandidates({ limit: 8 });
  const dailyCalibration = useFinancialDailyCalibration({ top_tickers: 8 });
  const signals = latest.data ?? EMPTY_SIGNALS;
  const alertRows = transitions.data ?? EMPTY_TRANSITIONS;
  const watchlistLanes = watchlistCandidates.data?.lanes ?? EMPTY_LANES;
  const activeTicker = selectedTicker ?? signals[0]?.ticker ?? null;
  const detail = useFinancialSignalDetail(activeTicker, {
    transition_limit: 12,
    lookback_days: 30,
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
    watchlistCandidates.isFetching ||
    dailyCalibration.isFetching;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">Hedge Fund Signals</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Dochia v0 daily, weekly, and monthly signal cockpit.
          </p>
        </div>
        <div className="flex items-center gap-2">
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
              void watchlistCandidates.refetch();
              void dailyCalibration.refetch();
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
