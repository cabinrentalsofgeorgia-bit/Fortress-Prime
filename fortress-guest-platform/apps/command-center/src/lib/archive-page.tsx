import type { Metadata } from "next";
import Link from "next/link";
import Script from "next/script";

import {
  loadArchiveRecord,
  type SovereignArchiveRecord,
} from "@/lib/archive-records";
import { buildBackendUrl } from "@/lib/server/backend-url";

type ArchivePageLoadResult = {
  record: SovereignArchiveRecord | null;
  recoveryStatus: "local_cache" | "cache_hit" | "restored" | "soft_landed" | "unavailable";
};

type UnifiedLiveSeoPayload = {
  property_slug: string;
  property_name: string;
  page_path: string;
  payload: {
    title?: string;
    meta_description?: string;
    og_title?: string;
    og_description?: string;
    h1?: string;
    h1_suggestion?: string;
    intro?: string;
    faq?: Array<{ q?: string; a?: string }>;
    jsonld?: Record<string, unknown>;
    json_ld?: Record<string, unknown>;
    canonical_url?: string;
    alt_tags?: Record<string, string>;
  };
  deployed_at: string | null;
  godhead_score: number | null;
};

type LegacyArchiveType = "review" | "page" | "blog_post";

type ArchiveMetadataOptions = {
  slug: string;
  canonicalPath: string;
};

type ArchivePageOptions = {
  slug: string;
  canonicalPath: string;
  pathLabel: string;
  pathValue: string;
};

const SEO_REVALIDATE_SECONDS = 300;

export function sanitizeArchiveText(rawHtml: string): string {
  const withoutTags = rawHtml
    .replace(/<[^>]*>?/gm, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">");

  return withoutTags.replace(/\s+/g, " ").trim();
}

function resolveLegacyType(record: SovereignArchiveRecord): LegacyArchiveType {
  const legacyType = record.legacy_type?.trim().toLowerCase();
  if (legacyType === "review" || legacyType === "testimonial") return "review";
  if (legacyType === "article" || legacyType === "blog" || legacyType === "blog_post") return "blog_post";

  const nodeType = record.node_type?.trim().toLowerCase();
  if (nodeType === "testimonial" || nodeType === "review") return "review";
  if (nodeType === "article" || nodeType === "blog" || nodeType === "blog_post" || nodeType === "news") {
    return "blog_post";
  }
  return "page";
}

function buildDescription(body: string, title: string | undefined, legacyType: LegacyArchiveType): string {
  const fallback = legacyType === "review"
    ? "Verified historical guest review from the Cabin Rentals of Georgia archive."
    : legacyType === "blog_post"
      ? "Archived historical article recovered from the legacy Drupal estate."
      : "Archived historical page recovered from the legacy Drupal estate.";
  const cleanText = sanitizeArchiveText(body) || title?.trim() || fallback;
  return cleanText.length > 155 ? `${cleanText.substring(0, 155)}...` : cleanText;
}

function buildTitle(title: string | undefined, legacyType: LegacyArchiveType): string {
  if (title?.trim()) return title.trim();
  if (legacyType === "review") return "Archived Guest Review";
  if (legacyType === "blog_post") return "Archived Blog Post";
  return "Archived Legacy Page";
}

function buildMetadataSuffix(legacyType: LegacyArchiveType): string {
  if (legacyType === "review") return "Archived Reviews";
  if (legacyType === "blog_post") return "Archived Articles";
  return "Archived Pages";
}

function buildUnavailableTitle(recoveryStatus: ArchivePageLoadResult["recoveryStatus"]): string {
  return recoveryStatus === "soft_landed"
    ? "Historical Archive Unavailable"
    : "Historical Archive Recovery Pending";
}

function toIsoFromUnix(timestamp?: number): string | undefined {
  if (!timestamp || Number.isNaN(timestamp)) return undefined;
  return new Date(timestamp * 1000).toISOString();
}

