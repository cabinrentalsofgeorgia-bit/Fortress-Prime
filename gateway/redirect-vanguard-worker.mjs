/**
 * Strike 8 — Redirect Vanguard ("Switchman")
 *
 * Strangler Fig at the edge for cabin-rentals-of-georgia.com:
 * - GET/HEAD/POST /cabins/{slug} → if KV key exists, proxy to SOVEREIGN_ORIGIN (e.g. Vercel).
 * - Mirrored policy, management, area-guide, and blog routes → proxy to SOVEREIGN_ORIGIN.
 * - All other paths → DRUPAL_ORIGIN so legacy 301s and non-migrated routes stay on Drupal.
 *
 * Bindings:
 *   DEPLOYED_SLUGS — Workers KV namespace (keys = lowercase slug, value = "1")
 *
 * Env vars:
 *   SOVEREIGN_ORIGIN — e.g. https://cabin-rentals-of-georgia.vercel.app
 *   DRUPAL_ORIGIN    — tunnel or origin hostname for legacy Drupal (no trailing slash)
 */
export default {
  async fetch(request, env) {
    const drupal = String(env.DRUPAL_ORIGIN || "").replace(/\/$/, "");
    const sovereign = String(env.SOVEREIGN_ORIGIN || "").replace(/\/$/, "");
    if (!drupal || !sovereign) {
      return new Response("Redirect Vanguard: set DRUPAL_ORIGIN and SOVEREIGN_ORIGIN", {
        status: 500,
      });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const search = url.search;
    const alwaysSovereignPaths = new Set([
      "/faq",
      "/privacy-policy",
      "/terms-and-conditions",
      "/your-home-vacation-prosperity",
      "/about-blue-ridge-ga",
      "/about-us",
      "/blue-ridge-georgia-activities",
      "/choose-from-our-gorgeous-venues-below",
      "/christmas-new-year’s-cabin-rentals-blue-ridge-ga",
      "/event/santa-train-ride",
      "/experience-north-georgia",
      "/lady-bugs-blue-ridge-ga-cabins",
      "/large-groups-family-reunions",
      "/north-georgia-cabin-rentals",
      "/rental-policies",
      "/specials-discounts",
      "/2-bedroom-cabins",
      "/3-bedroom-cabin-rentals",
      "/4-bedroom-cabin-rentals",
      "/5-bedroom-cabin-rentals",
      "/access-denied",
      "/book-now-before-its-too-late",
      "/book-one-now-while-you-still-can",
      "/lakefront-cabin-rentals",
      "/lake-view-cabin-rentals",
      "/luxury-river-cabins",
      "/mountain-view-cabin-rentals",
      "/only-3-cabins-left",
      "/our-pet-friendly-cabins",
      "/riverfront-cabin-rentals",
      "/river-view-cabin-rentals",
    ]);
    const mirroredContentPrefixes = ["/activity/", "/blog/"];
    const shouldProxyStorefrontPath =
      alwaysSovereignPaths.has(path) ||
      mirroredContentPrefixes.some((prefix) => path.startsWith(prefix)) ||
      path === "/book" ||
      path.startsWith("/book/") ||
      path.startsWith("/api/") ||
      path.startsWith("/_next/") ||
      path === "/favicon.ico";

    if (shouldProxyStorefrontPath) {
      return proxyToOrigin(request, sovereign, path, search, true);
    }

    const cabinMatch = path.match(/^\/cabins\/([^/]+)\/?$/i);
    if (cabinMatch && env.DEPLOYED_SLUGS) {
      const slug = cabinMatch[1].toLowerCase();
      const marker = await env.DEPLOYED_SLUGS.get(slug);
      if (marker != null) {
        return proxyToOrigin(request, sovereign, path, search, true);
      }
    }

    return proxyToOrigin(request, drupal, path, search, false);
  },
};

async function proxyToOrigin(request, origin, path, search, sovereignRoute) {
  const dest = new URL(path + search, origin);
  const destUrl = new URL(dest.toString());
  const upstream = new Request(destUrl.toString(), {
    method: request.method,
    headers: filterProxyHeaders(request.headers, new URL(request.url), destUrl),
    body: request.body,
    redirect: "manual",
  });
  const response = await fetch(upstream);
  const headers = new Headers(response.headers);
  if (sovereignRoute) {
    headers.set("X-Sovereign-Route", "true");
    headers.set("X-Vanguard-Intercept", "true");
  } else {
    headers.delete("X-Sovereign-Route");
    headers.delete("X-Vanguard-Intercept");
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

/**
 * @param {Headers} headers
 * @param {URL} incomingUrl
 * @param {URL} destinationUrl
 */
function filterProxyHeaders(headers, incomingUrl, destinationUrl) {
  const out = new Headers(headers);
  const guestIp = headers.get("CF-Connecting-IP");
  out.delete("host");
  out.delete("cf-connecting-ip");
  out.delete("cf-ray");
  out.delete("cf-visitor");
  out.set("X-Forwarded-Host", incomingUrl.host);
  out.set("X-Forwarded-Proto", incomingUrl.protocol.replace(":", ""));
  out.set("X-Forwarded-Port", incomingUrl.port || (incomingUrl.protocol === "https:" ? "443" : "80"));
  out.set("X-Forwarded-Origin", incomingUrl.origin);
  out.set("X-Forwarded-Server", destinationUrl.host);
  if (guestIp) {
    out.set("X-Forwarded-For", guestIp);
  }
  return out;
}
