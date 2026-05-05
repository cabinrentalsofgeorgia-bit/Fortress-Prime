#!/usr/bin/env node
/**
 * Next.js `output: "standalone"` does not copy `.next/static` or `public` into the
 * standalone bundle. Without this step, HTML loads but `/_next/static/*` returns 404
 * (blank / broken client UI in production).
 *
 * Run from an app directory after `next build` (e.g. apps/command-center).
 */
import fs from "fs";
import path from "path";

const appRoot = process.cwd();
const nextDir = path.join(appRoot, ".next");
const staticSrc = path.join(nextDir, "static");
const publicSrc = path.join(appRoot, "public");
const standaloneRoot = path.join(nextDir, "standalone");

function findServerRoot(dir, depth = 0) {
  if (depth > 8 || !fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
    return null;
  }
  const serverPath = path.join(dir, "server.js");
  if (fs.existsSync(serverPath)) {
    return dir;
  }
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!ent.isDirectory()) continue;
    const found = findServerRoot(path.join(dir, ent.name), depth + 1);
    if (found) return found;
  }
  return null;
}

function syncDir(label, src, dest) {
  if (!fs.existsSync(src)) {
    console.warn(`sync-next-standalone-assets: skip ${label} (missing ${src})`);
    return;
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.rmSync(dest, { recursive: true, force: true });
  fs.cpSync(src, dest, { recursive: true });
  console.log(`sync-next-standalone-assets: ${label} -> ${dest}`);
}

if (!fs.existsSync(standaloneRoot)) {
  console.warn("sync-next-standalone-assets: no .next/standalone; skipping");
  process.exit(0);
}

const deployRoot = findServerRoot(standaloneRoot);
if (!deployRoot) {
  console.warn("sync-next-standalone-assets: server.js not under standalone; skipping");
  process.exit(0);
}

syncDir("static", staticSrc, path.join(deployRoot, ".next", "static"));
syncDir("public", publicSrc, path.join(deployRoot, "public"));
