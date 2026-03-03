import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

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
  matcher: ["/owner/:path*", "/owner"],
};
