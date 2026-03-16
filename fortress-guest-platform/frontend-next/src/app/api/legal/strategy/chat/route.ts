import { NextRequest } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const SESSION_COOKIE = "fortress_session";

/**
 * BFF SSE proxy for the Legal Strategy Terminal.
 *
 * Pipes the text/event-stream directly from the FastAPI backend to the
 * client without buffering, preserving real-time token streaming.
 */
export async function POST(request: NextRequest) {
  const target = `${FGP_BACKEND}/api/legal/strategy/chat`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };

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

  const rawCookies = request.headers.get("cookie") || "";
  if (rawCookies) headers["Cookie"] = rawCookies;

  console.log(
    `[BFF-SSE] POST /api/legal/strategy/chat → FGP:8100 | auth=${token ? "yes" : "NONE"}`,
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
        `[BFF-SSE] Strategy upstream returned ${upstream.status}: ${errorText.slice(0, 200)}`,
      );
      return new Response(
        JSON.stringify({
          detail: `Strategy backend returned ${upstream.status}`,
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
    console.error(`[BFF-SSE] FATAL strategy chat: ${message}`);
    return new Response(
      JSON.stringify({ detail: "Strategy terminal stream failed" }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }
}
