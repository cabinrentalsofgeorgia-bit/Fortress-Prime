import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";

function sessionFromCookieHeader(cookieHeader: string | null): string | null {
  if (!cookieHeader) return null;
  const parts = cookieHeader.split(";").map((p) => p.trim());
  const match = parts.find((p) => p.startsWith("fortress_session="));
  if (!match) return null;
  return decodeURIComponent(match.slice("fortress_session=".length));
}

async function forwardToBackend(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const pathString = path.join("/");
  const url = new URL(request.url);
  const target = `${BACKEND}/api/vrs/${pathString}${url.search}`;

  const cookie = request.headers.get("cookie");
  const auth = request.headers.get("authorization");
  const sessionToken = sessionFromCookieHeader(cookie);

  const headers: Record<string, string> = {
    "Content-Type": request.headers.get("content-type") || "application/json",
  };

  if (auth) {
    headers.Authorization = auth;
  } else if (sessionToken) {
    headers.Authorization = `Bearer ${sessionToken}`;
  }
  if (cookie) headers.Cookie = cookie;

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
    });

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  } catch (err) {
    console.error(`[BFF] ${request.method} /api/vrs/${pathString} proxy error:`, err);
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}

export const GET = forwardToBackend;
export const POST = forwardToBackend;
export const PUT = forwardToBackend;
export const PATCH = forwardToBackend;
export const DELETE = forwardToBackend;
export const OPTIONS = forwardToBackend;
