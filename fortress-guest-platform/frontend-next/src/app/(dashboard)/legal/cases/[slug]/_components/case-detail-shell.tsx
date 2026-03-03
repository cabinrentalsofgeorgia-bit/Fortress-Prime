"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCaseDetail, useCaseExtractionPoll } from "@/lib/legal-hooks";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertTriangle, Clock, Loader2, Scale } from "lucide-react";
import { DocumentViewer } from "./document-viewer";
import { ExtractionPanel } from "./extraction-panel";
import { HitlDeadlineQueue } from "./hitl-deadline-queue";
import type { LegalCase, ExtractionStatus } from "@/lib/legal-types";

function riskBadge(score: number | null) {
  if (score === null || score === undefined) return null;
  const cls =
    score >= 4
      ? "bg-red-500/10 text-red-500 border-red-500/30"
      : score >= 3
        ? "bg-amber-500/10 text-amber-500 border-amber-500/30"
        : "bg-green-500/10 text-green-500 border-green-500/30";
  return <Badge variant="outline" className={cls}>Risk {score}/5</Badge>;
}

function StatusPill({ status }: { status: ExtractionStatus }) {
  if (status === "processing" || status === "queued")
    return (
      <Badge variant="outline" className="bg-blue-500/10 text-blue-400 border-blue-500/30 animate-pulse">
        <Loader2 className="h-3 w-3 mr-1 animate-spin" />
        {status === "queued" ? "Queued" : "Extracting..."}
      </Badge>
    );
  if (status === "complete")
    return <Badge variant="outline" className="bg-green-500/10 text-green-500 border-green-500/30">Complete</Badge>;
  if (status === "failed")
    return <Badge variant="outline" className="bg-red-500/10 text-red-500 border-red-500/30">Failed</Badge>;
  return null;
}

export function CaseDetailShell({ slug }: { slug: string }) {
  const { data, isLoading, error } = useCaseDetail(slug);
  const poll = useCaseExtractionPoll(slug);
  const qc = useQueryClient();

  const liveCase = poll.data?.case ?? data?.case;

  useEffect(() => {
    if (liveCase?.extraction_status === "complete") {
      qc.invalidateQueries({ queryKey: ["legal", "case", slug] });
      qc.invalidateQueries({ queryKey: ["legal", "deadlines", slug] });
    }
  }, [liveCase?.extraction_status, qc, slug]);

  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-[600px] w-full" />
      </div>
    );
  }

  if (error || !liveCase) {
    return (
      <div className="p-6">
        <p className="text-destructive text-sm">
          Failed to load case: {error?.message ?? "Not found"}
        </p>
      </div>
    );
  }

  const c = liveCase;
  const daysRemaining = c.days_remaining ?? null;

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b space-y-1 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Scale className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-bold">{c.case_name}</h1>
          {riskBadge(c.risk_score)}
          <StatusPill status={c.extraction_status} />
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
          <span>{c.case_number}</span>
          <span>&middot;</span>
          <span>{c.court}</span>
          {c.judge && <><span>&middot;</span><span>Judge {c.judge}</span></>}
          <span>&middot;</span>
          <Badge variant="secondary" className="text-[10px]">{c.our_role}</Badge>
          {c.critical_date && (
            <>
              <span>&middot;</span>
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {c.critical_date}
                {daysRemaining !== null && daysRemaining <= 14 && (
                  <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-500 border-amber-500/30 ml-1">
                    <AlertTriangle className="h-2.5 w-2.5 mr-0.5" />
                    {daysRemaining}d left
                  </Badge>
                )}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <ResizablePanelGroup orientation="horizontal">
          <ResizablePanel defaultSize={45} minSize={30}>
            <DocumentViewer legalCase={c} slug={slug} />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={55} minSize={35}>
            <div className="h-full flex flex-col min-h-0 overflow-y-auto">
              <ExtractionPanel legalCase={c} slug={slug} />
              <HitlDeadlineQueue slug={slug} />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
