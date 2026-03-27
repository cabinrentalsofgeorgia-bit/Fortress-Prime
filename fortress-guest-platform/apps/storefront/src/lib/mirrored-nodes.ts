import "server-only";

import { buildBackendUrl } from "@/lib/server/backend-url";

export const MIRRORED_NODES_REVALIDATE_SECONDS = 300;

export interface MirroredNodeStaticParam {
  canonical_path: string;
  slug: string[];
  title: string;
  content_category: string;
  updated_at: string;
}

export interface MirroredNode {
  canonical_path: string;
  slug: string[];
  title: string;
  node_type: string;
  content_category: string;
  raw_html: string;
  body_text_preview: string | null;
  updated_at: string;
}

interface MirroredNodeResolveResponse {
  node: MirroredNode | null;
  static_params: MirroredNodeStaticParam[];
}

export function normalizeMirroredNodePath(path: string): string {
  const trimmed = path.trim();
  if (!trimmed) {
    return "/";
  }

  const withLeadingSlash = trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
  const normalized = withLeadingSlash
    .split("/")
    .filter(Boolean)
    .join("/");

  return normalized ? `/${normalized}` : "/";
}

export function resolveMirroredNodePathFromSlug(slug: string[]): string {
  return normalizeMirroredNodePath(slug.join("/"));
}

async function fetchMirroredNodePayload(path?: string): Promise<MirroredNodeResolveResponse | null> {
  try {
    const normalizedPath = path ? normalizeMirroredNodePath(path) : "";
    const search = normalizedPath ? `?path=${encodeURIComponent(normalizedPath)}` : "";
    const response = await fetch(buildBackendUrl(`/api/system/nodes/resolve${search}`), {
      next: { revalidate: MIRRORED_NODES_REVALIDATE_SECONDS },
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as MirroredNodeResolveResponse;
  } catch {
    return null;
  }
}

export async function fetchMirroredNode(path: string): Promise<MirroredNode | null> {
  const payload = await fetchMirroredNodePayload(path);
  return payload?.node ?? null;
}

export async function fetchMirroredNodeStaticParams(): Promise<Array<{ slug: string[] }>> {
  const payload = await fetchMirroredNodePayload();
  return (payload?.static_params ?? []).map((entry) => ({ slug: entry.slug }));
}

export function stripHtmlToText(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

export function formatMirroredNodeLabel(contentCategory: string): string {
  if (contentCategory === "area_guide") {
    return "Sovereign Area Guide";
  }
  if (contentCategory === "blog_article") {
    return "Sovereign Blog Mirror";
  }
  return "Sovereign Content Mirror";
}
