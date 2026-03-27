import type { MetadataRoute } from "next";
import { getBackendBaseUrl } from "@/lib/server/backend-url";
import { getStorefrontBaseUrl } from "@/lib/server/storefront-base-url";

interface LiveSlugResponse {
  slugs: string[];
}

async function getLiveSlugs(): Promise<string[]> {
  const res = await fetch(`${getBackendBaseUrl()}/api/seo/live/property-slugs`, {
    next: { revalidate: 300 },
  });
  if (!res.ok) return [];

  const body = (await res.json()) as LiveSlugResponse;
  return body.slugs || [];
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const baseUrl = getStorefrontBaseUrl();
  const now = new Date();
  try {
    const slugs = await getLiveSlugs();
    const cabinEntries: MetadataRoute.Sitemap = slugs.map((slug) => ({
      url: `${baseUrl}/cabins/${slug}`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.9,
    }));

    return [
      {
        url: `${baseUrl}/`,
        lastModified: now,
        changeFrequency: "weekly",
        priority: 0.5,
      },
      ...cabinEntries,
    ];
  } catch (error) {
    console.warn("[CI WARNING] Sitemap fetch failed during build. Falling back to static root.", error);
    return [
      {
        url: `${baseUrl}/`,
        lastModified: now,
        changeFrequency: "daily",
        priority: 1,
      },
    ];
  }
}
