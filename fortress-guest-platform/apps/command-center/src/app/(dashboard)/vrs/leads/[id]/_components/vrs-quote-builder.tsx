"use client";

import { useState } from "react";

interface VRSQuoteBuilderPanelProps {
  leadId: string;
  defaultCabin?: string;
}

type QuoteResult = {
  swarm_latency_ms: number;
  suggested_price: number;
  guest_message: string;
};

export function VRSQuoteBuilderPanel({ leadId, defaultCabin = "" }: VRSQuoteBuilderPanelProps) {
  const [cabinName, setCabinName] = useState<string>(defaultCabin);
  const [guestCount, setGuestCount] = useState<number>(2);
  const [checkIn, setCheckIn] = useState<string>("");
  const [checkOut, setCheckOut] = useState<string>("");
  const [specialRequests, setSpecialRequests] = useState<string>("");

  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [quoteResult, setQuoteResult] = useState<QuoteResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerateQuote = async () => {
    setIsGenerating(true);
    setError(null);
    setQuoteResult(null);

    try {
      const response = await fetch(`/api/vrs/leads/${leadId}/quotes/build`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
        body: JSON.stringify({
          cabin_name: cabinName,
          guest_count: guestCount,
          check_in: checkIn,
          check_out: checkOut,
          special_requests: specialRequests,
        }),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(
          typeof errData?.detail === "string"
            ? errData.detail
            : "Failed to generate quote from Swarm.",
        );
      }

      const data = await response.json();
      setQuoteResult(data as QuoteResult);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to generate quote from Swarm.");
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="bg-gray-900 border border-gray-700 p-6 rounded-lg shadow-lg text-white mt-6">
      <div className="flex justify-between items-center border-b border-gray-700 pb-4 mb-4">
        <h3 className="text-xl font-bold text-blue-400 uppercase tracking-wider">Dynamic Quote Engine</h3>
        <span className="text-xs bg-blue-900 text-blue-200 px-2 py-1 rounded font-mono">INTENT: COMMERCIAL</span>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-sm text-gray-400 mb-1">Cabin Selection</label>
          <input
            type="text"
            placeholder="e.g., Blue Ridge Summit"
            value={cabinName}
            onChange={(e) => setCabinName(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
            disabled={isGenerating}
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">Guest Count</label>
          <input
            type="number"
            value={guestCount}
            onChange={(e) => setGuestCount(Number(e.target.value))}
            min={1}
            max={20}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono"
            disabled={isGenerating}
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">Check-In</label>
          <input
            type="date"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono"
            disabled={isGenerating}
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">Check-Out</label>
          <input
            type="date"
            value={checkOut}
            onChange={(e) => setCheckOut(e.target.value)}
            className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono"
            disabled={isGenerating}
          />
        </div>
      </div>

      <div className="mb-6">
        <label className="block text-sm text-gray-400 mb-1">Special Requests / Context</label>
        <textarea
          rows={3}
          placeholder="e.g., Guest is asking about early check-in and pet fees..."
          value={specialRequests}
          onChange={(e) => setSpecialRequests(e.target.value)}
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 resize-none"
          disabled={isGenerating}
        />
      </div>

      <div className="flex justify-end">
        <button
          onClick={handleGenerateQuote}
          disabled={isGenerating || !cabinName || !checkIn || !checkOut}
          className={`px-6 py-2 rounded font-bold uppercase tracking-wide transition-colors ${
            isGenerating || !cabinName || !checkIn || !checkOut
              ? "bg-gray-700 text-gray-500 cursor-not-allowed"
              : "bg-blue-600 hover:bg-blue-500 text-white"
          }`}
        >
          {isGenerating ? "Swarm Decoding..." : "Build Quote & Draft Response"}
        </button>
      </div>

      {error && (
        <div className="bg-red-900/50 border border-red-500 p-4 rounded mt-4 text-red-200 text-sm font-mono">
          [ERROR]: {error}
        </div>
      )}

      {quoteResult && (
        <div className="bg-gray-800 border border-blue-700 p-4 rounded mt-4">
          <div className="flex justify-between items-center mb-4 text-sm border-b border-gray-700 pb-2">
            <span className="text-blue-400 font-bold">Quote Generated</span>
            <span className="text-gray-400 font-mono">Swarm Latency: {quoteResult.swarm_latency_ms}ms</span>
          </div>

          <div className="mb-4">
            <span className="block text-xs text-gray-500 uppercase mb-1">Suggested Baseline Price</span>
            <span className="text-3xl font-bold text-green-400">${quoteResult.suggested_price.toFixed(2)}</span>
          </div>

          <div>
            <span className="block text-xs text-gray-500 uppercase mb-1">Drafted Guest Response</span>
            <div className="bg-gray-900 p-4 rounded border border-gray-700 text-sm text-gray-200 whitespace-pre-wrap">
              {quoteResult.guest_message}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
