"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Mail,
  RefreshCw,
  Link2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Paperclip,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";

// ── Types ─────────────────────────────────────────────────────────────────────

interface IntakeRecord {
  id: number;
  message_uid: string;
  sender_email: string;
  sender_name: string | null;
  subject: string | null;
  body_text: string | null;
  case_slug: string | null;
  triage_result: Record<string, unknown> | null;
  intake_status: "pending" | "linked" | "unlinked" | "rejected";
  attachment_count: number;
  correspondence_id: number | null;
  received_at: string;
  processed_at: string | null;
}

interface IntakeListResponse {
  items: IntakeRecord[];
  total: number;
  limit: number;
  offset: number;
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: IntakeRecord["intake_status"] }) {
  const styles: Record<string, string> = {
    linked:   "bg-green-500/10 text-green-500 border-green-500/30",
    unlinked: "bg-amber-500/10 text-amber-500 border-amber-500/30",
    pending:  "bg-blue-500/10 text-blue-400 border-blue-500/30",
    rejected: "bg-zinc-500/10 text-zinc-400 border-zinc-500/30",
  };
  return (
    <Badge variant="outline" className={`text-xs capitalize ${styles[status] ?? ""}`}>
      {status}
    </Badge>
  );
}

// ── Link-to-case modal ────────────────────────────────────────────────────────

