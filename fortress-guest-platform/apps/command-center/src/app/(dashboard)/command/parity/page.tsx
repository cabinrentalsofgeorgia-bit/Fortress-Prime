"use client";

import Link from "next/link";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  Eye,
  LineChart,
  Radar,
  RefreshCw,
  Search,
  Shield,
  TrendingUp,
} from "lucide-react";

import { useParityDashboard, useTriggerSeoParityObservation } from "@/lib/hooks";
import { MarketIntelligenceFeed } from "./_components/market-intelligence-feed";
import { RecoveryDraftParity } from "./_components/recovery-draft-parity";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function formatPercent(value: number): string {
  const normalized = value <= 1 ? value * 100 : value;
  return `${normalized.toFixed(1)}%`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string): string {
  switch (status) {
    case "observation":
    case "active":
    case "online":
    case "observing":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "alert":
    case "degraded":
    case "error":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    case "not_configured":
    case "inactive":
      return "border-zinc-700 bg-zinc-900/80 text-zinc-300";
    default:
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  }
}

function driftTone(driftStatus: string | null | undefined): string {
  switch (driftStatus) {
    case "MATCH":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "CRITICAL_MISMATCH":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    default:
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  }
}

function quoteRunCardTone(status: string, driftStatus: string | null | undefined): string {
  if (status === "failed" || driftStatus === "CRITICAL_MISMATCH") {
    return "border-rose-500/30 bg-rose-950/20";
  }
  if (driftStatus === "MINOR_DRIFT") {
    return "border-amber-500/30 bg-amber-950/20";
  }
  return "border-zinc-800 bg-zinc-900/70";
}

function isCriticalSeoRun(status: string, error: string | null | undefined): boolean {
  return status === "failed" || Boolean(error);
}

function seoRunCardTone(status: string, error: string | null | undefined): string {
  if (isCriticalSeoRun(status, error)) {
    return "border-rose-500/30 bg-rose-950/20";
  }
  if (status === "running" || status === "queued" || status === "cancelled") {
    return "border-amber-500/30 bg-amber-950/20";
  }
  return "border-zinc-800 bg-zinc-900/70";
}

