import { NextRequest } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";
const SESSION_COOKIE = "fortress_session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * BFF SSE proxy for the Fortress Prime telemetry stream.
 *
 * Uses a ReadableStream transform to pipe SSE chunks from the FastAPI
 * backend through Next.js without buffering.
 */
export async function GET(request: NextRequest) {
  const target = `${FGP_BACKEND}/api/admin/prime/stream`;

  const headers: Record<string, string> = {
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

    const reader = upstream.body.getReader();

    const stream = new ReadableStream({
      async pull(controller) {
        try {
          const { done, value } = await reader.read();
          if (done) {
            controller.close();
            return;
          }
          controller.enqueue(value);
        } catch {
          controller.close();
        }
      },
      cancel() {
        reader.cancel();
      },
    });

    return new Response(stream, {
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
    console.error(`[BFF-SSE] FATAL prime stream: ${message}`);
    return new Response(
      JSON.stringify({ detail: "Prime telemetry stream failed" }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }
}
