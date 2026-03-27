import "server-only";
import { buildBackendUrl } from "@/lib/server/backend-url";

export const CONTENT_REVALIDATE_SECONDS = 300;

export interface ContentCategorySummary {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  meta_title: string | null;
  meta_description: string | null;
  article_count: number;
}

export interface RelatedCabinSummary {
  id: string;
  name: string;
  slug: string;
  property_type: string;
  max_guests: number;
}

export interface ContentArticleSummary {
  id: string;
  title: string;
  slug: string;
  author: string | null;
  published_date: string | null;
}

export interface ContentCategoryDetail extends ContentCategorySummary {
  articles: ContentArticleSummary[];
  related_cabins: RelatedCabinSummary[];
}

export interface ContentArticleDetail {
  id: string;
  title: string;
  slug: string;
  content_body_html: string;
  author: string | null;
  published_date: string | null;
  category: ContentCategorySummary;
}

async function fetchContent<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(buildBackendUrl(path), {
      next: { revalidate: CONTENT_REVALIDATE_SECONDS },
    });
    if (response.status === 404 || !response.ok) {
      return null;
    }
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export function buildCategoryPath(slug: string): string {
  return `/category/${slug}`;
}

export function buildGuidePath(slug: string): string {
  return `/guide/${slug}`;
}

export async function fetchContentCategories(): Promise<ContentCategorySummary[]> {
  return (await fetchContent<ContentCategorySummary[]>("/api/content/categories")) ?? [];
}

export async function fetchContentCategory(slug: string): Promise<ContentCategoryDetail | null> {
  return fetchContent<ContentCategoryDetail>(`/api/content/categories/${encodeURIComponent(slug)}`);
}

export async function fetchContentArticle(slug: string): Promise<ContentArticleDetail | null> {
  return fetchContent<ContentArticleDetail>(`/api/content/articles/${encodeURIComponent(slug)}`);
}

export async function fetchAllGuideStaticParams(): Promise<Array<{ slug: string }>> {
  const categories = await fetchContentCategories();
  const categoryPayloads = await Promise.all(
    categories.map(async (category) => fetchContentCategory(category.slug)),
  );

  return categoryPayloads
    .flatMap((category) => category?.articles ?? [])
    .map((article) => ({ slug: article.slug }));
}

export function stripHtmlToText(html: string): string {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}
