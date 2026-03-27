import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const SESSION_COOKIE = "fortress_session";

/**
 * BFF proxy for Legal DocGen (DOCX download).
 *
 * Dedicated route overriding the catch-all (which sends /api/legal/* to
 * Command Center). DocGen lives on FGP backend (port 8100).
 * Returns binary DOCX with Content-Disposition for browser download.
 */
export async function POST(request: NextRequest) {
  const target = buildBackendUrl("/api/legal/document/draft");

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
    `[BFF] POST /api/legal/document/draft → FGP:8100 | auth=${
      headers["Authorization"] ? "present" : "NONE"
    }`,
  );

  try {
    const body = await request.text();
    const res = await fetch(target, {
      method: "POST",
      headers,
      body,
      signal: AbortSignal.timeout(60_000),
    });

    const status = res.status;
    const contentType =
      res.headers.get("content-type") || "application/octet-stream";

    console.log(
      `[BFF] POST /api/legal/document/draft ← ${status} (${contentType})`,
    );

    if (status !== 200) {
      const errBody = await res.text();
      return new NextResponse(errBody, {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }

    const docxBuffer = Buffer.from(await res.arrayBuffer());
    const disposition =
      res.headers.get("content-disposition") ||
      'attachment; filename="Answer_and_Defenses.docx"';

    return new NextResponse(docxBuffer, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": disposition,
        "Content-Length": String(docxBuffer.length),
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error(`[BFF] FATAL /api/legal/document/draft: ${message}`);
    return NextResponse.json(
      {
        type: "https://fortress/errors/upstream-unreachable",
        title: "DocGen Backend Unreachable",
        status: 502,
        detail: "FGP backend unavailable for document generation",
      },
      { status: 502 },
    );
  }
}
