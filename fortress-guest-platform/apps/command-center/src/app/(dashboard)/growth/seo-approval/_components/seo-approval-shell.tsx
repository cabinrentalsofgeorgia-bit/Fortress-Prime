"use client";

import { useMemo, useState } from "react";
import {
  Check,
  Clock3,
  ExternalLink,
  LayoutGrid,
  List,
  Search,
  Sparkles,
  X,
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
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  useBulkApproveSeoPatches,
  useBulkRejectSeoPatches,
  useSeoPatchQueue,
} from "@/lib/hooks";
import type { SeoPatchQueueItem, SeoPatchQueueStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { SeoCouncilSidecar } from "./council-sidecar";

type ViewMode = "table" | "grid";

const STATUS_OPTIONS: Array<{ value: SeoPatchQueueStatus | "all"; label: string }> = [
  { value: "proposed", label: "Proposed" },
  { value: "needs_revision", label: "Needs Revision" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "deployed", label: "Deployed" },
  { value: "superseded", label: "Superseded" },
  { value: "all", label: "All Statuses" },
];

const STATUS_CLASSES: Record<string, string> = {
  proposed: "border-sky-500/20 bg-sky-500/10 text-sky-600 dark:text-sky-300",
  needs_revision:
    "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300",
  approved:
    "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300",
  rejected: "border-rose-500/20 bg-rose-500/10 text-rose-600 dark:text-rose-300",
  deployed:
    "border-violet-500/20 bg-violet-500/10 text-violet-600 dark:text-violet-300",
  superseded:
    "border-slate-500/20 bg-slate-500/10 text-slate-600 dark:text-slate-300",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function formatStatusLabel(status: string): string {
  return status
    .split("_")
    .map((chunk) => chunk.slice(0, 1).toUpperCase() + chunk.slice(1))
    .join(" ");
}

function normalizeTag(value: string): string {
  return value.trim().toLowerCase();
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const trimmed = value.trim();
    if (!trimmed) continue;
    const key = normalizeTag(trimmed);
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(trimmed);
  }
  return output;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return uniqueStrings(
    value.flatMap((entry) => {
      if (typeof entry === "string") {
        return entry
          .split(",")
          .map((token) => token.trim())
          .filter(Boolean);
      }
      const item = asRecord(entry);
      if (!item) return [];
      const candidate = item.name ?? item.value ?? item.label ?? item.q ?? item.a;
      return typeof candidate === "string" ? [candidate] : [];
    }),
  );
}

function pickFirstString(
  source: Record<string, unknown>,
  keys: string[],
): string | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function extractLegacyTags(snapshot: Record<string, unknown>): string[] {
  return uniqueStrings([
    ...readStringArray(snapshot.category_tags),
    ...readStringArray(snapshot.amenities),
  ]);
}

function extractProposedTags(item: SeoPatchQueueItem): string[] {
  const jsonLd = asRecord(item.proposed_json_ld) ?? {};
  const keywordTokens =
    typeof jsonLd.keywords === "string"
      ? jsonLd.keywords
          .split(",")
          .map((token) => token.trim())
          .filter(Boolean)
      : readStringArray(jsonLd.keywords);

  const amenityFeatures = Array.isArray(jsonLd.amenityFeature)
    ? jsonLd.amenityFeature.flatMap((entry) => {
        const feature = asRecord(entry);
        if (!feature) return [];
        const candidate = feature.name ?? feature.value;
        return typeof candidate === "string" ? [candidate] : [];
      })
    : [];

  return uniqueStrings([
    item.target_keyword,
    ...keywordTokens,
    ...amenityFeatures,
  ]);
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

function valuesMatch(
  legacyValue: string | null | undefined,
  proposedValue: string | null | undefined,
): boolean {
  return (legacyValue ?? "").trim() === (proposedValue ?? "").trim();
}

function EmptyValue({ label }: { label: string }) {
  return (
    <p className="text-sm italic text-muted-foreground">
      {label}
    </p>
  );
}

function JsonPane({
  title,
  value,
  tone,
}: {
  title: string;
  value: unknown;
  tone: "legacy" | "proposed" | "approved";
}) {
  const toneClasses =
    tone === "legacy"
      ? "border-slate-500/20 bg-slate-500/5"
      : tone === "approved"
        ? "border-emerald-500/20 bg-emerald-500/5"
        : "border-sky-500/20 bg-sky-500/5";

  return (
    <div className={cn("rounded-lg border p-4", toneClasses)}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          {title}
        </p>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-5 text-foreground">
        {prettyJson(value)}
      </pre>
    </div>
  );
}

function MetadataDiffCard({
  label,
  legacyValue,
  proposedValue,
}: {
  label: string;
  legacyValue: string | null;
  proposedValue: string | null;
}) {
  const changed = !valuesMatch(legacyValue, proposedValue);

  return (
    <div className="rounded-xl border p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{label}</h3>
        <Badge
          variant="outline"
          className={cn(
            changed
              ? "border-sky-500/20 bg-sky-500/10 text-sky-600 dark:text-sky-300"
              : "border-slate-500/20 bg-slate-500/10 text-slate-600 dark:text-slate-300",
          )}
        >
          {changed ? "Changed" : "Unchanged / Missing"}
        </Badge>
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <div className="rounded-lg border border-slate-500/20 bg-slate-500/5 p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Legacy
          </p>
          {legacyValue ? (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {legacyValue}
            </p>
          ) : (
            <EmptyValue label="Not captured in fact snapshot." />
          )}
        </div>
        <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
            Proposed
          </p>
          {proposedValue ? (
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {proposedValue}
            </p>
          ) : (
            <EmptyValue label="No proposed value." />
          )}
        </div>
      </div>
    </div>
  );
}

export function SeoApprovalShell() {
  const [statusFilter, setStatusFilter] = useState<SeoPatchQueueStatus | "all">(
    "proposed",
  );
  const [campaignFilter, setCampaignFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");

  const queue = useSeoPatchQueue({
    status: statusFilter,
    campaign: campaignFilter === "all" ? undefined : campaignFilter,
    limit: 100,
    offset: 0,
  });
  const approveBulk = useBulkApproveSeoPatches();
  const rejectBulk = useBulkRejectSeoPatches();

  const items = useMemo(() => queue.data?.items ?? [], [queue.data?.items]);

  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return items;
    return items.filter((item) => {
      const haystack = [
        item.target_slug,
        item.target_keyword,
        item.proposed_title,
        item.proposed_by,
        item.campaign,
        item.proposal_run_id ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [items, search]);

  const activePatch =
    filteredItems.find((item) => item.id === activeId) ?? filteredItems[0] ?? null;

  const selectedIdsInData = useMemo(() => {
    const validIds = new Set(items.map((item) => item.id));
    return new Set(Array.from(selectedIds).filter((id) => validIds.has(id)));
  }, [items, selectedIds]);

  const actionableIds = useMemo(() => {
    if (selectedIdsInData.size > 0) return Array.from(selectedIdsInData);
    return activePatch ? [activePatch.id] : [];
  }, [activePatch, selectedIdsInData]);

  const campaigns = useMemo(
    () => uniqueStrings(items.map((item) => item.campaign)),
    [items],
  );

  const selectedCount = selectedIdsInData.size;
  const pendingCount = queue.data?.total ?? 0;
  const averageScore = useMemo(() => {
    const scored = filteredItems.filter(
      (item) => typeof item.score_overall === "number",
    );
    if (!scored.length) return null;
    return (
      scored.reduce((sum, item) => sum + (item.score_overall ?? 0), 0) /
      scored.length
    );
  }, [filteredItems]);

  const allVisibleSelected =
    filteredItems.length > 0 &&
    filteredItems.every((item) => selectedIdsInData.has(item.id));
  const someVisibleSelected = filteredItems.some((item) =>
    selectedIdsInData.has(item.id),
  );
  const selectAllState: boolean | "indeterminate" = allVisibleSelected
    ? true
    : someVisibleSelected
      ? "indeterminate"
      : false;

  const activeSnapshot = asRecord(activePatch?.fact_snapshot) ?? {};
  const legacyTags = extractLegacyTags(activeSnapshot);
  const proposedTags = activePatch ? extractProposedTags(activePatch) : [];
  const sourceHref = pickFirstString(activeSnapshot, [
    "scrape_url",
    "archive_path",
    "source_alias",
    "original_slug",
  ]);
  const legacyTitle = pickFirstString(activeSnapshot, ["title", "page_title"]);
  const legacyMetaDescription = pickFirstString(activeSnapshot, [
    "meta_description",
    "description",
    "summary",
  ]);
  const legacyH1 = pickFirstString(activeSnapshot, ["h1", "heading", "title"]);
  const legacyIntro = pickFirstString(activeSnapshot, [
    "intro",
    "content_excerpt",
    "text_excerpt",
  ]);

  const isBusy = approveBulk.isPending || rejectBulk.isPending;
  const actionLabel =
    selectedCount > 0
      ? `${selectedCount} selected`
      : activePatch
        ? `active patch`
        : "none";

  const handleToggleSelection = (id: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleToggleAllVisible = (checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) {
        filteredItems.forEach((item) => next.add(item.id));
      } else {
        filteredItems.forEach((item) => next.delete(item.id));
      }
      return next;
    });
  };

  const clearSucceededIds = (succeeded: SeoPatchQueueItem[]) => {
    if (!succeeded.length) return;
    const succeededIds = new Set(succeeded.map((item) => item.id));
    setSelectedIds((current) => {
      const next = new Set<string>();
      current.forEach((id) => {
        if (!succeededIds.has(id)) next.add(id);
      });
      return next;
    });
    if (activePatch && succeededIds.has(activePatch.id)) {
      setActiveId(null);
    }
  };

  const handleApprove = () => {
    if (!actionableIds.length) return;
    approveBulk.mutate(
      { ids: actionableIds, note: reviewNote.trim() || undefined },
      {
        onSuccess: (result) => {
          clearSucceededIds(result.succeeded);
          if (result.failed.length === 0) {
            setReviewNote("");
          }
        },
      },
    );
  };

  const handleReject = () => {
    if (!actionableIds.length || !reviewNote.trim()) return;
    rejectBulk.mutate(
      { ids: actionableIds, note: reviewNote.trim() },
      {
        onSuccess: (result) => {
          clearSucceededIds(result.succeeded);
          if (result.failed.length === 0) {
            setReviewNote("");
          }
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="flex items-center gap-3 pt-4">
            <Sparkles className="h-8 w-8 text-sky-500" />
            <div>
              <p className="text-2xl font-bold">{pendingCount}</p>
              <p className="text-xs text-muted-foreground">Queue items</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-4">
            <Check className="h-8 w-8 text-emerald-500" />
            <div>
              <p className="text-2xl font-bold">{selectedCount}</p>
              <p className="text-xs text-muted-foreground">Selected for review</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-4">
            <Clock3 className="h-8 w-8 text-amber-500" />
            <div>
              <p className="text-2xl font-bold">
                {averageScore !== null ? averageScore.toFixed(1) : "--"}
              </p>
              <p className="text-xs text-muted-foreground">Average score</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 pt-4">
            <LayoutGrid className="h-8 w-8 text-violet-500" />
            <div>
              <p className="text-2xl font-bold">{campaigns.length}</p>
              <p className="text-xs text-muted-foreground">Campaigns represented</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Review Controls</CardTitle>
          <CardDescription>
            Bulk approve or reject the current selection. If nothing is selected,
            actions apply to the active patch.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={statusFilter}
                onValueChange={(value) =>
                  setStatusFilter(value as SeoPatchQueueStatus | "all")
                }
              >
                <SelectTrigger className="w-[170px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={campaignFilter} onValueChange={setCampaignFilter}>
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder="Campaign" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All campaigns</SelectItem>
                  {campaigns.map((campaign) => (
                    <SelectItem key={campaign} value={campaign}>
                      {campaign}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="relative min-w-[220px] flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search slug, keyword, proposal run..."
                  className="pl-9"
                />
              </div>

              <div className="ml-auto inline-flex items-center gap-1 rounded-md border p-1">
                <Button
                  type="button"
                  size="sm"
                  variant={viewMode === "table" ? "default" : "ghost"}
                  onClick={() => setViewMode("table")}
                >
                  <List className="mr-1.5 h-4 w-4" />
                  Table
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={viewMode === "grid" ? "default" : "ghost"}
                  onClick={() => setViewMode("grid")}
                >
                  <LayoutGrid className="mr-1.5 h-4 w-4" />
                  Grid
                </Button>
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                Review Note
              </p>
              <Textarea
                value={reviewNote}
                onChange={(event) => setReviewNote(event.target.value)}
                placeholder="Optional on approve. Required on reject."
                className="min-h-24"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={!actionableIds.length || isBusy}
              onClick={handleApprove}
            >
              <Check className="mr-1.5 h-4 w-4" />
              Approve {actionLabel}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!actionableIds.length || !reviewNote.trim() || isBusy}
              onClick={handleReject}
            >
              <X className="mr-1.5 h-4 w-4" />
              Reject {actionLabel}
            </Button>
            <p className="text-sm text-muted-foreground">
              Approved patches are immediately available to the live SEO payload
              readers.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <Card className="min-w-0">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Queued Proposals</CardTitle>
                <CardDescription>
                  {filteredItems.length} visible of {items.length} loaded
                </CardDescription>
              </div>
              <Badge variant="outline" className="font-mono">
                {queue.isFetching ? "refreshing" : "live"}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {queue.isLoading ? (
              <div className="flex h-[680px] items-center justify-center text-sm text-muted-foreground">
                Loading SEO queue...
              </div>
            ) : queue.error ? (
              <div className="flex h-[680px] items-center justify-center px-6 text-sm text-destructive">
                {queue.error instanceof Error
                  ? queue.error.message
                  : "Failed to load SEO queue."}
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="flex h-[680px] items-center justify-center text-sm text-muted-foreground">
                No queue items match the current filters.
              </div>
            ) : (
              <ScrollArea className="h-[680px]">
                {viewMode === "table" ? (
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-card">
                      <TableRow>
                        <TableHead className="w-12 pl-4">
                          <Checkbox
                            checked={selectAllState}
                            onCheckedChange={(checked) =>
                              handleToggleAllVisible(checked === true)
                            }
                            aria-label="Select visible SEO patches"
                          />
                        </TableHead>
                        <TableHead>Target</TableHead>
                        <TableHead>Keyword</TableHead>
                        <TableHead>Campaign</TableHead>
                        <TableHead>Score</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead className="pr-4">Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredItems.map((item) => {
                        const isActive = item.id === activePatch?.id;
                        const isSelected = selectedIdsInData.has(item.id);
                        return (
                          <TableRow
                            key={item.id}
                            data-state={isActive ? "selected" : undefined}
                            className="cursor-pointer"
                            onClick={() => setActiveId(item.id)}
                          >
                            <TableCell
                              className="pl-4"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={(checked) =>
                                  handleToggleSelection(item.id, checked === true)
                                }
                                aria-label={`Select ${item.target_slug}`}
                              />
                            </TableCell>
                            <TableCell className="whitespace-normal">
                              <div className="space-y-1">
                                <p className="font-medium">{item.target_slug}</p>
                                <p className="text-xs text-muted-foreground">
                                  {item.proposed_title || "Untitled proposal"}
                                </p>
                              </div>
                            </TableCell>
                            <TableCell className="whitespace-normal text-xs text-muted-foreground">
                              {item.target_keyword || "n/a"}
                            </TableCell>
                            <TableCell className="text-xs">{item.campaign}</TableCell>
                            <TableCell className="font-mono text-xs">
                              {item.score_overall?.toFixed(1) ?? "--"}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {formatDateTime(item.created_at)}
                            </TableCell>
                            <TableCell className="pr-4">
                              <Badge
                                variant="outline"
                                className={STATUS_CLASSES[item.status] ?? ""}
                              >
                                {formatStatusLabel(item.status)}
                              </Badge>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                ) : (
                  <div className="grid gap-3 p-4 md:grid-cols-2">
                    {filteredItems.map((item) => {
                      const isActive = item.id === activePatch?.id;
                      const isSelected = selectedIdsInData.has(item.id);
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => setActiveId(item.id)}
                          className={cn(
                            "rounded-xl border p-4 text-left transition-colors",
                            isActive
                              ? "border-sky-500/40 bg-sky-500/5"
                              : "hover:bg-muted/40",
                          )}
                        >
                          <div className="flex items-start gap-3">
                            <div
                              className="pt-0.5"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={(checked) =>
                                  handleToggleSelection(item.id, checked === true)
                                }
                                aria-label={`Select ${item.target_slug}`}
                              />
                            </div>
                            <div className="min-w-0 flex-1 space-y-2">
                              <div className="flex items-start justify-between gap-2">
                                <div>
                                  <p className="font-semibold">{item.target_slug}</p>
                                  <p className="text-xs text-muted-foreground">
                                    {item.target_keyword || "n/a"}
                                  </p>
                                </div>
                                <Badge
                                  variant="outline"
                                  className={STATUS_CLASSES[item.status] ?? ""}
                                >
                                  {formatStatusLabel(item.status)}
                                </Badge>
                              </div>
                              <p className="line-clamp-2 text-sm text-muted-foreground">
                                {item.proposed_title || "Untitled proposal"}
                              </p>
                              <div className="flex items-center justify-between text-xs text-muted-foreground">
                                <span>{item.campaign}</span>
                                <span className="font-mono">
                                  {item.score_overall?.toFixed(1) ?? "--"}
                                </span>
                              </div>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </ScrollArea>
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Proposal Detail</CardTitle>
            <CardDescription>
              Legacy snapshot vs proposed metadata, tags, and JSON-LD.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!activePatch ? (
              <div className="flex h-[680px] items-center justify-center text-sm text-muted-foreground">
                Select a patch to inspect its diff.
              </div>
            ) : (
              <ScrollArea className="h-[680px] pr-4">
                <div className="space-y-6">
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-xl font-semibold">
                            {activePatch.target_slug}
                          </h3>
                          <Badge
                            variant="outline"
                            className={STATUS_CLASSES[activePatch.status] ?? ""}
                          >
                            {formatStatusLabel(activePatch.status)}
                          </Badge>
                          <Badge variant="outline">
                            {activePatch.target_type === "property"
                              ? "Property"
                              : "Archive Review"}
                          </Badge>
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {activePatch.proposed_title || "Untitled proposal"}
                        </p>
                      </div>
                      {sourceHref ? (
                        <a
                          href={sourceHref}
                          target={sourceHref.startsWith("http") ? "_blank" : undefined}
                          rel={
                            sourceHref.startsWith("http")
                              ? "noreferrer noopener"
                              : undefined
                          }
                          className="inline-flex items-center gap-1 text-sm text-primary"
                        >
                          View source
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      ) : null}
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      <div className="rounded-xl border p-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          Score
                        </p>
                        <p className="mt-2 text-2xl font-bold">
                          {activePatch.score_overall?.toFixed(1) ?? "--"}
                        </p>
                      </div>
                      <div className="rounded-xl border p-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          Campaign
                        </p>
                        <p className="mt-2 text-sm font-medium">{activePatch.campaign}</p>
                      </div>
                      <div className="rounded-xl border p-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          Proposed By
                        </p>
                        <p className="mt-2 text-sm font-medium">{activePatch.proposed_by}</p>
                      </div>
                      <div className="rounded-xl border p-3">
                        <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                          Created
                        </p>
                        <p className="mt-2 text-sm font-medium">
                          {formatDateTime(activePatch.created_at)}
                        </p>
                      </div>
                    </div>

                    {Object.keys(activePatch.score_breakdown ?? {}).length > 0 ? (
                      <div className="grid gap-3 sm:grid-cols-2">
                        {Object.entries(activePatch.score_breakdown).map(
                          ([metric, value]) => (
                            <div key={metric} className="rounded-xl border p-3">
                              <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                                {formatStatusLabel(metric)}
                              </p>
                              <p className="mt-2 text-lg font-semibold">
                                {(value * 100).toFixed(1)}%
                              </p>
                            </div>
                          ),
                        )}
                      </div>
                    ) : null}
                  </div>

                  <SeoCouncilSidecar
                    key={activePatch.id}
                    patch={activePatch}
                  />

                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <h4 className="text-sm font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                        Metadata Diff
                      </h4>
                      <p className="text-xs text-muted-foreground">
                        Comparing the captured legacy snapshot against the proposal.
                      </p>
                    </div>
                    <div className="space-y-3">
                      <MetadataDiffCard
                        label="Title"
                        legacyValue={legacyTitle}
                        proposedValue={activePatch.proposed_title}
                      />
                      <MetadataDiffCard
                        label="Meta Description"
                        legacyValue={legacyMetaDescription}
                        proposedValue={activePatch.proposed_meta_description}
                      />
                      <MetadataDiffCard
                        label="H1"
                        legacyValue={legacyH1}
                        proposedValue={activePatch.proposed_h1}
                      />
                      <MetadataDiffCard
                        label="Intro"
                        legacyValue={legacyIntro}
                        proposedValue={activePatch.proposed_intro}
                      />
                    </div>
                  </div>

                  <div className="grid gap-3 xl:grid-cols-2">
                    <div className="rounded-xl border p-4">
                      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                        Legacy Tags
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {legacyTags.length > 0 ? (
                          legacyTags.map((tag) => (
                            <Badge key={tag} variant="outline">
                              {tag}
                            </Badge>
                          ))
                        ) : (
                          <EmptyValue label="No legacy tags captured." />
                        )}
                      </div>
                    </div>
                    <div className="rounded-xl border p-4">
                      <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                        Proposed Tags
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {proposedTags.length > 0 ? (
                          proposedTags.map((tag) => (
                            <Badge
                              key={tag}
                              variant="outline"
                              className="border-sky-500/20 bg-sky-500/10 text-sky-600 dark:text-sky-300"
                            >
                              {tag}
                            </Badge>
                          ))
                        ) : (
                          <EmptyValue label="No proposed tags derived from the payload." />
                        )}
                      </div>
                    </div>
                  </div>

                  <Tabs defaultValue="json-ld">
                    <TabsList>
                      <TabsTrigger value="json-ld">JSON-LD Diff</TabsTrigger>
                      <TabsTrigger value="legacy-snapshot">Legacy Snapshot</TabsTrigger>
                      <TabsTrigger value="approved-payload">Approved Payload</TabsTrigger>
                    </TabsList>
                    <TabsContent value="json-ld" className="mt-4">
                      <div className="grid gap-3 xl:grid-cols-2">
                        <JsonPane
                          title="Legacy Snapshot"
                          value={activePatch.fact_snapshot}
                          tone="legacy"
                        />
                        <JsonPane
                          title="Proposed JSON-LD"
                          value={activePatch.proposed_json_ld}
                          tone="proposed"
                        />
                      </div>
                    </TabsContent>
                    <TabsContent value="legacy-snapshot" className="mt-4">
                      <JsonPane
                        title="Captured fact_snapshot"
                        value={activePatch.fact_snapshot}
                        tone="legacy"
                      />
                    </TabsContent>
                    <TabsContent value="approved-payload" className="mt-4">
                      <JsonPane
                        title="Approved payload"
                        value={activePatch.approved_payload}
                        tone="approved"
                      />
                    </TabsContent>
                  </Tabs>

                  {activePatch.review_note ? (
                    <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">
                        Existing Review Note
                      </p>
                      <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                        {activePatch.review_note}
                      </p>
                    </div>
                  ) : null}
                </div>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
