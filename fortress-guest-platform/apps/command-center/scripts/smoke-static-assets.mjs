#!/usr/bin/env node
/**
 * Smoke the Next.js static assets referenced by the root HTML.
 *
 * This catches stale standalone runtimes where the server renders one build's
 * chunk names while the on-disk .next/static directory belongs to another.
 */

const baseUrl = (process.argv[2] || `http://127.0.0.1:${process.env.PORT || "3005"}`).replace(/\/$/, "");

function fail(message) {
  console.error(`static-asset-smoke: FAIL ${message}`);
  process.exit(1);
}

function assetPath(url) {
  try {
    return new URL(url, baseUrl).pathname;
  } catch {
    return url;
  }
}

async function fetchText(url) {
  const response = await fetch(url, { redirect: "manual" });
  const text = await response.text();
  return { response, text };
}

async function checkAsset(label, url) {
  const response = await fetch(url, { redirect: "manual" });
  const contentType = response.headers.get("content-type") || "unknown";
  console.log(`static-asset-smoke: ${label} ${assetPath(url)} -> ${response.status} ${contentType}`);
  if (response.status !== 200) {
    fail(`${label} returned HTTP ${response.status} for ${assetPath(url)}`);
  }
  if (label === "js" && !/(javascript|ecmascript|octet-stream|text\/plain)/i.test(contentType)) {
    fail(`unexpected JS content-type ${contentType} for ${assetPath(url)}`);
  }
  if (label === "css" && !/(text\/css|octet-stream|text\/plain)/i.test(contentType)) {
    fail(`unexpected CSS content-type ${contentType} for ${assetPath(url)}`);
  }
}

const { response, text: html } = await fetchText(`${baseUrl}/`);
console.log(`static-asset-smoke: root / -> ${response.status}`);
if (response.status !== 200) {
  fail(`root returned HTTP ${response.status}`);
}

const assets = [...html.matchAll(/(?:src|href)=["']([^"']*\/_next\/static\/[^"']+)["']/g)]
  .map((match) => new URL(match[1].replace(/&amp;/g, "&"), baseUrl).toString());
const uniqueAssets = [...new Set(assets)];
console.log(`static-asset-smoke: referenced assets ${uniqueAssets.length}`);

if (!uniqueAssets.length) {
  fail("root HTML referenced no /_next/static assets");
}

const jsAsset = uniqueAssets.find((url) => new URL(url).pathname.endsWith(".js"));
const cssAsset = uniqueAssets.find((url) => new URL(url).pathname.endsWith(".css"));

if (!jsAsset) {
  fail("root HTML referenced no JS asset");
}

await checkAsset("js", jsAsset);
if (cssAsset) {
  await checkAsset("css", cssAsset);
} else {
  console.log("static-asset-smoke: css SKIP (no CSS asset referenced)");
}

console.log("static-asset-smoke: PASS");
