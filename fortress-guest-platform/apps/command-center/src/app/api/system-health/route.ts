import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";
import { getFortressIngressHeaders } from "@/lib/server/fortress-ingress-headers";

const HEALTH_BACKEND = process.env.HEALTH_BACKEND_URL || buildBackendUrl("/api/system/health");

function logHealthError(event: string, details: Record<string, unknown>) {
  console.error(JSON.stringify({ event, route: "system-health-bff", ...details }));
}

export async function GET(request: NextRequest) {
  const cookie = request.cookies.get("fortress_session")?.value;
  const authHeader = request.headers.get("authorization");

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...getFortressIngressHeaders(request),
  };
  if (cookie) {
    headers["Cookie"] = `fortress_session=${cookie}`;
    headers["Authorization"] = `Bearer ${cookie}`;
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
      logHealthError("system_health_backend_error", {
        status: upstream.status,
        status_text: upstream.statusText,
      });
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
    logHealthError("system_health_fetch_failed", {
      error: message.slice(0, 300),
    });
    return NextResponse.json(
      { error: "Cluster unreachable", detail: message },
      { status: 502 }
    );
  }
}
