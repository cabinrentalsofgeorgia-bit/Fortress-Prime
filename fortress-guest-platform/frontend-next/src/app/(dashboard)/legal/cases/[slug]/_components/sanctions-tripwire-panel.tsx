"use client";

import { useEffect, useState } from "react";

interface SanctionsTripwirePanelProps {
  caseSlug: string;
}

type SanctionsAlert = {
  id: string;
  alert_type: string;
  contradiction_summary: string;
  confidence_score?: number | null;
  filing_ref?: string | null;
  draft_content?: string | null;
};

export function SanctionsTripwirePanel({ caseSlug }: SanctionsTripwirePanelProps) {
  const [alerts, setAlerts] = useState<SanctionsAlert[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSweeping, setIsSweeping] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAlerts = async () => {
    try {
      const response = await fetch(`/api/legal/cases/${caseSlug}/sanctions/alerts`, {
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error("Failed to fetch sanctions alerts.");
      }
      const data = await response.json().catch(() => ({}));
      setAlerts(Array.isArray(data?.alerts) ? data.alerts : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch sanctions alerts.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setIsLoading(true);
    setError(null);
    void fetchAlerts();
  }, [caseSlug]);

  const handleForceSweep = async () => {
    setIsSweeping(true);
    setError(null);
    try {
      // Case-scoped manual sweep keeps operator action deterministic.
      const response = await fetch(`/api/legal/cases/${caseSlug}/sanctions/sweep`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error("Manual tripwire sweep failed.");
      }
      await fetchAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Manual tripwire sweep failed.");
    } finally {
      setIsSweeping(false);
    }
  };

  if (isLoading) {
    return <div className="text-gray-400 font-mono animate-pulse">Loading Tripwire telemetry...</div>;
  }

  return (
    <div className="bg-gray-900 border border-red-900/50 p-6 rounded-lg shadow-lg text-white mt-6 relative overflow-hidden">
      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-red-600 to-red-900" />

      <div className="flex justify-between items-center border-b border-gray-800 pb-4 mb-4">
        <h3 className="text-xl font-bold text-red-500 uppercase tracking-wider flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-ping" />
          Sanctions Tripwire
        </h3>
        <button
          onClick={handleForceSweep}
          disabled={isSweeping}
          className={`text-xs px-3 py-1 rounded font-mono uppercase border transition-colors ${
            isSweeping
              ? "bg-red-900/20 text-red-500 border-red-900/50 cursor-not-allowed"
              : "bg-red-900/40 text-red-200 border-red-700 hover:bg-red-800/60"
          }`}
        >
          {isSweeping ? "Sweeping Case Graph..." : "Force Manual Sweep"}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-500 p-4 rounded mb-4 text-red-200 text-sm font-mono">
          [SYS_ERR]: {error}
        </div>
      )}

      {alerts.length === 0 ? (
        <div className="text-center p-6 border border-dashed border-gray-700 rounded text-gray-500 font-mono">
          No material contradictions detected. Opposing timeline holds.
        </div>
      ) : (
        <div className="space-y-4">
          {alerts.map((alert) => {
            const confidence = Number(alert.confidence_score ?? 0);
            const confidencePercent = confidence > 1 ? confidence : confidence * 100;
            return (
              <div key={alert.id} className="bg-black/40 border border-red-800/50 p-4 rounded">
                <div className="flex justify-between items-start mb-3">
                  <div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-widest bg-red-900 text-red-100 mr-2">
                      {String(alert.alert_type || "RULE_11").replace("_", " ")}
                    </span>
                    <span className="text-sm text-gray-400 font-mono">Ref: {alert.filing_ref || "N/A"}</span>
                  </div>
                  <div className="text-right">
                    <span className="block text-xs text-gray-500 uppercase">Confidence</span>
                    <span className={`font-mono text-sm ${confidencePercent >= 90 ? "text-red-400" : "text-amber-400"}`}>
                      {confidencePercent.toFixed(1)}%
                    </span>
                  </div>
                </div>

                <div className="mb-4">
                  <span className="block text-xs text-gray-500 uppercase mb-1">Detected Contradiction</span>
                  <p className="text-sm text-gray-200 border-l-2 border-red-600 pl-3 py-1 bg-red-900/10">
                    {alert.contradiction_summary}
                  </p>
                </div>

                <div>
                  <span className="block text-xs text-gray-500 uppercase mb-1">Drafted Response</span>
                  <div className="text-xs text-gray-400 font-mono bg-gray-900 p-3 rounded border border-gray-800 whitespace-pre-wrap max-h-32 overflow-y-auto">
                    {alert.draft_content || "No draft content attached for this alert."}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
