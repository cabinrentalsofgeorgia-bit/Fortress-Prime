import { NextRequest, NextResponse } from "next/server";
import { buildBackendUrl } from "@/lib/server/backend-url";

const COMMAND_CENTER =
  process.env.COMMAND_CENTER_URL || "http://localhost:9800";

/** Align HttpOnly cookie TTL with FastAPI JWT `expires_in` (seconds). */
function sessionCookieMaxAgeSeconds(expiresIn: unknown): number {
  if (typeof expiresIn === "number" && Number.isFinite(expiresIn) && expiresIn >= 300) {
    return Math.min(Math.floor(expiresIn), 86400 * 7);
  }
  return 86400;
}

function isLoopbackHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function shouldAttemptGateway(request: NextRequest): boolean {
  try {
    const gatewayUrl = new URL(COMMAND_CENTER);
    const requestUrl = new URL(request.url);
    const sameOrigin = gatewayUrl.origin === requestUrl.origin;
    const sameLocalPort =
      isLoopbackHost(gatewayUrl.hostname) &&
      isLoopbackHost(requestUrl.hostname) &&
      gatewayUrl.port === requestUrl.port;
    return !(sameOrigin || sameLocalPort);
  } catch {
    return true;
  }
}

/**
 * Bulletproof login BFF — dual-path authentication:
 *
 * PATH 1 (Gateway → SSO): Send username/password to the master console,
 *         exchange the gateway JWT for a local FGP token.
 * PATH 2 (Direct FGP):    If the gateway is down or rejects creds,
 *         send { email, password } directly to the FGP backend.
 *
 * IMPORTANT: Both paths now produce FGP-issued RS256 tokens (with a key ID
 * header) so session validation remains consistent across the migration.
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
    : `${identifier}@fortressprime.com`;
  const gatewayCandidates = Array.from(
    new Set([
      identifier,
      identifier.includes("@") ? identifier.split("@")[0] : "",
    ].filter(Boolean))
  );

  const loopbackRequest = isLoopbackHost(request.nextUrl.hostname);

  // ── PATH 1: Gateway (master console) → SSO exchange ──────────────
  let gatewayError: string | null = null;
  const tryGateway = !loopbackRequest && shouldAttemptGateway(request);

  if (tryGateway) {
    for (const gatewayUsername of gatewayCandidates) {
      try {
        const gwRes = await fetch(`${COMMAND_CENTER}/api/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ username: gatewayUsername, password }),
          signal: AbortSignal.timeout(1_500),
        });

        if (gwRes.ok) {
          const gwData = await gwRes.json();
          const gatewayToken: string = gwData.access_token;

          if (gatewayToken) {
            try {
              const ssoRes = await fetch(buildBackendUrl("/api/auth/sso"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ gateway_token: gatewayToken }),
                signal: AbortSignal.timeout(3_000),
              });

              if (ssoRes.ok) {
                const ssoData = await ssoRes.json();
                console.log("[BFF] Login success via gateway → SSO");
                const fgpToken = ssoData.access_token;
                const maxAge = sessionCookieMaxAgeSeconds(ssoData.expires_in);
                const responseBody = {
                  access_token: fgpToken,
                  user: ssoData.user,
                  expires_in: maxAge,
                };
                const ciOverride = process.env.CI === "true";
                const isSecure =
                  !ciOverride && (
                    request.headers.get("x-forwarded-proto") === "https" ||
                    request.nextUrl.protocol === "https:"
                  );

                const resp = NextResponse.json(responseBody);
                if (fgpToken) {
                  resp.cookies.set("fortress_session", fgpToken, {
                    httpOnly: true,
                    secure: isSecure,
                    sameSite: "lax",
                    path: "/",
                    maxAge,
                  });
                }
                return resp;
              } else {
                const ssoErr = await ssoRes.json().catch(() => null);
                const ssoDetail = ssoErr?.detail || `SSO exchange failed (${ssoRes.status})`;
                console.error(
                  `[BFF] SSO exchange failed (${ssoRes.status}), falling back to direct FGP login`
                );
                gatewayError = typeof ssoDetail === "string" ? ssoDetail : JSON.stringify(ssoDetail);
              }
            } catch {
              console.error("[BFF] SSO endpoint unreachable, falling back to direct FGP login");
              gatewayError = "SSO exchange unreachable";
            }
            break;
          }
          gatewayError = "Gateway login token missing";
          break;
        }

        if (gwRes.status === 401 || gwRes.status === 403) {
          const errBody = await gwRes.json().catch(() => null);
          gatewayError = errBody?.detail || "Invalid credentials";
          continue;
        }
        // Non-auth gateway errors should not block direct FGP fallback.
        break;
      } catch {
        console.error("[BFF] Gateway unreachable — falling through to direct FGP");
        break;
      }
    }
  } else {
    console.log("[BFF] Skipping gateway login path for loopback/local auth");
  }

  // ── PATH 2: Direct FGP login fallback (always try with normalized email) ──
  try {
    const fgpRes = await fetch(buildBackendUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ email, password }),
      signal: AbortSignal.timeout(5_000),
    });

    if (fgpRes.ok) {
      const fgpData = await fgpRes.json();
      console.log("[BFF] Login success via direct FGP");

      const ciOverride = process.env.CI === "true";
      const isSecure =
        !ciOverride && (
          request.headers.get("x-forwarded-proto") === "https" ||
          request.nextUrl.protocol === "https:"
        );

      const maxAge = sessionCookieMaxAgeSeconds(fgpData.expires_in);
      const resp = NextResponse.json({
        access_token: fgpData.access_token,
        user: fgpData.user,
        expires_in: maxAge,
      });
      if (fgpData.access_token) {
        resp.cookies.set("fortress_session", fgpData.access_token, {
          httpOnly: true,
          secure: isSecure,
          sameSite: "lax",
          path: "/",
          maxAge,
        });
      }
      return resp;
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

  const backendHint =
    "Next.js cannot reach FastAPI. On the app host, set FGP_BACKEND_URL to the backend base URL (e.g. http://127.0.0.1:8100) in the fortress-frontend systemd unit and restart. If the browser shows OpenAPI / JSON at https://crog-ai.com, Cloudflare ingress is pointing at :8100; it must target Next.js on :3001 (see fortress-guest-platform/infra/gateway/config.yml).";

  // Both paths exhausted — return the best available error
  if (gatewayError) {
    return NextResponse.json({ detail: gatewayError }, { status: 401 });
  }

  return NextResponse.json(
    { detail: "Authentication service unreachable", hint: backendHint },
    { status: 502 }
  );
}
