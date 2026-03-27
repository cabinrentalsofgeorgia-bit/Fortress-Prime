"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FileWarning,
  LoaderCircle,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  approveSeoQueuePatch,
  editSeoQueuePatch,
  getSeoPatchAuditTrail,
  getSeoQueuePatch,
  rejectSeoQueuePatch,
  type SeoReviewFinalPayload,
} from "@/lib/api/seo-queue";
import type { OpenShellAuditEntry, SeoReviewPatch } from "@/lib/types";

type JsonObject = Record<string, unknown>;

interface DraftFields {
  title: string;
  metaDescription: string;
  h1Suggestion: string;
  jsonldPayload: string;
}

function isRecord(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function prettyJson(value: unknown): string {
  if (!value) return "{}";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return "{}";
  }
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number") return "--";
  return value.toFixed(3);
}

function formatStatus(status: string): string {
  return status
    .split("_")
    .map((chunk) => chunk.slice(0, 1).toUpperCase() + chunk.slice(1))
    .join(" ");
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  return new Date(value).toLocaleString();
}

function deployBadgeClass(status: SeoReviewPatch["deploy_status"]): string {
  switch (status) {
    case "succeeded":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "failed":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    case "processing":
      return "border-sky-500/30 bg-sky-500/10 text-sky-200";
    case "queued":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    default:
      return "border-slate-700 bg-slate-900 text-slate-300";
  }
}

function formatDeployStatus(status: SeoReviewPatch["deploy_status"]): string {
  if (!status) return "Not Queued";
  return formatStatus(status);
}

function buildFinalPayload(patch: SeoReviewPatch, draft: DraftFields): SeoReviewFinalPayload {
  return {
    title: draft.title.trim() || null,
    meta_description: draft.metaDescription.trim() || null,
    og_title: patch.og_title,
    og_description: patch.og_description,
    h1_suggestion: draft.h1Suggestion.trim() || null,
    jsonld: JSON.parse(draft.jsonldPayload) as JsonObject,
    canonical_url: patch.canonical_url,
    alt_tags: patch.alt_tags ?? {},
  };
}

function extractFeedbackLines(feedback: Record<string, unknown> | null): string[] {
  if (!feedback) return [];

  const lines: string[] = [];
  const candidateKeys = [
    "warnings",
    "issues",
    "blockers",
    "recommendations",
    "feedback",
    "summary",
  ];

  for (const key of candidateKeys) {
    const value = feedback[key];
    if (typeof value === "string" && value.trim()) {
      lines.push(value.trim());
      continue;
    }

    if (!Array.isArray(value)) continue;

    for (const entry of value) {
      if (typeof entry === "string" && entry.trim()) {
        lines.push(entry.trim());
        continue;
      }

      if (isRecord(entry)) {
        const message = [entry.message, entry.warning, entry.issue, entry.title]
          .find((candidate) => typeof candidate === "string" && candidate.trim());
        if (typeof message === "string") {
          lines.push(message.trim());
        }
      }
    }
  }

  return Array.from(new Set(lines));
}

function JsonPreview({ value }: { value: Record<string, unknown> | null }) {
  return (
    <pre className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950 p-4 text-xs leading-6 text-slate-200">
      {prettyJson(value)}
    </pre>
  );
}

