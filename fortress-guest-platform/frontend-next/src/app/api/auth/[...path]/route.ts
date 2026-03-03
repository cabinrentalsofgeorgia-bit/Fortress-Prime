import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const subpath = path.join("/");
  const url = new URL(request.url);
  const target = `${BACKEND}/api/auth/${subpath}${url.search}`;

  const headers: Record<string, string> = {
    "Content-Type": request.headers.get("content-type") || "application/json",
  };
  const auth = request.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;

  const cookie = request.headers.get("cookie");
  if (cookie) headers["Cookie"] = cookie;

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
    });

    const data = await upstream.text();

    const responseHeaders = new Headers({
      "Content-Type": upstream.headers.get("content-type") || "application/json",
    });

    const setCookies =
      typeof upstream.headers.getSetCookie === "function"
        ? upstream.headers.getSetCookie()
        : [];
    for (const sc of setCookies) {
      responseHeaders.append("Set-Cookie", sc);
    }

    return new NextResponse(data, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (err) {
    console.error(`[BFF] ${request.method} /api/auth/${subpath} proxy error:`, err);
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
