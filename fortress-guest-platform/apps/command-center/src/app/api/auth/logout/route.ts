import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "fortress_session";
const OWNER_COOKIE = "fgp_owner_token";

export async function POST(request: NextRequest) {
  const isSecure =
    request.headers.get("x-forwarded-proto") === "https" ||
    request.nextUrl.protocol === "https:";
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, "", {
    httpOnly: true,
    secure: isSecure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  response.cookies.set(OWNER_COOKIE, "", {
    httpOnly: true,
    secure: isSecure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return response;
}
