import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  skipTrailingSlashRedirect: true,
  images: {
    remotePatterns: [
      // Sovereign crog-media-ledger R2 origins only.
      {
        protocol: "https",
        hostname: "pub-62267cefe3534b6c8c381d3e83b8fbf3.r2.dev",
      },
      {
        protocol: "https",
        hostname: "media.cabin-rentals-of-georgia.com",
      },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/cabin/:location/:slug",
        destination: "/cabins/:slug",
      },
      {
        source: "/cabin/:slug",
        destination: "/cabins/:slug",
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/cabin/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, s-maxage=300, stale-while-revalidate=86400",
          },
        ],
      },
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
};

export default nextConfig;
