import { NextRequest } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";
import { getFortressIngressHeaders } from "@/lib/server/fortress-ingress-headers";

const SESSION_COOKIE = "fortress_session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 300;

/**
 * BFF SSE proxy for the Fortress Prime telemetry stream.
 *
 * Uses a ReadableStream transform to pipe SSE chunks from the FastAPI
 * backend through Next.js without buffering.
 */
export async function GET(request: NextRequest) {
  const target = buildBackendUrl("/api/admin/prime/stream");

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
    ...getFortressIngressHeaders(request),
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
    `[BFF-SSE] GET /api/admin/prime/stream → FGP:8100 | auth=${token ? "yes" : "NONE"}`,
  );

  try {
    const upstream = await fetch(target, {
      method: "GET",
      headers,
      signal: AbortSignal.timeout(600_000),
    });

    if (!upstream.ok || !upstream.body) {
      const errorText = await upstream.text().catch(() => "Unknown error");
      console.error(
        `[BFF-SSE] Prime stream upstream returned ${upstream.status}: ${errorText.slice(0, 200)}`,
      );
      return new Response(
        JSON.stringify({
          detail: `Prime stream backend returned ${upstream.status}`,
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
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF-SSE] FATAL prime stream: ${message}`);
    return new Response(
      JSON.stringify({ detail: "Prime telemetry stream failed" }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }
}
