import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = request.nextUrl.host.toLowerCase();

  const enforceCanonical = (process.env.ENFORCE_CANONICAL_HOST ?? "true").toLowerCase() === "true";
  const canonicalAppUrl = process.env.NEXT_PUBLIC_APP_URL || "https://crog-ai.com";
  const isLocalHost = host.startsWith("127.0.0.1") || host.startsWith("localhost");

  if (enforceCanonical && isLocalHost && pathname.startsWith("/vrs/hunter")) {
    const target = new URL(`${canonicalAppUrl}${pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(target);
  }

  if (
    pathname.startsWith("/owner") &&
    !pathname.startsWith("/owner-login")
  ) {
    const token = request.cookies.get("fgp_owner_token")?.value;

    if (!token) {
      const loginUrl = new URL("/owner-login", request.url);
      return NextResponse.redirect(loginUrl);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/owner/:path*", "/owner", "/vrs/hunter"],
};
