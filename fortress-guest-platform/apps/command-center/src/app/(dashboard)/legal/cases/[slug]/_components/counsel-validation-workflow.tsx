"use client";

import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCounselValidation,
  useCounselValidationAction,
} from "@/lib/legal-hooks";
import type {
  CounselSourceCheckStatus,
  CounselValidationActionBody,
  CounselValidationRecord,
} from "@/lib/legal-types";
import {
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  History,
  Lock,
  MessageSquare,
  RotateCcw,
  XCircle,
} from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function statusTone(status: string) {
  if (status === "accepted_for_review_use") return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (status === "rejected") return "bg-red-500/10 text-red-300 border-red-500/30";
  if (status === "corrected") return "bg-blue-500/10 text-blue-300 border-blue-500/30";
  if (status === "privileged_locked_metadata_only") return "bg-purple-500/10 text-purple-300 border-purple-500/30";
  if (status === "needs_source_check") return "bg-amber-500/10 text-amber-300 border-amber-500/30";
  return "bg-zinc-800 text-zinc-300 border-zinc-700";
}

function ActionButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={disabled}
      onClick={onClick}
      className="h-7 px-2 text-[10px] gap-1"
    >
      {icon}
      {label}
    </Button>
  );
}

function ValidationRecordRow({
  record,
  onAction,
  disabled,
}: {
  record: CounselValidationRecord;
  onAction: (body: CounselValidationActionBody) => void;
  disabled?: boolean;
}) {
  const sourceCount = Array.isArray(record.source_refs) ? record.source_refs.length : 0;
  const sourceStatus: CounselSourceCheckStatus =
    sourceCount > 0 ? "verified" : "needs_page_chunk_verification";

  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-3 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-zinc-100 truncate">{record.item_title}</p>
          <p className="text-[10px] text-zinc-500">
            {record.item_type.replaceAll("_", " ")} / {record.item_id} / v{record.version}
          </p>
        </div>
        <Badge variant="outline" className={`text-[10px] ${statusTone(record.validation_status)}`}>
          {record.validation_status.replaceAll("_", " ")}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-[10px] text-zinc-500">
        <span>Source refs: {sourceCount}</span>
        <span>Source check: {record.source_check_status.replaceAll("_", " ")}</span>
        {record.locked_restricted_related && (
          <Badge variant="outline" className="text-[10px] bg-purple-500/10 text-purple-300 border-purple-500/30">
            <Lock className="h-3 w-3 mr-1" />
            Metadata only
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5">
        <ActionButton
          label="Accept"
          disabled={disabled || record.locked_restricted_related}
          icon={<CheckCircle2 className="h-3 w-3" />}
          onClick={() => onAction({ item_id: record.item_id, action: "accept" })}
        />
        <ActionButton
          label="Reject"
          disabled={disabled}
          icon={<XCircle className="h-3 w-3" />}
          onClick={() => onAction({ item_id: record.item_id, action: "reject" })}
        />
        <ActionButton
          label="Correct"
          disabled={disabled || record.locked_restricted_related}
          icon={<ClipboardCheck className="h-3 w-3" />}
          onClick={() =>
            onAction({
              item_id: record.item_id,
              action: "correct",
              correction_summary: "Correction requested from validation workflow.",
            })
          }
        />
        <ActionButton
          label="Source"
          disabled={disabled}
          icon={<FileSearch className="h-3 w-3" />}
          onClick={() =>
            onAction({
              item_id: record.item_id,
              action: "needs_source_check",
              source_check_status: sourceStatus,
            })
          }
        />
        <ActionButton
          label="Note"
          disabled={disabled}
          icon={<MessageSquare className="h-3 w-3" />}
          onClick={() =>
            onAction({
              item_id: record.item_id,
              action: "needs_counsel_review",
              note: "Counsel/operator note placeholder added from validation workflow.",
            })
          }
        />
        <ActionButton
          label="Reopen"
          disabled={disabled}
          icon={<RotateCcw className="h-3 w-3" />}
          onClick={() => onAction({ item_id: record.item_id, action: "reopen" })}
        />
      </div>
    </div>
  );
}

export function CounselValidationWorkflow({ slug }: { slug: string }) {
  const { data, isLoading, error } = useCounselValidation(slug);
  const action = useCounselValidationAction(slug);

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
        Counsel Validation Workflow is not initialized yet.
      </div>
    );
  }

  const priorityRecords = data.records
    .filter((record) =>
      ["needs_source_check", "needs_counsel_review", "privileged_locked_metadata_only"].includes(
        record.validation_status,
      ),
    )
    .slice(0, 10);
  const auditEntries = data.audit_history.slice(-5).reverse();

  return (
    <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-emerald-200 flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4" />
            Counsel Validation Workflow
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} from {data.source_workbench_execution_id}
          </p>
        </div>
        <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
          DRAFT / COUNSEL REVIEW REQUIRED
        </Badge>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <Metric label="Validation Items" value={data.summary.total_workbench_items} />
        <Metric label="Complete" value={`${data.summary.validation_complete_percent}%`} />
        <Metric label="Accepted for Review Use" value={data.summary.accepted_for_review_use} />
        <Metric label="Needs Source Check" value={data.summary.needs_source_check} />
        <Metric label="Counsel Signoff" value="Pending" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100">Validation Queues</p>
            <Badge variant="outline" className="text-[10px]">
              {data.summary.progress_label.replaceAll("_", " ")}
            </Badge>
          </div>
          <div className="space-y-2">
            {data.queues.map((queue) => (
              <div key={queue.queue_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-zinc-100">{queue.title}</p>
                  <Badge variant="outline" className="text-[10px]">{queue.item_count}</Badge>
                </div>
                <p className="text-[10px] text-zinc-500 mt-1">
                  Source check {queue.needs_source_check_count} / counsel review {queue.needs_counsel_review_count} / high priority {queue.high_priority_count}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100">Priority Validation Items</p>
            <Badge variant="outline" className="text-[10px]">
              {priorityRecords.length}
            </Badge>
          </div>
          <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
            {priorityRecords.map((record) => (
              <ValidationRecordRow
                key={record.validation_id}
                record={record}
                disabled={action.isPending}
                onAction={(body) => action.mutate(body)}
              />
            ))}
          </div>
        </section>
      </div>

      <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <History className="h-3.5 w-3.5 text-emerald-300" />
          <p className="text-xs font-semibold text-zinc-100">Validation Audit Trail</p>
        </div>
        <div className="grid gap-2 lg:grid-cols-2">
          {auditEntries.map((entry) => (
            <div key={entry.audit_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{entry.action.replaceAll("_", " ")}</p>
              <p className="text-[10px] text-zinc-500">
                {entry.reviewer_identity_safe_label} / {entry.created_at}
              </p>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-zinc-500">
          Accepted items are accepted_for_review_use only. Counsel signoff remains pending.
          Locked/restricted documents remain metadata-only and are not content-reviewed here.
        </p>
      </section>
    </div>
  );
}
