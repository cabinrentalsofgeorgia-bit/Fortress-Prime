# Phase G.0 Report — Frontend Discovery and Path Reconciliation
**Date:** 2026-04-15 (updated; original 2026-04-14)  
**Type:** Read-only discovery. No files modified.

---

## 1. Existing Payouts Page Summary

**File:** `apps/command-center/src/app/(dashboard)/admin/payouts/page.tsx`

This is a fully implemented, working page for **Stripe Connect disbursements** — a completely different feature from the Phase D–F statement workflow. It manages direct ACH transfers to owner Stripe accounts. It does NOT know about `OwnerBalancePeriod`, statement generation, approval workflow, or PDF rendering. We do not touch this page.

**What it does:**
- Lists all owner payout accounts via `GET /api/admin/payouts/pending`
- Shows outstanding balance, last payout date, account status, payout schedule
- Lets staff trigger an immediate Stripe payout (`POST /api/admin/payouts/{propertyId}/send`)
- Lets staff configure the recurring payout schedule (`PATCH /api/admin/payouts/{propertyId}/schedule`)
- Has a "Run Sweep" button to process all auto-scheduled payouts (`POST /api/admin/payouts/sweep`)

**Components imported:** `Badge`, `Button`, `Card`, `Dialog`, `Input`, `Label`, `Select`, `Table` — all from `@/components/ui/*` (shadcn). `Loader2`, `RefreshCw`, `Send`, `Settings`, `ArrowLeft` etc. from `lucide-react`. `Link` from `next/link`. `cn` from `@/lib/utils`.

**Patterns established:**
- `"use client"` at the top — fully client-side rendered
- Hooks at the top of the page component, no prop drilling
- Loading state: centered `Loader2` spinner inside the card while `isLoading`
- Empty state: centered icon + message
- Modals via `Dialog` + `DialogContent` with `open={!!target}` pattern
- Confirm-before-action pattern for destructive sends
- Inline status badges with conditional `cn()` coloring
- Currency formatting via local `fmtCurrency()` helper
- `refetch()` exposed on the query for manual refresh button
- `isPending` from mutations disables buttons while in-flight

---

## 2. Data-Fetching Pattern

**Library:** TanStack Query (`@tanstack/react-query`). All hooks are in `apps/command-center/src/lib/hooks.ts`.

**Query structure:**
```typescript
useQuery<T>({
  queryKey: ["some-stable-key", ...params],
  queryFn: () => api.get("/api/some/path"),
  refetchInterval: 60_000,  // where auto-polling is desired
  enabled: !!someParam,     // conditional fetch
})
```

**Mutation structure:**
```typescript
useMutation<TData, Error, TVariables>({
  mutationFn: (vars) => api.post("/api/some/path", vars),
  onSuccess: (data) => {
    qc.invalidateQueries({ queryKey: ["some-stable-key"] });
    toast.success("...");
  },
  onError: (err) => toast.error(err.message),
})
```

**Query keys** are plain string arrays, co-located with the hook definition in `hooks.ts`. No separate constants file.

**API client:** `apps/command-center/src/lib/api.ts`

All calls go through `api.get()`, `api.post()`, `api.patch()`, `api.delete()` which delegate to a single `request<T>()` function. Key behaviors:
- Paths beginning with `/api/` resolve to same-origin (empty base), so they hit the **Next.js BFF catch-all** at `apps/command-center/src/app/api/[...path]/route.ts`.
- The BFF catch-all proxies to **`127.0.0.1:8100`** (the FastAPI backend). It forwards JWT headers, adds an internal tunnel signature, and handles session cookie passthrough.
- There is NO separate NEXT_PUBLIC_API_URL needed for staff — command-center is designed to call `/api/*` only.

**Toast notifications:** via `sonner` (`toast.success`, `toast.error`).

---

## 3. Auth Pattern

**Mechanism:** **JWT Bearer token stored in `localStorage`** under key `fgp_token`.

Flow:
1. `POST /api/auth/login` → returns `{ access_token, user }` → stored via `setToken(access_token)` in `localStorage`
2. Every subsequent `request()` call in `api.ts` calls `getToken()` and adds `Authorization: Bearer {token}` header
3. The backend FastAPI verifies the JWT on every protected endpoint
4. On 401 response: `clearToken()`, fires `fortress:auth-expired` custom event, redirects to `/login?expired=1`
5. The request also sends `credentials: "include"` so a `fortress_session` cookie (set by the BFF) is included — this is a belt-and-suspenders approach

