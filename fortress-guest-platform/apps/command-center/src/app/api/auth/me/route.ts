import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const SESSION_COOKIE = "fortress_session";

/**
 * Staff session probe with cookie bridge: when the browser has no Bearer token in
 * localStorage but still holds `fortress_session` from login, synthesize
 * Authorization for FastAPI and echo `access_token` so the client can repopulate
 * `fgp_token` (see `fetchMe` in auth.ts).
 */
export async function GET(request: NextRequest) {
  const target = buildBackendUrl("/api/auth/me");

  const headers: Record<string, string> = {
    Accept: "application/json",
  };

  const authHeader = request.headers.get("authorization");
  const cookieToken = request.cookies.get(SESSION_COOKIE)?.value ?? null;
  let usedCookieAuth = false;

  if (authHeader?.startsWith("Bearer ")) {
    headers.Authorization = authHeader;
  } else if (cookieToken) {
    headers.Authorization = `Bearer ${cookieToken}`;
    usedCookieAuth = true;
  }

  const rawCookies = request.headers.get("cookie");
  if (rawCookies) {
    headers.Cookie = rawCookies;
  }

  try {
    const upstream = await fetch(target, {
      method: "GET",
      headers,
      signal: AbortSignal.timeout(10_000),
    });

    const text = await upstream.text();
    const contentType =
      upstream.headers.get("content-type") || "application/json";

    if (!upstream.ok) {
      return new NextResponse(text, {
        status: upstream.status,
        headers: { "Content-Type": contentType },
      });
    }

    if (!usedCookieAuth || !cookieToken) {
      return new NextResponse(text, {
        status: upstream.status,
        headers: { "Content-Type": contentType },
      });
    }

    try {
      const body = JSON.parse(text) as Record<string, unknown>;
      const merged = { ...body, access_token: cookieToken };
      return NextResponse.json(merged, { status: upstream.status });
    } catch {
      return new NextResponse(text, {
        status: upstream.status,
        headers: { "Content-Type": contentType },
      });
    }
  } catch (err) {
    console.error("[BFF] GET /api/auth/me proxy error:", err);
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}
