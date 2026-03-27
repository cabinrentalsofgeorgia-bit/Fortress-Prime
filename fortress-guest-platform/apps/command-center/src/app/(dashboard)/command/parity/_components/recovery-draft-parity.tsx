"use client";

import { MessageCircle } from "lucide-react";

import type {
  ConciergeAlphaObserverStatusResponse,
  RecoveryDraftComparisonResponse,
} from "@/lib/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string): string {
  switch (status) {
    case "succeeded":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "failed":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    case "inactive":
    case "idle":
      return "border-zinc-700 bg-zinc-900/80 text-zinc-300";
    default:
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  }
}

type RecoveryDraftParityProps = {
  observer: ConciergeAlphaObserverStatusResponse;
  comparisons: RecoveryDraftComparisonResponse[];
};

export function RecoveryDraftParity({ observer, comparisons }: RecoveryDraftParityProps) {
  const laneDisabled = !observer.enabled || !observer.agentic_system_active;

  return (
    <Card className="border-teal-500/20 bg-zinc-950/90">
      <CardHeader className="border-b border-zinc-800/80">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <MessageCircle className="h-5 w-5 text-teal-300" />
              Recovery Draft Parity
            </CardTitle>
            <CardDescription>
              Rue Ba Rue legacy SMS template vs sovereign personalized recovery drafts for high-intent funnel
              candidates. Shadow-only; no outbound sends.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <span
              className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(observer.last_job_status)}`}
            >
              {observer.enabled ? observer.last_job_status : "disabled"}
            </span>
            <span className="inline-flex rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] text-zinc-300">
              {Math.round(observer.interval_seconds / 60)}m cadence
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6 pt-6">
        {laneDisabled ? (
          <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-4 text-sm text-zinc-400">
            Concierge Alpha shadow-draft lane is disabled or the agentic gate is inactive. Enable{" "}
            <code className="rounded bg-zinc-950 px-1 py-0.5 text-zinc-200">CONCIERGE_SHADOW_DRAFT_ENABLED</code>{" "}
            on the worker and arm <code className="rounded bg-zinc-950 px-1 py-0.5 text-zinc-200">AGENTIC_SYSTEM_ACTIVE</code>{" "}
            to populate comparisons.
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Queued</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.queue_depth}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Running</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.running_jobs}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last inserted</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.last_inserted_count}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Dupes skipped</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.last_skipped_duplicate_count}</p>
          </div>
          <div className="md:col-span-2 xl:col-span-4 grid gap-3 text-sm text-zinc-400 md:grid-cols-3">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Candidates (last run)</p>
              <p className="mt-2 text-zinc-100">{observer.last_candidates_considered}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">No template skips</p>
              <p className="mt-2 text-zinc-100">{observer.last_skipped_no_template_count}</p>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last success</p>
              <p className="mt-2 text-zinc-100">{formatTimestamp(observer.last_success_at)}</p>
            </div>
          </div>
        </div>

        {comparisons.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
            No recovery draft comparisons recorded yet. The worker enqueues shadow-draft jobs on cadence when funnel
            recovery candidates exist.
          </div>
        ) : (
          <div className="space-y-4">
            {comparisons.map((row) => (
              <div
                key={row.id}
                className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4 text-sm text-zinc-300"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-zinc-100">
                      Session …{row.session_fp_suffix || row.session_fp.slice(-8)}
                    </p>
                    <p className="mt-1 text-xs text-zinc-500">
                      {row.drop_off_point_label || row.drop_off_point} · intent {row.intent_score_estimate.toFixed(2)}{" "}
                      · {row.property_slug || "no slug"} · {formatTimestamp(row.created_at)}
                    </p>
                    <p className="mt-1 text-[10px] uppercase tracking-[0.2em] text-zinc-600">
                      template {row.legacy_template_key} · dedupe {row.dedupe_hash.slice(0, 12)}…
                    </p>
                  </div>
                  <div className="text-right text-xs text-zinc-500">
                    Δ chars{" "}
                    <span className="font-mono text-zinc-200">
                      {typeof row.parity_summary.delta_chars === "number" ? row.parity_summary.delta_chars : "—"}
                    </span>
                  </div>
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  <div className="rounded-lg border border-amber-500/20 bg-amber-950/10 px-3 py-3">
                    <p className="text-[10px] font-medium uppercase tracking-[0.24em] text-amber-200/90">
                      Legacy (Rue Ba Rue)
                    </p>
                    <p className="mt-2 whitespace-pre-wrap text-zinc-200">{row.legacy_body}</p>
                  </div>
                  <div className="rounded-lg border border-teal-500/20 bg-teal-950/10 px-3 py-3">
                    <p className="text-[10px] font-medium uppercase tracking-[0.24em] text-teal-200/90">
                      Sovereign draft
                    </p>
                    <p className="mt-2 whitespace-pre-wrap text-zinc-200">{row.sovereign_body}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
