import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const SESSION_COOKIE = "fortress_session";

/**
 * BFF proxy for E-Discovery extraction.
 *
 * Dedicated route so the catch-all proxy (which sends /api/legal/* to the
 * Command Center on port 9800) does not intercept this endpoint.
 * The e-discovery service lives on the FGP backend (port 8100).
 */
export async function POST(request: NextRequest) {
  const target = buildBackendUrl("/api/legal/discovery/extract");

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const authHeader = request.headers.get("authorization");
  if (authHeader?.startsWith("Bearer ")) {
    headers["Authorization"] = authHeader;
  } else {
    const sessionCookie = request.cookies.get(SESSION_COOKIE);
    if (sessionCookie?.value) {
      headers["Authorization"] = `Bearer ${sessionCookie.value}`;
    }
  }

  const rawCookies = request.headers.get("cookie");
  if (rawCookies) headers["Cookie"] = rawCookies;

  console.log(
    `[BFF] POST /api/legal/discovery/extract → FGP:8100 | auth=${
      headers["Authorization"] ? "present" : "NONE"
    }`,
  );

  try {
    const body = await request.text();
    const res = await fetch(target, {
      method: "POST",
      headers,
      body,
      signal: AbortSignal.timeout(120_000),
    });

    const status = res.status;
    const contentType = res.headers.get("content-type") || "application/json";
    const responseBody = await res.text();

    console.log(
      `[BFF] POST /api/legal/discovery/extract ← ${status} (${contentType})`,
    );

    return new NextResponse(responseBody, {
      status,
      headers: { "Content-Type": contentType },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF] FATAL /api/legal/discovery/extract: ${message}`);
    return NextResponse.json(
      {
        type: "https://fortress/errors/upstream-unreachable",
        title: "E-Discovery Backend Unreachable",
        status: 502,
        detail: "FGP backend unavailable for e-discovery",
      },
      { status: 502 },
    );
  }
}
