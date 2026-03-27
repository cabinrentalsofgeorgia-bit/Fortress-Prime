import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const UPSTREAM = buildBackendUrl("/api/system/sensors/email");

function forwardHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  const cookie = request.cookies.get("fortress_session")?.value;
  if (cookie) headers["Cookie"] = `fortress_session=${cookie}`;
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  return headers;
}

export async function GET(request: NextRequest) {
  try {
    const upstream = await fetch(UPSTREAM, {
      method: "GET",
      headers: forwardHeaders(request),
      signal: AbortSignal.timeout(10_000),
    });
    if (!upstream.ok) {
      console.error(`[BFF /api/system/sensors] GET ${upstream.status} ${upstream.statusText}`);
      return NextResponse.json(
        { error: `Backend ${upstream.status}`, detail: upstream.statusText },
        { status: upstream.status },
      );
    }
    const data = await upstream.json();
    return NextResponse.json(data, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF /api/system/sensors] GET failed: ${msg}`);
    return NextResponse.json({ error: "Sensor backend unreachable", detail: msg }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const upstream = await fetch(UPSTREAM, {
      method: "POST",
      headers: forwardHeaders(request),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    });
    if (!upstream.ok) {
      console.error(`[BFF /api/system/sensors] POST ${upstream.status} ${upstream.statusText}`);
      const detail = await upstream.text().catch(() => upstream.statusText);
      return NextResponse.json(
        { error: `Backend ${upstream.status}`, detail },
        { status: upstream.status },
      );
    }
    const data = await upstream.json();
    return NextResponse.json(data, { status: 201 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF /api/system/sensors] POST failed: ${msg}`);
    return NextResponse.json({ error: "Sensor backend unreachable", detail: msg }, { status: 502 });
  }
}

export async function PATCH(request: NextRequest) {
  try {
    const body = await request.json();
    const sensorId = body?.sensor_id;
    if (!sensorId) {
      return NextResponse.json({ error: "sensor_id required in body" }, { status: 400 });
    }
    const upstream = await fetch(`${UPSTREAM}/${sensorId}`, {
      method: "PATCH",
      headers: forwardHeaders(request),
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10_000),
    });
    if (!upstream.ok) {
      const detail = await upstream.text().catch(() => upstream.statusText);
      return NextResponse.json(
        { error: `Backend ${upstream.status}`, detail },
        { status: upstream.status },
      );
    }
    const data = await upstream.json();
    return NextResponse.json(data);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: "Sensor backend unreachable", detail: msg }, { status: 502 });
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const sensorId = searchParams.get("id");
    if (!sensorId) {
      return NextResponse.json({ error: "id query param required" }, { status: 400 });
    }
    const upstream = await fetch(`${UPSTREAM}/${sensorId}`, {
      method: "DELETE",
      headers: forwardHeaders(request),
      signal: AbortSignal.timeout(10_000),
    });
    if (!upstream.ok) {
      const detail = await upstream.text().catch(() => upstream.statusText);
      return NextResponse.json(
        { error: `Backend ${upstream.status}`, detail },
        { status: upstream.status },
      );
    }
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: "Sensor backend unreachable", detail: msg }, { status: 502 });
  }
}
