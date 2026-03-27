import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import legacyRedirects from "@/data/legacy-redirects";
import redirectLedger from "@/lib/redirects.json";

type RedirectLedger = Record<string, string>;

const scaffoldRedirectMap = new Map(Object.entries(redirectLedger as RedirectLedger));

const sovereignCategoryRedirectMap = new Map<string, string>([
  ["/2-bedroom-cabins", "/cabins?bedrooms=2"],
  ["/3-bedroom-cabin-rentals", "/cabins?bedrooms=3"],
  ["/4-bedroom-cabin-rentals", "/cabins?bedrooms=4"],
  ["/5-bedroom-cabin-rentals", "/cabins?bedrooms=5"],
  ["/lakefront-cabin-rentals", "/cabins?amenities=lakefront"],
  ["/lake-view-cabin-rentals", "/cabins?amenities=lake-view"],
  ["/luxury-river-cabins", "/cabins?amenities=riverfront"],
  ["/mountain-view-cabin-rentals", "/cabins?amenities=mountain-view"],
  ["/our-pet-friendly-cabins", "/cabins?amenities=pet-friendly"],
  ["/riverfront-cabin-rentals", "/cabins?amenities=riverfront"],
  ["/river-view-cabin-rentals", "/cabins?amenities=river-view"],
  ["/book-now-before-its-too-late", "/cabins"],
  ["/book-one-now-while-you-still-can", "/cabins"],
  ["/only-3-cabins-left", "/cabins"],
  ["/access-denied", "/"],
]);

const legacyRedirectMap = new Map(
  legacyRedirects
    .filter((redirect) => !redirect.source.startsWith("/testimonial/"))
    .map((redirect) => [redirect.source, redirect.destination]),
);

function normalizePathname(pathname: string): string {
  if (!pathname || pathname === "/") {
    return "/";
  }

  const normalized = pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
  return normalized || "/";
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const normalizedPathname = normalizePathname(pathname);
  const requestHeaders = new Headers(request.headers);
  const legacyDestination =
    sovereignCategoryRedirectMap.get(normalizedPathname) ??
    scaffoldRedirectMap.get(normalizedPathname) ??
    legacyRedirectMap.get(normalizedPathname);

  if (legacyDestination && legacyDestination !== normalizedPathname) {
    const redirectUrl = request.nextUrl.clone();
    const destinationUrl = new URL(legacyDestination, request.url);
    redirectUrl.pathname = destinationUrl.pathname;
    redirectUrl.search = destinationUrl.search || redirectUrl.search;
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
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|map|txt|xml)$).*)",
  ],
};
