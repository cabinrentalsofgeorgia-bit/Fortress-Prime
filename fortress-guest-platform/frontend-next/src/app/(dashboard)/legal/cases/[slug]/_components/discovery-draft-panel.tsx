"use client";

import { useState } from "react";

import { HiveMindEditor } from "./hive-mind-editor";

type DiscoveryDraftPanelProps = {
  slug: string;
};

type DiscoveryItem = {
  category?: string;
  target_entity?: string;
  content?: string;
  relevance_score?: number;
  justification?: string;
  rationale?: string;
};

type DiscoveryDraftResponse = {
  proportionality_cap_used?: number;
  item_limit?: number;
  items?: DiscoveryItem[];
};

export function DiscoveryDraftPanel({ slug }: DiscoveryDraftPanelProps) {
  const [cap, setCap] = useState<number>(25);
  const [isDrafting, setIsDrafting] = useState<boolean>(false);
  const [draftResult, setDraftResult] = useState<DiscoveryDraftResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const updateDraftItemContent = (index: number, content: string) => {
    setDraftResult((prev) => {
      if (!prev || !Array.isArray(prev.items)) return prev;
      const nextItems = [...prev.items];
      const existing = nextItems[index] || {};
      nextItems[index] = { ...existing, content };
      return { ...prev, items: nextItems };
    });
  };

  const handleDraftGeneration = async () => {
    const safeCap = Math.max(1, Math.min(25, Number.isFinite(cap) ? cap : 25));

    setIsDrafting(true);
    setError(null);
    setDraftResult(null);

    try {
      // Guard against edge/proxy hangs while GPU swarm works.
      const timeoutMs = 130_000;
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const response = await fetch(`/api/legal/cases/${slug}/discovery/draft-pack`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify({ local_rules_cap: safeCap }),
          signal: controller.signal,
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
          throw new Error(data?.detail || "Failed to generate draft pack.");
        }

        const normalizedItems = Array.isArray(data?.items)
          ? data.items.map((item: unknown) => {
              if (typeof item === "string") {
                return { content: item, category: "interrogatory" } satisfies DiscoveryItem;
              }
              if (item && typeof item === "object") {
                return item as DiscoveryItem;
              }
              return { content: "", category: "interrogatory" } satisfies DiscoveryItem;
            })
          : [];

        setDraftResult({
          proportionality_cap_used: Number(data?.proportionality_cap_used ?? data?.item_limit ?? safeCap),
          item_limit: Number(data?.item_limit ?? safeCap),
          items: normalizedItems,
        });
      } finally {
        clearTimeout(timeoutId);
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        setError("Draft generation timed out after 120 seconds. The swarm may still be processing.");
      } else {
        setError(err instanceof Error ? err.message : "Draft generation failed.");
      }
    } finally {
      setIsDrafting(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 p-6 rounded-lg shadow-lg text-white mt-6">
      <div className="flex justify-between items-center border-b border-gray-700 pb-4 mb-4">
        <h3 className="text-xl font-bold text-red-400 uppercase tracking-wider">Rule 26 Discovery Draft</h3>
        <span className="text-xs bg-red-900 text-red-200 px-2 py-1 rounded font-mono">RESTRICTED SENSITIVITY</span>
      </div>

      <div className="mb-6 flex items-end gap-4">
        <div className="flex-1">
          <label className="block text-sm text-gray-400 mb-2">Proportionality Cap (Local Rules)</label>
          <input
            type="number"
            value={cap}
            onChange={(e) => setCap(Number(e.target.value))}
            min={1}
            max={25}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-red-500 font-mono"
            disabled={isDrafting}
          />
        </div>
        <button
          onClick={handleDraftGeneration}
          disabled={isDrafting}
          className={`px-6 py-2 rounded font-bold uppercase tracking-wide transition-colors ${
            isDrafting ? "bg-gray-700 text-gray-500 cursor-not-allowed" : "bg-red-600 hover:bg-red-500 text-white"
          }`}
        >
          {isDrafting ? "Swarm Decoding..." : "Generate Draft"}
        </button>
      </div>

      {isDrafting && (
        <p className="text-xs text-gray-400 mb-3 font-mono">
          GPU swarm inference in progress. This can take up to 120 seconds for large evidence graphs.
        </p>
      )}

      {error && (
        <div className="bg-red-900/50 border border-red-500 p-4 rounded mb-4 text-red-200 text-sm font-mono">
          [ERROR]: {error}
        </div>
      )}

      {draftResult && Array.isArray(draftResult.items) && draftResult.items.length > 0 && (
        <div className="bg-gray-800 border border-green-700 p-4 rounded mt-4">
          <div className="flex justify-between items-center mb-4 text-sm border-b border-gray-700 pb-2">
            <span className="text-green-400 font-bold">Draft Pack Generated</span>
            <span className="text-gray-400">Items: {draftResult.proportionality_cap_used ?? draftResult.item_limit ?? draftResult.items.length}</span>
          </div>
          <div className="max-h-64 overflow-y-auto pr-2 space-y-4">
            {draftResult.items.map((item, idx) => (
              <div key={idx} className="bg-gray-900 p-3 rounded border border-gray-700">
                <div className="flex justify-between text-xs text-gray-500 uppercase mb-2">
                  <span>{item.category ?? "interrogatory"}</span>
                  <span>Target: {item.target_entity ?? "Opposing Party"}</span>
                </div>
                <div className="mt-2 text-xs text-blue-400 font-mono">
                  [Relevance: {(item.relevance_score ?? 1).toFixed(2)}] {item.justification ?? item.rationale ?? "Graph-derived draft."}
                </div>
                <HiveMindEditor
                  caseSlug={slug}
                  moduleType={`discovery_${(item.category ?? "interrogatory").toLowerCase()}`}
                  initialText={item.content ?? ""}
                  onFinalize={(finalText) => updateDraftItemContent(idx, finalText)}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
