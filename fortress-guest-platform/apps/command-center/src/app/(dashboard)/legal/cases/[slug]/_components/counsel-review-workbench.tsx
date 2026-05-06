"use client";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useCounselWorkbench } from "@/lib/legal-hooks";
import { AlertTriangle, Eye, Lock, Scale, ShieldAlert } from "lucide-react";

function WorkbenchMetric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

export function CounselReviewWorkbench({ slug }: { slug: string }) {
  const { data, isLoading, error } = useCounselWorkbench(slug);

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-300">
        Counsel Review Workbench packet is not available yet.
      </div>
    );
  }

  const topIssues = data.issue_matrix.slice(0, 6);
  const highPriorityQueue = data.consolidated_review_queue
    .filter((item) => item.priority === "high")
    .slice(0, 6);
  const topBinders = data.evidence_binders.slice(0, 8);
  const topTriage = data.contradiction_triage.slice(0, 5);

  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-red-200 flex items-center gap-2">
            <Scale className="h-4 w-4" />
            Counsel Review Workbench
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} from {data.source_intelligence_execution_id}
          </p>
        </div>
        <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
          DRAFT / COUNSEL REVIEW REQUIRED
        </Badge>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <WorkbenchMetric label="Issues" value={data.issue_matrix.length} />
        <WorkbenchMetric label="Evidence Binders" value={data.evidence_binders.length} />
        <WorkbenchMetric label="Contradiction Triage" value={data.contradiction_triage.length} />
        <WorkbenchMetric label="Review Queue" value={data.consolidated_review_queue.length} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <Eye className="h-3.5 w-3.5 text-red-300" />
              Claims / Defenses / Issues Matrix
            </p>
            <Badge variant="outline" className="text-[10px]">{data.issue_matrix.length}</Badge>
          </div>
          <div className="space-y-2">
            {topIssues.map((issue) => (
              <div key={issue.id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-xs text-zinc-100">{issue.title}</p>
                  <Badge variant="outline" className="text-[10px] capitalize">
                    {issue.issue_type}
                  </Badge>
                </div>
                <p className="text-[10px] text-zinc-500 mt-1">
                  Confidence {Math.round(issue.confidence_score * 100)}% · Materiality {Math.round(issue.materiality_score * 100)}%
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <Scale className="h-3.5 w-3.5 text-blue-300" />
              Evidence Binders
            </p>
            <Badge variant="outline" className="text-[10px]">{data.evidence_binders.length}</Badge>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {topBinders.map((binder) => (
              <div key={binder.id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <p className="text-xs text-zinc-100">{binder.title}</p>
                <p className="text-[10px] text-zinc-500">{binder.document_count} docs · {binder.review_priority}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-300" />
              Contradiction Triage
            </p>
            <Badge variant="outline" className="text-[10px]">{data.contradiction_triage.length}</Badge>
          </div>
          <div className="space-y-2">
            {topTriage.map((item) => (
              <div key={item.id} className="rounded border border-amber-500/20 bg-amber-500/5 p-2">
                <p className="text-xs text-zinc-100">{item.conflict_type}</p>
                <p className="text-[10px] text-zinc-500">
                  {item.status} · Confidence {item.confidence_score ?? "N/A"}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-emerald-300" />
              Counsel Questions / Actions
            </p>
            <Badge variant="outline" className="text-[10px]">
              {data.counsel_questions.length + data.action_checklist.length}
            </Badge>
          </div>
          <div className="space-y-2">
            {data.counsel_questions.slice(0, 5).map((question) => (
              <div key={question.id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
                <p className="text-xs text-zinc-100">{question.title}</p>
                <p className="text-[10px] text-zinc-500">{question.category} · {question.priority}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <Lock className="h-3.5 w-3.5 text-purple-300" />
            Review Queue / Privilege Handling
          </p>
          <Badge variant="outline" className="text-[10px]">
            Locked: {data.privileged_locked_handling.locked_restricted_count}
          </Badge>
        </div>
        <div className="grid gap-2 lg:grid-cols-3">
          {highPriorityQueue.map((item) => (
            <div key={item.id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{item.title}</p>
              <p className="text-[10px] text-zinc-500">{item.category}</p>
            </div>
          ))}
        </div>
        <p className="text-[10px] text-zinc-500">
          Locked/restricted documents remain metadata-only. No locked content is analyzed or shown in this workbench.
        </p>
      </div>
    </div>
  );
}
