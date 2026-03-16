"use client";

import { useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
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

export function TapeChart({ properties, reservations, onSelectReservation }: TapeChartProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewStart, setViewStart] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    return startOfDay(d);
  });

  const daysToShow = 30;
  const viewEnd = useMemo(() => {
    const d = new Date(viewStart);
    d.setDate(d.getDate() + daysToShow);
    return d;
  }, [viewStart]);

  const today = startOfDay(new Date());

  const days = useMemo(() => {
    const arr: Date[] = [];
    for (let i = 0; i < daysToShow; i++) {
      const d = new Date(viewStart);
      d.setDate(d.getDate() + i);
      arr.push(d);
    }
    return arr;
  }, [viewStart]);

  const reservationsByProperty = useMemo(() => {
    const map = new Map<string, Reservation[]>();
    for (const r of reservations) {
      if (r.status === "cancelled") continue;
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
          <span className="text-sm text-muted-foreground ml-2">
            {viewStart.toLocaleDateString("en-US", { month: "short", year: "numeric" })}
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
            {properties.map((p) => (
              <div
                key={p.id}
                className="border-b px-3 flex flex-col justify-center"
                style={{ height: ROW_HEIGHT }}
              >
                <p className="text-sm font-medium truncate">{p.name}</p>
                <p className="text-xs text-muted-foreground">
                  {p.bedrooms}BR · Sleeps {p.max_guests}
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
              {properties.map((p) => {
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
                      const checkIn = startOfDay(new Date(r.check_in_date));
                      const checkOut = startOfDay(new Date(r.check_out_date));
                      const offsetDays = daysBetween(viewStart, checkIn);
                      const durationDays = daysBetween(checkIn, checkOut);

                      if (offsetDays + durationDays < 0 || offsetDays > daysToShow) return null;

                      const left = Math.max(offsetDays, 0) * DAY_WIDTH;
                      const clippedStart = Math.max(offsetDays, 0);
                      const clippedEnd = Math.min(offsetDays + durationDays, daysToShow);
                      const width = (clippedEnd - clippedStart) * DAY_WIDTH - 2;
                      if (width <= 0) return null;

                      const guestName = r.guest_name ?? `${r.guest?.first_name ?? ""} ${r.guest?.last_name ?? ""}`;

                      return (
                        <button
                          key={r.id}
                          className={cn(
                            "absolute top-2 bottom-2 rounded text-[11px] text-white font-medium px-1.5 truncate cursor-pointer transition-colors z-[1] flex items-center",
                            STATUS_COLORS[r.status] ?? "bg-blue-500/80",
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
