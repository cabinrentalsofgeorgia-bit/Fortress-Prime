"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSourceIntegrity } from "@/lib/legal-hooks";
import { AlertTriangle, CheckCircle2, FileSearch, Lock, ShieldAlert } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(status: string) {
  if (status === "source_verified_for_review_use") return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (status === "source_missing" || status === "unsupported") return "bg-red-500/10 text-red-300 border-red-500/30";
  if (status === "locked_or_privilege_limited") return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  return "bg-amber-500/10 text-amber-300 border-amber-500/30";
}

export function SourceIntegrityValidationPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useSourceIntegrity(slug);

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
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-300">
        Source Integrity Validation has not been generated yet.
      </div>
    );
  }

  const summary = data.source_integrity_summary;
  const queue = data.correction_queue.slice(0, 8);
  const blockers = data.signoff_blockers.slice(0, 8);
  const verified = data.verified_subset.slice(0, 8);

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-amber-200 flex items-center gap-2">
            <FileSearch className="h-4 w-4" />
            Source Integrity Validation
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / {data.signoff_packet_execution_id}
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
        <Metric label="Checked" value={`${summary.checked}/${summary.total_material_items}`} />
        <Metric label="Verified" value={summary.source_verified_for_review_use} />
        <Metric label="Source Missing" value={summary.source_missing} />
        <Metric label="Page/Chunk Review" value={summary.needs_page_or_chunk_review} />
        <Metric label="Privilege Limited" value={summary.locked_or_privilege_limited} />
        <Metric label="Signoff Blockers" value={summary.signoff_blockers} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
              Correction Queue
            </p>
            <Badge variant="outline" className="text-[10px]">{data.correction_queue.length}</Badge>
          </div>
          {queue.map((item) => (
            <div key={item.queue_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_type.replaceAll("_", " ")} / {item.item_id}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.source_support_status)}`}>
                {item.source_support_status.replaceAll("_", " ")}
              </Badge>
              <p className="text-[10px] text-zinc-500 mt-1">{item.required_next_action}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-red-300" />
              Signoff Blockers
            </p>
            <Badge variant="outline" className="text-[10px]">{data.signoff_blockers.length}</Badge>
          </div>
          {blockers.map((item) => (
            <div key={item.source_validation_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.item_title}</p>
              <p className="text-[10px] text-zinc-500">{item.packet_section}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(item.source_support_status)}`}>
                {item.source_support_status.replaceAll("_", " ")}
              </Badge>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
              Verified Subset
            </p>
            <Badge variant="outline" className="text-[10px]">{data.verified_subset.length}</Badge>
          </div>
          {verified.length === 0 ? (
            <p className="text-xs text-zinc-500">
              No items are source_verified_for_review_use yet. Source-check blockers remain classified for counsel review.
            </p>
          ) : (
            verified.map((item) => (
              <div key={item.source_validation_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <p className="text-xs text-zinc-100">{item.item_title}</p>
                <p className="text-[10px] text-zinc-500">{item.source_refs_checked.length} checked refs</p>
              </div>
            ))
          )}
          <div className="flex items-center gap-2 pt-2 text-[10px] text-zinc-500">
            <Lock className="h-3 w-3 text-purple-300" />
            Locked/restricted documents remain metadata-only; no locked content is source-checked here.
          </div>
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <p className="text-xs font-semibold text-zinc-100">Batch Results</p>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {data.batch_results.map((batch) => (
            <div key={batch.item_type} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{batch.item_type.replaceAll("_", " ")}</p>
              <p className="text-[10px] text-zinc-500">
                checked {batch.checked} / missing {batch.unsupported} / page-chunk {batch.needs_page_or_chunk_review}
              </p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