**No middleware.ts** exists in command-center — route protection is entirely client-side (redirect on 401).

**For Phase G.2:** No special auth wiring needed. Any hook that calls `/api/admin/payouts/*` or `/api/v1/admin/*` will automatically include the JWT header. The backend endpoints already require `require_manager_or_admin` which validates the JWT.

---

## 4. useOwnerStatements Mystery — Resolved

**The hook is broken. The URL returns 404.**

```typescript
// hooks.ts line 902
export function useOwnerStatements(ownerId: string) {
  return useQuery({
    queryKey: ["owner-statements", ownerId],
    queryFn: () => api.get(`/api/owner/statements/${ownerId}`),
    enabled: !!ownerId,
  });
}
```

This calls `GET /api/owner/statements/{ownerId}`. Here is what actually exists under `/api/owner`:

```python
# main.py lines 531 + 539
app.include_router(owner_portal.router, prefix="/api/owner", ...)  # twice, same module
```

The `owner_portal.py` router only has two routes:
- `GET /api/owner/invite/validate`
- `POST /api/owner/invite/accept`

**No `/api/owner/statements/{ownerId}` route exists anywhere.**

The `admin_statements.py` router handles `GET /statements/{owner_id}` but is mounted at prefix `/api/v1/admin` — so the full path is `GET /api/v1/admin/statements/{owner_id}`, which is completely different.

**Conclusion:** `useOwnerStatements` and `useLegacyStatements` are both orphaned hooks. They call URLs that have no backend handler. They would receive 404 on every call (`enabled: !!ownerId` prevents them from firing unless an ownerId is passed, so they've never visibly broken anything in production — there's just no UI that uses them).

**These hooks can either be updated to call the real Phase D–F endpoints or left as dead code.** For Phase G.2, we will write new hooks for the actual statement workflow endpoints.

`useLegacyStatements` (hooks.ts:934) calls `GET /api/owner/{propertyId}/statements/legacy`. Confirmed — this URL also has no backend handler in `owner_portal.py`. Both hooks are dead code.

---

## 5. Admin Nav Structure

**Navigation definition file:** `apps/command-center/src/config/navigation.ts`

The `commandHierarchy` array defines 5 nav sectors. Relevant to statement workflow:

**SHADOW OPS sector** (roles: `super_admin`, `ops_manager`):
- "Admin Ops" → `/admin` — this is the hub page with the "Owner Payouts" button

**STAKEHOLDERS sector** (roles: `super_admin`, `ops_manager`):
- "Owner Portal & Statements" → `/owner` ← **this route does NOT have a page.tsx**
- "Growth Deck" → `/analytics/insights`

**The `/owner` route in the nav points nowhere** — `apps/command-center/src/app/(dashboard)/owner/` does not exist.

**What the `/admin` hub page currently has** (the 4 action buttons in the header bar):
```
[Owner Payouts → /admin/payouts]   [Disputes]   [Contracts]   [Onboard Owner]
```

There is **no "Owner Statements" button** on the admin page yet. The statement workflow admin surface is completely absent from the frontend.

---

## 6. Recommended Shape for Phase G.2

### Directory

New page: `apps/command-center/src/app/(dashboard)/admin/statements/page.tsx`

This mirrors the existing payouts page pattern exactly:
- Same `(dashboard)` route group
- Same `/admin/` parent
- New slug: `statements` (distinct from `payouts`)

A detail page for a single statement: `apps/command-center/src/app/(dashboard)/admin/statements/[id]/page.tsx`

### Complete Phase A-F backend endpoint surface

