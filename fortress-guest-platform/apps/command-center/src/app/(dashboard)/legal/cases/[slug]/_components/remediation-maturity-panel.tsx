"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useRemediationMaturity } from "@/lib/legal-hooks";
import { GitBranch, ListFilter, ShieldCheck, SlidersHorizontal } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(value: string) {
  if (value.includes("locked") || value.includes("restricted")) return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  if (value.includes("contradiction")) return "bg-amber-500/10 text-amber-300 border-amber-500/30";
  if (value.includes("source_missing") || value.includes("unsupported")) return "bg-red-500/10 text-red-300 border-red-500/30";
  return "bg-blue-500/10 text-blue-300 border-blue-500/30";
}

export function RemediationMaturityPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useRemediationMaturity(slug);

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
        Remediation maturity read model is not available yet.
      </div>
    );
  }

  const topQueue = data.priority_queue.slice(0, 8);

  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-emerald-200 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" />
            Remediation Maturity / Review Queue
          </p>
          <p className="text-xs text-zinc-400">
            {data.source_manifests.targeted_source_completion_execution_id} / {data.source_manifests.limited_signoff_candidate_execution_id}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            DRAFT / COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            {data.governance.counsel_signoff}
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            {data.governance.external_submission_authority}
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Unresolved" value={data.remediation_summary.unresolved_total} />
        <Metric label="Missing Source" value={data.remediation_summary.unsupported_or_missing_source} />
        <Metric label="Restricted" value={data.remediation_summary.locked_restricted_no_review} />
        <Metric label="Evidence Needed" value={data.remediation_summary.evidence_needed} />
        <Metric label="Counsel Review" value={data.remediation_summary.counsel_review_required} />
        <Metric label="Verified Subset" value={data.remediation_summary.verified_subset_count} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.25fr_0.8fr_0.8fr]">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ListFilter className="h-3.5 w-3.5 text-emerald-300" />
            Prioritized Human Review Queue
          </p>
          <div className="space-y-2">
            {topQueue.map((item) => (
              <div key={`${item.item_type}-${item.item_id}`} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
                  <Badge variant="outline" className="text-[10px]">
                    score {item.priority_score}
                  </Badge>
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  <Badge variant="outline" className={`text-[10px] ${tone(item.review_lane)}`}>
                    {item.review_lane.replaceAll("_", " ")}
                  </Badge>
                  <Badge variant="outline" className={`text-[10px] ${tone(item.confidence_state)}`}>
                    {item.confidence_state.replaceAll("_", " ")}
                  </Badge>
                  {item.locked_restricted_involved ? (
                    <Badge variant="outline" className="bg-purple-500/10 text-purple-300 border-purple-500/30 text-[10px]">
                      metadata only restricted
                    </Badge>
                  ) : null}
                  <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
                    excluded from relied-upon sections
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 text-blue-300" />
            Review Confidence
          </p>
          {data.classification_counts.by_confidence_state.map((row) => (
            <div key={row.state} className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1.5">
              <span className="text-xs text-zinc-200">{row.state.replaceAll("_", " ")}</span>
              <Badge variant="outline" className={`text-[10px] ${tone(row.state)}`}>{row.count}</Badge>
            </div>
          ))}
          <p className="text-[10px] text-zinc-500">
            Priority model: {data.priority_model.name}; {data.priority_model.automation_boundary.replaceAll("_", " ")}.
          </p>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-cyan-300" />
            Evidence Lineage
          </p>
          <div className="space-y-1">
            {data.evidence_lineage.lineage_chain.map((step) => (
              <div key={step} className="rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-[11px] text-zinc-300">
                {step.replaceAll("_", " ")}
              </div>
            ))}
          </div>
          <p className="text-[10px] text-zinc-500">
            Mutation model: {data.evidence_lineage.mutation_model.replaceAll("_", " ")}. Silent transitions: {data.evidence_lineage.silent_state_transitions_allowed ? "allowed" : "blocked"}.
          </p>
        </section>
      </div>
    </div>
  );
}
