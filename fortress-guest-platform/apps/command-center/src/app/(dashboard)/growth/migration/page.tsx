"use client";

import { useMemo, useState, useCallback } from "react";
import {
  ArrowRightLeft,
  ChevronLeft,
  ChevronRight,
  Search,
  ExternalLink,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import blueprint from "@/data/drupal_granular_blueprint.json";

const PAGE_SIZES = [25, 50, 100] as const;

type MigrationStage = "drupal_fallback" | "next_candidate" | "next_staging" | "next_promoted";
type RiskLevel = "revenue" | "seo" | "content" | "utility";

interface LegacyEntry {
  alias: string;
  sourcePath: string;
  contentType: string;
  nodeType: string | null;
  title: string;
  nextRoute: string;
  migrationStage: MigrationStage;
  riskLevel: RiskLevel;
  parityGates: string[];
  rollbackRoute: string;
}

type BaseLegacyEntry = Omit<
  LegacyEntry,
  "migrationStage" | "riskLevel" | "parityGates" | "rollbackRoute"
>;

const MIGRATION_STAGE_LABELS: Record<MigrationStage, string> = {
  drupal_fallback: "Drupal fallback",
  next_candidate: "Next candidate",
  next_staging: "Next staging",
  next_promoted: "Next promoted",
};

const MIGRATION_STAGE_COLORS: Record<MigrationStage, string> = {
  drupal_fallback: "bg-zinc-500/10 text-zinc-300 border-zinc-500/20",
  next_candidate: "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
  next_staging: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  next_promoted: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
};

const RISK_LABELS: Record<RiskLevel, string> = {
  revenue: "Revenue",
  seo: "SEO",
  content: "Content",
  utility: "Utility",
};

const RISK_COLORS: Record<RiskLevel, string> = {
  revenue: "bg-rose-500/10 text-rose-400 border-rose-500/20",
  seo: "bg-fuchsia-500/10 text-fuchsia-400 border-fuchsia-500/20",
  content: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  utility: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
};

const STATIC_NEXT_ROUTES = new Set([
  "/faq",
  "/privacy-policy",
  "/terms-and-conditions",
  "/your-home-vacation-prosperity",
]);

function deriveNextRoute(sourcePath: string, alias: string): string {
  if (alias.startsWith("/activity/")) return `/activities${alias.slice("/activity".length)}`;
  if (alias.startsWith("/blog/")) return alias;
  if (alias.startsWith("/cabins/") || alias.startsWith("/the-cabins")) return alias;
  if (alias.startsWith("/bedrooms/")) return `/cabins${alias}`;
  if (alias.startsWith("/event/")) return `/events${alias.slice("/event".length)}`;
  if (alias.startsWith("/testimonial/")) return `/reviews/${alias.split("/").filter(Boolean).at(-1)}`;
  if (sourcePath.startsWith("node/")) return alias || `/${sourcePath}`;
  if (sourcePath.startsWith("taxonomy/")) return alias || `/${sourcePath}`;
  return alias || `/${sourcePath}`;
}

function isRevenuePath(alias: string): boolean {
  return (
    alias === "/availability" ||
    alias.startsWith("/availability/") ||
    alias.startsWith("/checkout") ||
    alias.startsWith("/cabins") ||
    alias.startsWith("/cabin/") ||
    alias.startsWith("/the-cabins") ||
    alias.startsWith("/bedrooms/") ||
    alias.includes("cabin-rental") ||
    alias.includes("cabin-rentals") ||
    alias.includes("pet-friendly-cabins") ||
    alias.includes("lakefront-cabin") ||
    alias.includes("riverfront-cabin") ||
    alias.includes("mountain-view-cabin")
  );
}

function deriveRiskLevel(entry: BaseLegacyEntry): RiskLevel {
  if (isRevenuePath(entry.alias)) return "revenue";
  if (
    entry.alias.startsWith("/blog/") ||
    entry.alias.startsWith("/activity/") ||
    entry.alias.startsWith("/activities/") ||
    entry.alias.startsWith("/event/") ||
    entry.alias.startsWith("/reviews/") ||
    entry.alias.startsWith("/testimonial/") ||
    entry.contentType === "Taxonomy"
  ) {
    return "seo";
  }
  if (
    entry.alias.startsWith("/owner") ||
    entry.alias.startsWith("/guest/") ||
    entry.alias.startsWith("/sign/") ||
    STATIC_NEXT_ROUTES.has(entry.alias)
  ) {
    return "utility";
  }
  return "content";
}

function deriveMigrationStage(entry: BaseLegacyEntry, riskLevel: RiskLevel): MigrationStage {
  if (riskLevel === "revenue") return "drupal_fallback";
  if (STATIC_NEXT_ROUTES.has(entry.alias) || entry.alias.startsWith("/testimonial/")) {
    return "next_staging";
  }
  if (riskLevel === "seo" || riskLevel === "content") return "next_candidate";
  return "drupal_fallback";
}

function deriveParityGates(riskLevel: RiskLevel): string[] {
  switch (riskLevel) {
    case "revenue":
      return ["SEO", "Redirect", "Quote", "Availability", "Checkout", "Rollback"];
    case "seo":
      return ["SEO", "Redirect", "Content", "Analytics", "Rollback"];
    case "utility":
      return ["Session", "Metadata", "Rollback"];
    default:
      return ["Content", "Redirect", "Metadata", "Rollback"];
  }
}

function withMigrationLedger(entry: BaseLegacyEntry): LegacyEntry {
  const riskLevel = deriveRiskLevel(entry);
  return {
    ...entry,
    riskLevel,
    migrationStage: deriveMigrationStage(entry, riskLevel),
    parityGates: deriveParityGates(riskLevel),
    rollbackRoute: entry.alias,
  };
}

function buildEntries(): LegacyEntry[] {
  const entries: LegacyEntry[] = [];

  const nodesByType = blueprint.nodes_by_type as Record<
    string,
    {
      type_info: { label: string | null; description: string | null };
      nodes: {
        nid: number;
        title: string;
        status: number;
        source_path: string;
        url_alias: string | null;
      }[];
    }
  >;

  for (const [nodeType, group] of Object.entries(nodesByType)) {
    for (const node of group.nodes) {
      const alias = node.url_alias ?? `/${node.source_path}`;
      entries.push(
        withMigrationLedger({
          alias,
          sourcePath: node.source_path,
          contentType: "Node",
          nodeType: group.type_info.label ?? nodeType,
          title: node.title,
          nextRoute: deriveNextRoute(node.source_path, alias),
        }),
      );
    }
  }

  const taxonomy = blueprint.taxonomy as {
    terms: { tid: number; vid: number; name: string }[];
  };
  for (const term of taxonomy.terms) {
    const sourcePath = `taxonomy/term/${term.tid}`;
    const aliasRecord = (blueprint.url_aliases as { records: { source_path: string; alias_path: string }[] })
      .records.find((r) => r.source_path === sourcePath);
    const alias = aliasRecord?.alias_path ?? `/${sourcePath}`;
    entries.push(
      withMigrationLedger({
        alias,
        sourcePath,
        contentType: "Taxonomy",
        nodeType: null,
        title: term.name,
        nextRoute: deriveNextRoute(sourcePath, alias),
      }),
    );
  }

  const menus = blueprint.menus as Record<
    string,
    {
      mlid: number;
      title: string;
      link_path: string;
      children: unknown[];
    }[]
  >;
  function walkMenu(items: typeof menus[string], menuName: string) {
    for (const item of items) {
      if (item.link_path && item.link_path !== "<nolink>") {
        const alias = item.link_path.startsWith("/") ? item.link_path : `/${item.link_path}`;
        entries.push(
          withMigrationLedger({
            alias,
            sourcePath: item.link_path,
            contentType: "Menu",
            nodeType: menuName,
            title: item.title || item.link_path,
            nextRoute: deriveNextRoute(item.link_path, alias),
          }),
        );
      }
      if (item.children?.length) {
        walkMenu(item.children as typeof menus[string], menuName);
      }
    }
  }
  for (const [menuName, roots] of Object.entries(menus)) {
    walkMenu(roots, menuName);
  }

  return entries;
}

const CONTENT_TYPE_COLORS: Record<string, string> = {
  Node: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  Taxonomy: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  Menu: "bg-amber-500/10 text-amber-500 border-amber-500/20",
};

export default function MigrationPage() {
  const allEntries = useMemo(() => buildEntries(), []);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [stageFilter, setStageFilter] = useState<string>("all");
  const [riskFilter, setRiskFilter] = useState<string>("all");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(50);

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return allEntries.filter((e) => {
      if (typeFilter !== "all" && e.contentType !== typeFilter) return false;
      if (stageFilter !== "all" && e.migrationStage !== stageFilter) return false;
      if (riskFilter !== "all" && e.riskLevel !== riskFilter) return false;
      if (!q) return true;
      return (
        e.alias.toLowerCase().includes(q) ||
        e.title.toLowerCase().includes(q) ||
        e.nextRoute.toLowerCase().includes(q) ||
        MIGRATION_STAGE_LABELS[e.migrationStage].toLowerCase().includes(q) ||
        RISK_LABELS[e.riskLevel].toLowerCase().includes(q) ||
        (e.nodeType?.toLowerCase().includes(q) ?? false)
      );
    });
  }, [allEntries, riskFilter, search, stageFilter, typeFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const slice = filtered.slice(safePage * pageSize, (safePage + 1) * pageSize);

  const handleSearch = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearch(e.target.value);
    setPage(0);
  }, []);

  const stats = useMemo(() => {
    const counts = {
      Node: 0,
      Taxonomy: 0,
      Menu: 0,
      drupal_fallback: 0,
      next_candidate: 0,
      next_staging: 0,
      next_promoted: 0,
      revenue: 0,
    };
    for (const e of allEntries) {
      counts[e.contentType as keyof typeof counts]++;
      counts[e.migrationStage]++;
      if (e.riskLevel === "revenue") counts.revenue++;
    }
    return counts;
  }, [allEntries]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Total Legacy URLs</p>
              <ArrowRightLeft className="h-3.5 w-3.5 text-emerald-400" />
            </div>
            <p className="text-xl font-bold font-mono">{allEntries.length.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Drupal Fallback</p>
              <ExternalLink className="h-3.5 w-3.5 text-blue-400" />
            </div>
            <p className="text-xl font-bold font-mono">{stats.drupal_fallback.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Next Candidates</p>
              <ExternalLink className="h-3.5 w-3.5 text-purple-400" />
            </div>
            <p className="text-xl font-bold font-mono">{stats.next_candidate.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Next Staging</p>
              <ExternalLink className="h-3.5 w-3.5 text-amber-400" />
            </div>
            <p className="text-xl font-bold font-mono">{stats.next_staging.toLocaleString()}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">Revenue Protected</p>
              <ExternalLink className="h-3.5 w-3.5 text-rose-400" />
            </div>
            <p className="text-xl font-bold font-mono">{stats.revenue.toLocaleString()}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle className="text-base">Strangler Fig Route Ledger</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Drupal remains fallback until each route has content, SEO, redirect, booking, and rollback parity.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={stageFilter} onValueChange={(v) => { setStageFilter(v); setPage(0); }}>
                <SelectTrigger className="h-8 w-[150px] text-xs">
                  <SelectValue placeholder="All Stages" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Stages</SelectItem>
                  <SelectItem value="drupal_fallback">Drupal fallback</SelectItem>
                  <SelectItem value="next_candidate">Next candidate</SelectItem>
                  <SelectItem value="next_staging">Next staging</SelectItem>
                  <SelectItem value="next_promoted">Next promoted</SelectItem>
                </SelectContent>
              </Select>
              <Select value={riskFilter} onValueChange={(v) => { setRiskFilter(v); setPage(0); }}>
                <SelectTrigger className="h-8 w-[130px] text-xs">
                  <SelectValue placeholder="All Risk" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Risk</SelectItem>
                  <SelectItem value="revenue">Revenue</SelectItem>
                  <SelectItem value="seo">SEO</SelectItem>
                  <SelectItem value="content">Content</SelectItem>
                  <SelectItem value="utility">Utility</SelectItem>
                </SelectContent>
              </Select>
              <Select value={typeFilter} onValueChange={(v) => { setTypeFilter(v); setPage(0); }}>
                <SelectTrigger className="h-8 w-[140px] text-xs">
                  <SelectValue placeholder="All Types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="Node">Node</SelectItem>
                  <SelectItem value="Taxonomy">Taxonomy</SelectItem>
                  <SelectItem value="Menu">Menu</SelectItem>
                </SelectContent>
              </Select>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search cabins, paths..."
                  value={search}
                  onChange={handleSearch}
                  className="h-8 w-[220px] pl-8 text-xs"
                />
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs text-muted-foreground uppercase pl-4">Legacy URL Alias</TableHead>
                <TableHead className="text-xs text-muted-foreground uppercase">Title</TableHead>
                <TableHead className="text-xs text-muted-foreground uppercase">Content Type</TableHead>
                <TableHead className="text-xs text-muted-foreground uppercase">Stage</TableHead>
                <TableHead className="text-xs text-muted-foreground uppercase">Risk</TableHead>
                <TableHead className="text-xs text-muted-foreground uppercase">Parity Gates</TableHead>
                <TableHead className="text-xs text-muted-foreground uppercase">Target Next.js Route</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {slice.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                    No matching URLs found.
                  </TableCell>
                </TableRow>
              ) : (
                slice.map((entry, i) => (
                  <TableRow key={`${entry.sourcePath}-${i}`}>
                    <TableCell className="pl-4 font-mono text-xs max-w-[280px] truncate">
                      {entry.alias}
                    </TableCell>
                    <TableCell className="text-xs max-w-[220px] truncate">{entry.title}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <Badge
                          variant="outline"
                          className={CONTENT_TYPE_COLORS[entry.contentType] ?? ""}
                        >
                          {entry.contentType}
                        </Badge>
                        {entry.nodeType && (
                          <span className="text-[10px] text-muted-foreground">{entry.nodeType}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={MIGRATION_STAGE_COLORS[entry.migrationStage]}
                      >
                        {MIGRATION_STAGE_LABELS[entry.migrationStage]}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={RISK_COLORS[entry.riskLevel]}>
                        {RISK_LABELS[entry.riskLevel]}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[340px]">
                      <div className="flex flex-wrap gap-1">
                        {entry.parityGates.map((gate) => (
                          <Badge
                            key={`${entry.sourcePath}-${gate}`}
                            variant="outline"
                            className="border-zinc-700 bg-zinc-900/60 text-[10px] text-zinc-300"
                          >
                            {gate}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-[280px]">
                      <p className="truncate font-mono text-xs text-emerald-500">{entry.nextRoute}</p>
                      <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                        rollback {entry.rollbackRoute}
                      </p>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          <div className="flex items-center justify-between border-t px-4 py-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>
                {filtered.length.toLocaleString()} result{filtered.length !== 1 ? "s" : ""}
              </span>
              <span>&middot;</span>
              <span>
                Page {safePage + 1} of {totalPages}
              </span>
              <Select
                value={String(pageSize)}
                onValueChange={(v) => { setPageSize(Number(v)); setPage(0); }}
              >
                <SelectTrigger className="h-7 w-[70px] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZES.map((s) => (
                    <SelectItem key={s} value={String(s)}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span>per page</span>
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="icon-xs"
                disabled={safePage === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="outline"
                size="icon-xs"
                disabled={safePage >= totalPages - 1}
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
