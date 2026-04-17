"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Reservation, Property } from "@/lib/types";

interface TapeChartProps {
  properties: Property[];
  reservations: Reservation[];
  onSelectReservation?: (r: Reservation) => void;
}

const STATUS_COLORS: Record<string, string> = {
  confirmed: "bg-blue-500/80 hover:bg-blue-500",
  checked_in: "bg-emerald-500/80 hover:bg-emerald-500",
  checked_out: "bg-slate-400/60 hover:bg-slate-400",
  cancelled: "bg-red-500/50 hover:bg-red-500/70",
  no_show: "bg-red-400/50 hover:bg-red-400/70",
};

const DAY_WIDTH = 44;
const ROW_HEIGHT = 56;
const HEADER_HEIGHT = 48;
const LABEL_WIDTH = 200;

function daysBetween(a: Date, b: Date) {
  return Math.round((b.getTime() - a.getTime()) / 86400000);
}

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Parse API date-only strings as local calendar days (avoids UTC off-by-one from `new Date("YYYY-MM-DD")`). */
function parseLocalDate(iso: string | undefined | null): Date | null {
  if (iso == null || String(iso).trim() === "") return null;
  const s = String(iso).trim();
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (m) {
    const y = Number(m[1]);
    const mo = Number(m[2]) - 1;
    const day = Number(m[3]);
    const d = new Date(y, mo, day);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

function normalizeReservationStatus(status?: string | null): string {
  return String(status ?? "")
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "_");
}

function isCancelledStatus(status?: string | null): boolean {
  return normalizeReservationStatus(status) === "cancelled";
}

function syntheticPropertyForReservation(r: Reservation): Property {
  return {
    id: r.property_id,
    name: r.property_name?.trim() || `Property ${r.property_id.slice(0, 8)}…`,
    slug: "",
    property_type: "cabin",
    bedrooms: 0,
    bathrooms: 0,
    max_guests: 0,
    is_active: true,
    created_at: "",
    updated_at: "",
  };
}

/** Widen the tape to include every non-cancelled stay (imported Streamline rows are often months out vs native CRG test bookings). */
function computeFitWindow(reservations: Reservation[]): { viewStart: Date; daysToShow: number } | null {
  const active = reservations.filter((r) => !isCancelledStatus(r.status));
  if (!active.length) return null;
  let minT = Infinity;
  let maxT = -Infinity;
  for (const r of active) {
    const a = parseLocalDate(r.check_in_date);
    const b = parseLocalDate(r.check_out_date);
    if (a) minT = Math.min(minT, startOfDay(a).getTime());
    if (b) maxT = Math.max(maxT, startOfDay(b).getTime());
  }
  if (minT === Infinity || maxT === -Infinity) return null;
  const PAD_START = 3;
  const PAD_END = 7;
  const spanDays = Math.ceil((maxT - minT) / 86400000) + PAD_START + PAD_END;
  const daysToShow = Math.min(400, Math.max(30, spanDays));
  const start = new Date(minT);
  start.setDate(start.getDate() - PAD_START);
  return { viewStart: startOfDay(start), daysToShow };
}

export function TapeChart({ properties, reservations, onSelectReservation }: TapeChartProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFitOnceRef = useRef(false);
  const [viewStart, setViewStart] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    return startOfDay(d);
  });

  const [daysToShow, setDaysToShow] = useState(30);
  const today = startOfDay(new Date());

  useEffect(() => {
    if (autoFitOnceRef.current) return;
    const fit = computeFitWindow(reservations);
    if (!fit) return;
    setViewStart(fit.viewStart);
    setDaysToShow(fit.daysToShow);
    autoFitOnceRef.current = true;
  }, [reservations]);

  const days = useMemo(() => {
    const arr: Date[] = [];
    for (let i = 0; i < daysToShow; i++) {
      const d = new Date(viewStart);
      d.setDate(d.getDate() + i);
      arr.push(d);
    }
    return arr;
  }, [viewStart, daysToShow]);

  /** Rows from /api/properties/ plus any property_id present on reservations but missing from that list (e.g. past default limit=100, or sync drift). */
  const chartProperties = useMemo(() => {
    const base = properties ?? [];
    const seen = new Set(base.map((p) => p.id));
    const extras: Property[] = [];
    for (const r of reservations) {
      if (!r.property_id || isCancelledStatus(r.status)) continue;
      if (seen.has(r.property_id)) continue;
      seen.add(r.property_id);
      extras.push(syntheticPropertyForReservation(r));
    }
    return [...base, ...extras];
  }, [properties, reservations]);

  const reservationsByProperty = useMemo(() => {
    const map = new Map<string, Reservation[]>();
    for (const r of reservations) {
      if (isCancelledStatus(r.status)) continue;
      if (!r.property_id) continue;
      const arr = map.get(r.property_id) ?? [];
      arr.push(r);
      map.set(r.property_id, arr);
    }
    return map;
  }, [reservations]);

  function scrollDays(n: number) {
    setViewStart((prev) => {
      const d = new Date(prev);
      d.setDate(d.getDate() + n);
      return d;
    });
  }

  function goToToday() {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    setViewStart(startOfDay(d));
    setDaysToShow(30);
  }

  function fitAllBookings() {
    const fit = computeFitWindow(reservations);
    if (fit) {
      setViewStart(fit.viewStart);
      setDaysToShow(fit.daysToShow);
    }
  }

  const totalWidth = daysToShow * DAY_WIDTH;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => scrollDays(-7)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={goToToday}>
            Today
          </Button>
          <Button variant="outline" size="sm" onClick={() => scrollDays(7)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={fitAllBookings} title="Zoom the tape to include every loaded booking">
            Fit all
          </Button>
          <span className="text-sm text-muted-foreground ml-2">
            {viewStart.toLocaleDateString("en-US", { month: "short", year: "numeric" })}
            {" · "}
            {daysToShow} days
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-blue-500/80" /> Confirmed</span>
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-emerald-500/80" /> Checked In</span>
          <span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-slate-400/60" /> Checked Out</span>
        </div>
      </div>

      <div className="rounded-lg border overflow-hidden">
        <div className="flex">
          {/* Property labels column */}
          <div
            className="shrink-0 border-r bg-card z-10"
            style={{ width: LABEL_WIDTH }}
          >
            <div
              className="border-b bg-muted/50 flex items-center px-3 text-xs font-medium text-muted-foreground"
              style={{ height: HEADER_HEIGHT }}
            >
              Property
            </div>
            {chartProperties.map((p) => (
              <div
                key={p.id}
                className="border-b px-3 flex flex-col justify-center"
                style={{ height: ROW_HEIGHT }}
              >
                <p className="text-sm font-medium truncate">{p.name}</p>
                <p className="text-xs text-muted-foreground">
                  {p.bedrooms > 0 || p.max_guests > 0
                    ? `${p.bedrooms}BR · Sleeps ${p.max_guests}`
                    : "—"}
                </p>
              </div>
            ))}
          </div>

          {/* Scrollable chart area */}
          <div ref={scrollRef} className="overflow-x-auto flex-1">
            <div style={{ width: totalWidth, position: "relative" }}>
              {/* Date header */}
              <div className="flex border-b bg-muted/50" style={{ height: HEADER_HEIGHT }}>
                {days.map((d, i) => {
                  const isToday = d.getTime() === today.getTime();
                  const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                  return (
                    <div
                      key={i}
                      className={cn(
                        "shrink-0 flex flex-col items-center justify-center text-xs border-r",
                        isToday && "bg-primary/10 font-bold text-primary",
                        isWeekend && !isToday && "bg-muted/80",
                      )}
                      style={{ width: DAY_WIDTH }}
                    >
                      <span className="text-[10px] text-muted-foreground">
                        {d.toLocaleDateString("en-US", { weekday: "narrow" })}
                      </span>
                      <span>{d.getDate()}</span>
                    </div>
                  );
                })}
              </div>

              {/* Property rows */}
              {chartProperties.map((p) => {
                const propRes = reservationsByProperty.get(p.id) ?? [];
                return (
                  <div
                    key={p.id}
                    className="relative border-b"
                    style={{ height: ROW_HEIGHT }}
                  >
                    {/* Grid lines */}
                    {days.map((d, i) => {
                      const isToday = d.getTime() === today.getTime();
                      const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                      return (
                        <div
                          key={i}
                          className={cn(
                            "absolute top-0 bottom-0 border-r",
                            isToday && "bg-primary/5",
                            isWeekend && !isToday && "bg-muted/30",
                          )}
                          style={{ left: i * DAY_WIDTH, width: DAY_WIDTH }}
                        />
                      );
                    })}

                    {/* Reservation bars */}
                    {propRes.map((r) => {
                      const inRaw = parseLocalDate(r.check_in_date);
                      const outRaw = parseLocalDate(r.check_out_date);
                      if (!inRaw || !outRaw) return null;
                      const checkIn = startOfDay(inRaw);
                      const checkOut = startOfDay(outRaw);
                      const offsetDays = daysBetween(viewStart, checkIn);
                      const durationDays = daysBetween(checkIn, checkOut);

                      if (offsetDays + durationDays < 0 || offsetDays > daysToShow) return null;

                      const left = Math.max(offsetDays, 0) * DAY_WIDTH;
                      const clippedStart = Math.max(offsetDays, 0);
                      const clippedEnd = Math.min(offsetDays + durationDays, daysToShow);
                      const width = (clippedEnd - clippedStart) * DAY_WIDTH - 2;
                      if (width <= 0) return null;

                      const guestName = r.guest_name ?? `${r.guest?.first_name ?? ""} ${r.guest?.last_name ?? ""}`;
                      const st = normalizeReservationStatus(r.status);

                      return (
                        <button
                          key={r.id}
                          type="button"
                          className={cn(
                            "absolute top-2 bottom-2 rounded text-[11px] text-white font-medium px-1.5 truncate cursor-pointer transition-colors z-[1] flex items-center",
                            STATUS_COLORS[st] ?? "bg-blue-500/80",
                          )}
                          style={{ left: left + 1, width: Math.max(width, 20) }}
                          title={`${guestName} | ${r.check_in_date} → ${r.check_out_date}`}
                          onClick={() => onSelectReservation?.(r)}
                        >
                          {width > 60 ? guestName : guestName.split(" ")[0]?.[0] ?? ""}
                        </button>
                      );
                    })}
                  </div>
                );
              })}

              {/* Today indicator line */}
              {(() => {
                const todayOffset = daysBetween(viewStart, today);
                if (todayOffset < 0 || todayOffset >= daysToShow) return null;
                return (
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-primary z-[2] pointer-events-none"
                    style={{ left: todayOffset * DAY_WIDTH + DAY_WIDTH / 2 }}
                  />
                );
              })()}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
