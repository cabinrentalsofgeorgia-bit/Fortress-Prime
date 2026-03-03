"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useCaseCorrespondence,
  useCaseTimeline,
  useUpdateCorrespondenceStatus,
  downloadCorrespondence,
  copyCorrespondenceContent,
} from "@/lib/legal-hooks";
import type { LegalCase, Correspondence, TimelineEvent } from "@/lib/legal-types";
import {
  FileText,
  Mail,
  Clock,
  ArrowDownLeft,
  ArrowUpRight,
  Download,
  ClipboardCopy,
  CheckCircle2,
  Loader2,
  Shield,
} from "lucide-react";

function CaseNotesView({ legalCase }: { legalCase: LegalCase }) {
  return (
    <div className="space-y-4 text-sm">
      {legalCase.our_claim_basis && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-1">Claim Basis</h4>
          <pre className="whitespace-pre-wrap text-xs bg-muted/30 rounded p-3">{legalCase.our_claim_basis}</pre>
        </div>
      )}
      {legalCase.notes && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-1">Notes</h4>
          <pre className="whitespace-pre-wrap text-xs bg-muted/30 rounded p-3">{legalCase.notes}</pre>
        </div>
      )}
      {legalCase.critical_note && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-1">Critical Note</h4>
          <pre className="whitespace-pre-wrap text-xs bg-muted/30 rounded p-3 text-amber-400">{legalCase.critical_note}</pre>
        </div>
      )}
      {!legalCase.our_claim_basis && !legalCase.notes && !legalCase.critical_note && (
        <p className="text-xs text-muted-foreground py-8 text-center">No case notes recorded.</p>
      )}
    </div>
  );
}

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-amber-500/10 text-amber-500 border-amber-500/30",
  approved: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  sent: "bg-green-500/10 text-green-500 border-green-500/30",
  filed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  received: "bg-purple-500/10 text-purple-400 border-purple-500/30",
  cancelled: "bg-zinc-500/10 text-zinc-400 border-zinc-500/30",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-zinc-500/10 text-zinc-400 border-zinc-500/30";
  return (
    <Badge variant="outline" className={`text-[10px] uppercase tracking-wider ${cls}`}>
      {status}
    </Badge>
  );
}

function hasTextFile(filePath: string | null): boolean {
  if (!filePath) return false;
  return filePath.endsWith(".txt") || filePath.endsWith(".md") || filePath.endsWith(".csv");
}

function CorrespondenceVaultRow({
  item,
  slug,
}: {
  item: Correspondence;
  slug: string;
}) {
  const statusMutation = useUpdateCorrespondenceStatus(slug);
  const [downloading, setDownloading] = useState(false);
  const [copying, setCopying] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await downloadCorrespondence(item.id);
    } finally {
      setDownloading(false);
    }
  };

  const handleCopy = async () => {
    setCopying(true);
    try {
      await copyCorrespondenceContent(item.id);
    } finally {
      setCopying(false);
    }
  };

  const handleMarkSent = () => {
    statusMutation.mutate({ corrId: item.id, status: "sent" });
  };

  const filename = item.file_path?.split("/").pop() ?? null;

  return (
    <div className="rounded border bg-card p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 text-xs min-w-0 flex-1">
          {item.direction === "inbound" ? (
            <ArrowDownLeft className="h-3.5 w-3.5 text-blue-400 shrink-0" />
          ) : (
            <ArrowUpRight className="h-3.5 w-3.5 text-green-400 shrink-0" />
          )}
          <span className="font-medium truncate">{item.subject}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Badge variant="outline" className="text-[10px]">{item.comm_type}</Badge>
          <StatusBadge status={item.status} />
        </div>
      </div>

      {item.recipient && (
        <p className="text-[11px] text-muted-foreground pl-5">
          To: {item.recipient}
        </p>
      )}
      {item.body && (
        <p className="text-xs text-muted-foreground line-clamp-2 pl-5">{item.body}</p>
      )}

      <div className="flex items-center justify-between pt-1 border-t border-border/50">
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
          <span>{new Date(item.created_at).toLocaleDateString()}</span>
          {item.sent_at && (
            <span className="text-green-500">
              Sent {new Date(item.sent_at).toLocaleDateString()}
            </span>
          )}
          {filename && (
            <span className="flex items-center gap-0.5">
              <Shield className="h-2.5 w-2.5" />
              {filename}
            </span>
          )}
        </div>

        <TooltipProvider delayDuration={200}>
          <div className="flex items-center gap-1">
            {item.file_path && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={handleDownload}
                    disabled={downloading}
                  >
                    {downloading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  <p>Download file</p>
                </TooltipContent>
              </Tooltip>
            )}

            {hasTextFile(item.file_path) && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={handleCopy}
                    disabled={copying}
                  >
                    {copying ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <ClipboardCopy className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  <p>Copy draft to clipboard</p>
                </TooltipContent>
              </Tooltip>
            )}

            {item.status === "draft" && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-green-500 hover:text-green-400 hover:bg-green-500/10"
                    onClick={handleMarkSent}
                    disabled={statusMutation.isPending}
                  >
                    {statusMutation.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  <p>Mark as sent</p>
                </TooltipContent>
              </Tooltip>
            )}
          </div>
        </TooltipProvider>
      </div>
    </div>
  );
}

