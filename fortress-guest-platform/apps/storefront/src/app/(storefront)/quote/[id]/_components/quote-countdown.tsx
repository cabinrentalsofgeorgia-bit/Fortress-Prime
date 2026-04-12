"use client";

import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

interface TimeRemaining {
  hours: number;
  minutes: number;
  totalMinutes: number;
}

function getTimeRemaining(expiresAt: string): TimeRemaining | null {
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return null;
  const totalMinutes = Math.floor(diff / 60_000);
  return {
    hours: Math.floor(totalMinutes / 60),
    minutes: totalMinutes % 60,
    totalMinutes,
  };
}

interface QuoteCountdownProps {
  expiresAt: string;
}

export function QuoteCountdown({ expiresAt }: QuoteCountdownProps) {
  const [remaining, setRemaining] = useState<TimeRemaining | null>(() =>
    getTimeRemaining(expiresAt),
  );

  useEffect(() => {
    const id = setInterval(() => setRemaining(getTimeRemaining(expiresAt)), 60_000);
    return () => clearInterval(id);
  }, [expiresAt]);

  if (!remaining) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-rose-700">
        <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
        Quote expired
      </div>
    );
  }

  const label =
    remaining.hours > 0
      ? `${remaining.hours}h ${remaining.minutes}m remaining`
      : `${remaining.minutes}m remaining`;

  if (remaining.totalMinutes < 60) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-rose-700">
        <Clock className="h-3 w-3" />
        {label}
      </div>
    );
  }

  if (remaining.hours < 4) {
    return (
      <div className="inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-amber-700">
        <Clock className="h-3 w-3" />
        {label} — act soon
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-emerald-700">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
      </span>
      {label}
    </div>
  );
}