function AuditTrail({ entries }: { entries: OpenShellAuditEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-sm text-slate-400">
        No deploy audit events have been recorded for this patch yet.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {entries.map((entry) => (
        <div key={entry.id} className="rounded-xl border border-slate-800 bg-slate-900/80 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-100">{entry.action}</p>
              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{entry.outcome}</p>
            </div>
            <p className="text-xs text-slate-500">{formatTimestamp(entry.created_at)}</p>
          </div>
          {typeof entry.metadata_json.error === "string" && entry.metadata_json.error ? (
            <p className="mt-3 text-sm text-rose-300">{entry.metadata_json.error}</p>
          ) : null}
          {typeof entry.metadata_json.http_status === "number" ? (
            <p className="mt-3 text-xs text-slate-400">
              HTTP status: {entry.metadata_json.http_status}
            </p>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function SeoReviewDetailContent({
  patch,
  patchId,
}: {
  patch: SeoReviewPatch;
  patchId: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<DraftFields>({
    title: patch.title ?? "",
    metaDescription: patch.meta_description ?? "",
    h1Suggestion: patch.h1_suggestion ?? "",
    jsonldPayload: prettyJson(patch.jsonld_payload ?? {}),
  });
  const [reviewNote, setReviewNote] = useState("");
  const [lastActionMessage, setLastActionMessage] = useState<string | null>(null);

  const parsedJsonLd = useMemo(() => {
    try {
      const parsed = JSON.parse(draft.jsonldPayload);
      if (!isRecord(parsed)) {
        return {
          value: null,
          error: "JSON-LD payload must be a JSON object.",
        };
      }

      return { value: parsed, error: null };
    } catch (error) {
      return {
        value: null,
        error: error instanceof Error ? error.message : "Invalid JSON-LD payload.",
      };
    }
  }, [draft.jsonldPayload]);

  const approveMutation = useMutation({
    mutationFn: () => approveSeoQueuePatch(patchId, { note: reviewNote }),
    onSuccess: (updatedPatch) => {
      queryClient.setQueryData(["seo-review-dashboard", "patch", patchId], updatedPatch);
      void queryClient.invalidateQueries({ queryKey: ["seo-review-dashboard", "queue"] });
      setLastActionMessage("Approval sealed. Revalidation strike queued.");
      toast.success("SEO patch approved. Revalidation strike queued.");
      setReviewNote("");
      router.refresh();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Approval failed.");
    },
  });

  const editMutation = useMutation({
    mutationFn: (payload: SeoReviewFinalPayload) =>
      editSeoQueuePatch(patchId, {
        final_payload: payload,
        note: reviewNote,
      }),
    onSuccess: (updatedPatch) => {
      queryClient.setQueryData(["seo-review-dashboard", "patch", patchId], updatedPatch);
      void queryClient.invalidateQueries({ queryKey: ["seo-review-dashboard", "queue"] });
      setLastActionMessage("Edited payload sealed. Revalidation strike queued.");
      toast.success("Edits saved. Revalidation strike queued.");
      setReviewNote("");
      router.refresh();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Edit approval failed.");
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectSeoQueuePatch(patchId, { note: reviewNote }),
    onSuccess: (updatedPatch) => {
      queryClient.setQueryData(["seo-review-dashboard", "patch", patchId], updatedPatch);
      void queryClient.invalidateQueries({ queryKey: ["seo-review-dashboard", "queue"] });
      toast.success("SEO patch rejected.");
      setReviewNote("");
      router.push("/seo-review");
      router.refresh();
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Reject failed.");
    },
  });

  const feedbackLines = extractFeedbackLines(patch.godhead_feedback ?? null);
  const isBusy =
    approveMutation.isPending || editMutation.isPending || rejectMutation.isPending;
  const isPendingHuman = patch.status === "pending_human";
  const isDeployInFlight = patch.deploy_status === "queued" || patch.deploy_status === "processing";

  const auditTrail = useQuery({
    queryKey: ["seo-review-dashboard", "patch-audit", patchId],
    queryFn: () => getSeoPatchAuditTrail(patchId),
    staleTime: 5_000,
    refetchInterval: isDeployInFlight ? 3_000 : false,
  });

  return (
    <div className="space-y-6">
      <Button asChild variant="ghost" size="sm">
        <Link href="/seo-review">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Review Queue
        </Link>
      </Button>

      <>
          <Card className="border-slate-800 bg-slate-950/70">
            <CardHeader className="border-b border-slate-800/80">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-2xl text-slate-100">
                      {patch.property_name ?? patch.property_slug ?? patch.page_path}
                    </CardTitle>
                    <Badge
                      variant="outline"
                      className="border-amber-500/30 bg-amber-500/10 text-amber-200"
                    >
                      {formatStatus(patch.status)}
                    </Badge>
                  </div>
                  <CardDescription className="text-slate-400">
                    {patch.page_path}
                  </CardDescription>
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                      God Head Score
                    </p>
                    <p className="mt-2 font-mono text-xl text-slate-100">
                      {formatScore(patch.godhead_score)}
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                      Grade Attempts
                    </p>
                    <p className="mt-2 text-xl text-slate-100">{patch.grade_attempts}</p>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">
                      God Head Model
                    </p>
                    <p className="mt-2 text-sm text-slate-100">
                      {patch.godhead_model ?? "Unknown"}
                    </p>
                  </div>
                </div>
              </div>
            </CardHeader>
          </Card>

          <Card className="border-slate-800 bg-slate-950/70">
            <CardHeader>
              <CardTitle className="text-base text-slate-100">Deployment Strike</CardTitle>
              <CardDescription className="text-slate-400">
                Authoritative approval state is sealed first. Edge acknowledgment is tracked separately.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="outline" className={deployBadgeClass(patch.deploy_status)}>
                  {formatDeployStatus(patch.deploy_status)}
                </Badge>
                {patch.deploy_task_id ? (
                  <p className="text-xs text-slate-500">Task {patch.deploy_task_id}</p>
                ) : null}
              </div>
              {lastActionMessage ? (
                <div className="rounded-xl border border-sky-500/20 bg-sky-500/10 p-3 text-sm text-sky-100">
                  {lastActionMessage}
                </div>
              ) : null}
              {patch.deploy_last_error ? (
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-200">
                  {patch.deploy_last_error}
                </div>
              ) : null}
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Queued</p>
                  <p className="mt-2 text-sm text-slate-100">{formatTimestamp(patch.deploy_queued_at)}</p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Acknowledged</p>
                  <p className="mt-2 text-sm text-slate-100">
                    {formatTimestamp(patch.deploy_acknowledged_at)}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">Attempts</p>
                  <p className="mt-2 text-sm text-slate-100">{patch.deploy_attempts}</p>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.22em] text-slate-500">HTTP Status</p>
                  <p className="mt-2 text-sm text-slate-100">
                    {patch.deploy_last_http_status ?? "--"}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <Card className="border-slate-800 bg-slate-950/70">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base text-slate-100">
                  <ShieldAlert className="h-4 w-4 text-amber-300" />
                  God Head Feedback
                </CardTitle>
                <CardDescription className="text-slate-400">
                  Audit warnings before sealing the deployment strike.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {feedbackLines.length > 0 ? (
                  <div className="space-y-3">
                    {feedbackLines.map((line) => (
                      <div
                        key={line}
                        className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-100"
                      >
                        {line}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-sm text-slate-400">
                    No structured warning lines were provided by the God Head feedback payload.
                  </div>
                )}

                <Separator className="bg-slate-800" />

                <div className="space-y-3">
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">
                    Raw Feedback Payload
                  </p>
                  <JsonPreview value={patch.godhead_feedback} />
                </div>
              </CardContent>
            </Card>

            <Card className="border-slate-800 bg-slate-950/70">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base text-slate-100">
                  <FileWarning className="h-4 w-4 text-sky-300" />
                  Draft Payload Editor
                </CardTitle>
                <CardDescription className="text-slate-400">
                  Edit the final review payload before approval. Approve As-Is ignores these edits.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="seo-title">Title</Label>
                  <Input
                    id="seo-title"
                    value={draft.title}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, title: event.target.value }))
                    }
                    className="border-slate-800 bg-slate-900 text-slate-100"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="seo-meta-description">Meta Description</Label>
                  <Textarea
                    id="seo-meta-description"
                    value={draft.metaDescription}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        metaDescription: event.target.value,
                      }))
                    }
                    className="min-h-[120px] border-slate-800 bg-slate-900 text-slate-100"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="seo-h1-suggestion">H1 Suggestion</Label>
                  <Input
                    id="seo-h1-suggestion"
                    value={draft.h1Suggestion}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        h1Suggestion: event.target.value,
                      }))
                    }
                    className="border-slate-800 bg-slate-900 text-slate-100"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="seo-jsonld-payload">JSON-LD Payload</Label>
                  <Textarea
                    id="seo-jsonld-payload"
                    value={draft.jsonldPayload}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        jsonldPayload: event.target.value,
                      }))
                    }
                    className="min-h-[300px] border-slate-800 bg-slate-950 font-mono text-xs text-slate-100"
                    spellCheck={false}
                  />
                  {parsedJsonLd.error ? (
                    <p className="text-sm text-rose-300">{parsedJsonLd.error}</p>
                  ) : (
                    <p className="text-sm text-slate-400">
                      JSON-LD validated. Save Edits & Approve will deploy this object.
                    </p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card className="border-slate-800 bg-slate-950/70">
            <CardHeader>
              <CardTitle className="text-base text-slate-100">Audit Telemetry</CardTitle>
              <CardDescription className="text-slate-400">
                OpenShell records for review, queue, and edge acknowledgment events.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {auditTrail.isLoading ? (
                <div className="flex items-center gap-3 text-sm text-slate-400">
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                  Loading audit telemetry...
                </div>
              ) : auditTrail.error ? (
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-200">
                  {auditTrail.error instanceof Error
                    ? auditTrail.error.message
                    : "Failed to load audit telemetry."}
                </div>
              ) : (
                <AuditTrail entries={auditTrail.data ?? []} />
              )}
            </CardContent>
          </Card>

          <Card className="border-slate-800 bg-slate-950/70">
            <CardHeader>
              <CardTitle className="text-base text-slate-100">Action Bar</CardTitle>
              <CardDescription className="text-slate-400">
                Approval note is optional. Reject requires a note for the audit trail.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!isPendingHuman ? (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-100">
                  This patch is no longer in `pending_human`. Review actions are disabled.
                </div>
              ) : null}

              <div className="space-y-2">
                <Label htmlFor="seo-review-note">Review Note</Label>
                <Textarea
                  id="seo-review-note"
                  value={reviewNote}
                  onChange={(event) => setReviewNote(event.target.value)}
                  className="min-h-[120px] border-slate-800 bg-slate-900 text-slate-100"
                />
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  disabled={!isPendingHuman || isBusy}
                  onClick={() => approveMutation.mutate()}
                >
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  Approve As-Is
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!isPendingHuman || isBusy || Boolean(parsedJsonLd.error)}
                  onClick={() => {
                    if (parsedJsonLd.error) return;
                    editMutation.mutate(buildFinalPayload(patch, draft));
                  }}
                >
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  Save Edits & Approve
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  disabled={!isPendingHuman || isBusy || !reviewNote.trim()}
                  onClick={() => rejectMutation.mutate()}
                >
                  <XCircle className="mr-2 h-4 w-4" />
                  Reject / Discard
                </Button>
              </div>
            </CardContent>
          </Card>
      </>
    </div>
  );
}

