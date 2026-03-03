import { NextRequest } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";
const SESSION_COOKIE = "fortress_session";

/**
 * SSE proxy for Legal Council of 9 deliberation.
 *
 * The catch-all BFF proxy buffers responses before returning them,
 * which breaks SSE streaming. This dedicated route pipes the
 * text/event-stream directly from the FastAPI backend to the client.
 *
 * Auth: Extracts Bearer token from the Authorization header and also
 * injects it as a fortress_session cookie for Command Center compat.
 */
export async function POST(request: NextRequest) {
  const target = `${FGP_BACKEND}/api/legal/council/deliberate`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };

  // Extract auth token from Bearer header or session cookie
  let token: string | null = null;
  const authHeader = request.headers.get("authorization");
  if (authHeader?.startsWith("Bearer ")) {
    token = authHeader.slice(7);
    headers["Authorization"] = authHeader;
  }

  const sessionCookie = request.cookies.get(SESSION_COOKIE);
  if (!token && sessionCookie?.value) {
    token = sessionCookie.value;
    headers["Authorization"] = `Bearer ${token}`;
  }

  // Forward cookies + inject fortress_session if needed
  const rawCookies = request.headers.get("cookie") || "";
  if (token && !rawCookies.includes(`${SESSION_COOKIE}=`)) {
    headers["Cookie"] = rawCookies
      ? `${rawCookies}; ${SESSION_COOKIE}=${token}`
      : `${SESSION_COOKIE}=${token}`;
  } else if (rawCookies) {
    headers["Cookie"] = rawCookies;
  }

  console.log(
    `[BFF-SSE] POST /api/legal/council/stream → ${target}` +
      ` | auth=${token ? "yes" : "NONE"}`,
  );

  try {
    const body = await request.text();

    const upstream = await fetch(target, {
      method: "POST",
      headers,
      body,
      signal: AbortSignal.timeout(600_000),
    });

    if (!upstream.ok || !upstream.body) {
      const errorText = await upstream.text().catch(() => "Unknown error");
      console.error(
        `[BFF-SSE] Upstream returned ${upstream.status}: ${errorText.slice(0, 200)}`,
      );
      return new Response(
        JSON.stringify({
          detail: `Legal Council backend returned ${upstream.status}`,
        }),
        {
          status: upstream.status || 502,
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-store",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF-SSE] FATAL: ${message}`);
    return new Response(
      JSON.stringify({ detail: "Legal Council stream failed" }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }
}
