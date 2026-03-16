import { NextRequest, NextResponse } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const COMMAND_CENTER =
  process.env.COMMAND_CENTER_URL || "http://127.0.0.1:9800";

const COMMAND_CENTER_PREFIXES = [
  "/api/vrs/",
  "/api/service-health",
  "/api/cluster-telemetry",
  "/api/bridge/",
  "/api/email-intake/",
  "/api/login",
  "/api/logout",
  "/api/verify",
  "/api/signup",
  "/api/profile",
  "/api/users",
];

const SESSION_COOKIE = "fortress_session";

function resolveUpstream(pathname: string): { base: string; isCC: boolean } {
  const isCC = COMMAND_CENTER_PREFIXES.some((p) => pathname.startsWith(p));
  return { base: isCC ? COMMAND_CENTER : FGP_BACKEND, isCC };
}

/**
 * Extract the auth token from the inbound request.
 *
 * Priority order:
 *   1. Authorization: Bearer <token>  (set by api.ts from localStorage)
 *   2. fortress_session cookie         (set by Command Center login)
 *   3. x-fgp-token header             (escape hatch for edge cases)
 */
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

/**
 * Build outgoing headers with strict auth injection.
 *
 * The Command Center's get_current_user() ONLY reads the fortress_session
 * cookie — it ignores Authorization headers. So for CC-bound requests we
 * MUST synthesize the cookie from the Bearer token.
 *
 * The FGP backend accepts Authorization: Bearer, so we always set that too.
 */
function buildUpstreamHeaders(
  request: NextRequest,
  token: string | null,
  isCC: boolean,
): Record<string, string> {
  const headers: Record<string, string> = {};

  const ct = request.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;

  const accept = request.headers.get("accept");
  if (accept) headers["Accept"] = accept;

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const rawCookies = request.headers.get("cookie") || "";

  if (isCC && token) {
    if (rawCookies.includes(`${SESSION_COOKIE}=`)) {
      headers["Cookie"] = rawCookies;
    } else {
      headers["Cookie"] = rawCookies
        ? `${rawCookies}; ${SESSION_COOKIE}=${token}`
        : `${SESSION_COOKIE}=${token}`;
    }
  } else if (rawCookies) {
    headers["Cookie"] = rawCookies;
  }

  const xff = request.headers.get("x-forwarded-for") || "";
  if (xff) headers["X-Forwarded-For"] = xff;

  return headers;
}

/**
 * Single catch-all BFF proxy for every /api/* path not handled by an
 * exact-match route handler (auth/login, auth/sso, system-health).
 *
 * Uses redirect: "follow" so FastAPI trailing-slash 307s are resolved
 * server-side — the browser never sees the redirect, preventing the
 * infinite loop where Next.js strips the trailing slash on each bounce.
 */
async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  await params;
  const pathname = request.nextUrl.pathname;
  const { base, isCC } = resolveUpstream(pathname);
  const target = `${base}${pathname}${request.nextUrl.search}`;
  const upstream = isCC ? "CC:9800" : "FGP:8100";

  const token = extractToken(request);
  const headers = buildUpstreamHeaders(request, token, isCC);

  console.log(
    `[BFF] ${request.method} ${pathname} → ${upstream}` +
      ` | auth=${token ? `Bearer(${token.slice(0, 8)}…)` : "NONE"}` +
      `${isCC && token ? " | cookie-injected" : ""}`,
  );

  try {
    const hasBody = !["GET", "HEAD"].includes(request.method);
    const body = hasBody ? await request.arrayBuffer() : undefined;

    const res = await fetch(target, {
      method: request.method,
      headers,
      body: body && body.byteLength > 0 ? Buffer.from(body) : undefined,
      redirect: "follow",
      signal: AbortSignal.timeout(60_000),
    });

    const status = res.status;
    const contentType =
      res.headers.get("content-type") || "application/json";

    if (status === 401) {
      console.error(
        `[BFF] AUTH FAILURE 401 ← ${upstream} | path=${pathname}` +
          ` | token=${token ? "present" : "MISSING"}` +
          ` | cookie-injected=${isCC && !!token}`,
      );
    } else {
      console.log(
        `[BFF] ${request.method} ${pathname} ← ${status} (${contentType})`,
      );
    }

    const responseHeaders = new Headers();
    responseHeaders.set("Content-Type", contentType);

    const setCookies =
      typeof res.headers.getSetCookie === "function"
        ? res.headers.getSetCookie()
        : [];
    for (const sc of setCookies) {
      responseHeaders.append("Set-Cookie", sc);
    }

    const disposition = res.headers.get("content-disposition");
    if (disposition) responseHeaders.set("Content-Disposition", disposition);

    const cacheControl = res.headers.get("cache-control");
    if (cacheControl) responseHeaders.set("Cache-Control", cacheControl);

    const isBinary =
      contentType.includes("pdf") ||
      contentType.includes("octet-stream") ||
      contentType.includes("image/");

    const responseBody = isBinary
      ? Buffer.from(await res.arrayBuffer())
      : await res.text();

    return new NextResponse(responseBody, {
      status,
      headers: responseHeaders,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(
      `[BFF] FATAL ${request.method} ${pathname} → ${upstream}: ${message}`,
    );
    return NextResponse.json(
      {
        type: "https://fortress/errors/upstream-unreachable",
        title: "Backend Unreachable",
        status: 502,
        detail: `Upstream ${upstream} unavailable`,
        instance: pathname,
      },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
