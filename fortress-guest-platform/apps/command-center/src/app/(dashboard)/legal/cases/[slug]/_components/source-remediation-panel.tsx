"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSourceRemediation } from "@/lib/legal-hooks";
import { CheckCircle2, FileWarning, ListChecks, ShieldAlert } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(outcome: string) {
  if (outcome.startsWith("resolved_")) return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (outcome.includes("locked")) return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  if (outcome.includes("unsupported") || outcome.includes("wrong")) return "bg-red-500/10 text-red-300 border-red-500/30";
  return "bg-amber-500/10 text-amber-300 border-amber-500/30";
}

export function SourceRemediationPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useSourceRemediation(slug);

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
        <Skeleton className="h-6 w-72" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">
        Source Remediation has not been generated yet.
      </div>
    );
  }

  const summary = data.remediation_summary;
  const blockers = data.refined_blocker_register.slice(0, 8);
  const verified = data.verified_subset.items.slice(0, 8);

  return (
    <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-cyan-200 flex items-center gap-2">
            <ListChecks className="h-4 w-4" />
            Source Blocker Remediation
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / {data.source_integrity_execution_id}
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
        <Metric label="Processed" value={summary.total_blockers_processed} />
        <Metric label="Verified Subset" value={summary.verified_subset_count} />
        <Metric label="Unsupported" value={summary.unresolved_unsupported} />
        <Metric label="Page/Chunk" value={summary.unresolved_needs_page_or_chunk_review} />
        <Metric label="Privilege Limited" value={summary.unresolved_locked_or_privilege_limited} />
        <Metric label="Remaining Blockers" value={summary.remaining_blockers} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
              Verified Subset
            </p>
            <Badge variant="outline" className="text-[10px]">{data.verified_subset.item_count}</Badge>
          </div>
          {verified.length === 0 ? (
            <p className="text-xs text-zinc-500">
              No limited signoff subset is ready. Source remediation classified every blocker, but source support remains unresolved.
            </p>
          ) : (
            verified.map((item) => (
              <div key={item.remediation_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
                <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.remediation_outcome)}`}>
                  {item.remediation_outcome.replaceAll("_", " ")}
                </Badge>
              </div>
            ))
          )}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-red-300" />
              Refined Blocker Register
            </p>
            <Badge variant="outline" className="text-[10px]">{data.refined_blocker_register.length}</Badge>
          </div>
          {blockers.map((item) => (
            <div key={item.remediation_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.remediation_outcome)}`}>
                {item.remediation_outcome.replaceAll("_", " ")}
              </Badge>
              <p className="text-[10px] text-zinc-500 mt-1">{item.required_next_action}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <FileWarning className="h-3.5 w-3.5 text-amber-300" />
            Signoff Readiness Addendum
          </p>
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            {data.signoff_readiness_addendum.readiness_recommendation}
          </Badge>
          <p className="text-xs text-zinc-500">{data.signoff_readiness_addendum.verified_subset_status}</p>
          <p className="text-xs text-zinc-500">
            Signoff remains pending. Remediation results are for counsel/source review only.
          </p>
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <p className="text-xs font-semibold text-zinc-100">Remediation Categories</p>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {data.remediation_category_summary.map((category) => (
            <div key={category.blocker_type} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{category.blocker_type.replaceAll("_", " ")}</p>
              <p className="text-[10px] text-zinc-500">
                {category.item_count} items / blocks signoff {category.blocks_signoff ? "yes" : "no"}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
