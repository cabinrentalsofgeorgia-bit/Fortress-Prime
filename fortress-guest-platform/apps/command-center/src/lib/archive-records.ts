import "server-only";

import { cache } from "react";
import { readFile } from "node:fs/promises";
import path from "node:path";

export interface SovereignArchiveRecord {
  legacy_node_id: string;
  original_slug: string;
  content_body: string;
  category_tags: string[];
  hmac_signature: string;
  title?: string;
  archive_slug?: string;
  archive_path?: string;
  source_ref?: string;
  node_type?: string;
  legacy_type?: string;
  legacy_created_at?: number;
  legacy_updated_at?: number;
  legacy_author_id?: string;
  legacy_language?: string;
  body_status?: string;
  related_property_slug?: string;
  related_property_path?: string;
  related_property_title?: string;
  signed_at?: string;
}

const TESTIMONIAL_ARCHIVE_DIRS = [
  path.resolve(process.cwd(), "src/data/legacy/testimonials"),
  path.resolve(process.cwd(), "../backend/data/archives/testimonials"),
];

function normalizeArchiveLookupPath(value: string): string | null {
  const trimmed = value.trim().toLowerCase();
  if (!trimmed) return null;

  const withoutOrigin = trimmed.replace(/^https?:\/\/[^/]+/i, "");
  const withLeadingSlash = withoutOrigin.startsWith("/") ? withoutOrigin : `/${withoutOrigin}`;
  const collapsed = withLeadingSlash.replace(/\/{2,}/g, "/");
  if (collapsed === "/") return null;
  return collapsed.endsWith("/") ? collapsed.slice(0, -1) : collapsed;
}

function buildArchiveCacheKey(value: string): string | null {
  const normalizedPath = normalizeArchiveLookupPath(value);
  if (!normalizedPath) return null;
  return encodeURIComponent(normalizedPath);
}

function normalizeArchiveSlug(slug: string): string | null {
  const value = slug.trim().toLowerCase();
  if (!value) return null;
  return /^[a-z0-9-]+$/.test(value) ? value : null;
}

export const loadArchiveRecord = cache(
  async (slug: string): Promise<SovereignArchiveRecord | null> => {
    const lookupKey = buildArchiveCacheKey(slug);
    if (lookupKey) {
      for (const archiveDir of TESTIMONIAL_ARCHIVE_DIRS) {
        try {
          const pathAwareFile = path.join(archiveDir, `${lookupKey}.json`);
          const payload = await readFile(pathAwareFile, "utf-8");
          return JSON.parse(payload) as SovereignArchiveRecord;
        } catch {
          // Fall through to the next archive directory.
        }
      }
    }

    const normalizedSlug = normalizeArchiveSlug(slug);
    if (!normalizedSlug) return null;

    for (const archiveDir of TESTIMONIAL_ARCHIVE_DIRS) {
      try {
        const legacyFile = path.join(archiveDir, `${normalizedSlug}.json`);
        const payload = await readFile(legacyFile, "utf-8");
        return JSON.parse(payload) as SovereignArchiveRecord;
      } catch {
        // Fall through to the next archive directory.
      }
    }
    return null;
  },
);

export const loadTestimonialArchiveRecord = loadArchiveRecord;
