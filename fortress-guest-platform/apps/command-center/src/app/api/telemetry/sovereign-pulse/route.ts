import { NextRequest, NextResponse } from "next/server";

import { buildBackendUrl } from "@/lib/server/backend-url";

const UPSTREAM = buildBackendUrl("/api/telemetry/sovereign-pulse");

function forwardHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const cookie = request.cookies.get("fortress_session")?.value;
  if (cookie) {
    headers["Cookie"] = `fortress_session=${cookie}`;
    headers["Authorization"] = `Bearer ${cookie}`;
  }
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  return headers;
}

export async function GET(request: NextRequest) {
  try {
    const upstream = await fetch(UPSTREAM, {
      method: "GET",
      headers: forwardHeaders(request),
      signal: AbortSignal.timeout(25_000),
    });
    if (!upstream.ok) {
      const detail = await upstream.text();
      return NextResponse.json(
        { error: `Backend ${upstream.status}`, detail: detail.slice(0, 500) },
        { status: upstream.status },
      );
    }
    const data = await upstream.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: "Sovereign Pulse unreachable", detail: msg }, { status: 502 });
  }
}
