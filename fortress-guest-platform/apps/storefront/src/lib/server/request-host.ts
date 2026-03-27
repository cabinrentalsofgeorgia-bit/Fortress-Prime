import "server-only";
import { headers } from "next/headers";

/** Normalize Host / X-Forwarded-Host for server components and metadata routes. */
export function hostFromForwardedHeaders(h: Headers): string {
  const forwarded = h.get("x-forwarded-host");
  if (forwarded) {
    return forwarded.split(",")[0]?.trim() ?? "";
  }
  return (h.get("host") ?? "").trim();
}

export async function getRequestHost(): Promise<string> {
  const h = await headers();
  return hostFromForwardedHeaders(h);
}
