/**
 * Fortress Prime — Storefront SEO Edge Worker
 *
 * Public-edge HTML enhancer for cabin-rentals-of-georgia.com.
 * This worker is intentionally separate from the internal API gateway worker:
 * - Origin HTML comes from the public storefront origin only
 * - SEO payloads come from the canonical /api/seo/live/... surface
 * - If no live payload exists, the worker returns origin HTML unchanged so
 *   Next.js metadata remains the fallback source of truth
 */

const HTML_CONTENT_TYPE = "text/html";
const DEFAULT_CACHE_TTL_SECONDS = 300;
const EDGE_JSONLD_SCRIPT_ID = "fortress-edge-seo-jsonld";
const PUBLIC_FILE_EXTENSION_RE = /\.[a-z0-9]+$/i;
const EXCLUDED_PREFIXES = [
  "/api/",
  "/_next/",
  "/dashboard",
  "/login",
  "/sso",
  "/owner",
  "/invite",
  "/book",
  "/availability",
  "/guest",
  "/sign",
];

function trimTrailingSlash(value) {
  return String(value || "").replace(/\/+$/, "");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeJsonForScript(value) {
  return JSON.stringify(value).replace(/<\//g, "<\\/");
}

function isHtmlDocumentResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  return contentType.toLowerCase().includes(HTML_CONTENT_TYPE);
}

function isExcludedPath(pathname) {
  return EXCLUDED_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function resolveSeoTarget(pathname) {
  const cabinMatch = pathname.match(/^\/cabins\/([^/?#]+)/i);
  if (cabinMatch) {
    return { kind: "property", slug: decodeURIComponent(cabinMatch[1]) };
  }

  const legacyCabinMatch = pathname.match(/^\/cabin\/(?:[^/?#]+\/)*([^/?#]+)/i);
  if (legacyCabinMatch) {
    return { kind: "property", slug: decodeURIComponent(legacyCabinMatch[1]) };
  }

  const reviewArchiveMatch = pathname.match(/^\/reviews\/archive\/([^/?#]+)/i);
  if (reviewArchiveMatch) {
    return { kind: "archive", slug: decodeURIComponent(reviewArchiveMatch[1]) };
  }

  const reviewMatch = pathname.match(/^\/reviews\/([^/?#]+)/i);
  if (reviewMatch) {
    return { kind: "archive", slug: decodeURIComponent(reviewMatch[1]) };
  }

  if (
    pathname === "/" ||
    PUBLIC_FILE_EXTENSION_RE.test(pathname) ||
    isExcludedPath(pathname)
  ) {
    return null;
  }

  const normalizedPath = pathname.replace(/^\/+|\/+$/g, "");
  if (!normalizedPath) {
    return null;
  }

  return { kind: "archive", slug: normalizedPath };
}

function buildOriginUrl(requestUrl, originBase) {
  const url = new URL(requestUrl);
  return `${originBase}${url.pathname}${url.search}`;
}

function buildSeoApiUrl(target, env) {
  const apiBase = trimTrailingSlash(env.SEO_API_ORIGIN || env.TUNNEL_HOSTNAME && `https://${env.TUNNEL_HOSTNAME}`);
  if (!apiBase) {
    return null;
  }
  if (target.kind === "property") {
    return `${apiBase}/api/seo/live/${encodeURIComponent(target.slug)}`;
  }
  return `${apiBase}/api/seo/live/archive/${encodeURIComponent(target.slug)}`;
}

function buildProxyHeaders(request) {
  const headers = new Headers(request.headers);
  headers.set("X-Fortress-Edge", "cloudflare-storefront-seo");
  headers.set("X-Request-ID", crypto.randomUUID());
  return headers;
}

function toAbsoluteCanonical(requestUrl, value) {
  if (!value) {
    return requestUrl;
  }
  try {
    return new URL(value, requestUrl).toString();
  } catch {
    return requestUrl;
  }
}

function normalizeSeoPayload(target, requestUrl, payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const body = payload.payload && typeof payload.payload === "object" ? payload.payload : null;
  if (!body) {
    return null;
  }

  const title = typeof body.title === "string" && body.title.trim() ? body.title.trim() : null;
  const description =
    typeof body.meta_description === "string" && body.meta_description.trim()
      ? body.meta_description.trim()
      : null;
  const ogTitle =
    typeof body.og_title === "string" && body.og_title.trim()
      ? body.og_title.trim()
      : title;
  const ogDescription =
    typeof body.og_description === "string" && body.og_description.trim()
      ? body.og_description.trim()
      : description;
  const canonical = toAbsoluteCanonical(
    requestUrl,
    typeof body.canonical_url === "string" ? body.canonical_url.trim() : "",
  );
  const jsonLdCandidate =
    body.jsonld && typeof body.jsonld === "object" && !Array.isArray(body.jsonld)
      ? body.jsonld
      : body.json_ld && typeof body.json_ld === "object" && !Array.isArray(body.json_ld)
        ? body.json_ld
        : null;

  return {
    kind: target.kind,
    slug: target.slug,
    title,
    description,
    ogTitle,
    ogDescription,
    canonical,
    jsonLd: jsonLdCandidate,
  };
}

async function fetchSeoPayload(target, env) {
  const seoUrl = buildSeoApiUrl(target, env);
  if (!seoUrl) {
    return null;
  }

  const response = await fetch(seoUrl, {
    headers: { Accept: "application/json" },
    cf: {
      cacheTtl: Number(env.SEO_EDGE_CACHE_TTL || DEFAULT_CACHE_TTL_SECONDS),
      cacheEverything: true,
    },
  });

  if (!response.ok) {
    if (response.status === 404) {
      return null;
    }
    throw new Error(`SEO API request failed with HTTP ${response.status}`);
  }

  return response.json();
}

class TitleHandler {
  constructor(value) {
    this.value = value;
    this.seen = false;
  }

  element(element) {
    this.seen = true;
    element.setInnerContent(this.value);
  }
}

class MetaHandler {
  constructor(content) {
    this.content = content;
    this.seen = false;
  }

  element(element) {
    this.seen = true;
    element.setAttribute("content", this.content);
  }
}

class CanonicalHandler {
  constructor(href) {
    this.href = href;
    this.seen = false;
  }

  element(element) {
    this.seen = true;
    element.setAttribute("href", this.href);
  }
}

class JsonLdHandler {
  constructor(scriptText) {
    this.scriptText = scriptText;
    this.seen = false;
  }

  element(element) {
    this.seen = true;
    element.setInnerContent(this.scriptText, { html: false });
  }
}

class HeadInjectionHandler {
  constructor(meta) {
    this.meta = meta;
  }

  element(element) {
    if (this.meta.title?.value && !this.meta.title.handler.seen) {
      element.append(
        `<title>${escapeHtml(this.meta.title.value)}</title>`,
        { html: true },
      );
    }
    if (this.meta.description?.value && !this.meta.description.handler.seen) {
      element.append(
        `<meta name="description" content="${escapeHtml(this.meta.description.value)}">`,
        { html: true },
      );
    }
    if (this.meta.ogTitle?.value && !this.meta.ogTitle.handler.seen) {
      element.append(
        `<meta property="og:title" content="${escapeHtml(this.meta.ogTitle.value)}">`,
        { html: true },
      );
    }
    if (this.meta.ogDescription?.value && !this.meta.ogDescription.handler.seen) {
      element.append(
        `<meta property="og:description" content="${escapeHtml(this.meta.ogDescription.value)}">`,
        { html: true },
      );
    }
    if (this.meta.canonical?.value && !this.meta.canonical.handler.seen) {
      element.append(
        `<link rel="canonical" href="${escapeHtml(this.meta.canonical.value)}">`,
        { html: true },
      );
    }
    if (this.meta.jsonLd?.value && !this.meta.jsonLd.handler.seen) {
      element.append(
        `<script id="${EDGE_JSONLD_SCRIPT_ID}" type="application/ld+json">${escapeJsonForScript(this.meta.jsonLd.value)}</script>`,
        { html: true },
      );
    }
  }
}

function buildMetaRegistry(seo) {
  return {
    title: seo.title
      ? { value: seo.title, handler: new TitleHandler(seo.title) }
      : null,
    description: seo.description
      ? { value: seo.description, handler: new MetaHandler(seo.description) }
      : null,
    ogTitle: seo.ogTitle
      ? { value: seo.ogTitle, handler: new MetaHandler(seo.ogTitle) }
      : null,
    ogDescription: seo.ogDescription
      ? { value: seo.ogDescription, handler: new MetaHandler(seo.ogDescription) }
      : null,
    canonical: seo.canonical
      ? { value: seo.canonical, handler: new CanonicalHandler(seo.canonical) }
      : null,
    jsonLd: seo.jsonLd
      ? { value: seo.jsonLd, handler: new JsonLdHandler(escapeJsonForScript(seo.jsonLd)) }
      : null,
  };
}

async function proxyStorefrontOrigin(request, env) {
  const originBase = trimTrailingSlash(
    env.STOREFRONT_ORIGIN || (env.TUNNEL_HOSTNAME ? `https://${env.TUNNEL_HOSTNAME}` : ""),
  );
  if (!originBase) {
    return new Response("STOREFRONT_ORIGIN is not configured.", { status: 500 });
  }

  const originUrl = buildOriginUrl(request.url, originBase);
  return fetch(originUrl, {
    method: request.method,
    headers: buildProxyHeaders(request),
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    redirect: "manual",
  });
}

async function maybeInjectSeo(request, env, originResponse) {
  if (request.method !== "GET" || !originResponse.ok || !isHtmlDocumentResponse(originResponse)) {
    return originResponse;
  }

  const requestUrl = new URL(request.url);
  const target = resolveSeoTarget(requestUrl.pathname);
  if (!target) {
    return originResponse;
  }

  let seoPayload;
  try {
    seoPayload = await fetchSeoPayload(target, env);
  } catch (error) {
    const passthroughHeaders = new Headers(originResponse.headers);
    passthroughHeaders.set("X-Fortress-Storefront-SEO", "seo-fetch-error");
    return new Response(originResponse.body, {
      status: originResponse.status,
      headers: passthroughHeaders,
    });
  }

  const normalizedSeo = normalizeSeoPayload(target, request.url, seoPayload);
  if (!normalizedSeo) {
    const passthroughHeaders = new Headers(originResponse.headers);
    passthroughHeaders.set("X-Fortress-Storefront-SEO", "origin-only");
    return new Response(originResponse.body, {
      status: originResponse.status,
      headers: passthroughHeaders,
    });
  }

  const meta = buildMetaRegistry(normalizedSeo);
  let rewriter = new HTMLRewriter();
  if (meta.title) {
    rewriter = rewriter.on("title", meta.title.handler);
  }
  if (meta.description) {
    rewriter = rewriter.on('meta[name="description"]', meta.description.handler);
  }
  if (meta.ogTitle) {
    rewriter = rewriter.on('meta[property="og:title"]', meta.ogTitle.handler);
  }
  if (meta.ogDescription) {
    rewriter = rewriter.on('meta[property="og:description"]', meta.ogDescription.handler);
  }
  if (meta.canonical) {
    rewriter = rewriter.on('link[rel="canonical"]', meta.canonical.handler);
  }
  if (meta.jsonLd) {
    rewriter = rewriter.on(`script#${EDGE_JSONLD_SCRIPT_ID}`, meta.jsonLd.handler);
  }
  rewriter = rewriter.on("head", new HeadInjectionHandler(meta));

  const headers = new Headers(originResponse.headers);
  headers.set("X-Fortress-Storefront-SEO", `${target.kind}-edge-injected`);
  headers.set("X-Fortress-SEO-Slug", target.slug);

  return new Response(rewriter.transform(originResponse).body, {
    status: originResponse.status,
    headers,
  });
}

export default {
  async fetch(request, env) {
    const originResponse = await proxyStorefrontOrigin(request, env);
    return maybeInjectSeo(request, env, originResponse);
  },
};
