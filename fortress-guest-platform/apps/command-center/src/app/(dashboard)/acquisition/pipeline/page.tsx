"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Building2, TrendingUp, Target, Handshake, CheckCircle2, XCircle } from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────

interface PipelineCard {
  pipeline_id: string;
  property_id: string;
  stage: string;
  llm_viability_score: number | null;
  next_action_date: string | null;
  rejection_reason: string | null;
  bedrooms: number | null;
  bathrooms: number | null;
  projected_adr: number | null;
  projected_annual_revenue: number | null;
  management_company: string | null;
  status: string | null;
  parcel_id: string | null;
  airbnb_listing_id: string | null;
}

interface KanbanStage {
  stage: string;
  cards: PipelineCard[];
}

interface KanbanData {
  stages: KanbanStage[];
  total: number;
}

// ── Stage config ──────────────────────────────────────────────────────────────

const STAGE_META: Record<string, { label: string; icon: React.ElementType; color: string; headerColor: string }> = {
  RADAR:         { label: "Radar",         icon: Target,      color: "text-slate-400",   headerColor: "bg-slate-800/60" },
  TARGET_LOCKED: { label: "Target Locked", icon: TrendingUp,  color: "text-blue-400",    headerColor: "bg-blue-900/40" },
  DEPLOYED:      { label: "Deployed",      icon: Building2,   color: "text-amber-400",   headerColor: "bg-amber-900/40" },
  ENGAGED:       { label: "Engaged",       icon: Handshake,   color: "text-purple-400",  headerColor: "bg-purple-900/40" },
  ACQUIRED:      { label: "Acquired",      icon: CheckCircle2, color: "text-emerald-400", headerColor: "bg-emerald-900/40" },
  REJECTED:      { label: "Rejected",      icon: XCircle,     color: "text-red-400",     headerColor: "bg-red-900/30" },
};

// ── Hooks ─────────────────────────────────────────────────────────────────────

function useKanban() {
  const [data, setData] = useState<KanbanData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/acquisition/pipeline/kanban")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<KanbanData>;
      })
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return { data, loading, error };
}

// ── Components ────────────────────────────────────────────────────────────────

function PropertyCard({ card }: { card: PipelineCard }) {
  const score = card.llm_viability_score;
  const revenue = card.projected_annual_revenue;

  return (
    <div className="rounded-lg border bg-card p-3 space-y-1.5 hover:border-primary/40 transition-colors cursor-pointer">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold leading-tight line-clamp-2">
          {card.management_company || `Property ${card.property_id.slice(0, 8)}…`}
        </p>
        {score != null && (
          <Badge
            variant="outline"
            className={`shrink-0 text-xs font-mono ${
              score >= 0.7 ? "text-emerald-400 border-emerald-500/30" :
              score >= 0.4 ? "text-amber-400 border-amber-500/30" :
              "text-red-400 border-red-500/30"
            }`}
          >
            {(score * 100).toFixed(0)}%
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground">
        {card.bedrooms != null && <span>{card.bedrooms}BR</span>}
        {card.bathrooms != null && <span>{card.bathrooms}BA</span>}
        {card.projected_adr != null && <span>ADR ${card.projected_adr.toFixed(0)}</span>}
        {revenue != null && (
          <span className="text-emerald-400/80">${(revenue / 1000).toFixed(0)}k/yr</span>
        )}
      </div>

      {card.next_action_date && (
        <p className="text-[10px] text-amber-400/80">
          Action: {card.next_action_date}
        </p>
      )}

      {card.airbnb_listing_id && (
        <p className="text-[10px] text-muted-foreground/60 truncate">
          Airbnb {card.airbnb_listing_id}
        </p>
      )}
    </div>
  );
}

function KanbanColumn({ stage: stageName, cards }: KanbanStage) {
  const meta = STAGE_META[stageName] ?? { label: stageName, icon: Building2, color: "text-slate-400", headerColor: "bg-slate-800/60" };
  const Icon = meta.icon;

  return (
    <div className="flex flex-col min-w-[220px] max-w-[260px] w-full">
      <div className={`rounded-t-lg px-3 py-2 ${meta.headerColor} flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <Icon className={`h-3.5 w-3.5 ${meta.color}`} />
          <span className="text-xs font-semibold">{meta.label}</span>
        </div>
        <Badge variant="secondary" className="text-xs h-5 px-1.5">
          {cards.length}
        </Badge>
      </div>
      <div className="rounded-b-lg border border-t-0 bg-muted/20 p-2 space-y-2 flex-1 min-h-[120px]">
        {cards.length === 0 ? (
          <p className="text-[10px] text-muted-foreground/50 text-center pt-4">Empty</p>
        ) : (
          cards.map((card) => (
            <PropertyCard key={card.pipeline_id} card={card} />
          ))
        )}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AcquisitionPipelinePage() {
  const { data, loading, error } = useKanban();

  if (error) {
    return (
      <div className="flex items-center justify-center h-48">
        <p className="text-sm text-destructive">Failed to load pipeline: {error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Acquisition Pipeline</h1>
          <p className="text-xs text-muted-foreground">
            {loading ? "Loading…" : `${data?.total ?? 0} properties tracked`}
          </p>
        </div>
        {!loading && data && (
          <div className="flex gap-3 text-xs text-muted-foreground">
            <span className="text-emerald-400 font-medium">
              {data.stages.find(s => s.stage === "ACQUIRED")?.cards.length ?? 0} acquired
            </span>
            <span>
              {data.stages.find(s => s.stage === "ENGAGED")?.cards.length ?? 0} in negotiation
            </span>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex gap-3 overflow-x-auto pb-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="min-w-[220px]">
              <Skeleton className="h-9 rounded-t-lg rounded-b-none" />
              <div className="border border-t-0 rounded-b-lg p-2 space-y-2 min-h-[120px]">
                <Skeleton className="h-16" />
                <Skeleton className="h-14" />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto pb-4">
          <div className="flex gap-3 min-w-max">
            {data?.stages.map((stage) => (
              <KanbanColumn key={stage.stage} {...stage} />
            ))}
          </div>
        </div>
      )}

      {/* Stats bar */}
      {!loading && data && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Funnel Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
              {data.stages.map((stage) => {
                const meta = STAGE_META[stage.stage] ?? { label: stage.stage, color: "text-slate-400" };
                return (
                  <div key={stage.stage} className="text-center">
                    <p className={`text-xl font-bold font-mono ${meta.color}`}>
                      {stage.cards.length}
                    </p>
                    <p className="text-[10px] text-muted-foreground">{meta.label}</p>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
