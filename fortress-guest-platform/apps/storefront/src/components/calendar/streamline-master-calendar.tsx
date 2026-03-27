"use client";

import { ChevronLeft, ChevronRight, Lock, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { StreamlineMasterCalendarResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY_WIDTH = 56;

function formatMonthLabel(isoDate: string) {
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

function formatMoney(amount: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

function isWithinSelection(day: string, start?: string, end?: string) {
  if (!start) {
    return false;
  }
  if (!end) {
    return day === start;
  }
  return day >= start && day <= end;
}

interface StreamlineMasterCalendarProps {
  calendar: StreamlineMasterCalendarResponse | undefined;
  isLoading: boolean;
  selectedStart?: string;
  selectedEnd?: string;
  onSelectDay: (isoDate: string) => void;
  onPreviousWindow: () => void;
  onNextWindow: () => void;
  onJumpToToday: () => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}

export function StreamlineMasterCalendar({
  calendar,
  isLoading,
  selectedStart,
  selectedEnd,
  onSelectDay,
  onPreviousWindow,
  onNextWindow,
  onJumpToToday,
  onRefresh,
  isRefreshing,
}: StreamlineMasterCalendarProps) {
  const dayEntries = Object.entries(calendar?.days ?? {});
  const totalWidth = Math.max(dayEntries.length * DAY_WIDTH, 720);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="text-lg font-semibold tracking-tight">Master Calendar</h3>
          <p className="text-sm text-muted-foreground">
            Live Streamline availability and nightly pricing, cached server-side in Redis.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={onPreviousWindow}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={onJumpToToday}>
            Today
          </Button>
          <Button variant="outline" size="sm" onClick={onNextWindow}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={isRefreshing}>
            <RefreshCw className={cn("h-4 w-4", isRefreshing && "animate-spin")} />
            Refresh Cache
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <span className="h-3 w-3 rounded border border-emerald-500/40 bg-emerald-500/15" />
          Available
        </span>
        <span className="flex items-center gap-2">
          <span className="h-3 w-3 rounded border border-sky-500/40 bg-sky-500/15" />
          Booked
        </span>
        <span className="flex items-center gap-2">
          <span className="h-3 w-3 rounded border border-amber-500/40 bg-amber-500/15" />
          Blocked
        </span>
        <span className="flex items-center gap-2">
          <span className="h-3 w-3 rounded border border-primary/60 bg-primary/20" />
          Selected
        </span>
      </div>

      {calendar ? (
        <div className="rounded-xl border">
          <div className="border-b px-4 py-3">
            <div className="flex flex-col gap-1 md:flex-row md:items-center md:justify-between">
              <div>
                <p className="font-medium">{calendar.property_name}</p>
                <p className="text-sm text-muted-foreground">
                  {formatMonthLabel(calendar.start_date)} window · Avg nightly{" "}
                  {formatMoney(calendar.summary.average_nightly_rate)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <Badge variant="outline">Available {calendar.summary.available_days}</Badge>
                <Badge variant="outline">Booked {calendar.summary.booked_days}</Badge>
                <Badge variant="outline">Blocked {calendar.summary.blocked_days}</Badge>
              </div>
            </div>
          </div>

          {isLoading ? (
            <div className="flex min-h-56 items-center justify-center text-sm text-muted-foreground">
              Loading live Streamline calendar...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <div style={{ width: totalWidth }}>
                <div className="flex border-b bg-muted/40">
                  {dayEntries.map(([isoDate]) => {
                    const jsDate = new Date(`${isoDate}T00:00:00`);
                    const isToday = isoDate === new Date().toISOString().slice(0, 10);
                    return (
                      <div
                        key={isoDate}
                        className={cn(
                          "flex shrink-0 flex-col items-center justify-center border-r py-2 text-xs",
                          isToday && "bg-primary/10 text-primary",
                        )}
                        style={{ width: DAY_WIDTH }}
                      >
                        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
                          {jsDate.toLocaleDateString("en-US", { weekday: "short" })}
                        </span>
                        <span className="font-medium">{jsDate.getDate()}</span>
                      </div>
                    );
                  })}
                </div>

                <TooltipProvider delayDuration={150}>
                  <div className="flex">
                    {dayEntries.map(([isoDate, day]) => {
                      const selected = isWithinSelection(isoDate, selectedStart, selectedEnd);
                      const canSelect = day.status === "available";
                      const stateClass =
                        day.status === "booked"
                          ? "bg-sky-500/15"
                          : day.status === "blocked"
                            ? "bg-amber-500/15"
                            : "bg-emerald-500/10";

                      return (
                        <Tooltip key={isoDate}>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              className={cn(
                                "flex h-24 shrink-0 flex-col items-center justify-between border-r px-1 py-2 text-center transition-colors",
                                stateClass,
                                canSelect && "cursor-pointer hover:bg-primary/10",
                                !canSelect && "cursor-default",
                                selected && "bg-primary/20 ring-1 ring-inset ring-primary/60",
                              )}
                              style={{ width: DAY_WIDTH }}
                              onClick={() => canSelect && onSelectDay(isoDate)}
                            >
                              {day.status === "blocked" ? (
                                <Lock className="mt-1 h-3.5 w-3.5 text-amber-500" />
                              ) : day.status === "booked" ? (
                                <Badge className="mt-0.5 bg-sky-600 text-[10px]">RSV</Badge>
                              ) : (
                                <span className="h-4" />
                              )}

                              <div className="mt-auto space-y-0.5">
                                <p
                                  className={cn(
                                    "text-[10px] font-medium",
                                    day.status === "available"
                                      ? "text-emerald-700 dark:text-emerald-300"
                                      : "text-muted-foreground",
                                  )}
                                >
                                  {formatMoney(day.nightly_rate)}
                                </p>
                                {day.is_peak ? (
                                  <p className="text-[9px] font-semibold uppercase tracking-wider text-red-400">
                                    Peak
                                  </p>
                                ) : (
                                  <span className="block h-[10px]" />
                                )}
                              </div>
                            </button>
                          </TooltipTrigger>
                          <TooltipContent side="bottom" className="max-w-52 text-xs">
                            <div className="space-y-1">
                              <p className="font-semibold">{isoDate}</p>
                              <p>Status: {day.status}</p>
                              <p>Nightly: {formatMoney(day.nightly_rate)}</p>
                              {day.block_type ? <p>Block Type: {day.block_type}</p> : null}
                              {day.confirmation_id ? (
                                <p>Confirmation: {day.confirmation_id}</p>
                              ) : null}
                              <p>Pricing Source: {day.pricing_source ?? "streamline_live"}</p>
                              {canSelect ? (
                                <p className="text-emerald-400">Click to anchor quote dates.</p>
                              ) : null}
                            </div>
                          </TooltipContent>
                        </Tooltip>
                      );
                    })}
                  </div>
                </TooltipProvider>
              </div>
            </div>
          )}
        </div>
      ) : isLoading ? (
        <div className="rounded-xl border p-10 text-sm text-muted-foreground">
          Loading live Streamline calendar...
        </div>
      ) : (
        <div className="rounded-xl border border-dashed p-10 text-sm text-muted-foreground">
          Select a property to pull its live Streamline calendar.
        </div>
      )}
    </div>
  );
}
