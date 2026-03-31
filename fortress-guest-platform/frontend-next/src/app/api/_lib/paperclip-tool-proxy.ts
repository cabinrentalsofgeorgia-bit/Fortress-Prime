import { NextRequest, NextResponse } from "next/server";

const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";
const SESSION_COOKIE = "fortress_session";

function buildForwardHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};

  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  const accept = request.headers.get("accept");
  if (accept) headers["Accept"] = accept;

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

  const xff = request.headers.get("x-forwarded-for");
  if (xff) headers["X-Forwarded-For"] = xff;

  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers["User-Agent"] = userAgent;

  return headers;
}

export async function proxyPaperclipTool(
  request: NextRequest,
  upstreamPath: string,
  timeoutMs = 600_000,
): Promise<NextResponse> {
  const target = `${FGP_BACKEND}${upstreamPath}${request.nextUrl.search}`;
  const headers = buildForwardHeaders(request);

  console.log(
    `[BFF] ${request.method} ${request.nextUrl.pathname} → FGP:8100 | timeout=${timeoutMs}ms | auth=${
      headers["Authorization"] ? "present" : "NONE"
    }`,
  );

  try {
    const hasBody = !["GET", "HEAD"].includes(request.method);
    const body = hasBody ? await request.arrayBuffer() : undefined;

    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: body && body.byteLength > 0 ? Buffer.from(body) : undefined,
      redirect: "follow",
      signal: AbortSignal.timeout(timeoutMs),
    });

    const responseHeaders = new Headers();
    responseHeaders.set(
      "Content-Type",
      upstream.headers.get("content-type") || "application/json",
    );

    const setCookies =
      typeof upstream.headers.getSetCookie === "function"
        ? upstream.headers.getSetCookie()
        : [];
    for (const sc of setCookies) {
      responseHeaders.append("Set-Cookie", sc);
    }

    const cacheControl = upstream.headers.get("cache-control");
    if (cacheControl) responseHeaders.set("Cache-Control", cacheControl);

    const disposition = upstream.headers.get("content-disposition");
    if (disposition) responseHeaders.set("Content-Disposition", disposition);

    const contentType = responseHeaders.get("Content-Type") || "";
    const isBinary =
      contentType.includes("pdf") ||
      contentType.includes("octet-stream") ||
      contentType.includes("image/");

    const payload = isBinary
      ? Buffer.from(await upstream.arrayBuffer())
      : await upstream.text();

    console.log(
      `[BFF] ${request.method} ${request.nextUrl.pathname} ← ${upstream.status} (${contentType})`,
    );

    return new NextResponse(payload, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(
      `[BFF] FATAL ${request.method} ${request.nextUrl.pathname} → FGP:8100: ${message}`,
    );
    return NextResponse.json(
      {
        type: "https://fortress/errors/upstream-unreachable",
        title: "Paperclip Tool Backend Unreachable",
        status: 502,
        detail: "FGP backend unavailable for Paperclip tool execution",
        instance: request.nextUrl.pathname,
      },
      { status: 502 },
    );
  }
}
