"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useLimitedSignoffCandidate } from "@/lib/legal-hooks";
import { FileCheck2, ListFilter, Scale, ShieldAlert } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(value: string) {
  if (value.includes("include")) return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (value.includes("locked")) return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  if (value.includes("unsupported")) return "bg-red-500/10 text-red-300 border-red-500/30";
  return "bg-amber-500/10 text-amber-300 border-amber-500/30";
}

export function LimitedSignoffCandidatePanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useLimitedSignoffCandidate(slug);

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
        Limited Signoff Candidate Packet has not been generated yet.
      </div>
    );
  }

  const packet = data.limited_signoff_candidate_packet;
  const tiers = data.tier_summary;
  const highMateriality = data.high_materiality_source_review.items.slice(0, 6);
  const excluded = data.unresolved_blocker_register_v2.slice(0, 6);

  return (
    <div className="rounded-lg border border-indigo-500/30 bg-indigo-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-indigo-200 flex items-center gap-2">
            <Scale className="h-4 w-4" />
            Limited Signoff Candidate Packet
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / {data.targeted_source_completion_execution_id}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            COUNSEL_SIGNOFF_PENDING
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            NOT FINAL LEGAL CONCLUSION
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Verified Used" value={data.verified_subset_used.item_count} />
        <Metric label="Included" value={packet.included_item_count} />
        <Metric label="Excluded" value={packet.excluded_item_count} />
        <Metric label="Tier 1" value={tiers.tier_1_count} />
        <Metric label="Tier 2" value={tiers.tier_2_count} />
        <Metric label="Tier 3" value={tiers.tier_3_count} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <FileCheck2 className="h-3.5 w-3.5 text-emerald-300" />
            Limited Candidate Scope
          </p>
          <Badge variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
            {packet.signoff_scope_recommendation}
          </Badge>
          <p className="text-xs text-zinc-500">
            Candidate packet includes source-routed review-use items only and excludes unresolved source blockers.
          </p>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />
            High-Materiality Source Review
          </p>
          {highMateriality.map((item) => (
            <div key={item.limited_signoff_review_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.candidate_outcome)}`}>
                {item.candidate_outcome.replaceAll("_", " ")}
              </Badge>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ListFilter className="h-3.5 w-3.5 text-indigo-300" />
            Excluded Items Register
          </p>
          {excluded.map((item) => (
            <div key={item.limited_signoff_review_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <p className="text-[10px] text-zinc-500">{item.required_next_action}</p>
            </div>
          ))}
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <p className="text-xs font-semibold text-zinc-100">Remaining Blockers By Tier</p>
        <div className="grid gap-2 sm:grid-cols-3">
          <Metric label="Requires Counsel" value={tiers.requires_counsel_interpretation} />
          <Metric label="Requires Evidence" value={tiers.requires_more_evidence} />
          <Metric label="Locked / Privilege" value={tiers.locked_privilege_limited} />
        </div>
      </section>
    </div>
  );
}
