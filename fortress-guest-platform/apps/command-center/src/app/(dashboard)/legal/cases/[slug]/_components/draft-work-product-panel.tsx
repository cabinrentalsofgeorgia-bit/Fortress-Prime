"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useDraftWorkProduct } from "@/lib/legal-hooks";
import { BookOpenCheck, FileText, ListChecks, MapPinned, ShieldAlert } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function SectionList({
  title,
  sections,
}: {
  title: string;
  sections: Array<{ section_id: string; title: string; item_count: number; notes: string }>;
}) {
  return (
    <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
      <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
        <FileText className="h-3.5 w-3.5 text-sky-300" />
        {title}
      </p>
      {sections.map((section) => (
        <div key={section.section_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-zinc-100">{section.title}</p>
            <Badge variant="outline" className="text-[10px] bg-zinc-950 text-zinc-300 border-zinc-700">
              {section.item_count}
            </Badge>
          </div>
          <p className="mt-1 text-[10px] text-zinc-500">{section.notes}</p>
        </div>
      ))}
    </section>
  );
}

export function DraftWorkProductPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useDraftWorkProduct(slug);

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
        <Skeleton className="h-6 w-80" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">
        Draft Work Product Packet has not been generated yet.
      </div>
    );
  }

  const sections = data.draft_packet.sections;
  const reliedUpon = sections.slice(0, 6);
  const planning = sections.slice(6, 12);
  const appendices = sections.slice(12);

  return (
    <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-sky-200 flex items-center gap-2">
            <BookOpenCheck className="h-4 w-4" />
            Draft Work Product Packet
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / checksum {data.manifest_checksum.slice(0, 12)}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {data.governance_labels.map((label) => (
            <Badge
              key={label}
              variant="outline"
              className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]"
            >
              {label}
            </Badge>
          ))}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Verified Items Used" value={data.source_basis.included_verified_item_count} />
        <Metric label="Excluded Unresolved" value={data.source_basis.excluded_unresolved_item_count} />
        <Metric label="Sections" value={data.draft_packet.sections_generated} />
        <Metric label="Source Refs" value={data.source_basis.source_refs_total} />
        <Metric label="Locked Content Used" value={data.source_basis.locked_restricted_used_for_content ? "Yes" : "No"} />
        <Metric label="Counsel Status" value={data.draft_packet.counsel_signoff_pending ? "Pending" : "Recorded"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <SectionList title="Draft Outputs" sections={reliedUpon} />
        <SectionList title="Review Planning" sections={planning} />
        <SectionList title="Appendices / Source Map" sections={appendices} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ListChecks className="h-3.5 w-3.5 text-emerald-300" />
            Source Basis
          </p>
          <p className="text-xs text-zinc-500">
            Draft work product is generated from source-verified and corrected review-use items only.
          </p>
          <Badge variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
            SOURCE-VERIFIED SUBSET ONLY
          </Badge>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />
            External Use Guard
          </p>
          <p className="text-xs text-zinc-500">
            This packet is internal draft work product only and is not filing, service, sending, email, or external-submission authority.
          </p>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            NOT FINAL LEGAL ADVICE
          </Badge>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <MapPinned className="h-3.5 w-3.5 text-sky-300" />
            Source Map
          </p>
          <p className="text-xs text-zinc-500">
            {data.source_map.included_item_ids.length} included IDs / {data.source_map.excluded_item_ids.length} excluded IDs.
          </p>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            NO DOCUMENT BODY TEXT
          </Badge>
        </section>
      </div>
    </div>
  );
}
