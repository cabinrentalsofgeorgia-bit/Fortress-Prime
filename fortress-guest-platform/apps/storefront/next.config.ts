import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  skipTrailingSlashRedirect: true,
  experimental: {
    serverActions: {
      allowedOrigins: [
        "cabin-rentals-of-georgia.com",
        "www.cabin-rentals-of-georgia.com",
        "staging.cabin-rentals-of-georgia.com",
        "beta.cabin-rentals-of-georgia.com",
        "cabin-rentals-of-georgia.vercel.app",
        "localhost",
        "127.0.0.1",
      ],
    },
  },
  images: {
    remotePatterns: [
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
  async redirects() {
    return [
      {
        source: "/cabins/above-it-all-lodge",
        destination: "/availability",
        permanent: true,
      },
    ];
  },
  async rewrites() {
    return {
      beforeFiles: [
        // 1. THE FRONT DOOR: Retreat the homepage back to Drupal
        {
          source: "/",
          destination: "https://legacy.cabin-rentals-of-georgia.com/",
        },
        // 2. THE REVENUE PROTECTORS: Keep the money zones on Drupal
        {
          source: "/cabins/:path*",
          destination: "https://legacy.cabin-rentals-of-georgia.com/cabins/:path*",
        },
        {
          source: "/availability",
          destination: "https://legacy.cabin-rentals-of-georgia.com/availability",
        },
        {
          source: "/checkout/:path*",
          destination: "https://legacy.cabin-rentals-of-georgia.com/checkout/:path*",
        }
      ],
      // 3. THE SAFETY NET: Catch unhandled legacy pages
      fallback: [
        {
          source: "/:path*",
          destination: "https://legacy.cabin-rentals-of-georgia.com/:path*",
        },
      ],
    };
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