export function SeoReviewDetail({ patchId }: { patchId: string }) {
  const patch = useQuery({
    queryKey: ["seo-review-dashboard", "patch", patchId],
    queryFn: () => getSeoQueuePatch(patchId),
    staleTime: 5_000,
    refetchInterval: (query) => {
      const current = query.state.data;
      if (!current) return false;
      return current.deploy_status === "queued" || current.deploy_status === "processing"
        ? 3_000
        : false;
    },
  });

  if (patch.isLoading) {
    return (
      <div className="space-y-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/seo-review">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Review Queue
          </Link>
        </Button>
        <Card className="border-slate-800 bg-slate-950/70">
          <CardContent className="flex min-h-[420px] items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <LoaderCircle className="h-4 w-4 animate-spin" />
              Loading SEO patch detail...
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (patch.error) {
    return (
      <div className="space-y-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/seo-review">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Review Queue
          </Link>
        </Button>
        <Card className="border-rose-900/60 bg-slate-950/70">
          <CardContent className="flex min-h-[420px] flex-col items-center justify-center gap-4 px-6 text-center">
            <AlertCircle className="h-8 w-8 text-rose-400" />
            <p className="max-w-xl text-sm text-rose-300">
              {patch.error instanceof Error
                ? patch.error.message
                : "Failed to load the SEO patch detail."}
            </p>
            <Button type="button" onClick={() => patch.refetch()}>
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!patch.data) {
    return (
      <div className="space-y-6">
        <Button asChild variant="ghost" size="sm">
          <Link href="/seo-review">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Review Queue
          </Link>
        </Button>
        <Card className="border-slate-800 bg-slate-950/70">
          <CardContent className="flex min-h-[420px] items-center justify-center text-sm text-slate-400">
            No SEO patch found for this review target.
          </CardContent>
        </Card>
      </div>
    );
  }

  return <SeoReviewDetailContent key={patch.data.id} patch={patch.data} patchId={patchId} />;
}
