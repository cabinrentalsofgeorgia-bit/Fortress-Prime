# FORTRESS PRIME — Architecture Constitution

**Effective Date:** 2026-02-26
**Tag Baseline:** `v3.0.0-stable-auth`
**Classification:** Non-Negotiable Engineering Standard

---

## I. Network Perimeter

All external traffic enters through a single point and is routed by Nginx.

```
                        ┌─────────────┐
    Internet ──────────>│  Cloudflare  │
                        └──────┬──────┘
                               │
                        ┌──────▼──────┐
                        │   Nginx LB  │  (wolfpack-lb, port 80/443)
                        └──────┬──────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
     ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
     │   Next.js   │   │  FGP Backend │   │   Master    │
     │  (port 3001)│   │  (port 8100) │   │   Console   │
     │  Frontend   │   │  FastAPI     │   │  (port 9800)│
     └─────────────┘   └─────────────┘   └─────────────┘
```

### Nginx Routing Rules (crog-ai.com server block)

| Location | Upstream | Port | Purpose |
|---|---|---|---|
| `= /api/login` | `command_center` | 9800 | Master console gateway authentication |
| `= /api/logout` | `command_center` | 9800 | Master console session teardown |
| `/api/vrs/` | `command_center` | 9800 | VRS proxy (master console → FGP) |
| `/api/legal/` | `command_center` | 9800 | Legal API proxy |
| `/api/email-intake/` | `command_center` | 9800 | Email intake proxy |
| `/api/` | `guest_platform` | 8100 | All other API calls (FGP backend) |
| `/console/` | `command_center` | 9800 | Legacy master console (deprecated path) |
| `/_next/` | `nextjs_frontend` | 3001 | Next.js static assets |
| `/` | `nextjs_frontend` | 3001 | Default — all pages served by Next.js |

**Rule:** Nginx is the single ingress point. No service exposes ports to the internet directly.

---

## II. Authentication Flow

Next.js owns the login screen. There are no legacy HTML login pages in the primary auth flow.

```
User visits crog-ai.com/
        │
        ▼
   Next.js serves page
   AuthGuard checks localStorage for fgp_token
        │
   ┌────┴────┐
   │ No token │──────> router.replace("/login")
   └─────────┘              │
                             ▼
                    Native React Login Page
                    (src/app/login/page.tsx)
                             │
                    User enters username + password
                             │
              ┌──────────────┴──────────────┐
              │ Step 1                       │
              │ POST /api/login              │
              │ Nginx → Master Console (9800)│
              │ Returns: gateway JWT         │
              └──────────────┬──────────────┘
                             │
              ┌──────────────┴──────────────┐
              │ Step 2                       │
              │ POST /api/auth/sso           │
              │ Nginx → FGP Backend (8100)   │
              │ Exchanges gateway JWT for    │
              │ local FGP JWT + user object  │
              └──────────────┬──────────────┘
                             │
                    Store FGP token in localStorage
                    Store user in app store
                    router.replace("/")
                             │
                             ▼
                    AuthGuard → fetchMe() via
                    GET /api/auth/me → validates
                    token → dashboard renders
```

### Auth Rules

1. **Next.js owns the login screen.** The native React login page at `/login` is the only entry point. No redirects to `/console/` or legacy `login.html`.
2. **Two-step token exchange.** The login form authenticates against the master console (gateway JWT), then exchanges that for a local FGP JWT via the SSO endpoint. The FGP token is what gets stored and used for all subsequent API calls.
3. **Bearer token auth.** All authenticated API calls include `Authorization: Bearer <fgp_token>` in the request header. The token is stored in `localStorage` under the key `fgp_token`.
4. **AuthGuard is the gate.** Every page inside `src/app/(dashboard)/` is wrapped by `AuthGuard`. Unauthenticated users are redirected to `/login`. Failed token validation clears the token and redirects to `/login`.
5. **Logout is local.** `logout()` clears the token from localStorage and redirects to `/login`. No cross-origin calls, no command-center-url fetches.

---

## III. The BFF Rule (Backend-for-Frontend)

**This is the most important rule in the codebase.**

### The Problem

