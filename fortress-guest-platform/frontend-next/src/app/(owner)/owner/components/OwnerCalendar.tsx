"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  TrendingDown,
  Trash2,
  Lock,
} from "lucide-react";
import {
  useOwnerCalendar,
  useCalculateYieldLoss,
  useCreateOwnerBlock,
  useDeleteOwnerBlock,
} from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const DAY_W = 44;
const ROW_H = 120;
const HEADER_H = 48;

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function toISO(d: Date) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

function fmt(n: number | null | undefined): string {
  if (n == null) return "–";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

interface Props {
  propertyId: string;
}

export function OwnerCalendar({ propertyId }: Props) {
  const [viewStart, setViewStart] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    return startOfDay(d);
  });
  const [selectStart, setSelectStart] = useState<string | null>(null);
  const [selectEnd, setSelectEnd] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const daysToShow = 30;
  const viewEndStr = useMemo(() => {
    const d = new Date(viewStart);
    d.setDate(d.getDate() + daysToShow);
    return toISO(d);
  }, [viewStart]);

  const { data: calendar, isLoading } = useOwnerCalendar(propertyId);
  const yieldLoss = useCalculateYieldLoss(propertyId);
  const createBlock = useCreateOwnerBlock(propertyId);
  const deleteBlock = useDeleteOwnerBlock(propertyId);

  const today = startOfDay(new Date());
  const todayISO = toISO(today);

  const days = useMemo(() => {
    const arr: Date[] = [];
    for (let i = 0; i < daysToShow; i++) {
      const d = new Date(viewStart);
      d.setDate(d.getDate() + i);
      arr.push(d);
    }
    return arr;
  }, [viewStart]);

  function scrollDays(n: number) {
    setViewStart((prev) => {
      const d = new Date(prev);
      d.setDate(d.getDate() + n);
      return d;
    });
  }

  function goToday() {
    const d = new Date();
    d.setDate(d.getDate() - 3);
    setViewStart(startOfDay(d));
  }

  function handleDayClick(iso: string) {
    const dayInfo = calendar?.days?.[iso];
    if (!dayInfo) return;

    if (dayInfo.status === "blocked" && dayInfo.block_type === "owner_hold" && dayInfo.block_id) {
      deleteBlock.mutate(dayInfo.block_id);
      return;
    }

    if (dayInfo.status !== "available") return;

    if (!selectStart || (selectStart && selectEnd)) {
      setSelectStart(iso);
      setSelectEnd(null);
    } else if (selectStart && !selectEnd) {
      if (iso < selectStart) {
        setSelectStart(iso);
      } else {
        setSelectEnd(iso);
        const endPlusOne = new Date(iso);
        endPlusOne.setDate(endPlusOne.getDate() + 1);
        yieldLoss.mutate(
          { start_date: selectStart, end_date: toISO(endPlusOne) },
          { onSuccess: () => setIsModalOpen(true) }
        );
      }
    }
  }

  function confirmBlock() {
    if (!selectStart || !selectEnd) return;
    const endPlusOne = new Date(selectEnd);
    endPlusOne.setDate(endPlusOne.getDate() + 1);
    createBlock.mutate(
      { start_date: selectStart, end_date: toISO(endPlusOne), reason: "owner_stay" },
      {
        onSuccess: () => {
          setIsModalOpen(false);
          setSelectStart(null);
          setSelectEnd(null);
        },
      }
    );
  }

  function cancelBlock() {
    setIsModalOpen(false);
    setSelectStart(null);
    setSelectEnd(null);
  }

  const isInSelection = (iso: string) => {
    if (!selectStart) return false;
    if (selectEnd) return iso >= selectStart && iso <= selectEnd;
    return iso === selectStart;
  };

  const totalWidth = daysToShow * DAY_W;

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => scrollDays(-7)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={goToday}>
            Today
          </Button>
          <Button variant="outline" size="sm" onClick={() => scrollDays(7)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground ml-2">
            {viewStart.toLocaleDateString("en-US", { month: "long", year: "numeric" })}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-blue-500/80" /> Reservation
          </span>
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-amber-500/80" /> Owner Hold
          </span>
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-emerald-500/20 border border-emerald-500/30" />{" "}
            Available
          </span>
          <span className="flex items-center gap-1">
            <span className="h-3 w-3 rounded bg-red-500/20 border border-red-500/30" /> Peak
          </span>
        </div>
      </div>

      {selectStart && !selectEnd && (
        <div className="text-sm text-muted-foreground flex items-center gap-2 px-1">
          <CalendarDays className="h-4 w-4" />
          Selection started: {selectStart}. Click an end date to complete.
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          Loading calendar...
        </div>
      ) : (
        <div className="rounded-lg border overflow-hidden">
          <div className="overflow-x-auto">
            <div style={{ width: totalWidth, position: "relative" }}>
              {/* Date header */}
              <div className="flex border-b bg-muted/50" style={{ height: HEADER_H }}>
                {days.map((d, i) => {
                  const iso = toISO(d);
                  const isToday = iso === todayISO;
                  const isWeekend = d.getDay() === 0 || d.getDay() === 6;
                  return (
                    <div
                      key={i}
                      className={cn(
                        "shrink-0 flex flex-col items-center justify-center text-xs border-r",
                        isToday && "bg-primary/10 font-bold text-primary",
                        isWeekend && !isToday && "bg-muted/80"
                      )}
                      style={{ width: DAY_W }}
                    >
                      <span className="text-[10px] text-muted-foreground">
                        {d.toLocaleDateString("en-US", { weekday: "narrow" })}
                      </span>
                      <span>{d.getDate()}</span>
                    </div>
                  );
                })}
              </div>

              {/* Calendar row */}
              <TooltipProvider delayDuration={200}>
                <div className="flex" style={{ height: ROW_H }}>
                  {days.map((d, i) => {
                    const iso = toISO(d);
                    const isToday = iso === todayISO;
                    const dayInfo = calendar?.days?.[iso];
                    const status = dayInfo?.status ?? "available";
                    const rate = dayInfo?.nightly_rate ?? 0;
                    const isPeak = dayInfo?.is_peak ?? false;
                    const selected = isInSelection(iso);

                    let bgClass = "";
                    let cursor = "cursor-default";

                    if (status === "booked") {
                      bgClass = "bg-blue-500/15";
                    } else if (status === "blocked") {
                      bgClass = "bg-amber-500/15";
                      if (dayInfo?.block_type === "owner_hold") cursor = "cursor-pointer";
                    } else {
                      bgClass = isPeak ? "bg-red-500/5" : "bg-emerald-500/5";
                      cursor = "cursor-pointer";
                    }

                    if (selected) bgClass = "bg-primary/20 ring-1 ring-primary/50";

                    return (
                      <Tooltip key={i}>
                        <TooltipTrigger asChild>
                          <div
                            className={cn(
                              "shrink-0 border-r flex flex-col items-center justify-between py-2 transition-colors",
                              bgClass,
                              cursor,
                              isToday && "ring-1 ring-primary/30"
                            )}
                            style={{ width: DAY_W }}
                            onClick={() => handleDayClick(iso)}
                          >
                            {status === "booked" && (
                              <Badge
                                variant="default"
                                className="text-[8px] px-1 py-0 bg-blue-500"
                              >
                                RSV
                              </Badge>
                            )}
                            {status === "blocked" && (
                              <div className="flex flex-col items-center gap-0.5">
                                <Lock className="h-3 w-3 text-amber-500" />
                                <Badge
                                  variant="secondary"
                                  className="text-[8px] px-1 py-0 bg-amber-500/20 text-amber-400"
                                >
                                  HOLD
                                </Badge>
                              </div>
                            )}
                            {status === "available" && (
                              <div className="h-4" />
                            )}

                            <div className="flex flex-col items-center gap-0.5 mt-auto">
                              {rate > 0 && (
                                <span
                                  className={cn(
                                    "text-[9px] font-mono",
                                    status === "available"
                                      ? "text-emerald-500"
                                      : "text-muted-foreground"
                                  )}
                                >
                                  ${Math.round(rate)}
                                </span>
                              )}
                              {isPeak && (
                                <span className="text-[8px] text-red-400 font-semibold">
                                  PEAK
                                </span>
                              )}
                            </div>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent side="bottom" className="text-xs">
                          <div className="space-y-1">
                            <div className="font-semibold">{iso}</div>
                            <div>Status: {status}</div>
                            {rate > 0 && <div>Rate: ${fmt(rate)}/night</div>}
                            {status === "booked" && dayInfo?.confirmation_code && (
                              <div>Reservation: {dayInfo.confirmation_code}</div>
                            )}
                            {status === "blocked" &&
                              dayInfo?.block_type === "owner_hold" && (
                                <div className="text-amber-400">Click to remove hold</div>
                              )}
                            {status === "available" && (
                              <div className="text-emerald-400">Click to select for owner hold</div>
                            )}
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })}
                </div>
              </TooltipProvider>

              {/* Today indicator */}
              {(() => {
                const todayIdx = days.findIndex((d) => toISO(d) === todayISO);
                if (todayIdx < 0) return null;
                return (
                  <div
                    className="absolute top-0 bottom-0 w-0.5 bg-primary z-[2] pointer-events-none"
                    style={{ left: todayIdx * DAY_W + DAY_W / 2 }}
                  />
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Active Owner Holds Summary */}
      {calendar?.blocks && calendar.blocks.filter((b) => b.block_type === "owner_hold").length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-muted-foreground">Active Owner Holds</h4>
          <div className="flex flex-wrap gap-2">
            {calendar.blocks
              .filter((b) => b.block_type === "owner_hold")
              .map((b) => (
                <div
                  key={b.id}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 text-sm"
                >
                  <Lock className="h-3.5 w-3.5 text-amber-500" />
                  <span>
                    {b.start_date} — {b.end_date}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                    onClick={() => deleteBlock.mutate(b.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* YIELD LOSS INTERCEPT DIALOG */}
      <Dialog open={isModalOpen} onOpenChange={(open) => !open && cancelBlock()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Yield Loss Warning
            </DialogTitle>
            <DialogDescription>
              You are requesting to block high-demand inventory.
            </DialogDescription>
          </DialogHeader>

          {yieldLoss.data && (
            <div className="space-y-4 py-2">
              <div className="p-4 rounded-lg border border-destructive/30 bg-destructive/5 space-y-3">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Blocked Nights:</span>
                  <span className="font-mono font-semibold">
                    {yieldLoss.data.requested_nights}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Projected ADR:</span>
                  <span className="font-mono">${fmt(yieldLoss.data.projected_adr)}/night</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Gross Revenue Loss:</span>
                  <span className="font-mono">${fmt(yieldLoss.data.gross_revenue_loss)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Cleaning Fee:</span>
                  <span className="font-mono">${fmt(yieldLoss.data.cleaning_fee)}</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">Est. Taxes:</span>
                  <span className="font-mono">${fmt(yieldLoss.data.tax_estimate)}</span>
                </div>
                <div className="border-t pt-3 flex items-center justify-between">
                  <span className="text-sm font-semibold text-destructive">
                    Total Revenue Loss:
                  </span>
                  <span className="font-mono font-bold text-destructive text-lg flex items-center gap-1">
                    <TrendingDown className="h-4 w-4" />$
                    {fmt(yieldLoss.data.total_estimated_loss)}
                  </span>
                </div>
              </div>

              {yieldLoss.data.demand_alert && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-sm text-red-400">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  {yieldLoss.data.peak_nights} of {yieldLoss.data.requested_nights} nights
                  are in peak season demand.
                </div>
              )}

              <p className="text-xs text-muted-foreground text-center">
                {yieldLoss.data.warning_message}
              </p>
            </div>
          )}

          {yieldLoss.isPending && (
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              Analyzing market pacing...
            </div>
          )}

          <DialogFooter className="sm:justify-between gap-2">
            <Button variant="ghost" onClick={cancelBlock}>
              Cancel Block
            </Button>
            <Button
              variant="destructive"
              onClick={confirmBlock}
              disabled={createBlock.isPending}
            >
              {createBlock.isPending ? "Processing..." : "Confirm Owner Stay"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
