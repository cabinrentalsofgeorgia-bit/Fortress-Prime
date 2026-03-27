"use client";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTemplateLibrary } from "@/lib/hooks";
import { Mail, ShieldCheck, Clock } from "lucide-react";

const TRIGGER_LABELS: Record<string, { label: string; color: string }> = {
  inquiry_received: { label: "Inquiry", color: "bg-blue-500/15 text-blue-400 border-blue-500/20" },
  cart_abandoned_2h: { label: "Cart Abandoned", color: "bg-red-500/15 text-red-400 border-red-500/20" },
  "7_days_before_checkin": { label: "7 Days Pre-Arrival", color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20" },
  "3_days_before_checkin": { label: "3 Days Pre-Arrival", color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20" },
  "1_day_before_checkin": { label: "1 Day Pre-Arrival", color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/20" },
  "2_days_into_stay": { label: "Mid-Stay", color: "bg-amber-500/15 text-amber-400 border-amber-500/20" },
  "1_day_after_checkout": { label: "Post-Checkout", color: "bg-violet-500/15 text-violet-400 border-violet-500/20" },
  "11_months_after_checkout": { label: "Win-Back", color: "bg-pink-500/15 text-pink-400 border-pink-500/20" },
  manual: { label: "Manual", color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/20" },
};

function triggerBadge(event: string) {
  const entry = TRIGGER_LABELS[event] ?? {
    label: event.replace(/_/g, " "),
    color: "bg-zinc-500/15 text-zinc-400 border-zinc-500/20",
  };
  return (
    <Badge variant="outline" className={`text-[10px] font-medium ${entry.color}`}>
      <Clock className="mr-1 h-3 w-3" />
      {entry.label}
    </Badge>
  );
}

export function TemplateGrid() {
  const { data: templates = [], isLoading } = useTemplateLibrary();

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="pb-3">
              <div className="h-5 w-3/4 rounded bg-muted" />
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="h-4 w-full rounded bg-muted" />
                <div className="h-4 w-2/3 rounded bg-muted" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (templates.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
          <Mail className="h-10 w-10 mb-3 opacity-40" />
          <p className="text-sm">No templates found. Seed your template library to get started.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {templates.map((tpl) => (
        <Card key={tpl.id} className="group relative overflow-hidden transition-colors hover:border-primary/30">
          <CardHeader className="pb-3">
            <div className="flex items-start justify-between gap-2">
              <CardTitle className="text-sm font-semibold leading-snug">
                {tpl.name}
              </CardTitle>
              {!tpl.is_active && (
                <Badge variant="secondary" className="text-[10px] shrink-0">
                  Inactive
                </Badge>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {triggerBadge(tpl.trigger_event)}
              {tpl.requires_human_approval && (
                <Badge variant="outline" className="text-[10px] font-medium bg-amber-500/15 text-amber-400 border-amber-500/20">
                  <ShieldCheck className="mr-1 h-3 w-3" />
                  Copilot
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground line-clamp-2">
              {tpl.subject_template}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
