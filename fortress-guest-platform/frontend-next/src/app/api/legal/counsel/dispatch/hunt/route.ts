import { NextRequest, NextResponse } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const SESSION_COOKIE = "fortress_session";

/**
 * BFF proxy for Outside Counsel Headhunter.
 * POST /api/legal/counsel/dispatch/hunt → FGP:8100
 */
export async function POST(request: NextRequest) {
  const target = `${FGP_BACKEND}/api/legal/counsel/dispatch/hunt`;

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
    `[BFF] POST /api/legal/counsel/dispatch/hunt → FGP:8100 | auth=${
      headers["Authorization"] ? "present" : "NONE"
    }`,
  );

  try {
    const body = await request.text();
    const res = await fetch(target, {
      method: "POST",
      headers,
      body,
      signal: AbortSignal.timeout(180_000),
    });

    const status = res.status;

    console.log(
      `[BFF] POST /api/legal/counsel/dispatch/hunt ← ${status}`,
    );

    const resBody = await res.text();
    return new NextResponse(resBody, {
      status,
      headers: {
        "Content-Type": res.headers.get("content-type") || "application/json",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(
      `[BFF] FATAL /api/legal/counsel/dispatch/hunt: ${message}`,
    );
    return NextResponse.json(
      {
        type: "https://fortress/errors/upstream-unreachable",
        title: "Counsel Hunt Backend Unreachable",
        status: 502,
        detail: "FGP backend unavailable for attorney search",
      },
      { status: 502 },
    );
  }
}