Mounted at `prefix="/api/admin/payouts"` via `admin_statements_workflow.py` (`main.py:568`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/admin/payouts/statements/generate` | Create/update drafts for a period; supports `dry_run` |
| `GET`  | `/api/admin/payouts/statements` | List `OwnerBalancePeriod` rows (filters: status, period_start, period_end, owner_payout_account_id, limit, offset) |
| `GET`  | `/api/admin/payouts/statements/{id}` | Full detail: balance row + live line items from `compute_owner_statement()` |
| `POST` | `/api/admin/payouts/statements/{id}/approve` | `pending_approval` → `approved` |
| `POST` | `/api/admin/payouts/statements/{id}/void` | → `voided` (body: `{ reason: string }`) |
| `POST` | `/api/admin/payouts/statements/{id}/mark-paid` | `approved` → `paid` (body: `{ payment_reference: string }`) |
| `POST` | `/api/admin/payouts/statements/{id}/mark-emailed` | `approved/paid` → `emailed` (usually called by cron) |
| `GET`  | `/api/admin/payouts/statements/{id}/pdf` | Binary PDF download |
| `POST` | `/api/admin/payouts/statements/{id}/send-test` | Test email to `override_email`; does NOT change status |

Response shape for a period (from `_period_dict()` in `admin_statements_workflow.py`):
```typescript
interface OwnerBalancePeriod {
  id: number;
  owner_payout_account_id: number;
  period_start: string;        // ISO date
  period_end: string;          // ISO date
  opening_balance: string;     // Decimal as string
  closing_balance: string;
  total_revenue: string;
  total_commission: string;
  total_charges: string;
  total_payments: string;
  total_owner_income: string;
  status: "draft" | "pending_approval" | "approved" | "paid" | "emailed" | "voided";
  created_at: string | null;
  updated_at: string | null;
  approved_at: string | null;
  approved_by: string | null;
  paid_at: string | null;
  paid_by: string | null;
  emailed_at: string | null;
  voided_at: string | null;
  voided_by: string | null;
  notes: string | null;
}
```

### New hooks to add to `hooks.ts`

All call Phase A-F backend endpoints. None of these hooks exist yet.

```typescript
// List statements with filters
useAdminStatements(params?: { status?, period_start?, period_end?, owner_payout_account_id? })
  → GET /api/admin/payouts/statements

// Single statement with line items
useAdminStatement(periodId: number)
  → GET /api/admin/payouts/statements/{id}

// Lifecycle mutations
useGenerateStatements()
  → POST /api/admin/payouts/statements/generate
  // body: { period_start: string, period_end: string, dry_run?: boolean }

useApproveStatement()
  → POST /api/admin/payouts/statements/{id}/approve

useVoidStatement()
  → POST /api/admin/payouts/statements/{id}/void
  // body: { reason: string }

useMarkStatementPaid()
  → POST /api/admin/payouts/statements/{id}/mark-paid
  // body: { payment_reference: string }

useMarkStatementEmailed()
  → POST /api/admin/payouts/statements/{id}/mark-emailed

useSendTestStatement()
  → POST /api/admin/payouts/statements/{id}/send-test
  // body: { override_email: string, note?: string }

// PDF download — returns a blob, handled differently (direct link or fetch)
// Use a plain anchor tag with href="/api/admin/payouts/statements/{id}/pdf"
// rather than a hook, since it's a file download
```

### Navigation wiring

Two changes needed:

1. Add a button to the `/admin` page header bar:
   ```
   [Owner Payouts → /admin/payouts]  [Owner Statements → /admin/statements]  [Disputes]  [Contracts]  [Onboard Owner]
   ```

2. Update `navigation.ts` STAKEHOLDERS sector — either change "Owner Portal & Statements" to point to `/admin/statements` (its actual new home), or add a new entry.

### Build order

1. Hooks first (no UI, testable immediately in the browser console)
2. Statement list page (`/admin/statements`) — mirrors the payouts page structure: summary cards + table + status filters
3. Statement detail page (`/admin/statements/[id]`) — shows the full statement with line items, approve/void/mark-paid actions, PDF download button, send-test form
4. Nav wiring — add button to admin hub and update navigation.ts

### Patterns to copy directly

- Loading / empty state pattern from `payouts/page.tsx`
- Modal confirm pattern from `payouts/page.tsx` (for approve, void, mark-paid confirmations)
- `StatusBadge` component pattern — adapt for statement statuses (draft/pending_approval/approved/paid/emailed/voided)
- `fmtCurrency()` and `fmtDate()` helpers — move to `@/lib/utils` or duplicate inline
- `refetch()` + Refresh button pattern
- `isPending` → disabled button + spinner pattern

### What NOT to copy

- The payouts page has no error state display — the statement page should add one (show a toast + error banner when the backend returns an error, not just silently fail)
- The payouts page has no pagination — the statement list likely needs it (could accumulate hundreds of rows)

---

## 7. Open Questions

1. **`/owner` nav item**: The STAKEHOLDERS nav points to `/owner` which has no page. Should "Owner Portal & Statements" → `/admin/statements`, or does the product owner want a separate `/owner` hub page that combines the Stripe payout view + statement view?

2. **Statement list entry point**: Should `/admin/statements` show ALL statements (all owners, all periods, filterable) or should it default to the current month's statements only? The backend supports both via the `period_start`/`period_end` query parameters.

3. **Role access**: Which staff roles should see the statement workflow? Currently the admin payouts page is accessible to `super_admin` only (via the "Admin Ops" nav item). Should statements be visible to `ops_manager` as well? The backend already gates all statement endpoints with `require_manager_or_admin`.

4. **PDF in the UI**: The `GET /api/admin/payouts/statements/{id}/pdf` endpoint returns a binary PDF. The cleanest pattern is a plain `<a href="...">` tag with `target="_blank"` rather than a React Query hook. Confirm this is acceptable or whether an in-browser PDF preview is wanted.

5. **Generate button placement**: The "Generate Statements" action (`POST /statements/generate`) is the starting point of the monthly workflow. Where does the product owner want this trigger? Options: (a) a standalone button on the list page, (b) a cron-only action (no manual trigger in UI), (c) only accessible from the alert email link.

6. **Statement status colors**: Need confirmation of the visual language for each status. Suggested: draft=grey, pending_approval=amber, approved=green, paid=blue, emailed=teal, voided=red.

7. **`useOwnerStatements` cleanup**: The orphaned hook calls a 404 URL. Should it be updated to call `GET /api/v1/admin/statements/{owner_id}` (the Phase B `admin_statements.py` endpoint), or removed? It is not used anywhere visible in the current codebase.

8. **Port discrepancy**: `command-center/package.json` dev script uses `next dev -p 3000`, but `infra/gateway/config.yml` routes `crog-ai.com` → port 3001. Likely the production systemd unit overrides the port. Confirm before setting up any local test proxying.

9. **`pg` dependency violation**: `command-center/package.json` lists `"pg": "^8.20.0"` as a runtime dependency. CLAUDE.md explicitly prohibits frontend code from importing database drivers. This is pre-existing and unrelated to Phase G.2 — flag for cleanup separately.

---

## 8. Confidence Level for Phase G.2

**HIGH.**

All architectural questions are resolved:
- Auth: JWT in localStorage, auto-attached by `api.ts`, no extra wiring needed
- BFF: `/api/*` calls automatically proxied to FastAPI by the catch-all route, no CORS or env var changes needed
- Pattern: payouts page is a clear, complete template to follow
- Hooks: straightforward TanStack Query wrappers — no unusual patterns
- Routing: `(dashboard)/admin/statements/` is the obvious correct location
- Nav: one button addition to admin page + one navigation.ts update

The only items that could slow Phase G.2 are the open questions above (particularly #1 and #5), which are product decisions rather than technical ones. If the product owner answers those, Phase G.2 can begin immediately.

---

## Summary Table

| Item | Status |
|---|---|
| Auth mechanism | JWT Bearer, `api.ts` handles it automatically |
| BFF proxy | `/api/[...path]/route.ts` → `:8100` FastAPI, no config needed |
| Domain | `crog-ai.com` → `:3001` (command-center) |
| Payouts page patterns | Clear template — copy for statement list page |
| Admin nav entry point | `/admin` hub page, add "Owner Statements" button |
| `commandHierarchy` STAKEHOLDERS | `/owner` → broken link, needs update |
| `useOwnerStatements` hook | **Broken — calls 404 URL** — dead code |
| New hooks needed | 8 hooks covering all Phase D–F endpoints |
| New pages needed | 2 pages: `/admin/statements` + `/admin/statements/[id]` |
| Phase G.2 ready? | **Yes, pending 2 product decisions (entry point + generate trigger)** |
