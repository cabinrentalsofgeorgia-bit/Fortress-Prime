import { NextRequest } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const SESSION_COOKIE = "fortress_session";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 300;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  const upstreamUrl = new URL(
    buildBackendUrl(`/api/legal/council/${encodeURIComponent(jobId)}/stream`),
  );
  const cursor = request.nextUrl.searchParams.get("cursor");
  if (cursor) {
    upstreamUrl.searchParams.set("cursor", cursor);
  }

  const headers: Record<string, string> = {
    Accept: "text/event-stream",
  };

  let token: string | null = null;
  const authHeader = request.headers.get("authorization");
  if (authHeader?.startsWith("Bearer ")) {
    token = authHeader.slice(7);
    headers.Authorization = authHeader;
  }

  const sessionCookie = request.cookies.get(SESSION_COOKIE);
  if (!token && sessionCookie?.value) {
    token = sessionCookie.value;
    headers.Authorization = `Bearer ${token}`;
  }

  const rawCookies = request.headers.get("cookie") || "";
  if (rawCookies) {
    headers.Cookie = rawCookies;
  }

  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) {
    headers["Last-Event-ID"] = lastEventId;
  }

  try {
    const upstream = await fetch(upstreamUrl, {
      method: "GET",
      headers,
      signal: AbortSignal.timeout(600_000),
    });

    if (!upstream.ok || !upstream.body) {
      const errorText = await upstream.text().catch(() => "Unknown error");
      return new Response(
        JSON.stringify({
          detail: `Legal council stream backend returned ${upstream.status}`,
          upstream_error: errorText.slice(0, 300),
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
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return new Response(
      JSON.stringify({ detail: "Legal council SSE proxy failed", error: message }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      },
    );
  }
}
