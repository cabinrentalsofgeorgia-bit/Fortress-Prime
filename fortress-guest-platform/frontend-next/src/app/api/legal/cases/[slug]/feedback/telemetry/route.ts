import { NextRequest, NextResponse } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
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

  const rawCookies = request.headers.get("cookie");
  if (rawCookies) {
    headers["Cookie"] = rawCookies;
  }

  return headers;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const target = `${FGP_BACKEND}/api/legal/cases/${encodeURIComponent(slug)}/feedback/telemetry`;
  const authHeaders = extractAuth(request);

  try {
    const body = await request.text();
    const upstream = await fetch(target, {
      method: "POST",
      headers: {
        ...authHeaders,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body,
      signal: AbortSignal.timeout(15_000),
    });

    const raw = await upstream.text();
    let data: unknown = null;
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: raw };
      }
    }

    return NextResponse.json(data ?? {}, { status: upstream.status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF] telemetry proxy failed: ${message}`);
    return NextResponse.json({ detail: "Failed to proxy telemetry" }, { status: 502 });
  }
}