function formatLegacyTimestamp(timestamp?: number): string | null {
  if (!timestamp || Number.isNaN(timestamp)) return null;
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "long",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(timestamp * 1000));
}

function buildDefaultJsonLd(
  record: SovereignArchiveRecord,
  legacyType: LegacyArchiveType,
  canonical: string,
  title: string,
  description: string,
): Record<string, unknown> {
  if (legacyType === "review") {
    return {
      "@context": "https://schema.org",
      "@type": "Review",
      name: title,
      url: canonical,
      reviewBody: sanitizeArchiveText(record.content_body) || description,
      itemReviewed: {
        "@type": "VacationRental",
        name: record.related_property_title?.trim() || "Cabin Rentals of Georgia",
      },
    };
  }

  if (legacyType === "blog_post") {
    const payload: Record<string, unknown> = {
      "@context": "https://schema.org",
      "@type": "BlogPosting",
      headline: title,
      description,
      url: canonical,
    };
    const published = toIsoFromUnix(record.legacy_created_at);
    const updated = toIsoFromUnix(record.legacy_updated_at);
    if (published) payload.datePublished = published;
    if (updated) payload.dateModified = updated;
    if (record.legacy_author_id?.trim()) {
      payload.author = {
        "@type": "Person",
        name: `Legacy Author ${record.legacy_author_id.trim()}`,
      };
    }
    return payload;
  }

  return {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: title,
    description,
    url: canonical,
  };
}

function normalizeArchiveJsonLd(
  record: SovereignArchiveRecord,
  legacyType: LegacyArchiveType,
  canonical: string,
  title: string,
  description: string,
  seoJsonLd?: Record<string, unknown>,
): Record<string, unknown> {
  if (!seoJsonLd || Object.keys(seoJsonLd).length === 0) {
    return buildDefaultJsonLd(record, legacyType, canonical, title, description);
  }

  if (legacyType !== "review") {
    return {
      "@context": "https://schema.org",
      url: canonical,
      ...seoJsonLd,
    };
  }

  const normalized = { ...seoJsonLd };
  const reviewBody = sanitizeArchiveText(record.content_body) || description;
  const reviewedName = record.related_property_title?.trim() || "Cabin Rentals of Georgia";
  const rawItemReviewed = normalized.itemReviewed;
  const reviewedObject = (
    rawItemReviewed &&
    typeof rawItemReviewed === "object" &&
    !Array.isArray(rawItemReviewed)
  )
    ? (rawItemReviewed as Record<string, unknown>)
    : null;
  const itemReviewed = reviewedObject
    ? {
        ...reviewedObject,
        "@type": "VacationRental",
        name: typeof reviewedObject.name === "string" && reviewedObject.name.trim()
          ? reviewedObject.name.trim()
          : reviewedName,
      }
    : {
        "@type": "VacationRental",
        name: reviewedName,
      };

  return {
    "@context": "https://schema.org",
    "@type": "Review",
    url: canonical,
    name: typeof normalized.name === "string" && normalized.name.trim() ? normalized.name.trim() : title,
    reviewBody: typeof normalized.reviewBody === "string" && normalized.reviewBody.trim()
      ? normalized.reviewBody.trim()
      : reviewBody,
    ...normalized,
    itemReviewed,
  };
}

async function loadArchiveRecordWithRecovery(slug: string): Promise<ArchivePageLoadResult> {
  const record = await loadArchiveRecord(slug);
  if (record) {
    return { record, recoveryStatus: "local_cache" };
  }

  try {
    const response = await fetch(
      buildBackendUrl(`/api/v1/history/restore/${encodeURIComponent(slug)}`),
      {
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      },
    );

    if (response.status === 404) {
      return { record: null, recoveryStatus: "soft_landed" };
    }

    if (!response.ok) {
      return { record: null, recoveryStatus: "unavailable" };
    }

    const payload = (await response.json()) as {
      status?: "cache_hit" | "restored";
      record?: SovereignArchiveRecord | null;
    };

    if (!payload.record) {
      return { record: null, recoveryStatus: "unavailable" };
    }

    return {
      record: payload.record,
      recoveryStatus: payload.status ?? "restored",
    };
  } catch {
    return { record: null, recoveryStatus: "unavailable" };
  }
}

