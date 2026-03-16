import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.FGP_BACKEND_URL || "http://127.0.0.1:8100";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const upstream = await fetch(`${BACKEND}/api/auth/sso`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await upstream.json().catch(() => null);

    if (!upstream.ok) {
      console.error(
        `[BFF] POST /api/auth/sso → ${upstream.status}: ${JSON.stringify(data)}`
      );
      return NextResponse.json(
        data ?? { detail: "SSO authentication failed" },
        { status: upstream.status }
      );
    }

    return NextResponse.json(data);
  } catch (err) {
    console.error("[BFF] POST /api/auth/sso proxy error:", err);
    return NextResponse.json(
      { detail: "Backend unreachable" },
      { status: 502 }
    );
  }
}
