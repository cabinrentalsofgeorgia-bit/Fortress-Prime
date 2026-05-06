"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCounselSignoffAction,
  useCounselSignoffPacket,
  useCounselSignoffReopen,
} from "@/lib/legal-hooks";
import { SourceIntegrityValidationPanel } from "./source-integrity-validation-panel";
import { SourceLinkRepairPanel } from "./source-link-repair-panel";
import { SourceRemediationPanel } from "./source-remediation-panel";
import { TargetedSourceCompletionPanel } from "./targeted-source-completion-panel";
import {
  AlertTriangle,
  CheckCircle2,
  FileCheck2,
  FileText,
  History,
  Lock,
  PenLine,
  ShieldAlert,
} from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(status: string) {
  if (status.toLowerCase().includes("pending")) return "bg-amber-500/10 text-amber-300 border-amber-500/30";
  if (status.toLowerCase().includes("ready")) return "bg-blue-500/10 text-blue-300 border-blue-500/30";
  if (status.toLowerCase().includes("signed")) return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  return "bg-zinc-800 text-zinc-300 border-zinc-700";
}

export function CounselSignoffStrategyPacket({ slug }: { slug: string }) {
  const { data, isLoading, error } = useCounselSignoffPacket(slug);
  const signoff = useCounselSignoffAction(slug);
  const reopen = useCounselSignoffReopen(slug);
  const [scopeConfirmed, setScopeConfirmed] = useState(false);

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
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-300">
        Reviewed Strategy Packet is not generated yet.
      </div>
    );
  }

  const keySections = [
    "reviewed-issue-matrix",
    "reviewed-master-chronology",
    "contradiction-triage-packet",
    "evidence-binder-index",
    "entity-actor-dossier",
    "case-theory-packet",
    "source-integrity-matrix",
    "unresolved-items-register",
    "signoff-capture",
  ];
  const visibleSections = data.sections.filter((section) => keySections.includes(section.section_id));
  const auditEntries = data.audit_history.slice(-5).reverse();
  const signoffRecorded = data.signoff_capture.signoff_recorded;

  return (
    <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-blue-200 flex items-center gap-2">
            <FileCheck2 className="h-4 w-4" />
            Strategy Packet / Counsel Signoff
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / v{data.packet_version} / {data.packet_checksum.slice(0, 12)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            DRAFT / COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className={`text-[10px] ${tone(data.signoff_status)}`}>
            {data.signoff_status.replaceAll("_", " ")}
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            NOT FINAL LEGAL CONCLUSION
          </Badge>
        </div>
      </div>

      <SourceIntegrityValidationPanel slug={slug} />
      <SourceRemediationPanel slug={slug} />
      <SourceLinkRepairPanel slug={slug} />
      <TargetedSourceCompletionPanel slug={slug} />

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <Metric label="Packet Sections" value={data.sections.length} />
        <Metric label="Unresolved Items" value={data.unresolved_items_register.length} />
        <Metric label="Source Checks Needed" value={data.source_integrity_matrix.items_needing_source_check} />
        <Metric label="Missing Source Refs" value={data.source_integrity_matrix.items_missing_source_refs} />
        <Metric label="Signoff" value={signoffRecorded ? "Recorded" : "Pending"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.3fr_0.9fr]">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-blue-300" />
              Reviewed Packet Sections
            </p>
            <Badge variant="outline" className="text-[10px]">
              {data.readiness_status.replaceAll("_", " ")}
            </Badge>
          </div>
          <div className="grid gap-2 lg:grid-cols-2">
            {visibleSections.map((section) => (
              <div key={section.section_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-zinc-100">{section.title}</p>
                  <Badge variant="outline" className={`text-[10px] ${tone(section.signoff_status)}`}>
                    {section.signoff_status.replaceAll("_", " ")}
                  </Badge>
                </div>
                <p className="text-[10px] text-zinc-500 mt-1">
                  Items {section.item_count} / unresolved {section.unresolved_count} / sources {section.source_refs_summary.total_source_refs}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />
            <p className="text-xs font-semibold text-zinc-100">Signoff Capture</p>
          </div>
          <div className="rounded border border-amber-500/20 bg-amber-500/5 p-2 text-[11px] text-amber-200">
            Signoff is scoped to the approved review matter only. It does not authorize filing,
            final legal conclusions, or unrestricted legal operations.
          </div>
          <label className="flex items-start gap-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={scopeConfirmed}
              onChange={(event) => setScopeConfirmed(event.target.checked)}
              className="mt-0.5"
            />
            I understand this is signoff for the approved review scope only.
          </label>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={!scopeConfirmed || signoff.isPending}
              onClick={() =>
                signoff.mutate({
                  signoff_type: "operator_review_acknowledgment",
                  scope_confirmed: scopeConfirmed,
                  notes: "Operator review acknowledgment captured from Strategy Packet panel.",
                })
              }
              className="gap-1"
            >
              <PenLine className="h-3.5 w-3.5" />
              Operator Acknowledge
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!scopeConfirmed || signoff.isPending}
              onClick={() =>
                signoff.mutate({
                  signoff_type: "counsel_review_acknowledgment",
                  scope_confirmed: scopeConfirmed,
                  notes: "Counsel review acknowledgment captured from Strategy Packet panel.",
                })
              }
              className="gap-1"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              Counsel Acknowledge
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={reopen.isPending}
              onClick={() => reopen.mutate({ notes: "Packet reopened from Strategy Packet panel." })}
            >
              Reopen
            </Button>
          </div>
          <p className="text-[10px] text-zinc-500">
            Packet checksum: {data.packet_checksum}. Export snapshot contains no document body text and no locked content.
          </p>
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
            <p className="text-xs font-semibold text-zinc-100">Source Integrity Matrix</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Metric label="Material Items" value={data.source_integrity_matrix.material_items} />
            <Metric label="With Sources" value={data.source_integrity_matrix.items_with_source_refs} />
            <Metric label="Need Check" value={data.source_integrity_matrix.items_needing_source_check} />
            <Metric label="Final Unsupported" value={data.source_integrity_matrix.unsupported_assertions_marked_final ? "Yes" : "No"} />
          </div>
          <p className="text-[10px] text-zinc-500">{data.source_integrity_matrix.recommended_action}</p>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center gap-2">
            <Lock className="h-3.5 w-3.5 text-purple-300" />
            <p className="text-xs font-semibold text-zinc-100">Readiness Checklist / Audit</p>
          </div>
          <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
            {data.signoff_readiness_checklist.map((check) => (
              <div key={check.check_id} className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900/70 px-2 py-1.5">
                <span className="text-xs text-zinc-200">{check.title}</span>
                <Badge variant="outline" className={check.passed ? "text-[10px] bg-emerald-500/10 text-emerald-300 border-emerald-500/30" : "text-[10px]"}>
                  {check.passed ? "Pass" : "Open"}
                </Badge>
              </div>
            ))}
          </div>
          <div className="space-y-1 pt-2 border-t border-zinc-800">
            <div className="flex items-center gap-2">
              <History className="h-3.5 w-3.5 text-blue-300" />
              <p className="text-xs font-semibold text-zinc-100">Audit</p>
            </div>
            {auditEntries.map((entry) => (
              <p key={entry.audit_id} className="text-[10px] text-zinc-500">
                {entry.action.replaceAll("_", " ")} / {entry.created_at}
              </p>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
