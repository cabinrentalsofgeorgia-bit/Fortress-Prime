"use client";

import { useCallback, useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";

export interface AiInsight {
  id: string;
  task_id: string;
  event_type: string;
  reference_id: string;
  insight_payload: Record<string, unknown>;
  created_at: string;
}

interface AiInsightListResponse {
  items: AiInsight[];
  count: number;
}

export interface AiInsightWidgetProps {
  /** e.g. reservation confirmation_code */
  referenceId: string;
  /** Kafka topic / stored event_type; default reservation.confirmed */
  eventType?: string;
}

function payloadPreview(payload: Record<string, unknown>): string {
  const summary = payload.summary;
  if (typeof summary === "string" && summary.trim()) return summary.trim();
  const text = payload.text;
  if (typeof text === "string" && text.trim()) return text.trim();
  const brief = payload.brief;
  if (typeof brief === "string" && brief.trim()) return brief.trim();
  const draftEmail = payload.draft_email;
  if (typeof draftEmail === "string" && draftEmail.trim()) return draftEmail.trim();
  const draftSms = payload.draft_sms;
  if (typeof draftSms === "string" && draftSms.trim()) return draftSms.trim();
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

export default function AiInsightWidget({
  referenceId,
  eventType = "reservation.confirmed",
}: AiInsightWidgetProps) {
  const [insights, setInsights] = useState<AiInsight[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!referenceId?.trim()) {
      setLoading(false);
      setInsights([]);
      return;
    }
    if (!getToken()) {
      setError("Staff session required");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await api.get<AiInsightListResponse>("/api/admin/insights", {
        reference_id: referenceId.trim(),
        event_type: eventType,
        limit: 20,
      });
      setInsights(data.items ?? []);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Request failed";
      setError(message);
      setInsights([]);
    } finally {
      setLoading(false);
    }
  }, [referenceId, eventType]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="animate-pulse text-emerald-500/50 font-mono text-sm">
        Intercepting AI telemetry…
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-red-400 font-mono text-sm border border-red-500/30 rounded-lg p-3 bg-red-500/5">
        Failed to load intel: {error}
      </div>
    );
  }
  if (insights.length === 0) {
    return (
      <div className="text-zinc-500 font-mono text-sm border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
        No AI insights generated for this asset yet.
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 font-mono text-sm shadow-lg">
      <div className="flex items-center justify-between mb-4 border-b border-zinc-700 pb-2">
        <h3 className="text-emerald-400 font-semibold uppercase tracking-wider">
          Ray Matrix Intelligence
        </h3>
        <span className="text-xs text-zinc-400 px-2 py-1 bg-zinc-800 rounded">{eventType}</span>
      </div>

      <div className="space-y-4">
        {insights.map((insight) => (
          <div
            key={insight.id}
            className="bg-zinc-800/50 p-3 rounded border border-zinc-700/50"
          >
            <div className="text-xs text-zinc-500 mb-2 flex justify-between gap-2">
              <span className="truncate">Task: {insight.task_id}</span>
              <span className="shrink-0">
                {new Date(insight.created_at).toLocaleString()}
              </span>
            </div>
            <div className="text-zinc-300 whitespace-pre-wrap break-words">
              {payloadPreview(insight.insight_payload)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
