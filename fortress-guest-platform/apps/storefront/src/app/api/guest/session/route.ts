import { NextRequest, NextResponse } from "next/server";

const GUEST_COOKIE_NAME = "fgp_guest_token";
const GUEST_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

export async function POST(request: NextRequest): Promise<NextResponse> {
  const payload = (await request.json().catch(() => null)) as { token?: string } | null;
  const token = payload?.token?.trim() || "";
  if (!token) {
    return NextResponse.json(
      { detail: "Guest token is required." },
      { status: 400 },
    );
  }

  const response = NextResponse.json({ status: "ok" });
  response.cookies.set({
    name: GUEST_COOKIE_NAME,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/itinerary",
    maxAge: GUEST_COOKIE_MAX_AGE_SECONDS,
  });
  return response;
}

export async function DELETE(): Promise<NextResponse> {
  const response = NextResponse.json({ status: "cleared" });
  response.cookies.set({
    name: GUEST_COOKIE_NAME,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/itinerary",
    maxAge: 0,
  });
  return response;
}