export default function ParityDashboardPage() {
  const { data, isLoading, error } = useParityDashboard();
  const triggerSeoObservation = useTriggerSeoParityObservation();
  const [quoteRunFilter, setQuoteRunFilter] = useState<"all" | "critical">("all");
  const [quoteTraceFilter, setQuoteTraceFilter] = useState<"all" | "critical">("all");
  const [seoRunFilter, setSeoRunFilter] = useState<"all" | "critical">("all");

  if (isLoading && !data) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-cyan-200">
            <Radar className="h-3.5 w-3.5" />
            Shadow Parallel
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Parity Dashboard</h1>
        </div>
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardContent className="pt-6 text-sm text-zinc-400">
            Loading sovereign-vs-legacy observation telemetry...
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
            Shadow Parallel
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Parity Dashboard</h1>
        </div>
        <Card className="border-rose-500/20 bg-zinc-950/90">
          <CardContent className="pt-6 text-sm text-zinc-300">
            {error instanceof Error ? error.message : "Parity telemetry is unavailable."}
          </CardContent>
        </Card>
      </div>
    );
  }

  const {
    shadow_mode,
    quote_parity,
    quote_observer,
    quote_observer_recent_runs,
    seo_parity,
    seo_observer,
    seo_observer_recent_runs,
    scout_observer,
    concierge_observer,
    market_intelligence_feed,
    scout_alpha_conversion,
    recovery_ghosts,
    recovery_comparisons,
    legacy_targets,
    agentic_observation,
  } = data;
  const criticalQuoteRunCount = quote_observer_recent_runs.filter(
    (run) => run.status === "failed" || run.drift_status === "CRITICAL_MISMATCH",
  ).length;
  const visibleQuoteObserverRuns =
    quoteRunFilter === "critical"
      ? quote_observer_recent_runs.filter(
          (run) => run.status === "failed" || run.drift_status === "CRITICAL_MISMATCH",
        )
      : quote_observer_recent_runs;
  const criticalQuoteTraceCount = quote_parity.recent_traces.filter(
    (trace) => trace.drift_status === "CRITICAL_MISMATCH",
  ).length;
  const visibleQuoteTraces =
    quoteTraceFilter === "critical"
      ? quote_parity.recent_traces.filter((trace) => trace.drift_status === "CRITICAL_MISMATCH")
      : quote_parity.recent_traces;
  const criticalSeoRunCount = seo_observer_recent_runs.filter((run) =>
    isCriticalSeoRun(run.status, run.error),
  ).length;
  const visibleSeoObserverRuns =
    seoRunFilter === "critical"
      ? seo_observer_recent_runs.filter((run) => isCriticalSeoRun(run.status, run.error))
      : seo_observer_recent_runs;

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.28em] text-cyan-200">
          <Eye className="h-3.5 w-3.5" />
          Shadow Parallel
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-zinc-50">Parity Dashboard</h1>
            <p className="mt-1 max-w-3xl text-sm text-zinc-400">
              Live sovereign-vs-legacy proof while Drupal, Streamline, and Rue Ba Rue remain the
              primary authority.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/"
              className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
            >
              God View
            </Link>
            <Link
              href="/api/openshell/audit/log?resource_type=shadow_quote_audit"
              target="_blank"
              className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20"
            >
              OpenShell Audit
            </Link>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-4">
        <Card
          className={`bg-zinc-950/90 ${
            quote_observer.last_drift_status === "CRITICAL_MISMATCH"
              ? "border-rose-500/30"
              : "border-cyan-500/20"
          }`}
        >
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Radar className="h-5 w-5 text-cyan-300" />
              Observation Mode
            </CardTitle>
            <CardDescription>Swarm posture and live authority boundary.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] ${statusTone(shadow_mode.status)}`}>
              {shadow_mode.status}
            </span>
            <p className="text-sm text-zinc-100">{shadow_mode.legacy_authority}</p>
            <p className="text-sm text-zinc-400">{shadow_mode.message}</p>
          </CardContent>
        </Card>

        <Card className="border-emerald-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Shield className="h-5 w-5 text-emerald-300" />
              Quote Parity
            </CardTitle>
            <CardDescription>Streamline versus sovereign checkout observation.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            <div className="text-4xl font-semibold tracking-tight text-zinc-50">
              {formatPercent(quote_parity.accuracy_rate)}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Gate Progress</p>
                <p className="mt-2 text-lg font-semibold text-zinc-100">{quote_parity.gate_progress}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Tax Accuracy</p>
                <p className="mt-2 text-lg font-semibold text-zinc-100">
                  {formatPercent(quote_parity.tax_accuracy_rate)}
                </p>
              </div>
            </div>
            <p className="text-sm text-zinc-400">
              Avg base drift {formatPercent(quote_parity.avg_base_drift_pct)}. Kill switch{" "}
              {quote_parity.kill_switch_armed ? "armed" : "clear"}.
            </p>
          </CardContent>
        </Card>

        <Card className="border-amber-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <TrendingUp className="h-5 w-5 text-amber-300" />
              Recovery Ghosts
            </CardTitle>
            <CardDescription>Recovered revenue and missed legacy recovery opportunities.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            <div className="text-4xl font-semibold tracking-tight text-zinc-50">
              {recovery_ghosts.total_resurrections}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Soft Landed Losses</p>
                <p className="mt-2 text-lg font-semibold text-zinc-100">
                  {recovery_ghosts.soft_landed_losses}
                </p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Signature Health</p>
                <p className="mt-2 text-lg font-semibold text-zinc-100">
                  {formatPercent(recovery_ghosts.signature_health_pct)}
                </p>
              </div>
            </div>
            <p className="text-sm text-zinc-400">
              {recovery_ghosts.total_events} recovery events observed in the active window.
            </p>
          </CardContent>
        </Card>

        <Card className="border-fuchsia-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Bot className="h-5 w-5 text-fuchsia-300" />
              Agentic Observation
            </CardTitle>
            <CardDescription>Live orchestrator posture across sovereign lanes.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] ${statusTone(agentic_observation.orchestrator_status)}`}>
              {agentic_observation.orchestrator_status}
            </span>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Automation Rate</p>
                <p className="mt-2 text-lg font-semibold text-zinc-100">
                  {formatPercent(agentic_observation.automation_rate_pct)}
                </p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Messages Observed</p>
                <p className="mt-2 text-lg font-semibold text-zinc-100">
                  {agentic_observation.total_messages}
                </p>
              </div>
            </div>
            <p className="text-sm text-zinc-400">
              Concierge {agentic_observation.lanes.concierge}, SEO {agentic_observation.lanes.seo_swarm},
              Yield {agentic_observation.lanes.yield_engine}.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-violet-500/20 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <LineChart className="h-5 w-5 text-violet-300" />
            SEMRush Observation Lane
          </CardTitle>
          <CardDescription>Legacy SEO score capture versus sovereign God Head output.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 pt-6 md:grid-cols-4">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Status</p>
            <span className={`mt-3 inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(seo_parity.status)}`}>
              {seo_parity.status}
            </span>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Legacy Avg</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">
              {seo_parity.avg_legacy_score.toFixed(1)}
            </p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Sovereign Avg</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">
              {seo_parity.avg_sovereign_score.toFixed(1)}
            </p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Avg Uplift</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">
              {seo_parity.avg_uplift_pct_points.toFixed(1)}
            </p>
          </div>
          <div className="md:col-span-4 flex flex-wrap items-center justify-between gap-3 text-sm text-zinc-400">
            <p>
              Observed {seo_parity.observed_count} pages. Superior {seo_parity.superior_count}, parity{" "}
              {seo_parity.parity_count}, trailing {seo_parity.trailing_count}, missing sovereign{" "}
              {seo_parity.missing_sovereign_count}.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={() => triggerSeoObservation.mutate()}
                disabled={triggerSeoObservation.isPending || !shadow_mode.active}
                className="bg-violet-600 text-white hover:bg-violet-500 disabled:bg-zinc-800 disabled:text-zinc-500"
              >
                <RefreshCw
                  className={`mr-2 h-4 w-4 ${triggerSeoObservation.isPending ? "animate-spin" : ""}`}
                />
                Run Observation Now
              </Button>
              <Link
                href="/api/openshell/audit/log?resource_type=shadow_seo_audit"
                target="_blank"
                className="rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-100 hover:bg-violet-500/20"
              >
                SEO Audit Lane
              </Link>
              <span className="text-xs text-zinc-500">
                Last observed {formatTimestamp(seo_parity.last_observed_at)}
              </span>
            </div>
          </div>
          {seo_parity.snapshot_path ? (
            <div className="md:col-span-4 text-xs text-zinc-500">
              Snapshot source: {seo_parity.snapshot_path}
            </div>
          ) : null}
          {!shadow_mode.active ? (
            <div className="md:col-span-4 text-xs text-zinc-500">
              Manual strike is disabled until `AGENTIC_SYSTEM_ACTIVE` is armed.
            </div>
          ) : null}
        </CardContent>
      </Card>

      <MarketIntelligenceFeed
        items={market_intelligence_feed}
        observer={scout_observer}
        alpha={scout_alpha_conversion}
      />

      <RecoveryDraftParity observer={concierge_observer} comparisons={recovery_comparisons} />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-cyan-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="text-zinc-50">Quote Observer Health</CardTitle>
            <CardDescription>Async shadow-audit posture for Streamline quote requests.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 pt-6 md:grid-cols-4">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Observer</p>
              <span className={`mt-3 inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(quote_observer.last_job_status)}`}>
                {quote_observer.last_job_status}
              </span>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Queued</p>
              <p className="mt-2 text-2xl font-semibold text-zinc-100">{quote_observer.queue_depth}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Running</p>
              <p className="mt-2 text-2xl font-semibold text-zinc-100">{quote_observer.running_jobs}</p>
            </div>
            <div className={`rounded-xl border px-4 py-4 ${quoteRunCardTone(quote_observer.last_job_status, quote_observer.last_drift_status)}`}>
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Drift</p>
              <div className="mt-2">
                <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${driftTone(quote_observer.last_drift_status)}`}>
                  {quote_observer.last_drift_status || "unknown"}
                </span>
              </div>
            </div>
            <div className="md:col-span-4 grid gap-3 text-sm text-zinc-400 md:grid-cols-4">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Quote</p>
                <p className="mt-2 text-zinc-100">{quote_observer.last_quote_id || "--"}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Job Created</p>
                <p className="mt-2 text-zinc-100">{formatTimestamp(quote_observer.last_job_created_at)}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Success</p>
                <p className="mt-2 text-zinc-100">{formatTimestamp(quote_observer.last_success_at)}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Audit Write</p>
                <p className="mt-2 text-zinc-100">{formatTimestamp(quote_observer.last_audit_at)}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card
          className={`bg-zinc-950/90 ${
            seo_observer.last_job_status === "failed" ? "border-rose-500/30" : "border-sky-500/20"
          }`}
        >
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="text-zinc-50">SEMRush Scheduler Health</CardTitle>
            <CardDescription>Worker cadence and latest automatic observation activity.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 pt-6 md:grid-cols-5">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Observer</p>
              <span className={`mt-3 inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(seo_observer.last_job_status)}`}>
                {seo_observer.enabled ? seo_observer.last_job_status : "disabled"}
              </span>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Interval</p>
              <p className="mt-2 text-2xl font-semibold text-zinc-100">
                {Math.round(seo_observer.interval_seconds / 60)}m
              </p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Queued</p>
              <p className="mt-2 text-2xl font-semibold text-zinc-100">{seo_observer.queue_depth}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Running</p>
              <p className="mt-2 text-2xl font-semibold text-zinc-100">{seo_observer.running_jobs}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Agentic Gate</p>
              <p className="mt-2 text-sm font-semibold text-zinc-100">
                {seo_observer.agentic_system_active ? "armed" : "inactive"}
              </p>
            </div>
            <div className="md:col-span-5 grid gap-3 text-sm text-zinc-400 md:grid-cols-3">
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Job Created</p>
                <p className="mt-2 text-zinc-100">{formatTimestamp(seo_observer.last_job_created_at)}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Success</p>
                <p className="mt-2 text-zinc-100">{formatTimestamp(seo_observer.last_success_at)}</p>
              </div>
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
                <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Audit Write</p>
                <p className="mt-2 text-zinc-100">{formatTimestamp(seo_observer.last_audit_at)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-cyan-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="text-zinc-50">Quote Observation Runs</CardTitle>
                <CardDescription>Recent Streamline shadow audit jobs from the async ledger.</CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setQuoteRunFilter("all")}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium uppercase tracking-[0.24em] ${
                    quoteRunFilter === "all"
                      ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-100"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                  }`}
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => setQuoteRunFilter("critical")}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium uppercase tracking-[0.24em] ${
                    quoteRunFilter === "critical"
                      ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                  }`}
                >
                  Critical Only
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {criticalQuoteRunCount > 0 ? (
              <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 px-4 py-3 text-sm text-rose-100">
                {criticalQuoteRunCount} critical quote run
                {criticalQuoteRunCount === 1 ? "" : "s"} detected in the recent ledger window.
              </div>
            ) : null}
            {visibleQuoteObserverRuns.length === 0 ? (
              <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
                {quoteRunFilter === "critical"
                  ? "No critical quote observation runs in the recent ledger window."
                  : "No quote observation runs have been recorded yet."}
              </div>
            ) : (
              visibleQuoteObserverRuns.map((run) => (
                <div
                  key={run.job_id}
                  className={`rounded-xl border px-4 py-4 ${quoteRunCardTone(run.status, run.drift_status)}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-zinc-100">{run.job_id}</p>
                      <p className="mt-1 text-xs text-zinc-500">
                        Quote {run.quote_id || "--"} by {run.requested_by || "unknown"} at{" "}
                        {formatTimestamp(run.created_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(run.status)}`}>
                        {run.status}
                      </span>
                      <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${driftTone(run.drift_status)}`}>
                        {run.drift_status || "unknown"}
                      </span>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Drift</p>
                      <p className="mt-1 text-sm text-zinc-100">{run.drift_status || "--"}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Trace</p>
                      <p className="mt-1 break-all text-sm text-zinc-100">{run.trace_id || "--"}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Finished</p>
                      <p className="mt-1 text-sm text-zinc-100">{formatTimestamp(run.finished_at)}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Link
                      href={run.async_job_href}
                      target="_blank"
                      className="inline-flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100 hover:bg-sky-500/20"
                    >
                      Job detail
                      <ArrowUpRight className="h-4 w-4" />
                    </Link>
                    <Link
                      href={run.audit_log_href}
                      target="_blank"
                      className="inline-flex items-center gap-1 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20"
                    >
                      Audit evidence
                      <ArrowUpRight className="h-4 w-4" />
                    </Link>
                  </div>
                  {run.error ? <p className="mt-3 text-sm text-rose-300">{run.error}</p> : null}
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-sky-500/20 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="text-zinc-50">SEMRush Observation Runs</CardTitle>
                <CardDescription>Recent manual and scheduled parity strikes from the async job ledger.</CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setSeoRunFilter("all")}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium uppercase tracking-[0.24em] ${
                    seoRunFilter === "all"
                      ? "border-sky-500/30 bg-sky-500/10 text-sky-100"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                  }`}
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => setSeoRunFilter("critical")}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium uppercase tracking-[0.24em] ${
                    seoRunFilter === "critical"
                      ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                  }`}
                >
                  Critical Only
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {criticalSeoRunCount > 0 ? (
              <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 px-4 py-3 text-sm text-rose-100">
                {criticalSeoRunCount} critical SEMRush run
                {criticalSeoRunCount === 1 ? "" : "s"} detected in the recent ledger window.
              </div>
            ) : null}
            {visibleSeoObserverRuns.length === 0 ? (
              <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
                {seoRunFilter === "critical"
                  ? "No critical SEMRush observation runs in the recent ledger window."
                  : "No SEMRush observation runs have been recorded yet."}
              </div>
            ) : (
              visibleSeoObserverRuns.map((run) => (
                <div
                  key={run.job_id}
                  className={`rounded-xl border px-4 py-4 ${seoRunCardTone(run.status, run.error)}`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-zinc-100">{run.job_id}</p>
                      <p className="mt-1 text-xs text-zinc-500">
                        {run.trigger_mode} strike by {run.requested_by || "unknown"} at{" "}
                        {formatTimestamp(run.created_at)}
                      </p>
                    </div>
                    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(run.status)}`}>
                      {run.status}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Observed</p>
                      <p className="mt-1 text-sm text-zinc-100">
                        {run.observed_count == null ? "--" : run.observed_count}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Superior</p>
                      <p className="mt-1 text-sm text-zinc-100">
                        {run.superior_count == null ? "--" : run.superior_count}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Finished</p>
                      <p className="mt-1 text-sm text-zinc-100">{formatTimestamp(run.finished_at)}</p>
                    </div>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Link
                      href={run.async_job_href}
                      target="_blank"
                      className="inline-flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100 hover:bg-sky-500/20"
                    >
                      Job detail
                      <ArrowUpRight className="h-4 w-4" />
                    </Link>
                    <Link
                      href={run.audit_log_href}
                      target="_blank"
                      className="inline-flex items-center gap-1 rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-100 hover:bg-violet-500/20"
                    >
                      Audit evidence
                      <ArrowUpRight className="h-4 w-4" />
                    </Link>
                  </div>
                  {run.error ? (
                    <p className="mt-3 text-sm text-rose-300">{run.error}</p>
                  ) : null}
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-zinc-950/90">
        <CardHeader className="border-b border-zinc-800/80">
          <CardTitle className="flex items-center gap-2 text-zinc-50">
            <Search className="h-5 w-5 text-zinc-300" />
            Legacy Target Scorecards
          </CardTitle>
          <CardDescription>Observation status for the strangled legacy lanes.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 pt-6 md:grid-cols-2 xl:grid-cols-3">
          {legacy_targets.map((target) => (
            <article key={target.target_id} className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-zinc-100">{target.label}</p>
                  <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">
                    {target.legacy_system}
                  </p>
                </div>
                <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(target.status)}`}>
                  {target.status}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Observed</p>
                  <p className="mt-1 text-lg font-semibold text-zinc-100">{target.observed_count}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Score</p>
                  <p className="mt-1 text-lg font-semibold text-zinc-100">
                    {target.score_pct == null ? "--" : formatPercent(target.score_pct)}
                  </p>
                </div>
              </div>
              <p className="mt-4 text-sm text-zinc-400">{target.proof}</p>
              <p className="mt-3 text-xs text-zinc-500">
                Last observed {formatTimestamp(target.last_observed_at)}
              </p>
            </article>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle className="text-zinc-50">Recent Shadow Traces</CardTitle>
                <CardDescription>Latest quote audits written into OpenShell.</CardDescription>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setQuoteTraceFilter("all")}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium uppercase tracking-[0.24em] ${
                    quoteTraceFilter === "all"
                      ? "border-cyan-500/30 bg-cyan-500/10 text-cyan-100"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                  }`}
                >
                  All
                </button>
                <button
                  type="button"
                  onClick={() => setQuoteTraceFilter("critical")}
                  className={`rounded-md border px-3 py-1.5 text-xs font-medium uppercase tracking-[0.24em] ${
                    quoteTraceFilter === "critical"
                      ? "border-rose-500/30 bg-rose-500/10 text-rose-100"
                      : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800"
                  }`}
                >
                  Critical Only
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 pt-6">
            {criticalQuoteTraceCount > 0 ? (
              <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 px-4 py-3 text-sm text-rose-100">
                {criticalQuoteTraceCount} critical trace
                {criticalQuoteTraceCount === 1 ? "" : "s"} detected in recent audit evidence.
              </div>
            ) : null}
            {visibleQuoteTraces.length === 0 ? (
              <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
                {quoteTraceFilter === "critical"
                  ? "No critical shadow traces in the recent audit window."
                  : "No shadow traces observed yet."}
              </div>
            ) : (
              visibleQuoteTraces.map((trace) => (
                <div
                  key={trace.trace_id}
                  className={`rounded-xl border px-4 py-4 ${quoteRunCardTone("succeeded", trace.drift_status)}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium text-zinc-100">{trace.trace_id}</p>
                      <p className="mt-1 text-xs text-zinc-500">{formatTimestamp(trace.created_at)}</p>
                    </div>
                    <span className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${driftTone(trace.drift_status)}`}>
                      {trace.drift_status}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Legacy</p>
                      <p className="mt-1 text-sm text-zinc-100">${trace.legacy_total.toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Sovereign</p>
                      <p className="mt-1 text-sm text-zinc-100">${trace.sovereign_total.toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Drift</p>
                      <p className="mt-1 text-sm text-zinc-100">{formatPercent(trace.total_drift_pct)}</p>
                    </div>
                  </div>
                  <div className="mt-4">
                    <div className="flex flex-wrap gap-2">
                      {trace.async_job_href ? (
                        <Link
                          href={trace.async_job_href}
                          target="_blank"
                          className="inline-flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-100 hover:bg-sky-500/20"
                        >
                          Job detail
                          <ArrowUpRight className="h-4 w-4" />
                        </Link>
                      ) : null}
                      <Link
                        href={trace.audit_log_href}
                        target="_blank"
                        className="inline-flex items-center gap-1 rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 hover:bg-cyan-500/20"
                      >
                        Audit evidence
                        <ArrowUpRight className="h-4 w-4" />
                      </Link>
                    </div>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-zinc-950/90">
          <CardHeader className="border-b border-zinc-800/80">
            <CardTitle className="text-zinc-50">Recovery Proof</CardTitle>
            <CardDescription>Top recovered slugs and soft-landed misses in the active window.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 pt-6 md:grid-cols-2">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Recovered Slugs</p>
              <div className="mt-3 space-y-3">
                {recovery_ghosts.top_recovered_slugs.length === 0 ? (
                  <p className="text-sm text-zinc-400">No recovered slugs yet.</p>
                ) : (
                  recovery_ghosts.top_recovered_slugs.map((slug) => (
                    <div key={slug.slug} className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-zinc-200">{slug.slug}</span>
                      <span className="text-zinc-500">{slug.count}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 p-4">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Soft-Landed Misses</p>
              <div className="mt-3 space-y-3">
                {recovery_ghosts.top_soft_landed_slugs.length === 0 ? (
                  <p className="text-sm text-zinc-400">No soft-landed losses yet.</p>
                ) : (
                  recovery_ghosts.top_soft_landed_slugs.map((slug) => (
                    <div key={slug.slug} className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-zinc-200">{slug.slug}</span>
                      <span className="text-zinc-500">{slug.count}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
