"use client";

import { use, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  AlertTriangle,
  ArrowLeft,
  Crosshair,
  Loader2,
  Search,
  Send,
  ShieldAlert,
  Swords,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { EvidenceUpload } from "../_components/evidence-upload";
import { AgentCommandTerminal } from "../_components/agent-command-terminal";
import { EdiscoveryDropzone } from "../_components/ediscovery-dropzone";

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

type ChatMessage = {
  role: "user" | "analyst";
  content: string;
  meta?: string;
};

type StrikeResult = {
  strike_type: string;
  output: string;
  inference_source: string;
  breaker_state: string;
  latency_ms: number;
};

const ENTITY_COLORS: Record<string, string> = {
  person: "border-blue-500/40 text-blue-400",
  company: "border-purple-500/40 text-purple-400",
  document: "border-emerald-500/40 text-emerald-400",
  claim: "border-red-500/40 text-red-400",
};

const STRIKE_CONFIG = [
  {
    key: "deposition_kill_sheet",
    label: "Initialize Deposition Kill-Sheet",
    icon: Crosshair,
    color: "text-red-400 border-red-500/40 hover:bg-red-500/10",
  },
  {
    key: "sanctions_tripwire",
    label: "Run Sanctions Tripwire",
    icon: Zap,
    color: "text-amber-400 border-amber-500/40 hover:bg-amber-500/10",
  },
  {
    key: "proportional_discovery",
    label: "Forge Discovery Draft",
    icon: Swords,
    color: "text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/10",
  },
] as const;

export default function WarRoomPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);

  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [graphLoading, setGraphLoading] = useState(true);

  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);

  const [strikeResult, setStrikeResult] = useState<StrikeResult | null>(null);
  const [activeStrike, setActiveStrike] = useState<string | null>(null);

  const nodeLabelById = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of nodes) m.set(n.id, n.label);
    return m;
  }, [nodes]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const snapshot = await api.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
          `/api/legal/cases/${slug}/graph/snapshot`,
        );
        if (cancelled) return;
        setNodes(Array.isArray(snapshot?.nodes) ? snapshot.nodes : []);
        setEdges(Array.isArray(snapshot?.edges) ? snapshot.edges : []);
      } catch {
        toast.error("Failed to load case graph");
      } finally {
        if (!cancelled) setGraphLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [slug]);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    setChatHistory((prev) => [...prev, { role: "user", content: q }]);
    setSearchQuery("");
    setSearching(true);
    try {
      const res = await api.post<{
        answer: string;
        records_searched: number;
        inference_source: string;
        latency_ms?: number;
      }>(`/api/legal/cases/${slug}/omni-search`, { query: q });
      setChatHistory((prev) => [
        ...prev,
        {
          role: "analyst",
          content: res.answer || "No records matched.",
          meta: `${res.records_searched} records · ${res.inference_source} · ${res.latency_ms ?? "?"}ms`,
        },
      ]);
    } catch (err) {
      setChatHistory((prev) => [
        ...prev,
        { role: "analyst", content: `Search failed: ${err instanceof Error ? err.message : "unknown"}` },
      ]);
    } finally {
      setSearching(false);
    }
  };

  const handleStrike = async (strikeType: string) => {
    setActiveStrike(strikeType);
    setStrikeResult(null);
    try {
      const res = await api.post<StrikeResult>(
        `/api/legal/cases/${slug}/tactical-strike`,
        { strike_type: strikeType },
      );
      setStrikeResult(res);
      toast.success(`${strikeType.replace(/_/g, " ")} complete`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Strike failed");
    } finally {
      setActiveStrike(null);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <header className="border-b border-neutral-800 px-4 py-3 flex items-center gap-3 bg-neutral-950/95 sticky top-0 z-20">
        <Link href={`/legal/cases/${slug}`}>
          <Button variant="ghost" size="icon" className="text-neutral-400 hover:text-neutral-100">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        </Link>
        <AlertTriangle className="h-5 w-5 text-red-500" />
        <h1 className="text-base font-bold tracking-tight text-red-500 uppercase">War Room</h1>
        <Badge variant="outline" className="text-[10px] border-neutral-700 text-neutral-400">{slug}</Badge>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-0 min-h-[calc(100vh-56px)]">
        {/* LEFT — Omni-Search */}
        <section className="lg:col-span-4 border-r border-neutral-800 flex flex-col">
          <div className="p-3 border-b border-neutral-800 flex items-center gap-2">
            <Search className="h-4 w-4 text-neutral-400" />
            <p className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Omni-Search</p>
          </div>
          <ScrollArea className="flex-1 p-3">
            <div className="space-y-3">
              {chatHistory.length === 0 && (
                <p className="text-xs text-neutral-500 text-center py-8">
                  Query your 56TB evidence vault. Ask anything.
                </p>
              )}
              {chatHistory.map((msg, idx) => (
                <div key={idx} className={`rounded-lg p-3 text-xs leading-relaxed ${
                  msg.role === "user"
                    ? "bg-blue-500/10 border border-blue-500/20 text-blue-100 ml-8"
                    : "bg-neutral-900 border border-neutral-800 text-neutral-200 mr-4"
                }`}>
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                  {msg.meta && (
                    <p className="text-[10px] text-neutral-500 mt-2">{msg.meta}</p>
                  )}
                </div>
              ))}
              {searching && (
                <div className="flex items-center gap-2 text-xs text-neutral-400 p-3">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Consulting Swarm...
                </div>
              )}
            </div>
          </ScrollArea>
          <form onSubmit={handleSearch} className="p-3 border-t border-neutral-800 flex gap-2">
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Did the guest complain about the HVAC?"
              className="bg-neutral-900 border-neutral-700 text-sm"
              disabled={searching}
            />
            <Button size="icon" type="submit" disabled={searching || !searchQuery.trim()} variant="ghost">
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </section>

        {/* CENTER — Tactical Grid */}
        <section className="lg:col-span-4 border-r border-neutral-800 flex flex-col">
          <div className="p-3 border-b border-neutral-800 flex items-center gap-2">
            <Crosshair className="h-4 w-4 text-red-400" />
            <p className="text-xs font-semibold uppercase tracking-wider text-neutral-400">Tactical Grid</p>
            <Badge variant="outline" className="text-[10px] ml-auto">{nodes.length} entities</Badge>
          </div>
          <ScrollArea className="flex-1 p-3">
            {graphLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-5 w-5 animate-spin text-neutral-500" />
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  {nodes.map((node) => (
                    <div
                      key={node.id}
                      className={`rounded-md border bg-neutral-900/70 px-3 py-2 ${
                        ENTITY_COLORS[node.entity_type] ?? "border-neutral-700 text-neutral-300"
                      }`}
                    >
                      <p className="text-xs font-medium truncate">{node.label}</p>
                      <p className="text-[10px] uppercase tracking-wider opacity-60 mt-0.5">{node.entity_type}</p>
                    </div>
                  ))}
                </div>
                {edges.length > 0 && (
                  <div className="space-y-1.5 mt-4">
                    <p className="text-[10px] uppercase tracking-wider text-neutral-500 font-semibold">Edge Ledger</p>
                    {edges.map((edge) => (
                      <div key={edge.id} className="rounded border border-neutral-800 bg-neutral-900/40 p-2">
                        <p className="text-[11px] text-neutral-200">
                          {nodeLabelById.get(edge.source_node_id) ?? "?"} → <span className="text-amber-300">{edge.relationship_type}</span> → {nodeLabelById.get(edge.target_node_id) ?? "?"}
                        </p>
                        <p className="text-[10px] text-neutral-500">w={edge.weight.toFixed(2)} · {edge.source_ref ?? "n/a"}</p>
                      </div>
                    ))}
                  </div>
                )}
                {nodes.length === 0 && !graphLoading && (
                  <p className="text-xs text-neutral-500 text-center py-8">
                    No graph entities. Run Graph Refresh on the case page first.
                  </p>
                )}
              </div>
            )}
          </ScrollArea>
        </section>

        {/* RIGHT — Arsenal */}
        <section className="lg:col-span-4 flex flex-col">
          <div className="p-3 border-b border-neutral-800 flex items-center gap-2">
            <Swords className="h-4 w-4 text-amber-400" />
            <p className="text-xs font-semibold uppercase tracking-wider text-neutral-400">The Arsenal</p>
          </div>
          <ScrollArea className="flex-1 p-3">
            <div className="space-y-2">
              {STRIKE_CONFIG.map((strike) => (
                <Button
                  key={strike.key}
                  type="button"
                  variant="outline"
                  className={`w-full justify-start gap-2 h-12 ${strike.color}`}
                  disabled={activeStrike !== null}
                  onClick={() => handleStrike(strike.key)}
                >
                  {activeStrike === strike.key ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <strike.icon className="h-4 w-4" />
                  )}
                  <span className="text-sm">{activeStrike === strike.key ? "Engaging Swarm..." : strike.label}</span>
                </Button>
              ))}
            </div>

            {strikeResult && (
              <div className="mt-4 space-y-3">
                <div className="rounded-md border-2 border-red-600 bg-red-950/60 p-3 flex items-start gap-2">
                  <ShieldAlert className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-bold text-red-400 uppercase tracking-wider">
                      Draft Only — Counsel Review Required Prior to Filing or Distribution
                    </p>
                    <p className="text-[10px] text-red-300/70 mt-1">
                      Generated by AI ({strikeResult.inference_source}). Not reviewed by licensed counsel.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="outline" className="text-[10px]">
                    {strikeResult.strike_type.replace(/_/g, " ")}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {strikeResult.inference_source}
                  </Badge>
                  <Badge variant="outline" className="text-[10px]">
                    {strikeResult.latency_ms}ms
                  </Badge>
                </div>

                <div className="rounded-md border border-neutral-800 bg-neutral-900/70 p-3">
                  <pre className="text-xs text-neutral-200 whitespace-pre-wrap leading-relaxed font-mono">
                    {strikeResult.output}
                  </pre>
                </div>
              </div>
            )}
            <div className="mt-4">
              <AgentCommandTerminal slug={slug} />
            </div>

            <div className="mt-4">
              <EdiscoveryDropzone slug={slug} />
            </div>

            <div className="mt-4">
              <EvidenceUpload slug={slug} onIngested={() => {
                api.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/api/legal/cases/${slug}/graph/snapshot`)
                  .then((s) => {
                    setNodes(Array.isArray(s?.nodes) ? s.nodes : []);
                    setEdges(Array.isArray(s?.edges) ? s.edges : []);
                  })
                  .catch(() => {});
              }} />
            </div>
          </ScrollArea>
        </section>
      </div>
    </div>
  );
}
