import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const SESSION_COOKIE = "fortress_session";

function extractAuth(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};

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
  if (token && !rawCookies.includes(`${SESSION_COOKIE}=`)) {
    headers["Cookie"] = rawCookies
      ? `${rawCookies}; ${SESSION_COOKIE}=${token}`
      : `${SESSION_COOKIE}=${token}`;
  } else if (rawCookies) {
    headers["Cookie"] = rawCookies;
  }

  return headers;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const target = buildBackendUrl(`/api/legal/cases/${encodeURIComponent(slug)}/state`);

  const authHeaders = extractAuth(request);
  console.log(`[BFF] GET /api/legal/cases/${slug}/state → ${target}`);

  try {
    const upstream = await fetch(target, {
      method: "GET",
      headers: { ...authHeaders, Accept: "application/json" },
      signal: AbortSignal.timeout(15_000),
    });

    if (!upstream.ok) {
      const errText = await upstream.text().catch(() => "Unknown error");
      console.error(`[BFF] Upstream ${upstream.status}: ${errText.slice(0, 200)}`);
      return NextResponse.json(
        { detail: `Backend returned ${upstream.status}` },
        { status: upstream.status },
      );
    }

    const data = await upstream.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF] GET state failed: ${message}`);
    return NextResponse.json({ detail: "Failed to fetch war room state" }, { status: 502 });
  }
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const target = buildBackendUrl(`/api/legal/cases/${encodeURIComponent(slug)}/state`);

  const authHeaders = extractAuth(request);
  console.log(`[BFF] PATCH /api/legal/cases/${slug}/state → ${target}`);

  try {
    const body = await request.text();

    const upstream = await fetch(target, {
      method: "PATCH",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body,
      signal: AbortSignal.timeout(15_000),
    });

    if (!upstream.ok) {
      const errText = await upstream.text().catch(() => "Unknown error");
      console.error(`[BFF] Upstream ${upstream.status}: ${errText.slice(0, 200)}`);
      return NextResponse.json(
        { detail: `Backend returned ${upstream.status}` },
        { status: upstream.status },
      );
    }

    const data = await upstream.json();
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF] PATCH state failed: ${message}`);
    return NextResponse.json({ detail: "Failed to save war room state" }, { status: 502 });
  }
}
