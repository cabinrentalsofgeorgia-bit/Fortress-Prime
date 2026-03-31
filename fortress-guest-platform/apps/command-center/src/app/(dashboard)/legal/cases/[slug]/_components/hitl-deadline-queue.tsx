"use client";

import { RoleGatedAction } from "@/components/access/role-gated-action";
import { useAppStore } from "@/lib/store";
import { canManageLegalOps } from "@/lib/roles";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useCaseDetail, useCaseDeadlines, useDeadlineReview } from "@/lib/legal-hooks";
import type { LegalDeadline, ExtractedDeadline, ExtractedEntities } from "@/lib/legal-types";
import { CheckCircle, XCircle, Quote, Clock, Shield, AlertTriangle } from "lucide-react";

function findSourceText(
  deadline: LegalDeadline,
  entities: ExtractedEntities | Record<string, never> | null,
): string | null {
  if (!entities || !("deadlines" in entities)) return null;
  const match = (entities.deadlines ?? []).find(
    (ed: ExtractedDeadline) =>
      ed.description === deadline.description ||
      ed.due_date === deadline.due_date,
  );
  return match?.source_text ?? null;
}

function urgencyBadge(urgency: string) {
  const cls =
    urgency === "overdue"
      ? "bg-red-500/10 text-red-500 border-red-500/30"
      : urgency === "critical"
        ? "bg-orange-500/10 text-orange-500 border-orange-500/30"
        : urgency === "urgent"
          ? "bg-amber-500/10 text-amber-500 border-amber-500/30"
          : "bg-green-500/10 text-green-500 border-green-500/30";
  return <Badge variant="outline" className={`text-[10px] ${cls}`}>{urgency}</Badge>;
}

function PendingDeadlineCard({
  deadline,
  sourceText,
  onApprove,
  onReject,
  isSubmitting,
  canOperate,
}: {
  deadline: LegalDeadline;
  sourceText: string | null;
  onApprove: () => void;
  onReject: () => void;
  isSubmitting: boolean;
  canOperate: boolean;
}) {
  return (
    <Card className="border-amber-500/20 bg-amber-500/5">
      <CardContent className="p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{deadline.description}</p>
            <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" />
              <span>Due: {deadline.due_date}</span>
              {urgencyBadge(deadline.urgency)}
              {deadline.auto_extracted && (
                <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/30">
                  AI Extracted
                </Badge>
              )}
            </div>
          </div>
        </div>

        {sourceText && (
          <div className="rounded bg-muted/40 border border-dashed border-muted-foreground/20 p-2">
            <p className="text-[10px] font-medium text-muted-foreground flex items-center gap-1 mb-1">
              <Quote className="h-3 w-3" /> AI Source Quote (from document)
            </p>
            <p className="text-xs italic leading-relaxed">
              &ldquo;{sourceText}&rdquo;
            </p>
          </div>
        )}

        <div className="flex items-center gap-2 pt-1">
          <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
            <Button
              size="sm"
              variant="outline"
              className="bg-green-500/10 text-green-500 border-green-500/30 hover:bg-green-500/20"
              disabled={isSubmitting}
              onClick={onApprove}
            >
              <CheckCircle className="h-3 w-3 mr-1" /> Approve
            </Button>
          </RoleGatedAction>
          <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
            <Button
              size="sm"
              variant="outline"
              className="bg-red-500/10 text-red-500 border-red-500/30 hover:bg-red-500/20"
              disabled={isSubmitting}
              onClick={onReject}
            >
              <XCircle className="h-3 w-3 mr-1" /> Reject
            </Button>
          </RoleGatedAction>
        </div>
      </CardContent>
    </Card>
  );
}

export function HitlDeadlineQueue({ slug }: { slug: string }) {
  const user = useAppStore((state) => state.user);
  const canOperate = canManageLegalOps(user);
  const { data: caseData } = useCaseDetail(slug);
  const { data: deadlinesData, isLoading } = useCaseDeadlines(slug);
  const review = useDeadlineReview(slug);

  const deadlines = (deadlinesData?.deadlines ?? []) as LegalDeadline[];
  const pending = deadlines.filter((d) => d.review_status === "pending_review");
  const reviewed = deadlines.filter((d) => d.review_status !== "pending_review");

  const entities = (caseData?.case?.extracted_entities ?? null) as ExtractedEntities | null;

  return (
    <div className="p-4 space-y-4">
      <h3 className="text-sm font-semibold flex items-center gap-2">
        <Shield className="h-4 w-4 text-amber-500" />
        HITL Deadline Queue
        {pending.length > 0 && (
          <Badge className="bg-amber-500/20 text-amber-400 text-[10px]">
            {pending.length} pending
          </Badge>
        )}
      </h3>

      {isLoading && <p className="text-xs text-muted-foreground">Loading deadlines...</p>}

      {pending.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-amber-500 flex items-center gap-1">
            <AlertTriangle className="h-3 w-3" /> Pending Review
          </h4>
          {pending.map((d) => (
            <PendingDeadlineCard
              key={d.id}
              deadline={d}
              sourceText={findSourceText(d, entities)}
              onApprove={() =>
                canOperate && review.mutate({ deadlineId: d.id, action: "approved" })
              }
              onReject={() =>
                canOperate && review.mutate({ deadlineId: d.id, action: "rejected" })
              }
              isSubmitting={review.isPending || !canOperate}
              canOperate={canOperate}
            />
          ))}
        </div>
      )}

      {pending.length === 0 && !isLoading && deadlines.length > 0 && (
        <p className="text-xs text-muted-foreground py-4 text-center border rounded">
          All deadlines reviewed.
        </p>
      )}

      {reviewed.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold text-muted-foreground">All Deadlines</h4>
          {reviewed.map((d) => (
            <div key={d.id} className="flex items-center justify-between rounded border px-3 py-2 text-xs">
              <div className="min-w-0 flex-1">
                <span className="font-medium">{d.description}</span>
                <span className="text-muted-foreground ml-2">{d.due_date}</span>
              </div>
              <div className="flex items-center gap-2">
                {urgencyBadge(d.urgency)}
                <Badge
                  variant="outline"
                  className={`text-[10px] ${
                    d.review_status === "approved"
                      ? "bg-green-500/10 text-green-500 border-green-500/30"
                      : d.review_status === "rejected"
                        ? "bg-red-500/10 text-red-500 border-red-500/30"
                        : ""
                  }`}
                >
                  {d.review_status}
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}

      {deadlines.length === 0 && !isLoading && (
        <p className="text-xs text-muted-foreground py-4 text-center border rounded">
          No deadlines on file. Run AI extraction to detect deadlines.
        </p>
      )}
    </div>
  );
}
