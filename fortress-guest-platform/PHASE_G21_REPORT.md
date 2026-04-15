# Phase G.2.1 Report — BFF Proxy Route for /api/admin/payouts/*
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** Complete. TypeScript clean. Build succeeded.

---

## 1. Bug Confirmed

After G.2 deployed, all data fetches from the statement pages returned 200 with the dashboard HTML shell instead of JSON. TanStack Query received HTML instead of a JSON object, causing `SyntaxError: Unexpected token '<'` on parse.

Symptoms:
- `useAdminStatements()` returned HTML body, parse failed
- Statement list page showed error state immediately on load
- Browser network tab: GET `/api/admin/payouts/statements` → 200, Content-Type: `text/html`

---

## 2. Root Cause

Next.js App Router route resolution is **exact-prefix + specificity** based. The existing catch-all at:

```
apps/command-center/src/app/api/[...path]/route.ts
```

handles `/api/*` requests generically. However, because a real directory exists at:

```
apps/command-center/src/app/api/admin/prime/
```

Next.js resolves `/api/admin/*` into the `admin/` subdirectory tree rather than the catch-all. Inside `admin/`, only `prime/` had a route handler. Requests to `/api/admin/payouts/*` matched the `admin/` directory but found no handler there, falling through to the page router which returned the dashboard HTML shell.

The VRS routes work because `apps/command-center/src/app/api/vrs/[...path]/route.ts` provides an explicit catch-all specifically for `/api/vrs/*`. The admin payouts routes had no equivalent.

---

## 3. Fix Applied

Created:
```
apps/command-center/src/app/api/admin/payouts/[...path]/route.ts
```

This is a direct copy of the VRS proxy (`apps/command-center/src/app/api/vrs/[...path]/route.ts`) with the path string changed from `/api/vrs/` to `/api/admin/payouts/`. All proxy logic, token extraction, header forwarding, cookie injection, error handling, and HTTP method exports are identical.

---

## 4. Diff vs VRS Template

```diff
32c32
<   const target = `${buildBackendUrl(`/api/vrs/${pathString}`)}${url.search}`;
---
>   const target = `${buildBackendUrl(`/api/admin/payouts/${pathString}`)}${url.search}`;

58c58
<       `[BFF] ${request.method} /api/vrs/${pathString} → FGP:8100` +
---
>       `[BFF] ${request.method} /api/admin/payouts/${pathString} → FGP:8100` +

71c71
<         `[BFF] AUTH FAILURE 401 ← FGP:8100 | path=/api/vrs/${pathString}` +
---
>         `[BFF] AUTH FAILURE 401 ← FGP:8100 | path=/api/admin/payouts/${pathString}` +

76c76
<         `[BFF] ${request.method} /api/vrs/${pathString} ← ${upstream.status}` +
---
>         `[BFF] ${request.method} /api/admin/payouts/${pathString} ← ${upstream.status}` +

86c86
<     console.error(`[BFF] ${request.method} /api/vrs/${pathString} proxy error:`, err);
---
>     console.error(`[BFF] ${request.method} /api/admin/payouts/${pathString} proxy error:`, err);
```

**5 lines changed.** All are the path prefix string in URL construction and log/error output. Zero logic changes.

---

## 5. TypeScript and Build

```
npx tsc --noEmit   → 0 errors
npm run build      → succeeded (standalone output + static sync complete)
```

New route appears in build output under `/api/admin/payouts/[...path]` (dynamic route, server-rendered on demand).

---

## 6. Restart Sequence

The currently running `next-server` process on port 3001 was built from the pre-G.2.1 build artifact. It must be restarted to pick up the new route.

**After Gary commits this change:**

```bash
# 1. Find the running next-server PID
ss -tlnp | grep :3001
# or: ps aux | grep next-server

# 2. Kill the current process gracefully
sudo kill <PID>
# If still running after a few seconds: sudo kill -9 <PID>

# 3. Start with the new build artifact
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center
nohup node .next/standalone/apps/command-center/server.js \
  --port 3001 --hostname 0.0.0.0 \
  > /home/admin/logs/fortress/console.log 2>&1 &
disown

# 4. Verify it's up
sleep 5
ss -tlnp | grep :3001

# 5. Verify the new proxy route reaches the backend (should return 401/403, NOT HTML)
curl -s -o /dev/null -w "%{http_code}\n" \
  "http://127.0.0.1:3001/api/admin/payouts/statements"
# Expected: 401 or 403 (auth required)
# Bug state was: 200 (HTML dashboard shell)
```

If step 5 returns 200 with `Content-Type: text/html`, the route is still being served by the old process or the build did not complete successfully. Re-run `npm run build` and repeat.

**Note:** The `fortress-console.service` systemd unit runs `master_console.py` (a Python tool), NOT this Next.js server. The Next.js command-center is running as an orphaned process. See §8 for the recommended follow-up.

---

## 7. Confidence Rating

| Item | Confidence |
|---|---|
| Root cause diagnosis | **CERTAIN** — `/api/admin/payouts/*` had no handler; `admin/prime/` exists as a sibling, preventing catch-all resolution |
| Fix correctness | **VERY HIGH** — exact mirror of the proven VRS proxy pattern; 5-line diff, zero logic change |
| TypeScript clean | **CERTAIN** — `npx tsc --noEmit` zero errors |
| Build success | **CERTAIN** — `npm run build` completed with standalone output |
| Will fix the symptom post-restart | **HIGH** — the new route will intercept `/api/admin/payouts/*` before the page router; pending manual verification after restart |

---

## 8. Recommended Follow-up: G.2.2 — Systemd Unit for Next.js Command Center

This is the second time in this project the command-center has no reliable process management. The `next-server` runs as an orphaned process that:
- Dies if the session that started it closes
- Cannot be restarted by systemd on crash
- Requires manual PID tracking to restart after updates

G.2.2 scope:
1. Write `/etc/systemd/system/fortress-command-center.service` that runs `node .next/standalone/apps/command-center/server.js` on port 3001
2. `systemctl enable fortress-command-center`
3. Update `infra/gateway/config.yml` description comment to note the correct service name
4. Add a build-and-restart script at `scripts/deploy-command-center.sh`

This is NOT in scope for G.2.1. Flag for Gary to schedule before shipping to Barbara.
