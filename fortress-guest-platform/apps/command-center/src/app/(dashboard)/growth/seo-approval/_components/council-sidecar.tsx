"use client";

import { useCallback, useMemo, useState } from "react";
import {
  FileJson,
  Loader2,
  Play,
  Radio,
  Route,
  Scale,
  Shield,
  Sparkles,
} from "lucide-react";

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
import type { SeoPatchQueueItem } from "@/lib/types";
import { useCouncilStream } from "@/lib/use-council-stream";
import { cn } from "@/lib/utils";

const SEO_MIGRATION_CASE_SLUG = "seo_migration_case";

const SIGNAL_STYLES: Record<string, string> = {
  STRONG_DEFENSE:
    "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  DEFENSE: "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300",
  NEUTRAL: "border-slate-500/30 bg-slate-500/10 text-slate-700 dark:text-slate-300",
  WEAK: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  VULNERABLE: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300",
  ERROR: "border-zinc-500/30 bg-zinc-500/10 text-zinc-700 dark:text-zinc-300",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function pickString(
  source: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
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

function buildSeoCouncilBrief(patch: SeoPatchQueueItem): string {
  const snapshot = asRecord(patch.fact_snapshot) ?? {};
  const jsonLd = asRecord(patch.proposed_json_ld) ?? {};
  const legacyPath = pickString(snapshot, [
    "scrape_url",
    "archive_path",
    "original_slug",
    "source_alias",
  ]);
  const proposedUrl = pickString(jsonLd, ["url", "@id"]) ?? `/properties/${patch.target_slug}`;
  const legacyTitle = pickString(snapshot, ["title", "page_title"]);
  const legacyDescription = pickString(snapshot, [
    "meta_description",
    "description",
    "summary",
  ]);

  return [
    "SEO migration sovereign audit.",
    "",
    `Legacy route: ${legacyPath ?? "unknown"}`,
    `Proposed route: ${proposedUrl}`,
    `Target slug: ${patch.target_slug}`,
    `Target keyword: ${patch.target_keyword || "n/a"}`,
    `Campaign: ${patch.campaign}`,
    "",
    "Determine whether the redirect and metadata preserve semantic intent between the Drupal archive page and the Next.js destination.",
    "",
    `Legacy title: ${legacyTitle ?? "n/a"}`,
    `Legacy description: ${legacyDescription ?? "n/a"}`,
    `Proposed title: ${patch.proposed_title || "n/a"}`,
    `Proposed meta description: ${patch.proposed_meta_description || "n/a"}`,
    `Proposed H1: ${patch.proposed_h1 || "n/a"}`,
  ].join("\n");
}

function buildSeoCouncilContext(patch: SeoPatchQueueItem): string {
  return [
    "Legacy snapshot:",
    prettyJson(patch.fact_snapshot),
    "",
    "Proposed JSON-LD:",
    prettyJson(patch.proposed_json_ld),
  ].join("\n");
}

function DetailBlock({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | null;
  tone?: "neutral" | "legacy" | "proposed";
}) {
  const toneClasses =
    tone === "legacy"
      ? "border-slate-500/20 bg-slate-500/5"
      : tone === "proposed"
        ? "border-sky-500/20 bg-sky-500/5"
        : "border-border bg-muted/20";

  return (
    <div className={cn("rounded-lg border p-3", toneClasses)}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">
        {value || "Not available"}
      </p>
    </div>
  );
}

export function SeoCouncilSidecar({
  patch,
}: {
  patch: SeoPatchQueueItem | null;
}) {
  const [launchError, setLaunchError] = useState<string | null>(null);

  const streamKey = patch ? `${SEO_MIGRATION_CASE_SLUG}:${patch.id}` : "";
  const council = useCouncilStream(streamKey, {
    buildStartRequest: useCallback(() => {
      if (!patch) {
        return { url: "/api/legal/council/deliberate" };
      }

      const snapshot = asRecord(patch.fact_snapshot) ?? {};
      const jsonLd = asRecord(patch.proposed_json_ld) ?? {};
      const legacyPath = pickString(snapshot, [
        "scrape_url",
        "archive_path",
        "original_slug",
        "source_alias",
      ]);
      const proposedUrl =
        pickString(jsonLd, ["url", "@id"]) ?? `/properties/${patch.target_slug}`;

      return {
        url: "/api/legal/council/deliberate",
        body: {
          case_type: "seo_migration",
          case_slug: SEO_MIGRATION_CASE_SLUG,
          trigger_type: "SEO_APPROVAL_SIDECAR",
          case_brief: buildSeoCouncilBrief(patch),
          context: buildSeoCouncilContext(patch),
          metadata: {
            patch_id: patch.id,
            target_slug: patch.target_slug,
            target_type: patch.target_type,
            target_keyword: patch.target_keyword,
            campaign: patch.campaign,
            proposal_run_id: patch.proposal_run_id,
            source_hash: patch.source_hash,
            legacy_path: legacyPath,
            proposed_url: proposedUrl,
            legacy_snapshot: patch.fact_snapshot,
            final_json_ld: patch.proposed_json_ld,
          },
        },
      };
    }, [patch]),
  });

  const snapshot = asRecord(patch?.fact_snapshot) ?? {};
  const jsonLd = useMemo(
    () => council.finalResult?.final_json_ld ?? patch?.proposed_json_ld ?? {},
    [council.finalResult?.final_json_ld, patch?.proposed_json_ld],
  );
  const legacyPath = pickString(snapshot, [
    "scrape_url",
    "archive_path",
    "original_slug",
    "source_alias",
  ]);
  const proposedUrl =
    pickString(asRecord(jsonLd) ?? {}, ["url", "@id"]) ??
    (patch ? `/properties/${patch.target_slug}` : null);
  const opinions = council.finalResult?.opinions.length
    ? council.finalResult.opinions
    : council.opinions;
  const consensus = council.finalResult ?? council.consensus;
  const liveSummary = useMemo(
    () => council.streamLines.slice(-10).reverse(),
    [council.streamLines],
  );

  const isRunning =
    council.connectionState !== "idle" &&
    council.connectionState !== "done" &&
    council.connectionState !== "stopped" &&
    council.connectionState !== "error";

  const handleStart = async () => {
    if (!patch) return;
    setLaunchError(null);
    try {
      await council.start();
    } catch (error) {
      setLaunchError(
        error instanceof Error ? error.message : "Failed to start council stream.",
      );
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <Shield className="h-4 w-4 text-primary" />
              SEO Council Sidecar
            </CardTitle>
            <CardDescription>
              Sovereign redirect audit for the selected SEO patch. Legacy evidence
              stays on the left. Live council reasoning and final JSON-LD stay on
              the right.
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="font-mono">
              {SEO_MIGRATION_CASE_SLUG}
            </Badge>
            <Badge variant="outline" className="gap-1">
              <Radio className="h-3 w-3" />
              {council.connectionState}
            </Badge>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleStart()}
              disabled={!patch || isRunning}
            >
              {isRunning ? (
                <>
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  Streaming
                </>
              ) : (
                <>
                  <Play className="mr-1.5 h-4 w-4" />
                  Run Sovereign Audit
                </>
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {!patch ? (
          <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            Select a queued SEO patch to open the sidecar.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div className="space-y-4">
              <div className="rounded-xl border p-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="gap-1">
                    <Route className="h-3 w-3" />
                    Redirect subject
                  </Badge>
                  <Badge variant="outline">{patch.target_type}</Badge>
                  <Badge variant="outline">{patch.campaign}</Badge>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <DetailBlock label="Legacy Route" value={legacyPath} tone="legacy" />
                  <DetailBlock
                    label="Next.js Destination"
                    value={proposedUrl}
                    tone="proposed"
                  />
                  <DetailBlock
                    label="Legacy Title"
                    value={pickString(snapshot, ["title", "page_title"])}
                    tone="legacy"
                  />
                  <DetailBlock
                    label="Proposed Title"
                    value={patch.proposed_title}
                    tone="proposed"
                  />
                  <DetailBlock
                    label="Legacy Meta Description"
                    value={pickString(snapshot, [
                      "meta_description",
                      "description",
                      "summary",
                    ])}
                    tone="legacy"
                  />
                  <DetailBlock
                    label="Proposed Meta Description"
                    value={patch.proposed_meta_description}
                    tone="proposed"
                  />
                  <DetailBlock
                    label="Legacy H1"
                    value={pickString(snapshot, ["h1", "heading", "title"])}
                    tone="legacy"
                  />
                  <DetailBlock
                    label="Proposed H1"
                    value={patch.proposed_h1}
                    tone="proposed"
                  />
                </div>
              </div>

              <div className="rounded-xl border p-4">
                <div className="mb-3 flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-sky-500" />
                  <p className="text-sm font-semibold">Prompt Frame</p>
                </div>
                <pre className="whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">
                  {buildSeoCouncilBrief(patch)}
                </pre>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-xl border p-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  {council.jobId ? (
                    <Badge variant="outline" className="font-mono">
                      job {council.jobId.slice(0, 8)}
                    </Badge>
                  ) : null}
                  {council.contextFrozen ? (
                    <Badge variant="outline">
                      {council.contextFrozen.vector_count} vectors frozen
                    </Badge>
                  ) : null}
                  {council.finalResult?.case_type ? (
                    <Badge variant="outline">{council.finalResult.case_type}</Badge>
                  ) : null}
                </div>

                {launchError || council.error ? (
                  <div className="mb-3 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-700 dark:text-rose-300">
                    {launchError || council.error}
                  </div>
                ) : null}

                {consensus ? (
                  <div
                    className={cn(
                      "mb-3 rounded-lg border p-3",
                      SIGNAL_STYLES[consensus.consensus_signal] ?? SIGNAL_STYLES.NEUTRAL,
                    )}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.2em]">
                        Consensus
                      </span>
                      <Badge variant="outline">
                        {consensus.consensus_signal}
                      </Badge>
                      <span className="ml-auto text-xs tabular-nums">
                        {(consensus.consensus_conviction * 100).toFixed(0)}% conviction
                      </span>
                    </div>
                  </div>
                ) : null}

                <div className="rounded-lg border bg-muted/20">
                  <div className="border-b px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                    Reasoning Trace
                  </div>
                  <ScrollArea className="h-40">
                    <div className="space-y-2 p-3">
                      {liveSummary.length > 0 ? (
                        liveSummary.map((line) => (
                          <div key={line.id} className="text-xs text-muted-foreground">
                            <span className="font-semibold text-foreground/80">
                              {line.type}
                            </span>
                            {" "}
                            {line.label}
                          </div>
                        ))
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          No live deliberation events yet.
                        </p>
                      )}
                    </div>
                  </ScrollArea>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {opinions.length > 0 ? (
                  opinions.map((opinion) => {
                    const signal = (opinion.signal || "NEUTRAL").toUpperCase();
                    return (
                      <div
                        key={`${opinion.seat}-${opinion.persona}`}
                        className={cn(
                          "rounded-xl border p-3",
                          SIGNAL_STYLES[signal] ?? SIGNAL_STYLES.NEUTRAL,
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold">{opinion.persona}</p>
                            <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                              Persona {opinion.seat}
                            </p>
                          </div>
                          <Badge variant="outline">{signal}</Badge>
                        </div>
                        <p className="mt-3 line-clamp-5 text-sm leading-6 text-foreground/85">
                          {opinion.reasoning}
                        </p>
                      </div>
                    );
                  })
                ) : (
                  <div className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground md:col-span-2">
                    The sidecar will populate persona arguments as each council seat
                    completes.
                  </div>
                )}
              </div>

              <div className="rounded-xl border p-4">
                <div className="mb-3 flex items-center gap-2">
                  <FileJson className="h-4 w-4 text-emerald-500" />
                  <p className="text-sm font-semibold">Final JSON-LD Payload</p>
                  {council.finalResult?.sha256_signature ? (
                    <Badge variant="outline" className="ml-auto gap-1">
                      <Scale className="h-3 w-3" />
                      sealed
                    </Badge>
                  ) : null}
                </div>
                <pre className="max-h-[24rem] overflow-auto whitespace-pre-wrap break-words rounded-lg border bg-muted/20 p-3 text-xs leading-5">
                  {prettyJson(jsonLd)}
                </pre>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
