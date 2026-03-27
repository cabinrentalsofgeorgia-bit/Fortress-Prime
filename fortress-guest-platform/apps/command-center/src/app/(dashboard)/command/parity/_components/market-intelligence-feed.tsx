"use client";

import Link from "next/link";
import { ArrowUpRight, Compass, Sparkles } from "lucide-react";

import type {
  MarketIntelligenceFeedItemResponse,
  ScoutAlphaConversionResponse,
  ScoutObserverStatusResponse,
} from "@/lib/types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function statusTone(status: string): string {
  switch (status) {
    case "succeeded":
    case "online":
    case "observing":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "failed":
    case "error":
      return "border-rose-500/30 bg-rose-500/10 text-rose-200";
    case "inactive":
    case "disabled":
      return "border-zinc-700 bg-zinc-900/80 text-zinc-300";
    default:
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
  }
}

function categoryTone(category: string): string {
  switch (category) {
    case "content_gap":
      return "border-cyan-500/30 bg-cyan-500/10 text-cyan-100";
    case "competitor_trend":
      return "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-100";
    case "market_shift":
      return "border-amber-500/30 bg-amber-500/10 text-amber-100";
    default:
      return "border-zinc-700 bg-zinc-900 text-zinc-200";
  }
}

type MarketIntelligenceFeedProps = {
  items: MarketIntelligenceFeedItemResponse[];
  observer: ScoutObserverStatusResponse;
  alpha: ScoutAlphaConversionResponse;
};

