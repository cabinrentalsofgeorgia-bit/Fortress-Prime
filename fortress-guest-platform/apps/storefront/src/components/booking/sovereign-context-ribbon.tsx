"use client";

import Link from "next/link";
import { useEffect, useMemo } from "react";
import { ArrowUpRight, Compass, Sparkles } from "lucide-react";

import type { ContextualIntelligenceInsightResponse } from "@/lib/types";
import { postStorefrontIntentEvent } from "@/lib/storefront-intent";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type SovereignContextRibbonProps = {
  propertySlug: string;
  propertyName: string;
  items: ContextualIntelligenceInsightResponse[];
};

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(parsed);
}

function categoryTone(category: string): string {
  switch (category) {
    case "content_gap":
      return "border-cyan-200 bg-cyan-50 text-cyan-900";
    case "competitor_trend":
      return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-900";
    case "market_shift":
      return "border-amber-200 bg-amber-50 text-amber-900";
    default:
      return "border-slate-200 bg-slate-100 text-slate-800";
  }
}

export function SovereignContextRibbon({
  propertySlug,
  propertyName,
  items,
}: SovereignContextRibbonProps) {
  const impressionKey = useMemo(() => {
    if (items.length === 0) {
      return null;
    }
    const ids = items.map((item) => item.id).sort().join(",");
    return `insight_impression:${propertySlug}:${ids}`;
  }, [items, propertySlug]);

  useEffect(() => {
    if (!impressionKey || items.length === 0) {
      return;
    }
    void postStorefrontIntentEvent({
      eventType: "insight_impression",
      propertySlug,
      dedupeKey: impressionKey,
      meta: {
        ribbon_surface: "sovereign_context_ribbon",
        property_name: propertyName,
        insight_count: items.length,
        intelligence_ids: items.map((item) => item.id).join(","),
      },
    });
  }, [impressionKey, items, propertyName, propertySlug]);

  if (items.length === 0) {
    return null;
  }

  return (
    <section className="rounded-[2rem] border border-violet-200 bg-gradient-to-br from-violet-50 via-white to-cyan-50 p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-violet-200 bg-white/90 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-violet-700">
            <Compass className="h-3.5 w-3.5" />
            Local Insights
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
              Live market signals around {propertyName}
            </h2>
            <p className="max-w-3xl text-sm leading-7 text-slate-600">
              Scout findings targeted to this cabin, grounded in live local discovery instead of
              stale OTA copy.
            </p>
          </div>
        </div>
        <Badge
          variant="outline"
          className="border-violet-200 bg-white/90 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-violet-700"
        >
          <Sparkles className="h-3.5 w-3.5" />
          {items.length} active signal{items.length === 1 ? "" : "s"}
        </Badge>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        {items.map((item) => (
          <article
            key={item.id}
            className="rounded-[1.5rem] border border-white/80 bg-white/95 p-5 shadow-[0_10px_30px_rgba(15,23,42,0.06)]"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <Badge
                variant="outline"
                className={cn(
                  "px-2.5 py-1 text-[10px] uppercase tracking-[0.24em]",
                  categoryTone(item.category),
                )}
              >
                {item.category.replaceAll("_", " ")}
              </Badge>
              <span className="text-xs uppercase tracking-[0.2em] text-slate-500">
                {formatTimestamp(item.discovered_at)} UTC
              </span>
            </div>

            <h3 className="mt-4 text-lg font-semibold tracking-tight text-slate-900">
              {item.title}
            </h3>
            <p className="mt-2 text-sm leading-7 text-slate-600">{item.summary}</p>

            <div className="mt-4 flex flex-wrap gap-2">
              {item.target_tags.slice(0, 3).map((tag) => (
                <Badge
                  key={`${item.id}-${tag}`}
                  variant="outline"
                  className="border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-slate-700"
                >
                  {tag.replaceAll("-", " ")}
                </Badge>
              ))}
              {item.confidence_score != null ? (
                <Badge
                  variant="outline"
                  className="border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] uppercase tracking-[0.2em] text-emerald-800"
                >
                  {(item.confidence_score * 100).toFixed(0)}% confidence
                </Badge>
              ) : null}
            </div>

            {item.source_urls.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {item.source_urls.slice(0, 2).map((url) => (
                  <Link
                    key={`${item.id}-${url}`}
                    href={url}
                    target="_blank"
                    className="inline-flex items-center gap-1 rounded-full border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-900 transition-colors hover:bg-sky-100"
                  >
                    Source
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Link>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
