import { NextRequest, NextResponse } from "next/server";

import { buildBackendUrl } from "@/lib/server/backend-url";

export async function GET(request: NextRequest) {
  const sessionId = request.nextUrl.searchParams.get("session_id");
  if (!sessionId?.trim()) {
    return NextResponse.json({ detail: "session_id required" }, { status: 400 });
  }

  const upstreamUrl = new URL(buildBackendUrl("/api/storefront/intent/nudge"));
  upstreamUrl.searchParams.set("session_id", sessionId.trim());

  try {
    const upstream = await fetch(upstreamUrl.toString(), {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(15_000),
    });
    const text = await upstream.text();
    let data: unknown;
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      data = { detail: text || upstream.statusText };
    }
    if (!upstream.ok) {
      return NextResponse.json(data, { status: upstream.status });
    }
    return NextResponse.json(data, {
      status: 200,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ detail: msg }, { status: 502 });
  }
}
