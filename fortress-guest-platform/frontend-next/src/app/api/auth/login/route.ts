import { NextRequest, NextResponse } from "next/server";

const COMMAND_CENTER =
  process.env.COMMAND_CENTER_URL || "http://localhost:9800";
const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";

/**
 * Unified login BFF: authenticates via the master console (gateway),
 * then exchanges the gateway JWT for a local FGP token via SSO.
 * The client sends one request and gets back a fully usable FGP JWT.
 */
export async function POST(request: NextRequest) {
  let body: { username?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Invalid request body" },
      { status: 400 }
    );
  }

  if (!body.username || !body.password) {
    return NextResponse.json(
      { detail: "Username and password are required" },
      { status: 400 }
    );
  }

  // Step 1: Authenticate against the master console (gateway)
  let gatewayToken: string;
  let gatewayUsername: string;
  let gatewayRole: string;

  try {
    const gwRes = await fetch(`${COMMAND_CENTER}/api/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        username: body.username,
        password: body.password,
      }),
    });

    if (!gwRes.ok) {
      const err = await gwRes.json().catch(() => null);
      console.error(
        `[BFF] POST /api/login → ${gwRes.status}: ${JSON.stringify(err)}`
      );
      return NextResponse.json(
        { detail: err?.detail || "Invalid credentials" },
        { status: gwRes.status }
      );
    }

    const gwData = await gwRes.json();
    gatewayToken = gwData.access_token;
    gatewayUsername = gwData.username;
    gatewayRole = gwData.role;
  } catch (err) {
    console.error("[BFF] Master console unreachable:", err);
    return NextResponse.json(
      { detail: "Authentication service unreachable" },
      { status: 502 }
    );
  }

  // Step 2: Exchange gateway token for a local FGP JWT via SSO
  try {
    const ssoRes = await fetch(`${FGP_BACKEND}/api/auth/sso`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ gateway_token: gatewayToken }),
    });

    if (ssoRes.ok) {
      const ssoData = await ssoRes.json();
      return NextResponse.json({
        access_token: ssoData.access_token,
        user: ssoData.user,
        gateway_role: gatewayRole,
      });
    }

    console.error(
      `[BFF] SSO exchange failed: ${ssoRes.status} — falling back to gateway token`
    );
  } catch (err) {
    console.error("[BFF] FGP SSO unreachable — falling back:", err);
  }

  // Fallback: return the gateway token directly with a synthetic user
  return NextResponse.json({
    access_token: gatewayToken,
    user: {
      id: gatewayUsername,
      email: `${gatewayUsername}@fortress.local`,
      first_name: gatewayUsername,
      last_name: "",
      role: gatewayRole || "admin",
      is_active: true,
    },
    gateway_role: gatewayRole,
  });
}
