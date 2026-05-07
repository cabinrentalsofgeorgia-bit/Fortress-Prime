"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSourceLinkRepair } from "@/lib/legal-hooks";
import { CheckCircle2, FileSearch, ListTree, ShieldAlert } from "lucide-react";

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

export function SourceLinkRepairPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useSourceLinkRepair(slug);

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
        Source Link Repair has not been generated yet.
      </div>
    );
  }

  const summary = data.repair_summary;
  const verified = data.verified_subset.items.slice(0, 8);
  const unresolved = data.refined_unresolved_register.slice(0, 8);

  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-emerald-200 flex items-center gap-2">
            <FileSearch className="h-4 w-4" />
            Source Link Repair
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / {data.source_remediation_execution_id}
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
        <Metric label="Corrected Verified" value={summary.corrected_verified_for_review_use} />
        <Metric label="Unsupported" value={summary.unsupported} />
        <Metric label="Privilege Limited" value={summary.locked_or_privilege_limited} />
        <Metric label="Unresolved" value={summary.remaining_unresolved} />
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
          {verified.map((item) => (
            <div key={item.source_link_repair_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.final_remediation_state)}`}>
                {item.final_remediation_state.replaceAll("_", " ")}
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
            <div key={item.source_link_repair_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.final_remediation_state)}`}>
                {item.final_remediation_state.replaceAll("_", " ")}
              </Badge>
              <p className="text-[10px] text-zinc-500 mt-1">{item.required_next_action}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ListTree className="h-3.5 w-3.5 text-emerald-300" />
            Limited Signoff Scope Recommendation
          </p>
          <Badge variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
            {data.verified_subset.signoff_scope_recommendation}
          </Badge>
          <p className="text-xs text-zinc-500">{data.signoff_readiness_addendum.readiness_recommendation}</p>
          <p className="text-xs text-zinc-500">
            Source-link verification is for review-use routing only; counsel signoff remains pending.
          </p>
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <p className="text-xs font-semibold text-zinc-100">Packet Sections Covered</p>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {data.packet_section_summary.map((section) => (
            <div key={section.item_type} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{section.item_type.replaceAll("_", " ")}</p>
              <p className="text-[10px] text-zinc-500">
                verified {section.verified_subset_count} / unresolved {section.unresolved_count}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
