"use client";

import { useMemo, useState } from "react";
import { Check, Clock3, FileJson2, RefreshCw, ShieldAlert, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  useApproveSeoReviewPatch,
  useRejectSeoReviewPatch,
  useSeoReviewPatch,
  useSeoReviewQueue,
} from "@/lib/hooks";
import { cn } from "@/lib/utils";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number") return "--";
  return value.toFixed(3);
}

function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return "{}";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getDisplaySlug(propertySlug: string | null, pagePath: string): string {
  if (propertySlug?.trim()) return propertySlug;
  const segments = pagePath.split("/").filter(Boolean);
  return segments.at(-1) ?? pagePath;
}

function buildDefaultFinalPayload(patch: {
  title: string | null;
  meta_description: string | null;
  og_title: string | null;
  og_description: string | null;
  h1_suggestion: string | null;
  jsonld_payload: Record<string, unknown> | null;
  canonical_url: string | null;
  alt_tags: Record<string, unknown> | null;
  final_payload: Record<string, unknown> | null;
}): Record<string, unknown> {
  if (isRecord(patch.final_payload) && Object.keys(patch.final_payload).length > 0) {
    return patch.final_payload;
  }
  return {
    title: patch.title,
    meta_description: patch.meta_description,
    og_title: patch.og_title,
    og_description: patch.og_description,
    h1_suggestion: patch.h1_suggestion,
    jsonld: patch.jsonld_payload ?? {},
    canonical_url: patch.canonical_url,
    alt_tags: patch.alt_tags ?? {},
  };
}

const JSON_TOKEN_PATTERN =
  /("(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:])/g;

function tokenClass(token: string, isKey: boolean): string {
  if (isKey) return "text-sky-300";
  if (token.startsWith('"')) return "text-emerald-300";
  if (token === "true" || token === "false") return "text-violet-300";
  if (token === "null") return "text-slate-400";
  if (/^-?\d/.test(token)) return "text-amber-300";
  return "text-slate-500";
}

function renderJsonLine(line: string, lineKey: string) {
  const fragments: React.ReactNode[] = [];
  let cursor = 0;
  let index = 0;

  for (const match of line.matchAll(JSON_TOKEN_PATTERN)) {
    const token = match[0];
    const matchIndex = match.index ?? 0;

    if (matchIndex > cursor) {
      fragments.push(
        <span key={`${lineKey}-plain-${index}`}>{line.slice(cursor, matchIndex)}</span>,
      );
      index += 1;
    }

    const suffix = line.slice(matchIndex + token.length);
    const isKey = token.startsWith('"') && suffix.trimStart().startsWith(":");
    fragments.push(
      <span key={`${lineKey}-token-${index}`} className={tokenClass(token, isKey)}>
        {token}
      </span>,
    );

    cursor = matchIndex + token.length;
    index += 1;
  }

  if (cursor < line.length) {
    fragments.push(<span key={`${lineKey}-tail`}>{line.slice(cursor)}</span>);
  }

  return fragments.length > 0 ? fragments : " ";
}

function JsonCodeBlock({
  label,
  value,
  muted,
}: {
  label: string;
  value: unknown;
  muted?: boolean;
}) {
  const content = prettyJson(value);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
          {label}
        </p>
      </div>
      <div
        className={cn(
          "overflow-hidden rounded-xl border bg-slate-950",
          muted ? "border-slate-800/80" : "border-sky-500/20",
        )}
      >
        <ScrollArea className="max-h-[420px]">
          <pre className="overflow-x-auto p-4 text-xs leading-6 text-slate-100">
            <code>
              {content.split("\n").map((line, index) => (
                <div key={`${label}-${index}`} className="whitespace-pre">
                  {renderJsonLine(line, `${label}-${index}`)}
                </div>
              ))}
            </code>
          </pre>
        </ScrollArea>
      </div>
    </div>
  );
}

function QueueMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border bg-card/60 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold">{value}</p>
    </div>
  );
}

function DetailField({
  label,
  value,
}: {
  label: string;
  value: string | null | undefined;
}) {
  return (
    <div className="rounded-xl border p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">
        {value?.trim() ? value : "Not provided."}
      </p>
    </div>
  );
}

