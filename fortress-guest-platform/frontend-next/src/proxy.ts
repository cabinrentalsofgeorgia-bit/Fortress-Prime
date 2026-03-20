import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import legacyRedirects from "@/data/legacy-redirects";

const legacyRedirectMap = new Map(
  legacyRedirects
    .filter((redirect) => !redirect.source.startsWith("/testimonial/"))
    .map((redirect) => [redirect.source, redirect.destination]),
);

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const requestHeaders = new Headers(request.headers);
  const legacyDestination = legacyRedirectMap.get(pathname);

  if (legacyDestination && legacyDestination !== pathname) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = legacyDestination;
    return NextResponse.redirect(redirectUrl, 301);
  }

  if (pathname === "/honeymoon-cabin") {
    const reviewUrl = request.nextUrl.clone();
    reviewUrl.pathname = "/reviews/honeymoon-majestic-lake-cabin";
    return NextResponse.redirect(reviewUrl, 301);
  }

  if (pathname.startsWith("/reviews/archive/")) {
    const slug = pathname.slice("/reviews/archive/".length).trim().replace(/^\/+/, "");
    if (slug) {
      const reviewUrl = request.nextUrl.clone();
      reviewUrl.pathname = `/reviews/${slug}`;
      return NextResponse.redirect(reviewUrl, 301);
    }
  }

  if (pathname.startsWith("/testimonial/")) {
    const slug = pathname.split("/").filter(Boolean).slice(1).join("/");
    if (slug) {
      const reviewUrl = request.nextUrl.clone();
      reviewUrl.pathname = `/reviews/${slug}`;
      requestHeaders.set("x-current-path", reviewUrl.pathname);
      return NextResponse.rewrite(reviewUrl, {
        request: {
          headers: requestHeaders,
        },
      });
    }
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

  if (pathname.startsWith("/reviews/")) {
    requestHeaders.set("x-current-path", pathname);
    return NextResponse.next({
      request: {
        headers: requestHeaders,
      },
    });
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\..*).*)"],
};
