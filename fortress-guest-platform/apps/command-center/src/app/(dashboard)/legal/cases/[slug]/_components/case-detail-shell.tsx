"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCaseGraph,
  useCaseDetail,
  useCaseExtractionPoll,
  useDiscoveryPacks,
  useGenerateDiscoveryDraftPack,
  useDepositionKillSheets,
  useSanctionsAlerts,
  downloadKillSheetMarkdown,
} from "@/lib/legal-hooks";
import { api } from "@/lib/api";
import { RoleGatedAction } from "@/components/access/role-gated-action";
import { useAppStore } from "@/lib/store";
import { canManageLegalOps } from "@/lib/roles";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  AlertTriangle,
  Clock,
  Eye,
  Loader2,
  Lock,
  Scale,
  ShieldAlert,
  Swords,
} from "lucide-react";
import { toast } from "sonner";
import { GraphSnapshotCard } from "./graph-snapshot-card";
import { MasterTimeline } from "./master-timeline";
import { InferenceRadar } from "./inference-radar";
import { EvidenceUpload } from "./evidence-upload";
import { CounselThreatMatrix } from "./counsel-threat-matrix";
import { DiscoveryDraftPanel } from "./discovery-draft-panel";
import { DepositionPrepPanel } from "./deposition-prep-panel";
import { SanctionsTripwirePanel } from "./sanctions-tripwire-panel";
import { DepositionWarRoomModal } from "./deposition-war-room";
import { JurisprudenceRadar } from "./jurisprudence-radar";
import { DocumentViewer } from "./document-viewer";
import { ExtractionPanel } from "./extraction-panel";
import { HitlDeadlineQueue } from "./hitl-deadline-queue";
import type { ExtractionStatus } from "@/lib/legal-types";

type GraphNode = {
  id: string;
  entity_type: string;
  label: string;
  node_metadata: Record<string, unknown>;
};

type GraphEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  weight: number;
  source_ref?: string | null;
};

type GraphSnapshot = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

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

