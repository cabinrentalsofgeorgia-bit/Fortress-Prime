import type { NextConfig } from "next";
import legacyRedirects from "./src/data/legacy-redirects";

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  async headers() {
    return [
      {
        source: "/cabins/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, s-maxage=300, stale-while-revalidate=86400",
          },
        ],
      },
      {
        source: "/sitemap.xml",
        headers: [
          {
            key: "Cache-Control",
            value: "public, s-maxage=300, stale-while-revalidate=86400",
          },
        ],
      },
      {
        source: "/robots.txt",
        headers: [
          {
            key: "Cache-Control",
            value: "public, s-maxage=300, stale-while-revalidate=86400",
          },
        ],
      },
      {
        source: "/((?!cabins/|sitemap.xml|robots.txt).*)",
        headers: [
          {
            key: "Cache-Control",
            value: "no-store, must-revalidate",
          },
        ],
      },
    ];
  },
  async redirects() {
    return legacyRedirects;
  },
};

export default nextConfig;
