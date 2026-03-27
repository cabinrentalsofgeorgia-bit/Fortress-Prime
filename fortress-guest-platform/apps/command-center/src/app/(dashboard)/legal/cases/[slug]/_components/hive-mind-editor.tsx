"use client";

import { useState } from "react";

interface HiveMindEditorProps {
  caseSlug: string;
  moduleType: string;
  initialText: string;
  onFinalize?: (finalText: string) => void;
}

type SyncState = "idle" | "synced" | "error";

export function HiveMindEditor({
  caseSlug,
  moduleType,
  initialText,
  onFinalize,
}: HiveMindEditorProps) {
  const [currentText, setCurrentText] = useState(initialText);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [syncState, setSyncState] = useState<SyncState>("idle");

  const transmitTelemetry = async (accepted: boolean) => {
    setIsSubmitting(true);
    setSyncState("idle");

    try {
      const response = await fetch(`/api/legal/cases/${caseSlug}/feedback/telemetry`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          module_type: moduleType,
          original_swarm_text: initialText,
          human_edited_text: currentText,
          accepted,
        }),
      });

      if (!response.ok) {
        throw new Error("Telemetry API rejected payload.");
      }

      setSyncState("synced");
      if (onFinalize && accepted) {
        onFinalize(currentText);
      }
    } catch (error) {
      console.error("[HIVE MIND] Telemetry drop failed:", error);
      setSyncState("error");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg overflow-hidden flex flex-col mt-3">
      <div className="flex justify-between items-center bg-gray-800 px-4 py-2 border-b border-gray-700">
        <span className="text-xs font-mono text-gray-400 uppercase tracking-widest">
          Counsel Review: {moduleType.replaceAll("_", " ")}
        </span>
        {syncState === "synced" && (
          <span className="text-xs font-mono text-emerald-400 animate-pulse">
            [TELEMETRY SYNCED TO HIVE MIND]
          </span>
        )}
        {syncState === "error" && (
          <span className="text-xs font-mono text-red-400">[SYNC ERROR]</span>
        )}
      </div>

      <textarea
        className="w-full h-56 bg-gray-900 text-gray-200 p-4 font-mono text-sm focus:outline-none focus:ring-1 focus:ring-emerald-500 resize-y"
        value={currentText}
        onChange={(e) => {
          setCurrentText(e.target.value);
          setSyncState("idle");
        }}
        disabled={isSubmitting}
      />

      <div className="bg-gray-800 p-3 flex justify-end gap-3 border-t border-gray-700">
        <button
          onClick={() => transmitTelemetry(false)}
          disabled={isSubmitting}
          className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-red-400 hover:bg-red-900/30 rounded transition-colors disabled:opacity-50"
        >
          Reject & Regenerate
        </button>
        <button
          onClick={() => transmitTelemetry(true)}
          disabled={isSubmitting}
          className="px-4 py-2 text-xs font-bold uppercase tracking-wider bg-emerald-700 hover:bg-emerald-600 text-white rounded transition-colors disabled:opacity-50"
        >
          {isSubmitting ? "Syncing..." : "Approve & File"}
        </button>
      </div>
    </div>
  );
}
