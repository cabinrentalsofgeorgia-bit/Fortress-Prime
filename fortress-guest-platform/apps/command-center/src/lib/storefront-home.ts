import "server-only";

import { cache } from "react";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { buildBackendUrl } from "@/lib/server/backend-url";

export interface StorefrontPropertySummary {
  id: string;
  name: string;
  slug: string;
  property_type: string;
  streamline_property_id: string;
  bedrooms: number;
  bathrooms: number;
  max_guests: number;
  address?: string | null;
  is_active: boolean;
  source: string;
}

export interface ReviewSpotlight {
  slug: string;
  title: string;
  excerpt: string;
  propertyTitle: string | null;
  propertyPath: string | null;
  originalSlug: string;
}

interface PropertyCatalogResponse {
  properties: StorefrontPropertySummary[];
}

interface ArchiveReviewRecord {
  archive_slug?: string;
  title?: string;
  content_body?: string;
  original_slug?: string;
  node_type?: string;
  legacy_type?: string;
  related_property_title?: string;
  related_property_path?: string;
}

const ARCHIVE_DIR = path.join(
  process.cwd(),
  "src",
  "data",
  "legacy",
  "testimonials",
);

function sanitizeHtml(html: string): string {
  return html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function truncate(text: string, limit: number): string {
  const normalized = text.trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 3).trimEnd()}...`;
}

function isReviewRecord(record: ArchiveReviewRecord): boolean {
  const nodeType = (record.node_type || "").trim().toLowerCase();
  const legacyType = (record.legacy_type || "").trim().toLowerCase();
  return nodeType === "testimonial" || nodeType === "review" || legacyType === "testimonial" || legacyType === "review";
}

async function fetchJson<T>(pathName: string): Promise<T> {
  const response = await fetch(buildBackendUrl(pathName), {
    next: { revalidate: 300 },
  });
  if (!response.ok) {
    throw new Error(`Failed to load backend data from ${pathName} (${response.status})`);
  }
  return response.json() as Promise<T>;
}

async function fetchPropertyCatalog(): Promise<PropertyCatalogResponse> {
  try {
    return await fetchJson<PropertyCatalogResponse>("/api/quotes/streamline/properties");
  } catch {
    return { properties: [] };
  }
}

export function getAvailabilityHref(): string {
  const today = new Date();
  const year = today.getUTCFullYear();
  const month = String(today.getUTCMonth() + 1).padStart(2, "0");
  return `/availability/${year}/${month}`;
}

export const getStorefrontHomeData = cache(async () => {
  const [catalog, reviewSpotlights] = await Promise.all([
    fetchPropertyCatalog(),
    loadReviewSpotlights(),
  ]);

  const activeProperties = catalog.properties
    .filter((property) => property.is_active)
    .sort((left, right) => left.name.localeCompare(right.name));

  return {
    allProperties: activeProperties,
    featuredProperties: activeProperties.slice(0, 6),
    navigationProperties: activeProperties.slice(0, 4),
    reviewSpotlights,
    availabilityHref: getAvailabilityHref(),
  };
});

const loadReviewSpotlights = cache(async (): Promise<ReviewSpotlight[]> => {
  let fileNames: string[];
  try {
    fileNames = (await readdir(ARCHIVE_DIR))
      .filter((name) => name.endsWith(".json"))
      .sort();
  } catch {
    return [];
  }

  const reviews: ReviewSpotlight[] = [];
  for (const fileName of fileNames) {
    if (reviews.length >= 3) {
      break;
    }
    const fullPath = path.join(ARCHIVE_DIR, fileName);
    try {
      const raw = await readFile(fullPath, "utf-8");
      const record = JSON.parse(raw) as ArchiveReviewRecord;
      if (!isReviewRecord(record) || !record.archive_slug || !record.title || !record.content_body) {
        continue;
      }
      reviews.push({
        slug: record.archive_slug,
        title: record.title.trim(),
        excerpt: truncate(sanitizeHtml(record.content_body), 180),
        propertyTitle: record.related_property_title?.trim() || null,
        propertyPath: record.related_property_path?.trim() || null,
        originalSlug: record.original_slug?.trim() || `/${record.archive_slug}`,
      });
    } catch {
      continue;
    }
  }

  return reviews;
});