function CorrespondenceVault({ slug }: { slug: string }) {
  const { data, isLoading } = useCaseCorrespondence(slug);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-8 justify-center">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading correspondence vault...
      </div>
    );
  }

  const items = data?.correspondence ?? [];

  if (items.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-8 text-center">
        No correspondence in the vault.
      </p>
    );
  }

  const drafts = items.filter((c: Correspondence) => c.status === "draft");
  const others = items.filter((c: Correspondence) => c.status !== "draft");

  return (
    <div className="space-y-3">
      {drafts.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold text-amber-500 uppercase tracking-wider flex items-center gap-1.5">
            <Mail className="h-3 w-3" />
            Pending Drafts ({drafts.length})
          </h4>
          {drafts.map((c: Correspondence) => (
            <CorrespondenceVaultRow key={c.id} item={c} slug={slug} />
          ))}
        </div>
      )}
      {others.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            History ({others.length})
          </h4>
          {others.map((c: Correspondence) => (
            <CorrespondenceVaultRow key={c.id} item={c} slug={slug} />
          ))}
        </div>
      )}
    </div>
  );
}

function TimelineView({ slug }: { slug: string }) {
  const { data, isLoading } = useCaseTimeline(slug);
  if (isLoading) return <p className="text-xs text-muted-foreground">Loading...</p>;
  const events = (data ?? []) as TimelineEvent[];
  if (events.length === 0) return <p className="text-xs text-muted-foreground py-8 text-center">No timeline events.</p>;
  return (
    <div className="space-y-2">
      {events.map((e, idx) => (
        <div key={idx} className="rounded border p-2 text-xs space-y-1">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">{e.event_type}</Badge>
            <span className="text-muted-foreground">
              {new Date(e.event_time).toLocaleString()}
            </span>
          </div>
          <p>{e.summary}</p>
        </div>
      ))}
    </div>
  );
}

export function DocumentViewer({ legalCase, slug }: { legalCase: LegalCase; slug: string }) {
  return (
    <div className="h-full overflow-y-auto p-4">
      <Tabs defaultValue="document">
        <TabsList className="w-full">
          <TabsTrigger value="document" className="flex items-center gap-1">
            <FileText className="h-3 w-3" /> Document
          </TabsTrigger>
          <TabsTrigger value="correspondence" className="flex items-center gap-1">
            <Shield className="h-3 w-3" /> Vault
          </TabsTrigger>
          <TabsTrigger value="timeline" className="flex items-center gap-1">
            <Clock className="h-3 w-3" /> Timeline
          </TabsTrigger>
        </TabsList>
        <TabsContent value="document" className="mt-3">
          <CaseNotesView legalCase={legalCase} />
        </TabsContent>
        <TabsContent value="correspondence" className="mt-3">
          <CorrespondenceVault slug={slug} />
        </TabsContent>
        <TabsContent value="timeline" className="mt-3">
          <TimelineView slug={slug} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