async function loadUnifiedLiveSeo(slug: string): Promise<UnifiedLiveSeoPayload | null> {
  try {
    const response = await fetch(buildBackendUrl(`/api/seo/live/${encodeURIComponent(slug)}`), {
      next: {
        revalidate: SEO_REVALIDATE_SECONDS,
        tags: [`seo-patch-${slug}`],
      },
    });

    if (response.status === 404 || !response.ok) {
      return null;
    }

    return (await response.json()) as UnifiedLiveSeoPayload;
  } catch {
    return null;
  }
}

function resolveUnifiedJsonLd(seo: UnifiedLiveSeoPayload | null): Record<string, unknown> | undefined {
  const candidate = seo?.payload.jsonld ?? seo?.payload.json_ld;
  if (!candidate || Array.isArray(candidate)) {
    return undefined;
  }
  return candidate;
}

export async function resolveArchiveHeadJsonLd({
  slug,
  canonicalPath,
}: ArchiveMetadataOptions): Promise<Record<string, unknown> | null> {
  const [{ record }, seo] = await Promise.all([
    loadArchiveRecordWithRecovery(slug),
    loadUnifiedLiveSeo(slug),
  ]);

  if (!record) {
    return null;
  }

  const legacyType = resolveLegacyType(record);
  const payload = seo?.payload;
  const title = payload?.title?.trim() || buildTitle(record.title, legacyType);
  const description = payload?.meta_description?.trim() || buildDescription(record.content_body, title, legacyType);
  return normalizeArchiveJsonLd(
    record,
    legacyType,
    canonicalPath,
    title,
    description,
    resolveUnifiedJsonLd(seo),
  );
}

export async function generateArchiveMetadata({ slug, canonicalPath }: ArchiveMetadataOptions): Promise<Metadata> {
  const [{ record, recoveryStatus }, seo] = await Promise.all([
    loadArchiveRecordWithRecovery(slug),
    loadUnifiedLiveSeo(slug),
  ]);

  if (!record) {
    return {
      title: buildUnavailableTitle(recoveryStatus),
      robots: {
        index: false,
        follow: true,
      },
    };
  }

  const legacyType = resolveLegacyType(record);
  const payload = seo?.payload;
  const title = payload?.title?.trim() || buildTitle(record.title, legacyType);
  const description = payload?.meta_description?.trim() || buildDescription(record.content_body, title, legacyType);
  const titleSuffix = buildMetadataSuffix(legacyType);

  return {
    title: `${title} | ${titleSuffix}`,
    description,
    alternates: {
      canonical: canonicalPath,
    },
    openGraph: {
      title: `${title} | ${titleSuffix}`,
      description,
      type: legacyType === "page" ? "website" : "article",
      url: canonicalPath,
    },
  };
}