function LinkModal({
  intakeId,
  onClose,
}: {
  intakeId: number;
  onClose: () => void;
}) {
  const [caseSlug, setCaseSlug] = useState("");
  const qc = useQueryClient();

  const linkMutation = useMutation({
    mutationFn: (slug: string) =>
      api.post<{ linked: boolean; case_slug: string }>(
        `/api/internal/legal/email-intake/${intakeId}/link`,
        { case_slug: slug },
      ),
    onSuccess: (data) => {
      toast.success(`Linked to case: ${data.case_slug}`);
      qc.invalidateQueries({ queryKey: ["legal", "email-intake"] });
      onClose();
    },
    onError: (err: Error) => {
      toast.error(`Link failed: ${err.message}`);
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-background border rounded-lg p-6 w-full max-w-sm shadow-xl space-y-4">
        <h3 className="font-semibold text-sm">Link to Case</h3>
        <input
          type="text"
          className="w-full rounded-md border bg-muted px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          placeholder="case-slug (e.g. johnson-v-crog)"
          value={caseSlug}
          onChange={(e) => setCaseSlug(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && caseSlug.trim()) linkMutation.mutate(caseSlug.trim());
          }}
        />
        <div className="flex gap-2 justify-end">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!caseSlug.trim() || linkMutation.isPending}
            onClick={() => linkMutation.mutate(caseSlug.trim())}
          >
            {linkMutation.isPending ? "Linking…" : "Link"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Row ───────────────────────────────────────────────────────────────────────

function IntakeRow({ record }: { record: IntakeRecord }) {
  const [expanded, setExpanded] = useState(false);
  const [showLinkModal, setShowLinkModal] = useState(false);
  const qc = useQueryClient();

  const rejectMutation = useMutation({
    mutationFn: () =>
      api.post<{ rejected: boolean }>(`/api/internal/legal/email-intake/${record.id}/reject`, {}),
    onSuccess: () => {
      toast.success("Marked as rejected");
      qc.invalidateQueries({ queryKey: ["legal", "email-intake"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const receivedDate = record.received_at
    ? new Date(record.received_at).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  const category = (record.triage_result?.category as string) || "";

  return (
    <>
      {showLinkModal && (
        <LinkModal intakeId={record.id} onClose={() => setShowLinkModal(false)} />
      )}
      <div className="border rounded-lg bg-card overflow-hidden">
        <div
          className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-accent/40 transition-colors"
          onClick={() => setExpanded((v) => !v)}
        >
          {/* Status */}
          <div className="shrink-0">
            <StatusBadge status={record.intake_status} />
          </div>

          {/* Subject + sender */}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">
              {record.subject || "(No subject)"}
            </p>
            <p className="text-xs text-muted-foreground truncate">
              {record.sender_name
                ? `${record.sender_name} <${record.sender_email}>`
                : record.sender_email}
              {category && (
                <span className="ml-2 text-muted-foreground/60">· {category}</span>
              )}
            </p>
          </div>

          {/* Case link */}
          <div className="shrink-0 text-xs text-muted-foreground w-36 truncate text-right">
            {record.case_slug ? (
              <Link
                href={`/legal/cases/${record.case_slug}`}
                className="text-primary hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {record.case_slug}
              </Link>
            ) : (
              "—"
            )}
          </div>

          {/* Attachments */}
          {record.attachment_count > 0 && (
            <div className="shrink-0 flex items-center gap-1 text-xs text-muted-foreground">
              <Paperclip className="h-3 w-3" />
              {record.attachment_count}
            </div>
          )}

          {/* Date */}
          <div className="shrink-0 text-xs text-muted-foreground w-28 text-right">
            {receivedDate}
          </div>

          {/* Expand chevron */}
          <div className="shrink-0 text-muted-foreground">
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </div>
        </div>

        {/* Expanded body */}
        {expanded && (
          <div className="border-t px-4 py-3 space-y-3 bg-muted/30">
            {record.body_text && (
              <pre className="text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed max-h-48 overflow-y-auto">
                {record.body_text.slice(0, 1200)}
                {record.body_text.length > 1200 && "\n…(truncated)"}
              </pre>
            )}

            {/* Actions */}
            {record.intake_status !== "rejected" && (
              <div className="flex gap-2 pt-1">
                {record.intake_status !== "linked" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-xs gap-1"
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowLinkModal(true);
                    }}
                  >
                    <Link2 className="h-3 w-3" />
                    Link to Case
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs gap-1 text-destructive hover:text-destructive"
                  disabled={rejectMutation.isPending}
                  onClick={(e) => {
                    e.stopPropagation();
                    rejectMutation.mutate();
                  }}
                >
                  <XCircle className="h-3 w-3" />
                  Reject
                </Button>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

// ── Main shell ────────────────────────────────────────────────────────────────

type FilterStatus = "all" | "unlinked" | "linked" | "rejected";

export function EmailIntakeShell() {
  const [filter, setFilter] = useState<FilterStatus>("unlinked");
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["legal", "email-intake", filter],
    queryFn: () => {
      const qs = filter !== "all" ? `?status=${filter}&limit=100` : "?limit=100";
      return api.get<IntakeListResponse>(`/api/internal/legal/email-intake${qs}`);
    },
    refetchInterval: 30_000,
  });

  const triggerMutation = useMutation({
    mutationFn: () =>
      api.post<{ triggered: boolean }>("/api/internal/legal/email-intake/trigger", {}),
    onSuccess: () => {
      toast.success("Import triggered — check back in a moment");
      setTimeout(() => qc.invalidateQueries({ queryKey: ["legal", "email-intake"] }), 3000);
    },
    onError: (err: Error) => toast.error(`Trigger failed: ${err.message}`),
  });

  const filterTabs: { key: FilterStatus; label: string }[] = [
    { key: "unlinked", label: "Unlinked" },
    { key: "linked",   label: "Linked" },
    { key: "all",      label: "All" },
    { key: "rejected", label: "Rejected" },
  ];

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/legal"
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <h1 className="text-xl font-bold flex items-center gap-2">
              <Mail className="h-5 w-5 text-primary" />
              Legal Email Intake
            </h1>
          </div>
          <p className="text-sm text-muted-foreground">
            Incoming correspondence from MailPlus — triaged, case-linked, and filed automatically.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="gap-2 shrink-0"
          disabled={triggerMutation.isPending}
          onClick={() => triggerMutation.mutate()}
        >
          <RefreshCw className={`h-4 w-4 ${triggerMutation.isPending ? "animate-spin" : ""}`} />
          {triggerMutation.isPending ? "Importing…" : "Trigger Import"}
        </Button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 border-b">
        {filterTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setFilter(tab.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
              filter === tab.key
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
        {data && (
          <span className="ml-auto self-center text-xs text-muted-foreground pr-1">
            {data.total} record{data.total !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-sm text-destructive py-4">
          Failed to load intake queue: {(error as Error).message}
        </p>
      )}

      {/* Empty state */}
      {!isLoading && !error && data?.items.length === 0 && (
        <div className="py-16 text-center text-muted-foreground text-sm space-y-2">
          <Mail className="h-8 w-8 mx-auto opacity-30" />
          <p>
            {filter === "unlinked"
              ? "No unlinked emails. All correspondence is accounted for."
              : `No ${filter} emails.`}
          </p>
        </div>
      )}

      {/* Records */}
      <div className="space-y-2">
        {data?.items.map((record) => (
          <IntakeRow key={record.id} record={record} />
        ))}
      </div>
    </div>
  );
}
