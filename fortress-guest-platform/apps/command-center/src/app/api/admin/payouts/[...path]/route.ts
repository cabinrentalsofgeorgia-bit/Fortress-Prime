import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";
import { getFortressIngressHeaders } from "@/lib/server/fortress-ingress-headers";

const SESSION_COOKIE = "fortress_session";

function extractToken(request: NextRequest): string | null {
  const authHeader = request.headers.get("authorization");
  if (authHeader?.startsWith("Bearer ")) {
    return authHeader.slice(7);
  }

  const sessionCookie = request.cookies.get(SESSION_COOKIE);
  if (sessionCookie?.value) return sessionCookie.value;

  const ownerCookie = request.cookies.get("fgp_owner_token");
  if (ownerCookie?.value) return ownerCookie.value;

  const headerToken = request.headers.get("x-fgp-token");
  if (headerToken) return headerToken;

  return null;
}

async function forwardToBackend(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const pathString = path.join("/");
  const url = new URL(request.url);
  const target = `${buildBackendUrl(`/api/admin/payouts/${pathString}`)}${url.search}`;

  const token = extractToken(request);
  const rawCookies = request.headers.get("cookie") || "";

  const headers: Record<string, string> = {
    "Content-Type": request.headers.get("content-type") || "application/json",
    Accept: request.headers.get("accept") || "application/json",
    ...getFortressIngressHeaders(request),
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (token) {
    headers.Cookie = rawCookies
      ? rawCookies.includes(`${SESSION_COOKIE}=`)
        ? rawCookies
        : `${rawCookies}; ${SESSION_COOKIE}=${token}`
      : `${SESSION_COOKIE}=${token}`;
  } else if (rawCookies) {
    headers.Cookie = rawCookies;
  }

  try {
    console.log(
      `[BFF] ${request.method} /api/admin/payouts/${pathString} → FGP:8100` +
        ` | auth=${token ? `Bearer(${token.slice(0, 8)}…)` : "NONE"}` +
        `${token ? " | cookie-injected" : ""}`,
    );
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
      redirect: "follow",
    });

    if (upstream.status === 401) {
      console.error(
        `[BFF] AUTH FAILURE 401 ← FGP:8100 | path=/api/admin/payouts/${pathString}` +
          ` | token=${token ? "present" : "MISSING"}`,
      );
    } else {
      console.log(
        `[BFF] ${request.method} /api/admin/payouts/${pathString} ← ${upstream.status}` +
          ` (${upstream.headers.get("content-type") || "unknown"})`,
      );
    }

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  } catch (err) {
    console.error(`[BFF] ${request.method} /api/admin/payouts/${pathString} proxy error:`, err);
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}

export const GET = forwardToBackend;
export const POST = forwardToBackend;
export const PUT = forwardToBackend;
export const PATCH = forwardToBackend;
export const DELETE = forwardToBackend;
export const OPTIONS = forwardToBackend;
