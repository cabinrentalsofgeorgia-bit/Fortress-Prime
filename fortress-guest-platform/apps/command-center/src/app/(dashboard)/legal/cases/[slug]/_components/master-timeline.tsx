"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Clock, Loader2, Zap } from "lucide-react";
import { toast } from "sonner";

interface TimelineEvent {
  id: string;
  event_date: string | null;
  event_description: string;
  entities_involved: string[];
  source_ref: string;
  event_type: string;
  significance: string;
}

const SIG_STYLES: Record<string, string> = {
  critical: "border-red-500/50 bg-red-500/5",
  high: "border-amber-500/40 bg-amber-500/5",
  normal: "border-border/50 bg-background/50",
};

const SIG_DOT: Record<string, string> = {
  critical: "bg-red-500",
  high: "bg-amber-500",
  normal: "bg-muted-foreground/50",
};

const TYPE_BADGE: Record<string, string> = {
  contract: "bg-violet-500/10 text-violet-400 border-violet-500/30",
  filing: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  payment: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  correspondence: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  deadline: "bg-red-500/10 text-red-400 border-red-500/30",
  fact: "bg-muted text-muted-foreground border-border",
};

export function MasterTimeline({ slug }: { slug: string }) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);

  const fetchTimeline = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<{ events: TimelineEvent[] }>(
        `/api/legal/cases/${slug}/chronology`,
      );
      setEvents(data.events ?? []);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    void fetchTimeline();
  }, [fetchTimeline]);

  const handleBuild = async () => {
    setBuilding(true);
    toast.info("Building chronology — Sovereign is reading the evidence...");
    try {
      await api.post(`/api/legal/cases/${slug}/chronology/build`, {});
      toast.success("Chronology build queued. Refreshing in 90 seconds...");
      setTimeout(() => {
        fetchTimeline();
        setBuilding(false);
      }, 90_000);
    } catch {
      toast.error("Chronology build failed");
      setBuilding(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-1.5">
            <Clock className="h-4 w-4 text-primary" />
            Master Chronology
          </CardTitle>
          <div className="flex items-center gap-2">
            {events.length > 0 && (
              <Badge variant="outline" className="text-[10px]">
                {events.length} events
              </Badge>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={handleBuild}
              disabled={building}
              className="text-xs h-7"
            >
              {building ? (
                <>
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  Extracting...
                </>
              ) : (
                <>
                  <Zap className="h-3 w-3 mr-1" />
                  Build Timeline
                </>
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading && events.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground text-xs">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
            Loading timeline...
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground text-xs">
            No timeline events yet. Click &ldquo;Build Timeline&rdquo; to extract from evidence.
          </div>
        ) : (
          <div className="relative ml-3 space-y-0">
            <div className="absolute left-0 top-2 bottom-2 w-px bg-border" />

            {events.map((ev, i) => {
              const sig = ev.significance || "normal";
              const etype = ev.event_type || "fact";

              return (
                <div key={ev.id || i} className="relative pl-6 pb-4 last:pb-0">
                  <div
                    className={`absolute left-0 top-2.5 w-2.5 h-2.5 rounded-full -translate-x-[5px] ring-2 ring-background ${SIG_DOT[sig] ?? SIG_DOT.normal}`}
                  />

                  <div
                    className={`rounded-lg border p-2.5 ${SIG_STYLES[sig] ?? SIG_STYLES.normal}`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-bold tabular-nums text-primary">
                        {ev.event_date ?? "Unknown"}
                      </span>
                      <Badge
                        variant="outline"
                        className={`text-[9px] px-1.5 py-0 ${TYPE_BADGE[etype] ?? TYPE_BADGE.fact}`}
                      >
                        {etype}
                      </Badge>
                      {sig === "critical" && (
                        <Badge variant="destructive" className="text-[9px] px-1.5 py-0">
                          CRITICAL
                        </Badge>
                      )}
                    </div>

                    <p className="text-xs text-foreground leading-snug mb-1.5">
                      {ev.event_description}
                    </p>

                    <div className="flex flex-wrap items-center gap-1.5">
                      {ev.entities_involved?.map((ent, j) => (
                        <Badge
                          key={j}
                          variant="secondary"
                          className="text-[9px] px-1.5 py-0 font-normal"
                        >
                          {ent}
                        </Badge>
                      ))}
                      {ev.source_ref && (
                        <Badge
                          variant="outline"
                          className="text-[9px] px-1.5 py-0 font-mono text-sky-400 border-sky-500/30 bg-sky-500/5 cursor-pointer hover:bg-sky-500/10"
                          title={ev.source_ref}
                        >
                          DOC: {ev.source_ref.length > 40 ? ev.source_ref.slice(0, 37) + "..." : ev.source_ref}
                        </Badge>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
