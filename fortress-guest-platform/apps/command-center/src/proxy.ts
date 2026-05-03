import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { isStorefrontHost } from "./lib/domain-boundaries";

/**
 * Command Center deployment: no legacy storefront 301 engine.
 * Staff hosts are isolated to this binary on the DGX.
 */
export function proxy(request: NextRequest) {
  if (isStorefrontHost(request.headers.get("host"))) {
    return new NextResponse("Not found", {
      status: 404,
      headers: {
        "Cache-Control": "no-store, must-revalidate",
        "X-Robots-Tag": "noindex, nofollow",
      },
    });
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|map|txt|xml)$).*)",
  ],
};
