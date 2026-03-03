import { NextRequest, NextResponse } from "next/server";

const LEGAL_API = process.env.LEGAL_API_URL || "http://localhost:8100";
const TIMEOUT_MS = 60_000;

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const subpath = path.join("/");
  const backendUrl = new URL(`/api/legal/${subpath}`, LEGAL_API);

  const qs = request.nextUrl.searchParams.toString();
  if (qs) backendUrl.search = qs;

  const cookie = request.cookies.get("fortress_session")?.value;
  const authHeader = request.headers.get("authorization");
  const isDownload = subpath.includes("/download");

  if (!cookie && !authHeader && !isDownload) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const headers: Record<string, string> = {};
  if (!isDownload) headers["Accept"] = "application/json";
  if (cookie) headers["Cookie"] = `fortress_session=${cookie}`;
  if (authHeader) headers["Authorization"] = authHeader;

  const contentType = request.headers.get("content-type");
  const isMultipart = contentType?.includes("multipart/form-data");

  if (contentType && !isMultipart) headers["Content-Type"] = contentType;
  if (isMultipart && contentType) headers["Content-Type"] = contentType;

  let body: BodyInit | null = null;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = isMultipart
      ? Buffer.from(await request.arrayBuffer())
      : await request.text();
  }

  try {
    const upstream = await fetch(backendUrl.toString(), {
      method: request.method,
      headers,
      body,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });

    if (!upstream.ok) {
      const detail = await upstream.text().catch(() => upstream.statusText);
      console.error(
        `[BFF /api/legal/${subpath}] Backend ${upstream.status}: ${detail.slice(0, 500)}`,
      );
      return new NextResponse(detail, {
        status: upstream.status,
        headers: {
          "Content-Type":
            upstream.headers.get("Content-Type") || "application/json",
        },
      });
    }

    if (isDownload) {
      const responseHeaders: Record<string, string> = {
        "Cache-Control": "no-store, max-age=0",
      };
      const ct = upstream.headers.get("content-type");
      if (ct) responseHeaders["Content-Type"] = ct;
      const cd = upstream.headers.get("content-disposition");
      if (cd) responseHeaders["Content-Disposition"] = cd;
      const cl = upstream.headers.get("content-length");
      if (cl) responseHeaders["Content-Length"] = cl;

      return new NextResponse(upstream.body, {
        status: upstream.status,
        headers: responseHeaders,
      });
    }

    const data = await upstream.text();
    return new NextResponse(data, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") || "application/json",
        "Cache-Control": "no-store, max-age=0",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF /api/legal/${subpath}] Fetch failed: ${message}`);
    return NextResponse.json(
      { error: "Backend unreachable", detail: message },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
