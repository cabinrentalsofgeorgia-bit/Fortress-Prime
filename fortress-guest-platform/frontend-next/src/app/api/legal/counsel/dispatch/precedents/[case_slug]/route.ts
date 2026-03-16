import { NextRequest, NextResponse } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const SESSION_COOKIE = "fortress_session";

/**
 * BFF proxy for Case Precedents lookup.
 * GET /api/legal/counsel/dispatch/precedents/{case_slug} → FGP:8100
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ case_slug: string }> },
) {
  const { case_slug } = await params;
  const target = `${FGP_BACKEND}/api/legal/counsel/dispatch/precedents/${encodeURIComponent(case_slug)}`;

  const headers: Record<string, string> = {};

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

  try {
    const res = await fetch(target, { headers, signal: AbortSignal.timeout(30_000) });
    const status = res.status;
    const resBody = await res.text();

    return new NextResponse(resBody, {
      status,
      headers: {
        "Content-Type": res.headers.get("content-type") || "application/json",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF] FATAL precedents/${case_slug}: ${message}`);
    return NextResponse.json(
      {
        type: "https://fortress/errors/upstream-unreachable",
        title: "Precedents Backend Unreachable",
        status: 502,
        detail: "FGP backend unavailable for precedent lookup",
      },
      { status: 502 },
    );
  }
}
