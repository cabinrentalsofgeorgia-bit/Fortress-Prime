import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Command Center deployment: no legacy storefront 301 engine.
 * Staff hosts are isolated to this binary on the DGX.
 */
export function proxy(_request: NextRequest) {
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|map|txt|xml)$).*)",
  ],
};
