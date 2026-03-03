import { NextRequest, NextResponse } from "next/server";

const COMMAND_CENTER =
  process.env.COMMAND_CENTER_URL || "http://localhost:9800";
const FGP_BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";

/**
 * Bulletproof login BFF — dual-path authentication:
 *
 * PATH 1 (Gateway → SSO): Send username/password to the master console,
 *         exchange the gateway JWT for a local FGP token.
 * PATH 2 (Direct FGP):    If the gateway is down or rejects creds,
 *         send { email, password } directly to the FGP backend.
 *
 * The frontend may send { email, password } or { username, password }.
 * This handler normalizes both into the correct format for each backend.
 */
export async function POST(request: NextRequest) {
  let body: { username?: string; email?: string; password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Invalid request body" },
      { status: 400 }
    );
  }

  const identifier = (body.email || body.username || "").trim();
  const password = body.password || "";

  if (!identifier || !password) {
    return NextResponse.json(
      { detail: "Email and password are required" },
      { status: 400 }
    );
  }

  const email = identifier.includes("@")
    ? identifier
    : `${identifier}@fortress.local`;

  // ── PATH 1: Gateway (master console) → SSO exchange ──────────────
  let gatewayError: string | null = null;

  try {
    const gwRes = await fetch(`${COMMAND_CENTER}/api/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username: identifier, password }),
    });

    if (gwRes.ok) {
      const gwData = await gwRes.json();
      const gatewayToken: string = gwData.access_token;

      if (gatewayToken) {
        try {
          const ssoRes = await fetch(`${FGP_BACKEND}/api/auth/sso`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ gateway_token: gatewayToken }),
          });

          if (ssoRes.ok) {
            const ssoData = await ssoRes.json();
            console.log("[BFF] Login success via gateway → SSO");
            return NextResponse.json({
              access_token: ssoData.access_token,
              user: ssoData.user,
            });
          }

          console.error(
            `[BFF] SSO exchange failed (${ssoRes.status}), returning gateway token`
          );
        } catch (ssoErr) {
          console.error("[BFF] SSO endpoint unreachable, returning gateway token");
        }

        return NextResponse.json({
          access_token: gatewayToken,
          user: {
            id: gwData.username || identifier,
            email,
            first_name: gwData.full_name || gwData.username || identifier,
            last_name: "",
            role: gwData.role || "admin",
            is_active: true,
          },
        });
      }
    }

    if (gwRes.status === 401 || gwRes.status === 403) {
      const errBody = await gwRes.json().catch(() => null);
      gatewayError = errBody?.detail || "Invalid credentials";
    }
  } catch {
    console.error("[BFF] Gateway unreachable — falling through to direct FGP");
  }

  // ── PATH 2: Direct FGP login (only if identifier is a valid email) ──
  const isEmail = identifier.includes("@");

  if (isEmail) {
    try {
      const fgpRes = await fetch(`${FGP_BACKEND}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ email, password }),
      });

      if (fgpRes.ok) {
        const fgpData = await fgpRes.json();
        console.log("[BFF] Login success via direct FGP");
        return NextResponse.json({
          access_token: fgpData.access_token,
          user: fgpData.user,
        });
      }

      const errBody = await fgpRes.json().catch(() => null);
      const raw = errBody?.detail ?? errBody?.error ?? gatewayError ?? "Invalid credentials";
      const detail =
        typeof raw === "string"
          ? raw
          : Array.isArray(raw)
            ? raw.map((e: Record<string, unknown>) => e?.msg ?? e?.message ?? JSON.stringify(e)).join("; ")
            : JSON.stringify(raw);

      console.error(`[BFF] Direct FGP login failed: ${fgpRes.status} — ${detail}`);
      return NextResponse.json({ detail }, { status: fgpRes.status });
    } catch (fgpErr) {
      console.error("[BFF] FGP backend unreachable:", fgpErr);
    }
  }

  // Both paths exhausted — return the best available error
  if (gatewayError) {
    return NextResponse.json({ detail: gatewayError }, { status: 401 });
  }

  return NextResponse.json(
    { detail: "Authentication service unreachable" },
    { status: 502 }
  );
}
