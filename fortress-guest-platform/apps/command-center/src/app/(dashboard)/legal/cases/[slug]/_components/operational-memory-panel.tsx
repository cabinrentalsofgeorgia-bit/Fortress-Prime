"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useOperationalMemory } from "@/lib/legal-hooks";
import { BrainCircuit, DatabaseZap, FileCheck2, GitBranch, ShieldCheck } from "lucide-react";

function label(value: string) {
  return value.replaceAll("_", " ");
}

function Metric({ label: metricLabel, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{metricLabel}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

export function OperationalMemoryPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useOperationalMemory(slug);

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
        Operational memory registries are not available yet.
      </div>
    );
  }

  const capabilities = data.registries.capabilities.capabilities.slice(0, 8);
  const evidence = data.registries.evidence.evidenceDirectories.slice(0, 8);
  const wikiEntries = data.registries.wiki_knowledge_index.entries.slice(0, 8);
  const feedbackTypes = data.registries.reviewer_feedback_ledger.allowedFeedbackTypes.slice(0, 8);

  return (
    <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-violet-100 flex items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-violet-300" />
            Operational Memory / Machine-Readable Cognition
          </p>
          <p className="text-xs text-zinc-400">
            {label(data.status)} / registry-as-operational-memory, not legal authority.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            COUNSEL_SIGNOFF_PENDING
          </Badge>
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            NOT_AUTHORIZED
          </Badge>
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            NOT FINAL LEGAL ADVICE
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Capabilities" value={data.summary.capabilityCount} />
        <Metric label="Evidence Refs" value={data.summary.evidenceDirectoryCount} />
        <Metric label="Wiki Index" value={data.summary.wikiKnowledgeEntries} />
        <Metric label="Feedback Entries" value={data.summary.reviewerFeedbackEntries} />
        <Metric label="Unresolved Sources" value={data.summary.unresolvedSourceIssues} />
        <Metric label="Registry Valid" value={data.registries.validation_report.ok ? "PASS" : "REVIEW"} />
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <section className="rounded border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
            Governance Registry
          </p>
          <div className="flex flex-wrap gap-1">
            {data.registries.governance.forbiddenOperations.slice(0, 8).map((operation) => (
              <Badge key={operation} variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
                forbidden {label(operation)}
              </Badge>
            ))}
          </div>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <DatabaseZap className="h-3.5 w-3.5 text-cyan-300" />
            Remediation Registry
          </p>
          <p className="text-[10px] text-zinc-500">
            {label(data.registries.remediation.unresolvedSourceExclusionStatus)} / no auto resolution {String(data.registries.remediation.noAutoResolution)}.
          </p>
          <div className="flex flex-wrap gap-1">
            {data.registries.remediation.categories.slice(0, 6).map((category) => (
              <Badge key={category} variant="outline" className="bg-blue-500/10 text-blue-300 border-blue-500/30 text-[10px]">
                {label(category)}
              </Badge>
            ))}
          </div>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <FileCheck2 className="h-3.5 w-3.5 text-amber-300" />
            Reviewer Feedback Ledger Foundation
          </p>
          <p className="text-[10px] text-zinc-500">
            {label(data.summary.reviewerLedgerMode)} / no freeform legal text {String(data.registries.reviewer_feedback_ledger.noFreeformLegalText)}.
          </p>
          <div className="flex flex-wrap gap-1">
            {feedbackTypes.map((feedbackType) => (
              <Badge key={feedbackType} variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30 text-[10px]">
                {label(feedbackType)}
              </Badge>
            ))}
          </div>
        </section>
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <section className="rounded border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100">Capability Registry</p>
          <div className="space-y-1">
            {capabilities.map((capability) => (
              <div key={capability.id} className="rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-[10px] text-zinc-300">
                {label(capability.id)} / {label(capability.status)} / {label(capability.maturityLevel)}
              </div>
            ))}
          </div>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100">Evidence Registry</p>
          <div className="space-y-1">
            {evidence.map((entry) => (
              <div key={entry.phase} className="rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-[10px] text-zinc-300">
                {label(entry.phase)} / {label(entry.status)}
              </div>
            ))}
          </div>
        </section>

        <section className="rounded border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-violet-300" />
            Wiki / App / Evidence Knowledge Index
          </p>
          <div className="space-y-1">
            {wikiEntries.map((entry) => (
              <div key={entry.path} className="rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-[10px] text-zinc-300">
                {label(entry.category)} / {label(entry.freshness)}
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="flex flex-wrap gap-1">
        {Object.entries(data.negativeControls).map(([key, value]) => (
          <Badge key={key} variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            {label(key)} {String(value)}
          </Badge>
        ))}
      </div>
    </div>
  );
}
