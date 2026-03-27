"use client";

import { useMemo, useState, useTransition } from "react";

export interface PropertyCalendarPayload {
  property_id: string;
  property_slug: string;
  month: number;
  year: number;
  start_date: string;
  end_date: string;
  blocked_dates: string[];
  blocked_dates_count: number;
  available_dates_count: number;
  generated_at: string;
  pricing_source?: string;
  availability_source?: string;
  month_grid?: Record<
    string,
    {
      date: string;
      status: string;
      available: boolean;
      nightly_rate: number | null;
      season: string;
      multiplier: number;
    }
  >;
}

interface SovereignAvailabilityCalendarProps {
  propertySlug: string;
  initialCalendar: PropertyCalendarPayload;
  checkIn: string;
  checkOut: string;
  onDatesChange: (next: { checkIn: string; checkOut: string }) => void;
}

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function monthKey(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function shiftMonth(year: number, month: number, delta: number): { year: number; month: number } {
  const cursor = new Date(Date.UTC(year, month - 1 + delta, 1));
  return {
    year: cursor.getUTCFullYear(),
    month: cursor.getUTCMonth() + 1,
  };
}

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function formatMonthLabel(year: number, month: number): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, 1)));
}

function formatRefreshLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "just now";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatPriceHint(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return `$${Math.round(value)}`;
}

export function SovereignAvailabilityCalendar({
  propertySlug,
  initialCalendar,
  checkIn,
  checkOut,
  onDatesChange,
}: SovereignAvailabilityCalendarProps) {
  const [calendarCache, setCalendarCache] = useState<Record<string, PropertyCalendarPayload>>({
    [monthKey(initialCalendar.year, initialCalendar.month)]: initialCalendar,
  });
  const [visibleMonth, setVisibleMonth] = useState(initialCalendar.month);
  const [visibleYear, setVisibleYear] = useState(initialCalendar.year);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const currentKey = monthKey(visibleYear, visibleMonth);
  const calendar = calendarCache[currentKey] ?? initialCalendar;
  const blockedDates = useMemo(() => new Set(calendar.blocked_dates), [calendar.blocked_dates]);
  const daysInMonth = new Date(Date.UTC(calendar.year, calendar.month, 0)).getUTCDate();
  const leadingBlankDays = new Date(Date.UTC(calendar.year, calendar.month - 1, 1)).getUTCDay();

  const selectedStart = checkIn || "";
  const selectedEnd = checkOut || "";

  function loadMonth(year: number, month: number): void {
    const key = monthKey(year, month);
    if (calendarCache[key]) {
      setVisibleMonth(month);
      setVisibleYear(year);
      setError(null);
      return;
    }

    startTransition(async () => {
      try {
        const response = await fetch(
          `/api/direct-booking/property/${encodeURIComponent(propertySlug)}/calendar-v2?year=${year}&month=${month}`,
          { cache: "no-store" },
        );
        if (!response.ok) {
          throw new Error("Calendar fetch failed");
        }
        const payload = (await response.json()) as PropertyCalendarPayload;
        setCalendarCache((current) => ({ ...current, [key]: payload }));
        setVisibleMonth(month);
        setVisibleYear(year);
        setError(null);
      } catch {
        setError("Calendar refresh unavailable. Try again.");
      }
    });
  }

  function handleDateClick(iso: string, blocked: boolean): void {
    if (blocked || iso < todayIso) {
      return;
    }
    if (!selectedStart || (selectedStart && selectedEnd)) {
      onDatesChange({ checkIn: iso, checkOut: "" });
      return;
    }
    if (iso <= selectedStart) {
      onDatesChange({ checkIn: iso, checkOut: "" });
      return;
    }
    onDatesChange({ checkIn: selectedStart, checkOut: iso });
  }

  return (
    <section className="rounded-[2rem] border border-slate-200 bg-slate-50 p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
            Native Availability Calendar
          </p>
          <h3 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">
            {formatMonthLabel(calendar.year, calendar.month)}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              const previous = shiftMonth(visibleYear, visibleMonth, -1);
              loadMonth(previous.year, previous.month);
            }}
            className="rounded-full border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
          >
            Prev
          </button>
          <button
            type="button"
            onClick={() => {
              const next = shiftMonth(visibleYear, visibleMonth, 1);
              loadMonth(next.year, next.month);
            }}
            className="rounded-full border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
          >
            Next
          </button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-xs uppercase tracking-[0.18em] text-slate-500">
        <span>Open {calendar.available_dates_count}</span>
        <span>Blocked {calendar.blocked_dates_count}</span>
        {calendar.pricing_source ? <span>Rates {calendar.pricing_source.replaceAll("_", " ")}</span> : null}
        <span>Availability refreshed {formatRefreshLabel(calendar.generated_at)}</span>
      </div>

      <div className="mt-5 grid grid-cols-7 gap-2 text-center text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
        {WEEKDAY_LABELS.map((label) => (
          <div key={label}>{label}</div>
        ))}
      </div>

      <div className="mt-2 grid grid-cols-7 gap-2">
        {Array.from({ length: leadingBlankDays }, (_, index) => (
          <div key={`blank-${index}`} className="aspect-square rounded-2xl bg-transparent" />
        ))}

        {Array.from({ length: daysInMonth }, (_, index) => {
          const day = index + 1;
          const iso = isoDate(calendar.year, calendar.month, day);
          const monthCell = calendar.month_grid?.[iso];
          const blocked = monthCell ? !monthCell.available : blockedDates.has(iso);
          const priceHint = formatPriceHint(monthCell?.nightly_rate);
          const selected =
            iso === selectedStart ||
            iso === selectedEnd ||
            (selectedStart && selectedEnd && iso > selectedStart && iso < selectedEnd);
          const inPast = iso < todayIso;

          return (
            <button
              key={iso}
              type="button"
              onClick={() => handleDateClick(iso, blocked)}
              disabled={blocked || inPast}
              className={[
                "aspect-square rounded-2xl border px-1 py-2 text-sm transition",
                selected
                  ? "border-slate-900 bg-slate-900 text-white"
                  : blocked || inPast
                    ? "border-slate-200 bg-slate-100 text-slate-400"
                    : "border-slate-200 bg-white text-slate-900 hover:border-slate-300 hover:bg-slate-50",
              ].join(" ")}
              aria-label={`${iso} ${blocked ? "unavailable" : "available"}`}
            >
              <span className="sr-only">{iso}</span>
              <span className="flex h-full flex-col items-center justify-center leading-none">
                <span className="text-sm font-medium">{day}</span>
                {!blocked && priceHint ? (
                  <span className={selected ? "mt-1 text-[10px] text-slate-200" : "mt-1 text-[10px] text-emerald-700"}>
                    {priceHint}
                  </span>
                ) : (
                  <span className="mt-1 text-[10px] opacity-0">.</span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-slate-600">
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 rounded-full bg-slate-900" />
          Selected stay
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 rounded-full border border-slate-300 bg-white" />
          Available
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-3 w-3 rounded-full bg-slate-200" />
          Blocked
        </span>
      </div>

      {isPending ? (
        <p className="mt-4 text-sm text-slate-500">Refreshing local calendar...</p>
      ) : null}
      {error ? <p className="mt-4 text-sm text-rose-700">{error}</p> : null}
    </section>
  );
}