export async function ArchivePageContent({
  slug,
  canonicalPath,
  pathLabel,
  pathValue,
}: ArchivePageOptions) {
  const [{ record, recoveryStatus }, seo] = await Promise.all([
    loadArchiveRecordWithRecovery(slug),
    loadUnifiedLiveSeo(slug),
  ]);

  if (!record) {
    return (
      <main className="mx-auto max-w-4xl space-y-8 px-6 py-10">
        <header className="space-y-3">
          <div className="inline-flex items-center rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-sm font-medium text-amber-700 dark:text-amber-300">
            Soft-Landed Historical Loss
          </div>
          <h1 className="text-4xl font-bold tracking-tight">This legacy archive record could not be resurrected.</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            The requested archive slug was probed against the historical blueprint, but no signed legacy source is currently available for this
            path. The event has been recorded so the missing volume can be repaired.
          </p>
        </header>

        <section className="grid gap-4 rounded-xl border p-5 md:grid-cols-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Requested Slug</p>
            <p className="mt-1 font-mono text-sm">{slug}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{pathLabel}</p>
            <p className="mt-1 font-mono text-sm">{pathValue}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Recovery Status</p>
            <p className="mt-1 font-mono text-sm">{recoveryStatus}</p>
          </div>
        </section>

        <section className="rounded-xl border p-6">
          <p className="text-sm text-muted-foreground">
            Use the links below to return to live inventory while the archive ledger is repaired.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link
              href="/"
              className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              Return to Live Site
            </Link>
            <Link
              href="/"
              className="inline-flex items-center rounded-md border px-4 py-2 text-sm font-medium"
            >
              Return Home
            </Link>
          </div>
        </section>
      </main>
    );
  }

  const legacyType = resolveLegacyType(record);
  const payload = seo?.payload;
  const title = payload?.h1_suggestion?.trim() || payload?.h1?.trim() || buildTitle(record.title, legacyType);
  const intro = payload?.intro?.trim() || null;
  const faq = Array.isArray(payload?.faq) ? payload.faq : [];
  const jsonLd = await resolveArchiveHeadJsonLd({ slug, canonicalPath });
  const publishedAt = formatLegacyTimestamp(record.legacy_created_at);
  const updatedAt = formatLegacyTimestamp(record.legacy_updated_at);
  const ctaHref = record.related_property_path || "/";
  const ctaLabel = record.related_property_title?.trim()
    ? `Return to Modern ${record.related_property_title.trim()}`
    : record.related_property_slug
      ? "Return to Modern Cabin"
      : "Explore Available Cabins";
  const badgeLabel = record.body_status === "verified" ? "Verified Historical Record" : "Historical Record Pending Verification";
  const recoveryBadge = recoveryStatus === "restored"
    ? "Resurrected On Demand"
    : recoveryStatus === "cache_hit" || recoveryStatus === "local_cache"
      ? "Sovereign Cache Hit"
      : null;
  const watermarkLabel = legacyType === "blog_post" ? "Archived Article" : "Archived Page";

  return (
    <main className="mx-auto max-w-4xl space-y-8 px-6 py-10">
      {jsonLd ? (
        <Script
          id={`archive-jsonld-${slug.replace(/[^a-z0-9-]+/gi, "-")}`}
          type="application/ld+json"
          strategy="beforeInteractive"
        >
          {JSON.stringify(jsonLd)}
        </Script>
      ) : null}
      <header className="space-y-3">
        {legacyType === "review" ? (
          <div className="inline-flex items-center rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-sm font-medium text-emerald-700 dark:text-emerald-300">
            {badgeLabel}
          </div>
        ) : (
          <div className="inline-flex items-center rounded-full border border-slate-500/30 bg-slate-500/10 px-3 py-1 text-sm font-medium text-slate-700 dark:text-slate-300">
            {watermarkLabel}
          </div>
        )}
        {recoveryBadge ? (
          <div className="inline-flex items-center rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
            {recoveryBadge}
          </div>
        ) : null}
        <h1 className="text-4xl font-bold tracking-tight">{title}</h1>
        {intro ? (
          <p className="max-w-3xl text-base text-muted-foreground">{intro}</p>
        ) : null}
        {legacyType === "review" ? (
          <p className="text-lg tracking-[0.35em] text-amber-500" aria-label="Historical guest review">
            ★★★★★
          </p>
        ) : null}
        <p className="text-sm text-muted-foreground">
          {pathLabel}: <span className="font-mono">{pathValue}</span>
        </p>
      </header>

      <section className="grid gap-4 rounded-xl border p-5 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Legacy Node</p>
          <p className="mt-1 font-mono text-sm">{record.legacy_node_id}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Original Slug</p>
          <p className="mt-1 font-mono text-sm">{record.original_slug}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Legacy Type</p>
          <p className="mt-1 text-sm capitalize">{legacyType.replace("_", " ")}</p>
        </div>
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Integrity Seal</p>
          <p className="mt-1 break-all font-mono text-xs">{record.hmac_signature}</p>
        </div>
      </section>

      {legacyType === "review" ? (
        <section className="space-y-3 rounded-xl border p-6">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold">Historical Testimonial</h2>
            <Link
              href={ctaHref}
              className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              {ctaLabel}
            </Link>
          </div>
          {record.content_body.trim() ? (
            <blockquote
              className="prose prose-slate max-w-none border-l-4 border-amber-400 pl-5 text-base leading-7 dark:prose-invert"
              dangerouslySetInnerHTML={{ __html: record.content_body }}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              This archival node has been signed and routed, but its raw testimonial body is not yet present in the extracted Drupal blueprint.
            </p>
          )}
        </section>
      ) : (
        <section className="space-y-5 rounded-xl border p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold">
                {legacyType === "blog_post" ? "Legacy Blog Article" : "Legacy Page Snapshot"}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {legacyType === "blog_post"
                  ? "Recovered from the historical Drupal blueprint for continuity and reference."
                  : "Recovered from the historical Drupal blueprint as an archived page snapshot."}
              </p>
            </div>
            <div className="rounded-lg border border-dashed px-3 py-2 text-xs uppercase tracking-[0.2em] text-muted-foreground">
              {watermarkLabel}
            </div>
          </div>

          {legacyType === "blog_post" && (publishedAt || updatedAt || record.legacy_author_id || record.legacy_language) ? (
            <div className="grid gap-4 rounded-lg bg-muted/30 p-4 md:grid-cols-2 xl:grid-cols-4">
              {publishedAt ? (
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Published</p>
                  <p className="mt-1 text-sm">{publishedAt}</p>
                </div>
              ) : null}
              {updatedAt ? (
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Updated</p>
                  <p className="mt-1 text-sm">{updatedAt}</p>
                </div>
              ) : null}
              {record.legacy_author_id ? (
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Legacy Author</p>
                  <p className="mt-1 text-sm">{record.legacy_author_id}</p>
                </div>
              ) : null}
              {record.legacy_language ? (
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">Language</p>
                  <p className="mt-1 text-sm">{record.legacy_language}</p>
                </div>
              ) : null}
            </div>
          ) : null}

          {record.content_body.trim() ? (
            <article
              className="prose prose-slate max-w-none dark:prose-invert"
              dangerouslySetInnerHTML={{ __html: record.content_body }}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              This archival node has been signed and routed, but its raw page body is not yet present in the extracted Drupal blueprint.
            </p>
          )}

          <div className="flex flex-wrap gap-3">
            <Link
              href="/"
              className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              Return to Live Site
            </Link>
            <Link
              href="/properties"
              className="inline-flex items-center rounded-md border px-4 py-2 text-sm font-medium"
            >
              Explore Available Cabins
            </Link>
          </div>
        </section>
      )}

      {record.category_tags.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Category Tags</h2>
          <div className="flex flex-wrap gap-2">
            {record.category_tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full border px-3 py-1 text-sm text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {faq.length > 0 ? (
        <section className="space-y-4 rounded-xl border p-6">
          <h2 className="text-xl font-semibold">Frequently Asked Questions</h2>
          {faq.map((item, idx) => (
            <article key={`${idx}-${item.q || "question"}`} className="space-y-2 rounded-lg border p-4">
              <h3 className="font-medium">{item.q || "Question"}</h3>
              <p className="text-sm text-muted-foreground">{item.a || ""}</p>
            </article>
          ))}
        </section>
      ) : null}
    </main>
  );
}