function SanctionsAlertsPanel({ slug }: { slug: string }) {
  const { data } = useSanctionsAlerts(slug);
  const alerts = data?.alerts ?? [];
  if (alerts.length === 0) return null;

  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-red-400" />
        <span className="text-sm font-semibold text-red-400">
          Sanctions Alerts ({alerts.length})
        </span>
        <Badge variant="outline" className="text-[10px] bg-red-500/10 text-red-400 border-red-500/30 ml-auto">
          Counsel Review Required
        </Badge>
      </div>
      <div className="space-y-1.5 max-h-48 overflow-y-auto">
        {alerts.map((a) => (
          <div key={a.id} className="rounded bg-background/50 border border-border/50 p-2 text-xs">
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant="outline"
                className={
                  a.alert_type === "SPOLIATION"
                    ? "text-[10px] bg-amber-500/10 text-amber-400 border-amber-500/30"
                    : "text-[10px] bg-red-500/10 text-red-400 border-red-500/30"
                }
              >
                {a.alert_type === "SPOLIATION" ? "Spoliation" : "Rule 11"}
              </Badge>
              <span className="text-muted-foreground truncate">
                Confidence: {a.confidence_score ?? 0}
              </span>
              <span className="text-muted-foreground ml-auto whitespace-nowrap">
                {a.created_at?.slice(0, 10)}
              </span>
            </div>
            {a.contradiction_summary && (
              <p className="text-muted-foreground leading-snug line-clamp-3">
                {a.contradiction_summary}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function CaseDetailShell({ slug }: { slug: string }) {
  const user = useAppStore((state) => state.user);
  const canOperate = canManageLegalOps(user);
  const { data, isLoading, error } = useCaseDetail(slug);
  const poll = useCaseExtractionPoll(slug);
  const caseGraphQuery = useCaseGraph(slug);
  const discoveryQuery = useDiscoveryPacks(slug);
  const sanctionsQuery = useSanctionsAlerts(slug);
  const killSheetsQuery = useDepositionKillSheets(slug);
  const generateDiscoveryPack = useGenerateDiscoveryDraftPack(slug);
  const qc = useQueryClient();
  const [graphSnapshot, setGraphSnapshot] = useState<GraphSnapshot>({ nodes: [], edges: [] });
  const [graphError, setGraphError] = useState<string | null>(null);
  const [isGraphLoading, setIsGraphLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [refreshBaseline, setRefreshBaseline] = useState<string>("");
  const [activeTargetNode, setActiveTargetNode] = useState<GraphNode | null>(null);
  const [isWarRoomOpen, setIsWarRoomOpen] = useState<boolean>(false);

  const liveCase = poll.data?.case ?? data?.case;

  useEffect(() => {
    if (liveCase?.extraction_status === "complete") {
      qc.invalidateQueries({ queryKey: ["legal", "case", slug] });
      qc.invalidateQueries({ queryKey: ["legal", "deadlines", slug] });
    }
  }, [liveCase?.extraction_status, qc, slug]);

  const snapshotSignature = (snapshot: GraphSnapshot) =>
    JSON.stringify({
      nodes: snapshot.nodes.map((n) => `${n.id}:${n.label}:${n.entity_type}`),
      edges: snapshot.edges.map(
        (e) =>
          `${e.id}:${e.source_node_id}:${e.target_node_id}:${e.relationship_type}:${e.weight}:${e.source_ref ?? ""}`,
      ),
    });

  useEffect(() => {
    let cancelled = false;
    const loadSnapshot = async () => {
      setIsGraphLoading(true);
      setGraphError(null);
      try {
        const snapshot = await api.get<GraphSnapshot>(`/api/internal/legal/cases/${slug}/graph/snapshot`);
        if (cancelled) return;
        setGraphSnapshot({
          nodes: Array.isArray(snapshot?.nodes) ? snapshot.nodes : [],
          edges: Array.isArray(snapshot?.edges) ? snapshot.edges : [],
        });
      } catch (err) {
        if (cancelled) return;
        setGraphError(err instanceof Error ? err.message : "Unable to load graph snapshot");
      } finally {
        if (!cancelled) setIsGraphLoading(false);
      }
    };
    loadSnapshot();
    return () => { cancelled = true; };
  }, [slug]);

  useEffect(() => {
    if (!isRefreshing) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const pollSnapshot = async () => {
      try {
        const snapshot = await api.get<GraphSnapshot>(`/api/internal/legal/cases/${slug}/graph/snapshot`);
        if (cancelled) return;
        const next: GraphSnapshot = {
          nodes: Array.isArray(snapshot?.nodes) ? snapshot.nodes : [],
          edges: Array.isArray(snapshot?.edges) ? snapshot.edges : [],
        };
        setGraphSnapshot(next);
        if (snapshotSignature(next) !== refreshBaseline) {
          setIsRefreshing(false);
          setRefreshBaseline("");
          toast.success("Graph topology updated");
          return;
        }
      } catch { /* keep polling */ }
      if (!cancelled) timer = setTimeout(pollSnapshot, 3000);
    };
    timer = setTimeout(pollSnapshot, 3000);
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [isRefreshing, refreshBaseline, slug]);

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
  const syncedCount = Array.isArray(graphSnapshot.nodes) ? graphSnapshot.nodes.length : 0;
  const armedLabel = syncedCount === 1 ? "Entity" : "Entities";
  const radarNodes = Array.isArray(caseGraphQuery.data?.nodes)
    ? caseGraphQuery.data.nodes.length
    : syncedCount;
  const radarEdges = Array.isArray(caseGraphQuery.data?.edges)
    ? caseGraphQuery.data.edges.filter((edge) =>
        String(edge.relationship_type ?? "").toLowerCase().includes("contradict"),
      ).length
    : 0;
  const latestPackItems = discoveryQuery.data?.latest_pack?.items ?? [];
  const topScoredDraftItems = latestPackItems
    .filter((item) => item?.content)
    .slice(0, 3);
  const primarySanctionsAlert = sanctionsQuery.data?.alerts?.[0] ?? null;
  const latestKillSheet = killSheetsQuery.data?.kill_sheets?.[0] ?? null;

  const handleGraphRefresh = async () => {
    setGraphError(null);
    try {
      const response = await api.post<{ status: string; case_slug: string }>(
        `/api/internal/legal/cases/${slug}/graph/refresh`,
      );
      if (response?.status === "refresh_queued") {
        setRefreshBaseline(snapshotSignature(graphSnapshot));
        setIsRefreshing(true);
        toast.success("Refresh queued on DGX Cluster");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to queue graph refresh");
    }
  };

  const handleNodeTarget = (node: GraphNode) => {
    setActiveTargetNode(node);
    setIsWarRoomOpen(true);
  };

  return (
    <div className="flex flex-col h-full">
      {/* ── Case Header ── */}
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
          {c.case_phase && (
            <>
              <span>&middot;</span>
              <Badge variant="outline" className="text-[10px] capitalize">
                {c.case_phase.replace(/_/g, " ")}
              </Badge>
            </>
          )}
        </div>
        {/* PR G — Privileged counsel domains. Each domain = one badge so a
            quick scan reveals attorney-client relationships without opening
            the full case detail. */}
        {Array.isArray(c.privileged_counsel_domains) && c.privileged_counsel_domains.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap text-[10px] pt-1">
            <Lock className="h-3 w-3 text-purple-400" />
            <span className="text-zinc-500 uppercase tracking-wider font-semibold">Privileged counsel:</span>
            {c.privileged_counsel_domains.map((domain) => (
              <Badge
                key={domain}
                variant="outline"
                className="text-[10px] text-purple-300 border-purple-500/40 bg-purple-500/5"
              >
                {domain}
              </Badge>
            ))}
          </div>
        )}
        {Array.isArray(c.related_matters) && c.related_matters.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap text-[10px] pt-1 text-zinc-500">
            <span className="uppercase tracking-wider font-semibold">Related matters:</span>
            {c.related_matters.map((slug) => (
              <a
                key={slug}
                href={`/legal/cases/${slug}`}
                className="text-[10px] text-zinc-300 hover:text-zinc-100 underline decoration-dotted underline-offset-2"
              >
                {slug}
              </a>
            ))}
          </div>
        )}
      </div>

      {/* ── Three-Tab Command Deck ── */}
      <Tabs defaultValue="panopticon" className="flex-1 flex flex-col min-h-0">
        <div className="px-4 pt-3 pb-0 border-b shrink-0">
          <TabsList className="grid w-full grid-cols-3 max-w-lg">
            <TabsTrigger value="panopticon" className="text-xs gap-1.5">
              <Eye className="h-3 w-3" />
              Panopticon
            </TabsTrigger>
            <TabsTrigger value="deliberation" className="text-xs gap-1.5">
              <ShieldAlert className="h-3 w-3" />
              Deliberation
            </TabsTrigger>
            <TabsTrigger value="vanguard" className="text-xs gap-1.5">
              <Swords className="h-3 w-3" />
              Vanguard
            </TabsTrigger>
          </TabsList>
        </div>

        {/* ── TAB 1: THE PANOPTICON (Intelligence & Ground Truth) ── */}
        <TabsContent value="panopticon" className="flex-1 overflow-y-auto p-4 space-y-4 mt-0">
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-2">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm font-semibold text-primary">Graph Radar</p>
              <Badge variant="outline" className="bg-red-500/10 text-red-400 border-red-500/30 text-[10px]">
                DRAFT / COUNSEL REVIEW REQUIRED
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {radarNodes} Entities Mapped | {radarEdges} Contradiction Edges
            </p>
            <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
              <Button type="button" onClick={handleGraphRefresh} disabled={!canOperate || isRefreshing} size="sm" className="w-fit">
                {isRefreshing ? "Refreshing Graph..." : "Refresh Graph"}
              </Button>
            </RoleGatedAction>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
              <Button type="button" onClick={handleGraphRefresh} disabled={!canOperate || isRefreshing} size="sm">
                {isRefreshing ? "Recalculating..." : "Recalculate Graph Topology"}
              </Button>
            </RoleGatedAction>
            <Badge variant="outline" className="bg-blue-500/10 text-blue-400 border-blue-500/30">
              Graph Synced: {syncedCount} {armedLabel}
            </Badge>
          </div>

          <InferenceRadar />

          <div className="grid gap-4 lg:grid-cols-2">
            <MasterTimeline slug={slug} />
            <div className="space-y-4">
              <GraphSnapshotCard
                nodes={graphSnapshot.nodes}
                edges={graphSnapshot.edges}
                isLoading={isGraphLoading}
                error={graphError}
                onNodeClick={handleNodeTarget}
              />
            </div>
          </div>

          <EvidenceUpload slug={slug} canOperate={canOperate} onIngested={() => {
            setIsGraphLoading(true);
            api.get<GraphSnapshot>(`/api/internal/legal/cases/${slug}/graph/snapshot`)
              .then((s) => setGraphSnapshot({ nodes: Array.isArray(s?.nodes) ? s.nodes : [], edges: Array.isArray(s?.edges) ? s.edges : [] }))
              .catch(() => {})
              .finally(() => setIsGraphLoading(false));
          }} />

          <DocumentViewer legalCase={c} slug={slug} />
        </TabsContent>

        {/* ── TAB 2: THE DELIBERATION CHAMBER (Strategy) ── */}
        <TabsContent value="deliberation" className="flex-1 overflow-y-auto p-4 space-y-4 mt-0">
          <CounselThreatMatrix slug={slug} />
          <JurisprudenceRadar slug={slug} />
          <SanctionsAlertsPanel slug={slug} />
          <ExtractionPanel legalCase={c} slug={slug} />
          <HitlDeadlineQueue slug={slug} />
        </TabsContent>

        {/* ── TAB 3: THE VANGUARD ARSENAL (Offense & Output) ── */}
        <TabsContent value="vanguard" className="flex-1 overflow-y-auto p-4 space-y-4 mt-0">
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-400 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 flex-shrink-0" />
            All outputs are Draft only — Counsel Review Required before filing.
          </div>

          <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm font-semibold text-zinc-100">Discovery Arsenal</p>
              <Badge variant="outline" className="text-[10px] bg-red-500/10 text-red-400 border-red-500/30">
                DRAFT / COUNSEL REVIEW REQUIRED
              </Badge>
            </div>
            <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
              <Button
                type="button"
                size="sm"
                disabled={!canOperate || generateDiscoveryPack.isPending}
                onClick={() =>
                  generateDiscoveryPack.mutate({
                    target_entity: c.case_name || c.case_slug,
                    max_items: 10,
                  })
                }
              >
                {generateDiscoveryPack.isPending ? "Generating..." : "Generate New Draft Pack"}
              </Button>
            </RoleGatedAction>
            <div className="space-y-2">
              {topScoredDraftItems.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No discovery draft items available yet.
                </p>
              )}
              {topScoredDraftItems.map((item, idx) => (
                <div key={`${item.id ?? idx}`} className="rounded border border-zinc-700 bg-zinc-900/70 p-3 space-y-1">
                  <p className="text-xs text-zinc-100 leading-relaxed">{item.content}</p>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline" className="text-[10px]">
                      Lethality: {item.lethality_score ?? "N/A"}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                      Proportionality: {item.proportionality_score ?? "N/A"}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 space-y-3">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <p className="text-sm font-semibold text-red-400">Tripwire & Kill-Sheet</p>
              <Badge variant="outline" className="text-[10px] bg-red-500/10 text-red-400 border-red-500/30">
                DRAFT / COUNSEL REVIEW REQUIRED
              </Badge>
            </div>
            {primarySanctionsAlert ? (
              <div className="rounded border border-red-500/30 bg-background/40 p-3 text-xs text-red-200 space-y-1">
                <div className="font-medium">
                  Active {primarySanctionsAlert.alert_type} Alert (Confidence: {primarySanctionsAlert.confidence_score ?? 0})
                </div>
                <p className="leading-snug">
                  {primarySanctionsAlert.contradiction_summary ?? "No contradiction summary available."}
                </p>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No active sanctions alerts.</p>
            )}
            <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
              <Button
                type="button"
                size="sm"
                disabled={!canOperate || !latestKillSheet?.id}
                onClick={() => {
                  if (!latestKillSheet?.id) return;
                  void downloadKillSheetMarkdown(
                    slug,
                    latestKillSheet.id,
                    `${latestKillSheet.deponent_entity.replaceAll(" ", "_")}_Kill_Sheet.md`,
                  );
                }}
              >
                Download Kill-Sheet
              </Button>
            </RoleGatedAction>
          </div>

          <DiscoveryDraftPanel slug={slug} />
          <DepositionPrepPanel caseSlug={slug} />
          <SanctionsTripwirePanel caseSlug={slug} />
          <DepositionWarRoomModal
            slug={slug}
            isOpen={isWarRoomOpen}
            targetNode={activeTargetNode}
            nodes={graphSnapshot.nodes}
            edges={graphSnapshot.edges}
            onClose={() => {
              setIsWarRoomOpen(false);
              setActiveTargetNode(null);
            }}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
