import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const subpath = path.join("/");
  const url = new URL(request.url);
  const target = `${BACKEND}/api/${subpath}${url.search}`;

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

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: upstream.headers,
    });
  } catch (err) {
    console.error(`[BFF] ${request.method} /api/${subpath} proxy error:`, err);
    return NextResponse.json({ detail: "Backend unreachable" }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
