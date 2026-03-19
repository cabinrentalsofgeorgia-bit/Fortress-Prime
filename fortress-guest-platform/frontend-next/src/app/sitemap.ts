import type { MetadataRoute } from "next";

interface LiveSlugResponse {
  slugs: string[];
}

function getBaseUrl(): string {
  const appUrl = process.env.NEXT_PUBLIC_APP_URL?.trim();
  if (appUrl) return appUrl.replace(/\/$/, "");

  const vercelUrl = process.env.VERCEL_URL?.trim();
  if (vercelUrl) return `https://${vercelUrl.replace(/\/$/, "")}`;

  return "http://127.0.0.1:3000";
}

async function getLiveSlugs(): Promise<string[]> {
  const res = await fetch(`${getBaseUrl()}/api/seo-patches/live/property-slugs`, {
    next: { revalidate: 300 },
  });
  if (!res.ok) return [];

  const body = (await res.json()) as LiveSlugResponse;
  return body.slugs || [];
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const baseUrl = getBaseUrl();
  const slugs = await getLiveSlugs();
  const now = new Date();

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
}