export function MarketIntelligenceFeed({ items, observer, alpha }: MarketIntelligenceFeedProps) {
  const isDisabled = !observer.enabled || !observer.agentic_system_active;

  return (
    <Card className="border-violet-500/20 bg-zinc-950/90">
      <CardHeader className="border-b border-zinc-800/80">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-zinc-50">
              <Compass className="h-5 w-5 text-violet-300" />
              Market Intelligence Feed
            </CardTitle>
            <CardDescription>
              Sovereign Alpha only. Deduplication hash suppresses repeated Scout discoveries across daily cycles.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-2">
            <span
              className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${statusTone(observer.last_job_status)}`}
            >
              {observer.enabled ? observer.last_job_status : "disabled"}
            </span>
            <span className="inline-flex rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] text-zinc-300">
              {Math.round(observer.interval_seconds / 3600)}h cadence
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 pt-6">
        <div className="grid gap-3 md:grid-cols-6">
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Queued</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.queue_depth}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Running</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.running_jobs}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Inserted</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.last_inserted_count}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Last Deduped</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.last_duplicate_count}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">SEO Drafts</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{observer.last_seo_draft_count}</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Pricing Signals</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">
              {observer.last_pricing_signal_count}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-zinc-400">
          <p>
            Last success {formatTimestamp(observer.last_success_at)}. Last unique discovery{" "}
            {formatTimestamp(observer.last_discovery_at)}.
          </p>
          <Link
            href="/api/intelligence/feed/latest"
            target="_blank"
            className="inline-flex items-center gap-1 rounded-md border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-100 hover:bg-violet-500/20"
          >
            Feed API
            <ArrowUpRight className="h-4 w-4" />
          </Link>
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          <div className="rounded-xl border border-violet-500/20 bg-violet-500/5 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Scout Patches</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{alpha.scout_patch_count}</p>
            <p className="mt-1 text-xs text-zinc-400">{alpha.scout_deployed_count} deployed</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Manual Patches</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{alpha.manual_patch_count}</p>
            <p className="mt-1 text-xs text-zinc-400">{alpha.manual_deployed_count} deployed</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Scout Intent</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">{alpha.scout_intent_event_count}</p>
            <p className="mt-1 text-xs text-zinc-400">{alpha.scout_hold_started_count} hold starts</p>
          </div>
          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Insight Impressions</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">
              {alpha.scout_insight_impression_count}
            </p>
            <p className="mt-1 text-xs text-zinc-400">Scout ribbon attribution</p>
          </div>
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-3">
            <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">Manual Intent</p>
            <p className="mt-2 text-2xl font-semibold text-zinc-100">
              {alpha.manual_intent_event_count}
            </p>
            <p className="mt-1 text-xs text-zinc-400">{alpha.manual_hold_started_count} hold starts</p>
          </div>
        </div>

        {alpha.category_breakdown.length > 0 ? (
          <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs uppercase tracking-[0.24em] text-zinc-500">
                Alpha Conversion Window
              </p>
              <span className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[10px] uppercase tracking-[0.24em] text-zinc-300">
                {alpha.window_days}d
              </span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {alpha.category_breakdown.slice(0, 4).map((bucket) => (
                <span
                  key={bucket.category}
                  className="rounded-full border border-violet-500/30 bg-violet-500/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.24em] text-violet-100"
                >
                  {bucket.category.replaceAll("_", " ")} {bucket.patch_count}
                </span>
              ))}
            </div>
          </div>
        ) : null}

        {items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/60 px-4 py-6 text-sm text-zinc-400">
            {isDisabled
              ? "Scout feed is gated until RESEARCH_SCOUT_ENABLED and AGENTIC_SYSTEM_ACTIVE are armed."
              : "No unique market intelligence findings have been written yet."}
          </div>
        ) : (
          items.map((item) => (
            <article
              key={item.id}
              className="rounded-xl border border-zinc-800 bg-zinc-900/70 px-4 py-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-zinc-100">{item.title}</p>
                  <p className="mt-1 text-xs text-zinc-500">
                    {item.locality || item.market} • {formatTimestamp(item.discovered_at)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <span
                    className={`inline-flex rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] ${categoryTone(item.category)}`}
                  >
                    {item.category.replaceAll("_", " ")}
                  </span>
                  {item.confidence_score != null ? (
                    <span className="inline-flex rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.24em] text-zinc-300">
                      {(item.confidence_score * 100).toFixed(0)}% confidence
                    </span>
                  ) : null}
                </div>
              </div>
              <p className="mt-3 text-sm text-zinc-300">{item.summary}</p>
              <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                {item.query_topic ? (
                  <span className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 uppercase tracking-[0.24em]">
                    {item.query_topic.replaceAll("_", " ")}
                  </span>
                ) : null}
                <span className="inline-flex items-center gap-1">
                  <Sparkles className="h-3.5 w-3.5" />
                  dedupe hash armed
                </span>
                {item.seo_patch_ids.length > 0 ? (
                  <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 uppercase tracking-[0.24em] text-emerald-100">
                    {item.seo_patch_ids.length} hunter draft
                    {item.seo_patch_ids.length === 1 ? "" : "s"}
                  </span>
                ) : null}
                {item.pricing_signal_ids.length > 0 ? (
                  <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 uppercase tracking-[0.24em] text-amber-100">
                    {item.pricing_signal_ids.length} treasurer signal
                    {item.pricing_signal_ids.length === 1 ? "" : "s"}
                  </span>
                ) : null}
              </div>
              {item.target_tags.length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {item.target_tags.map((tag) => (
                    <span
                      key={`${item.id}-${tag}`}
                      className="rounded-full border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-[10px] uppercase tracking-[0.24em] text-zinc-300"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              ) : null}
              {item.targeted_properties.length > 0 ? (
                <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-950/80 px-3 py-3">
                  <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-500">
                    Targeted Cabins
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {item.targeted_properties.map((property) => (
                      <span
                        key={property.id}
                        className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-[10px] uppercase tracking-[0.24em] text-cyan-100"
                      >
                        {property.slug}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
              {item.source_urls.length > 0 ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {item.source_urls.slice(0, 3).map((url) => (
                    <Link
                      key={`${item.id}-${url}`}
                      href={url}
                      target="_blank"
                      className="inline-flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-100 hover:bg-sky-500/20"
                    >
                      Source
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                  ))}
                </div>
              ) : null}
            </article>
          ))
        )}
      </CardContent>
    </Card>
  );
}