The user's browser runs on their laptop. It cannot reach `http://localhost:8100` or `http://localhost:9800` — those are server-local addresses. Any client-side `fetch("http://localhost:8100/...")` will fail with `ERR_CONNECTION_REFUSED` in production.

### The Solution

All client-side API calls MUST use **relative URLs**:

```typescript
// CORRECT — relative URL, routed by Nginx in production
fetch("/api/auth/login", { method: "POST", body: ... })
fetch("/api/auth/me")
fetch("/api/damage-claims/")

// FORBIDDEN — will fail in production
fetch("http://localhost:8100/api/auth/login", ...)
fetch("http://localhost:9800/api/login", ...)
```

### Where localhost IS Allowed

Server-side BFF route handlers (`src/app/api/**/route.ts`) run on the same machine as the backends. They MUST use localhost to reach internal services:

```typescript
// src/app/api/auth/[...path]/route.ts — SERVER-SIDE, localhost is correct
const BACKEND = process.env.FGP_BACKEND_URL || "http://localhost:8100";
const upstream = await fetch(`${BACKEND}/api/auth/${subpath}`, ...);
```

### The Enforcement

A pre-commit hook at `.git/hooks/pre-commit` physically blocks commits that introduce localhost calls in client-side `.ts`/`.tsx` files. BFF `route.ts` files are exempt.

---

## IV. File Ownership Map

### Frontend (Next.js)

| Path | Purpose |
|---|---|
| `src/app/login/page.tsx` | Native login form (username + password) |
| `src/app/sso/page.tsx` | SSO bridge for gateway token exchange |
| `src/app/(dashboard)/layout.tsx` | Dashboard shell with AuthGuard |
| `src/components/auth-guard.tsx` | Session gatekeeper — redirects to /login |
| `src/lib/api.ts` | API client with BFF prefix routing |
| `src/lib/auth.ts` | Login, logout, fetchMe, token helpers |
| `src/lib/store.ts` | Zustand app store (user, sidebar state) |
| `src/app/api/auth/[...path]/route.ts` | Catch-all BFF proxy → FGP (8100) |
| `src/app/api/auth/login/route.ts` | Login BFF: master console → FGP SSO |
| `src/app/api/email-intake/[...path]/route.ts` | Email intake BFF → master console (9800) |
| `src/app/api/legal/[...path]/route.ts` | Legal BFF → legal API (9878) |
| `src/app/api/intelligence/[...path]/route.ts` | Intelligence BFF → FGP (8100) |

### Backend (Python)

| Service | Port | Path | Purpose |
|---|---|---|---|
| Master Console | 9800 | `tools/master_console.py` | Legacy command center, gateway auth |
| FGP Backend | 8100 | `fortress-guest-platform/backend/` | Core API (reservations, guests, etc.) |
| Legal API | 9878 | `tools/legal_case_manager.py` | Legal CRM CRUD |
| Batch Classifier | 9877 | `tools/batch_classifier.py` | AI classification engine |
| System Health | 9876 | `tools/bare_metal_dashboard.py` | Cluster monitoring |

---

## V. Forbidden Patterns

1. **DO NOT** use `http://localhost:*` in any client-side `.ts` or `.tsx` file.
2. **DO NOT** redirect to `/console/` or `/console/login` from React code.
3. **DO NOT** fetch `command-center-url` to determine where to redirect.
4. **DO NOT** set `NEXT_PUBLIC_API_URL` to a localhost address — it leaks into client bundles.
5. **DO NOT** add `next.config` rewrites to proxy API routes. Use explicit BFF route handlers.
6. **DO NOT** bypass the AuthGuard for dashboard pages.
7. **DO NOT** store raw passwords or gateway tokens in localStorage. Only the FGP JWT is stored.
8. **DO NOT** modify the Nginx routing without updating this document.

---

## VI. Recovery Points

| Tag | Description | Safe to rollback to |
|---|---|---|
| `v3.0.0-stable-auth` | Unified auth perimeter, native React login | Yes |

To restore: `git checkout v3.0.0-stable-auth`

---

## VII. Amendment Process

1. Read this document before proposing architectural changes.
2. If your change contradicts any rule above, you must rewrite the proposal.
3. Nginx routing changes require this document to be updated in the same commit.
4. New BFF routes must be registered in Section IV.
5. New backend services must be registered in Section IV with their port number.
