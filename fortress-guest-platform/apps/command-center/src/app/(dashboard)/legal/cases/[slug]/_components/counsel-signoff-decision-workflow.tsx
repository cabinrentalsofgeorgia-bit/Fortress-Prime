"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  useCounselSignoffDecision,
  useCounselSignoffDecisionAction,
} from "@/lib/legal-hooks";
import type { CounselSignoffDecisionType } from "@/lib/legal-types";
import { CheckSquare, FileWarning, History, RotateCcw, ShieldCheck } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100 break-words">{value}</p>
    </div>
  );
}

const SIGNOFF_TYPES: CounselSignoffDecisionType[] = [
  "counsel_approved_for_internal_review_use",
  "counsel_approved_limited_subset_for_review_use",
  "counsel_approved_specific_sections_for_review_use",
];

function labelFor(value: string) {
  return value.replaceAll("_", " ");
}

export function CounselSignoffDecisionWorkflow({ slug }: { slug: string }) {
  const { data, isLoading, error } = useCounselSignoffDecision(slug);
  const decisionAction = useCounselSignoffDecisionAction(slug);
  const [decisionType, setDecisionType] = useState<CounselSignoffDecisionType>("signoff_deferred");
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [exclusionsAcknowledged, setExclusionsAcknowledged] = useState(false);
  const [privilegeAcknowledged, setPrivilegeAcknowledged] = useState(false);
  const [noExternalAcknowledged, setNoExternalAcknowledged] = useState(false);
  const [notes, setNotes] = useState("");

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
        Counsel Signoff Decision Workflow has not been initialized yet.
      </div>
    );
  }

  const allConfirmations = scopeConfirmed && exclusionsAcknowledged && privilegeAcknowledged && noExternalAcknowledged;
  const selectedRecordsSignoff = SIGNOFF_TYPES.includes(decisionType);
  const canSubmit = selectedRecordsSignoff ? allConfirmations : true;
  const latestDecision = data.decision_records.at(-1);

  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-emerald-200 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            Counsel Signoff Decision Workflow
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / packet {data.packet.packet_execution_id}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            {data.counsel_status}
          </Badge>
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            DRAFT / COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            EXTERNAL_SUBMISSION_NOT_AUTHORIZED
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            NOT FINAL LEGAL CONCLUSION
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Packet Version" value={data.packet.packet_version} />
        <Metric label="Packet Checksum" value={`${data.packet.packet_hash.slice(0, 12)}...`} />
        <Metric label="Included Items" value={data.packet.included_verified_subset} />
        <Metric label="Excluded Items" value={data.packet.excluded_unresolved_items} />
        <Metric label="Unresolved Sources" value={data.packet.unresolved_source_issue_count} />
        <Metric label="Locked / Restricted" value={data.packet.locked_restricted_count} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <CheckSquare className="h-3.5 w-3.5 text-emerald-300" />
            Decision Paths
          </p>
          <div className="space-y-1.5">
            {data.decision_paths.map((path) => (
              <button
                key={path.decision_type}
                type="button"
                onClick={() => setDecisionType(path.decision_type)}
                className={`w-full rounded border px-2 py-1.5 text-left text-xs transition ${
                  decisionType === path.decision_type
                    ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-100"
                    : "border-zinc-800 bg-zinc-900/60 text-zinc-300 hover:border-zinc-700"
                }`}
              >
                <span className="block font-medium">{path.label}</span>
                <span className="text-[10px] text-zinc-500">{path.resulting_counsel_status}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-3">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <FileWarning className="h-3.5 w-3.5 text-amber-300" />
            Explicit Confirmation Checklist
          </p>
          <div className="space-y-2">
            {[
              [scopeConfirmed, setScopeConfirmed, data.explicit_confirmation_checklist[0]],
              [exclusionsAcknowledged, setExclusionsAcknowledged, data.explicit_confirmation_checklist[1]],
              [privilegeAcknowledged, setPrivilegeAcknowledged, data.explicit_confirmation_checklist[2]],
              [noExternalAcknowledged, setNoExternalAcknowledged, data.explicit_confirmation_checklist[3]],
            ].map(([checked, setter, label], index) => (
              <Label key={index} className="flex items-start gap-2 text-xs text-zinc-300 leading-snug">
                <Checkbox
                  checked={Boolean(checked)}
                  onCheckedChange={(value) => (setter as (next: boolean) => void)(Boolean(value))}
                  className="mt-0.5"
                />
                <span>{String(label)}</span>
              </Label>
            ))}
          </div>
          <Textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Decision notes or revision request summary"
            className="min-h-20 text-xs"
          />
          <Button
            type="button"
            size="sm"
            disabled={!canSubmit || decisionAction.isPending}
            onClick={() =>
              decisionAction.mutate({
                decision_type: decisionType,
                decision_scope: "limited_packet_or_selected_items",
                explicit_scope_confirmed: scopeConfirmed,
                unresolved_exclusions_acknowledged: exclusionsAcknowledged,
                privilege_handling_acknowledged: privilegeAcknowledged,
                no_external_submission_authority_acknowledged: noExternalAcknowledged,
                decision_notes: notes || undefined,
              })
            }
          >
            {decisionAction.isPending ? "Recording..." : selectedRecordsSignoff ? "Record Explicit Counsel Decision" : "Record Decision"}
          </Button>
          {selectedRecordsSignoff && !allConfirmations && (
            <p className="text-[10px] text-amber-300">
              Counsel signoff paths require every explicit confirmation before recording.
            </p>
          )}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <History className="h-3.5 w-3.5 text-indigo-300" />
            Decision Audit History
          </p>
          {latestDecision ? (
            <div className="rounded border border-zinc-800 bg-zinc-900/70 p-2 text-xs">
              <p className="text-zinc-100">{labelFor(latestDecision.decision_type)}</p>
              <p className="text-[10px] text-zinc-500">{latestDecision.signed_or_decided_at}</p>
              <Badge variant="outline" className="mt-2 text-[10px] bg-zinc-950 text-zinc-300 border-zinc-700">
                {latestDecision.status_after}
              </Badge>
            </div>
          ) : (
            <p className="text-xs text-zinc-500">
              No explicit decision has been recorded. Counsel signoff remains pending.
            </p>
          )}
          <div className="rounded border border-zinc-800 bg-zinc-900/60 p-2 text-[10px] text-zinc-400 space-y-1">
            <p>Auto-sign prevented: {data.decision_readiness.auto_signoff_prevented ? "YES" : "NO"}</p>
            <p>External submission authority available: {data.decision_readiness.external_submission_authority_available ? "YES" : "NO"}</p>
            <p>Final legal conclusion available: {data.decision_readiness.final_legal_conclusion_available ? "YES" : "NO"}</p>
          </div>
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
          <RotateCcw className="h-3.5 w-3.5 text-zinc-400" />
          Revision / Source Remediation Routing
        </p>
        <p className="text-xs text-zinc-500">
          Revision requests and return-to-source-remediation decisions preserve packet history, keep unresolved items excluded, and do not alter raw documents.
        </p>
      </section>
    </div>
  );
}
