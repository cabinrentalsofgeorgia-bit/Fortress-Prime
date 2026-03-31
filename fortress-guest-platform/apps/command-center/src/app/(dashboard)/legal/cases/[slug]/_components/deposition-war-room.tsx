"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RoleGatedAction } from "@/components/access/role-gated-action";
import { useAppStore } from "@/lib/store";
import { canManageLegalOps } from "@/lib/roles";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { X } from "lucide-react";

type GraphNode = {
  id: string;
  entity_type: string;
  label: string;
};

type GraphEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  relationship_type: string;
  source_ref?: string | null;
};

type DepositionWarRoomModalProps = {
  slug: string;
  isOpen: boolean;
  targetNode: GraphNode | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onClose: () => void;
};

type ParsedFunnel = {
  id?: string;
  target_id?: string;
  target_status?: "drafting" | "ready" | "completed";
  topic: string;
  lock_in_questions: string[];
  the_strike_document: string;
  strike_script?: string;
};

export function DepositionWarRoomModal({
  slug,
  isOpen,
  targetNode,
  nodes,
  edges,
  onClose,
}: DepositionWarRoomModalProps) {
  const user = useAppStore((state) => state.user);
  const canOperate = canManageLegalOps(user);
  const [streamingFunnelText, setStreamingFunnelText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [savedToVault, setSavedToVault] = useState(false);
  const [parsedFunnel, setParsedFunnel] = useState<ParsedFunnel | null>(null);
  const [editableQuestions, setEditableQuestions] = useState<string[]>([]);
  const [editableStrikeScript, setEditableStrikeScript] = useState("");
  const [targetStatus, setTargetStatus] = useState<"drafting" | "ready" | "completed">("drafting");
  const [isCommitting, setIsCommitting] = useState(false);
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false);
  const [isResolvingExport, setIsResolvingExport] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const splitStrikePayload = (raw: string) => {
    const parts = (raw ?? "").split(" || Script: ");
    return {
      document: parts[0]?.trim() ?? "",
      script: parts[1]?.trim() ?? "",
    };
  };

  const parseStreamedJson = (raw: string): ParsedFunnel | null => {
    const trimmed = (raw ?? "").trim();
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed) as Partial<ParsedFunnel>;
      if (!parsed?.the_strike_document || !Array.isArray(parsed?.lock_in_questions)) return null;
      return {
        topic: String(parsed.topic ?? "Cross-Examination Funnel"),
        lock_in_questions: parsed.lock_in_questions.map((q) => String(q)),
        the_strike_document: String(parsed.the_strike_document),
        strike_script: parsed.strike_script ? String(parsed.strike_script) : undefined,
      };
    } catch {
      const start = trimmed.indexOf("{");
      const end = trimmed.lastIndexOf("}");
      if (start < 0 || end <= start) return null;
      try {
        const parsed = JSON.parse(trimmed.slice(start, end + 1)) as Partial<ParsedFunnel>;
        if (!parsed?.the_strike_document || !Array.isArray(parsed?.lock_in_questions)) return null;
        return {
          topic: String(parsed.topic ?? "Cross-Examination Funnel"),
          lock_in_questions: parsed.lock_in_questions.map((q) => String(q)),
          the_strike_document: String(parsed.the_strike_document),
          strike_script: parsed.strike_script ? String(parsed.strike_script) : undefined,
        };
      } catch {
        return null;
      }
    }
  };

  const nodeLabelById = useMemo(() => {
    const labelMap = new Map<string, string>();
    for (const node of nodes) {
      labelMap.set(node.id, node.label);
    }
    return labelMap;
  }, [nodes]);

  const relatedEdges = useMemo(() => {
    if (!targetNode?.label) return [];
    return edges.filter((edge) => {
      const sourceLabel = nodeLabelById.get(edge.source_node_id);
      const targetLabel = nodeLabelById.get(edge.target_node_id);
      return sourceLabel === targetNode.label || targetLabel === targetNode.label;
    });
  }, [edges, nodeLabelById, targetNode?.label]);

  const handleDismiss = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
    setIsStreaming(false);
    setSavedToVault(false);
    setStreamingFunnelText("");
    setParsedFunnel(null);
    setEditableQuestions([]);
    setEditableStrikeScript("");
    setTargetStatus("drafting");
    onClose();
  }, [onClose]);

  const commitEditsToVault = async () => {
    if (!parsedFunnel?.id) {
      toast.error("No persisted funnel available to update yet.");
      return;
    }
    setIsCommitting(true);
    try {
      await fetch(`/api/internal/legal/cases/${slug}/deposition/funnels/${parsedFunnel.id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lock_in_questions: editableQuestions,
          strike_script: editableStrikeScript,
        }),
      }).then(async (res) => {
        if (!res.ok) {
          const detail = await res.text();
          throw new Error(detail || "Failed to update funnel");
        }
      });
      setParsedFunnel((prev) =>
        prev
          ? {
              ...prev,
              lock_in_questions: editableQuestions,
              strike_script: editableStrikeScript,
            }
          : prev,
      );
      toast.success("Work Product Saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to commit edits");
    } finally {
      setIsCommitting(false);
    }
  };

  const updateTargetStatus = async (nextStatus: "drafting" | "ready" | "completed") => {
    if (!parsedFunnel?.target_id) {
      toast.error("No target loaded yet.");
      return;
    }
    setIsUpdatingStatus(true);
    try {
      await fetch(`/api/internal/legal/cases/${slug}/deposition/targets/${parsedFunnel.target_id}/status`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      }).then(async (res) => {
        if (!res.ok) {
          const detail = await res.text();
          throw new Error(detail || "Failed to update target status");
        }
      });
      setTargetStatus(nextStatus);
      setParsedFunnel((prev) => (prev ? { ...prev, target_status: nextStatus } : prev));
      toast.success(nextStatus === "ready" ? "Target marked READY" : "Target status updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setIsUpdatingStatus(false);
    }
  };

  const openCourtroomPacket = async () => {
    if (parsedFunnel?.target_id) {
      window.open(
        `/legal/cases/${slug}/deposition/${parsedFunnel.target_id}/print`,
        "_blank",
        "noopener,noreferrer",
      );
      return;
    }

    setIsResolvingExport(true);
    try {
      const resp = await fetch(`/api/internal/legal/cases/${slug}/deposition/targets`, {
        method: "GET",
        credentials: "include",
      });
      if (!resp.ok) {
        throw new Error("Unable to resolve target for export");
      }
      const payload = (await resp.json()) as {
        targets?: Array<{
          id?: string;
          entity_name?: string;
          funnels?: Array<{ id?: string }>;
        }>;
      };
      const matched = (payload.targets ?? []).find((t) => t.entity_name === targetNode?.label);
      if (!matched?.id) {
        throw new Error("Target is not yet saved in vault");
      }

      setParsedFunnel((prev) =>
        prev
          ? {
              ...prev,
              target_id: String(matched.id),
              id: prev.id || String(matched.funnels?.[0]?.id ?? ""),
            }
          : prev,
      );
      window.open(
        `/legal/cases/${slug}/deposition/${matched.id}/print`,
        "_blank",
        "noopener,noreferrer",
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export target unavailable");
    } finally {
      setIsResolvingExport(false);
    }
  };

  useEffect(() => {
    if (!isOpen || !targetNode?.label) return;

    setStreamingFunnelText("");
    setSavedToVault(false);
    setParsedFunnel(null);
    setIsStreaming(true);

    const streamUrl = `/api/internal/legal/cases/${slug}/deposition/stream-funnel?target_name=${encodeURIComponent(
      targetNode.label,
    )}`;
    const source = new EventSource(streamUrl, { withCredentials: true });
    sourceRef.current = source;
    let streamedText = "";

    const hydrateParsedFromVault = async () => {
      try {
        const resp = await fetch(`/api/internal/legal/cases/${slug}/deposition/targets`, {
          method: "GET",
          credentials: "include",
        });
        if (!resp.ok) throw new Error("targets fetch failed");
        const payload = (await resp.json()) as {
          targets?: Array<{
            id?: string;
            entity_name?: string;
            status?: "drafting" | "ready" | "completed";
            funnels?: Array<{
              id?: string;
              topic?: string;
              lock_in_questions?: string[];
              the_strike_document?: string;
              strike_script?: string;
            }>;
          }>;
        };
        const target = (payload.targets ?? []).find((t) => t.entity_name === targetNode.label);
        const funnel = target?.funnels?.[0];
        if (funnel?.the_strike_document && Array.isArray(funnel?.lock_in_questions)) {
          const hydrated: ParsedFunnel = {
            id: funnel?.id ? String(funnel.id) : undefined,
            target_id: target?.id ? String(target.id) : undefined,
            target_status: target?.status ?? "drafting",
            topic: String(funnel.topic ?? "Cross-Examination Funnel"),
            lock_in_questions: funnel.lock_in_questions.map((q) => String(q)),
            the_strike_document: String(funnel.the_strike_document),
            strike_script: funnel.strike_script ? String(funnel.strike_script) : undefined,
          };
          setParsedFunnel(hydrated);
          setEditableQuestions(hydrated.lock_in_questions);
          setEditableStrikeScript(hydrated.strike_script ?? "");
          setTargetStatus(hydrated.target_status ?? "drafting");
          return;
        }
      } catch {
        // Fall through to streamed JSON parse.
      }

      const fallback = parseStreamedJson(streamedText);
      if (fallback) {
        setParsedFunnel(fallback);
        setEditableQuestions(fallback.lock_in_questions);
        setEditableStrikeScript(fallback.strike_script ?? "");
        setTargetStatus(fallback.target_status ?? "drafting");
      }
    };

    source.onmessage = (event) => {
      if (!event?.data) return;
      streamedText += event.data;
      setStreamingFunnelText((prev) => `${prev}${event.data}`);
    };

    source.addEventListener("close", async () => {
      setIsStreaming(false);
      setSavedToVault(true);
      await hydrateParsedFromVault();
      source.close();
      sourceRef.current = null;
    });

    source.addEventListener("error", () => {
      setIsStreaming(false);
      source.close();
      sourceRef.current = null;
    });

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [isOpen, slug, targetNode?.label]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        handleDismiss();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleDismiss, isOpen]);

  if (!isOpen || !targetNode) return null;

  const strikeSource = parsedFunnel?.the_strike_document ?? relatedEdges[0]?.source_ref ?? "n/a";
  const strike = splitStrikePayload(strikeSource);

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/95 backdrop-blur-sm">
      <div className="h-full w-full p-6">
        <div className="flex h-full flex-col rounded-lg border border-slate-800 bg-slate-950">
          <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold uppercase tracking-[0.2em] text-slate-200">
                Deposition War Room
              </h2>
              <Badge variant="outline" className="border-red-500/40 bg-red-500/10 text-red-300">
                {targetNode.label}
              </Badge>
              {isStreaming && (
                <Badge variant="outline" className="border-amber-400/40 bg-amber-400/10 text-amber-200">
                  Streaming Live
                </Badge>
              )}
              {savedToVault && (
                <Badge variant="outline" className="border-green-500/40 bg-green-500/10 text-green-300">
                  Saved to Vault
                </Badge>
              )}
              <Badge
                variant="outline"
                className={
                  targetStatus === "ready"
                    ? "border-green-500/40 bg-green-500/10 text-green-300"
                    : targetStatus === "completed"
                      ? "border-blue-500/40 bg-blue-500/10 text-blue-300"
                      : "border-yellow-500/40 bg-yellow-500/10 text-yellow-300"
                }
              >
                {targetStatus.toUpperCase()}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
                <Button
                  type="button"
                  variant={targetStatus === "drafting" ? "default" : "outline"}
                  disabled={!canOperate || isUpdatingStatus}
                  onClick={() => updateTargetStatus("drafting")}
                >
                  Draft
                </Button>
              </RoleGatedAction>
              <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
                <Button
                  type="button"
                  variant={targetStatus === "ready" ? "default" : "outline"}
                  disabled={!canOperate || isUpdatingStatus}
                  onClick={() => updateTargetStatus("ready")}
                >
                  Mark Ready for Deposition
                </Button>
              </RoleGatedAction>
              <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
                <Button
                  type="button"
                  variant="outline"
                  disabled={!canOperate || isStreaming || isResolvingExport}
                  onClick={openCourtroomPacket}
                >
                  {isResolvingExport ? "Resolving Packet..." : "Export Courtroom Packet"}
                </Button>
              </RoleGatedAction>
              <Button variant="outline" size="icon" onClick={handleDismiss} aria-label="Close War Room">
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="grid h-full min-h-0 grid-cols-1 md:grid-cols-2">
            <div className="h-full overflow-y-auto border-r border-slate-800 p-6">
              <p className="mb-4 text-xs uppercase tracking-[0.2em] text-slate-400">The Funnel</p>
              {isStreaming && (
                <>
                  <p className="mb-4 text-xs uppercase tracking-[0.2em] text-amber-300 animate-pulse">
                    Sovereign Graph Traversal Active...
                  </p>
                  <div className="whitespace-pre-wrap font-serif text-3xl leading-relaxed text-white">
                    {streamingFunnelText || "Awaiting Sovereign stream..."}
                  </div>
                </>
              )}
              {!isStreaming && parsedFunnel && (
                <div className="space-y-5">
                  <p className="text-sm font-semibold uppercase tracking-[0.25em] text-yellow-500">
                    {parsedFunnel.topic}
                  </p>
                  {editableQuestions.map((question, index) => (
                    <div
                      key={`${parsedFunnel.topic}-q-${index}`}
                      className="border-l-4 border-slate-700 pl-4 mb-6"
                    >
                      <p className="mb-2 text-base font-medium uppercase tracking-[0.2em] text-slate-400">
                        Q{index + 1}
                      </p>
                      <textarea
                        value={question}
                        onChange={(event) => {
                          const next = [...editableQuestions];
                          next[index] = event.target.value;
                          setEditableQuestions(next);
                        }}
                        className="w-full resize-y rounded bg-slate-900/60 p-3 font-serif text-4xl text-white leading-tight outline-none ring-0 border border-slate-700 focus:border-slate-500"
                        rows={3}
                      />
                    </div>
                  ))}
                  <div className="rounded border border-red-500/50 bg-red-900/20 p-6">
                    <p className="mb-2 text-sm font-semibold uppercase tracking-[0.2em] text-red-300">
                      The Strike
                    </p>
                    <p className="text-2xl text-red-100">{strike.document || "Evidence reference unavailable"}</p>
                    <textarea
                      value={editableStrikeScript || strike.script}
                      onChange={(event) => setEditableStrikeScript(event.target.value)}
                      className="mt-3 w-full resize-y rounded bg-red-950/40 p-3 text-lg text-red-200 outline-none border border-red-500/40 focus:border-red-300/60"
                      rows={4}
                    />
                    <div className="mt-4 flex justify-end">
                      <RoleGatedAction allowed={canOperate} reason="Manager or admin role required.">
                        <Button type="button" onClick={commitEditsToVault} disabled={!canOperate || isCommitting}>
                          {isCommitting ? "Committing..." : "Commit Edits to Vault"}
                        </Button>
                      </RoleGatedAction>
                    </div>
                  </div>
                </div>
              )}
              {!isStreaming && !parsedFunnel && (
                <p className="font-serif text-2xl text-slate-200">
                  Stream complete. No structured funnel payload was parsed.
                </p>
              )}
            </div>

            <div className="h-full overflow-y-auto bg-slate-900 p-6 text-sm text-slate-300">
              <p className="mb-4 font-mono text-xs uppercase tracking-[0.2em] text-slate-400">The Evidence</p>
              <div className="space-y-4">
                <div className="rounded-md border border-slate-700 bg-slate-950/40 p-3">
                  <p className="font-semibold text-slate-100">Target Node</p>
                  <p className="mt-1 font-mono text-xs text-slate-300">{targetNode.label}</p>
                  <p className="font-mono text-xs text-slate-500">{targetNode.entity_type}</p>
                </div>

                <div className="space-y-2">
                  {relatedEdges.map((edge) => {
                    const sourceLabel = nodeLabelById.get(edge.source_node_id) ?? edge.source_node_id;
                    const targetLabel = nodeLabelById.get(edge.target_node_id) ?? edge.target_node_id;
                    return (
                      <div key={edge.id} className="rounded-md border border-slate-700 bg-slate-950/40 p-3">
                        <p className="font-mono text-xs text-slate-200">
                          [{sourceLabel}] -&gt; ({edge.relationship_type}) -&gt; [{targetLabel}]
                        </p>
                        <p className="mt-2 font-mono text-xs text-slate-400">
                          Strike Document: {edge.source_ref ?? "n/a"}
                        </p>
                      </div>
                    );
                  })}
                  {relatedEdges.length === 0 && (
                    <p className="font-mono text-xs text-slate-500">
                      No contradiction edges currently linked to this node.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
