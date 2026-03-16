import { NextRequest, NextResponse } from "next/server";

const HEALTH_BACKEND = process.env.HEALTH_BACKEND_URL || "http://127.0.0.1:9876/api/health";

export async function GET(request: NextRequest) {
  const cookie = request.cookies.get("fortress_session")?.value;
  const authHeader = request.headers.get("authorization");

  const headers: Record<string, string> = {
    "Accept": "application/json",
  };
  if (cookie) {
    headers["Cookie"] = `fortress_session=${cookie}`;
  }
  if (authHeader) {
    headers["Authorization"] = authHeader;
  }

  try {
    const upstream = await fetch(HEALTH_BACKEND, {
      method: "GET",
      headers,
      signal: AbortSignal.timeout(30_000),
    });

    if (!upstream.ok) {
      console.error(
        `[BFF /api/system-health] Backend returned ${upstream.status} ${upstream.statusText}`
      );
      return NextResponse.json(
        { error: `Backend returned ${upstream.status}`, detail: upstream.statusText },
        { status: upstream.status }
      );
    }

    const data = await upstream.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF /api/system-health] Fetch failed: ${message}`);
    return NextResponse.json(
      { error: "Cluster unreachable", detail: message },
      { status: 502 }
    );
  }
}
