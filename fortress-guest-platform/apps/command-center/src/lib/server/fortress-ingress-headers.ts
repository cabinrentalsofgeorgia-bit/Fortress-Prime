import type { NextRequest } from "next/server";

/** Same tunnel + forwarded headers as apps/command-center/src/app/api/[...path]/route.ts */
const INTERNAL_TUNNEL_SIGNATURE =
  process.env.INTERNAL_API_TOKEN || process.env.SWARM_API_KEY || "";

/**
 * Forward browser + tunnel context so FastAPI `GlobalAuthMiddleware` accepts
 * server-side BFF fetches (no browser Origin unless we copy it from the inbound request).
 */
export function buildFortressIngressHeaders(request: NextRequest): Record<string, string> {
  const headers: Record<string, string> = {};
  const origin = request.headers.get("origin");
  const referer = request.headers.get("referer");
  if (origin) headers["Origin"] = origin;
  if (referer) headers["Referer"] = referer;
  const host = request.headers.get("host") || request.nextUrl.host;
  if (host) headers["X-Forwarded-Host"] = host;
  const xff = request.headers.get("x-forwarded-for");
  if (xff) headers["X-Forwarded-For"] = xff;

  if (INTERNAL_TUNNEL_SIGNATURE) {
    headers["X-Fortress-Ingress"] = "command_center";
    headers["X-Fortress-Tunnel-Signature"] = INTERNAL_TUNNEL_SIGNATURE;
  }
  return headers;
}

/** Alias for call sites that prefer `get*` naming. */
export const getFortressIngressHeaders = buildFortressIngressHeaders;
