import type { MetadataRoute } from "next";
import { getStorefrontBaseUrl } from "@/lib/server/storefront-base-url";

export default async function robots(): Promise<MetadataRoute.Robots> {
  const baseUrl = getStorefrontBaseUrl();
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/cabins/"],
        disallow: ["/api/", "/guest/", "/owner/", "/dashboard/"],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
    host: baseUrl,
  };
}
