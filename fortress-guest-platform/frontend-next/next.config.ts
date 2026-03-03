import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  async rewrites() {
    // All /api/* traffic is handled by explicit BFF route handlers:
    //   src/app/api/auth/          → FGP backend (port 8100)
    //   src/app/api/reservations/  → FGP backend (port 8100)
    //   src/app/api/[...path]/     → routes to FGP or Command Center
    // No rewrites needed — BFF handlers preserve trailing slashes
    // and forward Authorization headers properly.
    return [];
  },
  async redirects() {
    return [];
  },
};

export default nextConfig;
