"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useTargetedSourceCompletion } from "@/lib/legal-hooks";
import { FileCheck2, GitCompareArrows, ListChecks, ShieldAlert } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(state: string) {
  if (state.includes("verified")) return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (state.includes("locked")) return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  if (state.includes("unsupported") || state.includes("wrong")) return "bg-red-500/10 text-red-300 border-red-500/30";
  return "bg-amber-500/10 text-amber-300 border-amber-500/30";
}

export function TargetedSourceCompletionPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useTargetedSourceCompletion(slug);

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
        <Skeleton className="h-6 w-80" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">
        Targeted Source Completion has not been generated yet.
      </div>
    );
  }

  const summary = data.completion_summary;
  const trackA = summary.track_results.track_a_page_chunk_review;
  const trackB = summary.track_results.track_b_unsupported_recheck;
  const trackC = summary.track_results.track_c_locked_privilege_limited;
  const newVerified = data.expanded_verified_subset.new_items.slice(0, 8);
  const unresolved = data.refined_unresolved_register.slice(0, 8);

  return (
    <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-cyan-200 flex items-center gap-2">
            <GitCompareArrows className="h-4 w-4" />
            Targeted Source Completion
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / from {data.source_link_repair_execution_id}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            DRAFT / COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            COUNSEL_SIGNOFF_PENDING
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Processed" value={summary.items_processed} />
        <Metric label="Prior Subset" value={summary.prior_verified_subset_count} />
        <Metric label="New Subset" value={summary.new_verified_subset_count} />
        <Metric label="Delta" value={`+${summary.verified_subset_delta}`} />
        <Metric label="Unsupported" value={summary.unsupported} />
        <Metric label="Unresolved" value={summary.remaining_unresolved} />
      </div>

      <div className="grid gap-2 md:grid-cols-3">
        <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
          <p className="text-xs font-semibold text-zinc-100">Track A / Page Chunk</p>
          <p className="text-[10px] text-zinc-500">
            items {trackA.items} / corrected {trackA.corrected} / unresolved {trackA.unresolved}
          </p>
        </div>
        <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
          <p className="text-xs font-semibold text-zinc-100">Track B / Unsupported Re-check</p>
          <p className="text-[10px] text-zinc-500">
            items {trackB.items} / corrected {trackB.corrected} / still unsupported {trackB.still_unsupported}
          </p>
        </div>
        <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
          <p className="text-xs font-semibold text-zinc-100">Track C / Locked Privilege</p>
          <p className="text-[10px] text-zinc-500">
            items {trackC.items} / metadata-only {trackC.preserved_metadata_only}
          </p>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <FileCheck2 className="h-3.5 w-3.5 text-emerald-300" />
              Expanded Verified Subset
            </p>
            <Badge variant="outline" className="text-[10px]">{data.expanded_verified_subset.new_item_count}</Badge>
          </div>
          {newVerified.map((item) => (
            <div key={item.targeted_source_completion_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.final_state)}`}>
                {item.final_state.replaceAll("_", " ")}
              </Badge>
              <p className="text-[10px] text-zinc-500 mt-1">{item.corrected_claim_summary}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-red-300" />
              Refined Unresolved Register
            </p>
            <Badge variant="outline" className="text-[10px]">{data.refined_unresolved_register.length}</Badge>
          </div>
          {unresolved.map((item) => (
            <div key={item.targeted_source_completion_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.final_state)}`}>
                {item.final_state.replaceAll("_", " ")}
              </Badge>
              <p className="text-[10px] text-zinc-500 mt-1">{item.required_next_action}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ListChecks className="h-3.5 w-3.5 text-cyan-300" />
            Signoff Readiness Addendum
          </p>
          <Badge variant="outline" className="bg-cyan-500/10 text-cyan-300 border-cyan-500/30 text-[10px]">
            {data.expanded_verified_subset.signoff_scope_recommendation}
          </Badge>
          <p className="text-xs text-zinc-500">{data.signoff_readiness_addendum.verified_subset_status}</p>
          <p className="text-xs text-zinc-500">
            Targeted completion expands review-use source routing only; counsel signoff remains pending.
          </p>
        </section>
      </div>
    </div>
  );
}