export function SeoReviewShell() {
  const queue = useSeoReviewQueue();
  const approvePatch = useApproveSeoReviewPatch();
  const rejectPatch = useRejectSeoReviewPatch();

  const [manualSelectedId, setManualSelectedId] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [payloadDraft, setPayloadDraft] = useState<{ patchId: string | null; text: string }>({
    patchId: null,
    text: "{}",
  });

  const queueItems = useMemo(() => queue.data ?? [], [queue.data]);
  const selectedId = useMemo(() => {
    if (!queueItems.length) return null;
    if (manualSelectedId && queueItems.some((item) => item.id === manualSelectedId)) {
      return manualSelectedId;
    }
    return queueItems[0]?.id ?? null;
  }, [manualSelectedId, queueItems]);

  const selectedPatch = useSeoReviewPatch(selectedId);
  const activePatch = selectedPatch.data ?? null;
  const defaultPayloadText = useMemo(
    () => (activePatch ? prettyJson(buildDefaultFinalPayload(activePatch)) : "{}"),
    [activePatch],
  );
  const payloadText =
    payloadDraft.patchId === activePatch?.id ? payloadDraft.text : defaultPayloadText;

  const averageScore = useMemo(() => {
    const scored = queueItems.filter((item) => typeof item.godhead_score === "number");
    if (scored.length === 0) return null;
    return (
      scored.reduce((sum, item) => sum + (item.godhead_score ?? 0), 0) / scored.length
    );
  }, [queueItems]);

  const newestClearTime = queueItems[0]?.updated_at ?? queueItems[0]?.created_at ?? null;

  const parsedPayload = useMemo(() => {
    try {
      const parsed = JSON.parse(payloadText);
      if (!isRecord(parsed)) {
        return {
          value: null,
          error: "Final payload override must be a JSON object.",
        };
      }
      return { value: parsed, error: null };
    } catch (error) {
      return {
        value: null,
        error: error instanceof Error ? error.message : "Invalid JSON payload.",
      };
    }
  }, [payloadText]);

  const isBusy = approvePatch.isPending || rejectPatch.isPending;

  const handleApprove = () => {
    if (!activePatch || parsedPayload.error || !parsedPayload.value) return;

    approvePatch.mutate(
      {
        patchId: activePatch.id,
        final_payload: parsedPayload.value,
        note: reviewNote.trim() || undefined,
      },
      {
        onSuccess: () => {
          setReviewNote("");
        },
      },
    );
  };

  const handleReject = () => {
    if (!activePatch) return;

    rejectPatch.mutate(
      {
        patchId: activePatch.id,
        note: reviewNote.trim() || undefined,
      },
      {
        onSuccess: () => {
          setReviewNote("");
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-3">
        <QueueMetric label="Pending Human Queue" value={String(queueItems.length)} />
        <QueueMetric
          label="Average God Head Score"
          value={averageScore === null ? "--" : averageScore.toFixed(3)}
        />
        <QueueMetric
          label="Latest Alpha Rubric Clear"
          value={formatDateTime(newestClearTime)}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Pending Queue</CardTitle>
                <CardDescription>
                  Human review targets cleared by the God Head.
                </CardDescription>
              </div>
              <Badge variant="outline" className="font-mono">
                {queue.isFetching ? "refreshing" : "live"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {queue.isLoading ? (
              <div className="flex h-[780px] items-center justify-center text-sm text-muted-foreground">
                Loading pending queue...
              </div>
            ) : queue.error ? (
              <div className="flex h-[780px] items-center justify-center px-6 text-center text-sm text-destructive">
                {queue.error instanceof Error
                  ? queue.error.message
                  : "Failed to load pending queue."}
              </div>
            ) : queueItems.length === 0 ? (
              <div className="flex h-[780px] items-center justify-center px-6 text-center text-sm text-muted-foreground">
                No pending human approvals in the queue.
              </div>
            ) : (
              <ScrollArea className="h-[780px]">
                <div className="space-y-3 p-4">
                  {queueItems.map((item) => {
                    const slug = getDisplaySlug(item.property_slug, item.page_path);
                    const isActive = item.id === selectedId;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setManualSelectedId(item.id)}
                        className={cn(
                          "w-full rounded-xl border p-4 text-left transition-colors",
                          isActive
                            ? "border-sky-500/40 bg-sky-500/10"
                            : "hover:bg-muted/50",
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate font-semibold">{slug}</p>
                            <p className="mt-1 truncate text-xs text-muted-foreground">
                              {item.page_path}
                            </p>
                          </div>
                          <Badge variant="outline" className="font-mono">
                            {formatScore(item.godhead_score)}
                          </Badge>
                        </div>
                        <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            <Clock3 className="h-3.5 w-3.5" />
                            {formatDateTime(item.updated_at ?? item.created_at)}
                          </span>
                          <span className="truncate">{item.property_name ?? "Unknown property"}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-6">
          {!selectedId ? (
            <Card>
              <CardContent className="flex h-[780px] items-center justify-center text-sm text-muted-foreground">
                Select a queue item to inspect the proposed payload.
              </CardContent>
            </Card>
          ) : selectedPatch.isLoading ? (
            <Card>
              <CardContent className="flex h-[780px] items-center justify-center text-sm text-muted-foreground">
                Loading patch detail...
              </CardContent>
            </Card>
          ) : selectedPatch.error || !activePatch ? (
            <Card>
              <CardContent className="flex h-[780px] items-center justify-center px-6 text-center text-sm text-destructive">
                {selectedPatch.error instanceof Error
                  ? selectedPatch.error.message
                  : "Failed to load patch detail."}
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardHeader className="pb-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-xl">
                          {getDisplaySlug(activePatch.property_slug, activePatch.page_path)}
                        </CardTitle>
                        <Badge variant="outline">{activePatch.status}</Badge>
                        <Badge variant="outline" className="font-mono">
                          score {formatScore(activePatch.godhead_score)}
                        </Badge>
                      </div>
                      <CardDescription>{activePatch.page_path}</CardDescription>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="inline-flex items-center gap-1">
                        <ShieldAlert className="h-3.5 w-3.5" />
                        {activePatch.godhead_model ?? "God Head model unknown"}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <RefreshCw className="h-3.5 w-3.5" />
                        {activePatch.grade_attempts} grading attempt
                        {activePatch.grade_attempts === 1 ? "" : "s"}
                      </span>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-3 xl:grid-cols-3">
                  <DetailField label="Proposed Title" value={activePatch.title} />
                  <DetailField
                    label="Meta Description"
                    value={activePatch.meta_description}
                  />
                  <DetailField label="H1" value={activePatch.h1_suggestion} />
                </CardContent>
              </Card>

              <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                <Card className="min-w-0">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">JSON-LD Diff Engine</CardTitle>
                    <CardDescription>
                      Generated schema payload ready for the final cache strike.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <JsonCodeBlock
                      label="Generated JSON-LD"
                      value={activePatch.jsonld_payload ?? {}}
                    />
                  </CardContent>
                </Card>

                <Card className="min-w-0">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base">God Head Trace</CardTitle>
                    <CardDescription>
                      Structured grading feedback currently available for human audit.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="rounded-xl border p-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                          Cleared At
                        </p>
                        <p className="mt-2 text-sm font-medium">
                          {formatDateTime(activePatch.updated_at ?? activePatch.created_at)}
                        </p>
                      </div>
                      <div className="rounded-xl border p-3">
                        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
                          Generation Time
                        </p>
                        <p className="mt-2 text-sm font-medium">
                          {typeof activePatch.generation_ms === "number"
                            ? `${activePatch.generation_ms.toLocaleString()} ms`
                            : "Unknown"}
                        </p>
                      </div>
                    </div>
                    <Separator />
                    <JsonCodeBlock
                      label="God Head Feedback"
                      value={activePatch.godhead_feedback ?? {}}
                      muted
                    />
                  </CardContent>
                </Card>
              </div>

              <Card className="min-w-0">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Final Payload Override</CardTitle>
                  <CardDescription>
                    Optional phase 1.5 raw JSON editor. Approval will deploy this object.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Textarea
                    value={payloadText}
                    onChange={(event) =>
                      setPayloadDraft({
                        patchId: activePatch.id,
                        text: event.target.value,
                      })
                    }
                    className="min-h-[260px] font-mono text-xs"
                    spellCheck={false}
                  />
                  {parsedPayload.error ? (
                    <p className="text-sm text-destructive">{parsedPayload.error}</p>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Override payload validated. Approve will ship this object to deploy.
                    </p>
                  )}
                </CardContent>
              </Card>

              <Card className="sticky bottom-0 z-10 border-sky-500/20 bg-background/95 backdrop-blur">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Execution Surface</CardTitle>
                  <CardDescription>
                    Seal or reject the current payload with a single tactical action.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <Textarea
                    value={reviewNote}
                    onChange={(event) => setReviewNote(event.target.value)}
                    className="min-h-24"
                    placeholder="Optional review note for audit trail."
                  />
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      type="button"
                      disabled={isBusy || Boolean(parsedPayload.error)}
                      onClick={handleApprove}
                    >
                      <Check className="mr-1.5 h-4 w-4" />
                      Approve And Strike Cache
                    </Button>
                    <Button
                      type="button"
                      variant="destructive"
                      disabled={isBusy}
                      onClick={handleReject}
                    >
                      <X className="mr-1.5 h-4 w-4" />
                      Reject Draft
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={isBusy}
                      onClick={() =>
                        setPayloadDraft({
                          patchId: activePatch.id,
                          text: prettyJson(buildDefaultFinalPayload(activePatch)),
                        })
                      }
                    >
                      <FileJson2 className="mr-1.5 h-4 w-4" />
                      Reset JSON Override
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
