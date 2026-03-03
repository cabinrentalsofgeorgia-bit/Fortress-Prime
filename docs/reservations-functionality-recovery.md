# Reservations Functionality Recovery

This document inventories reservation functionality across the active VRS HTML, legacy UI references, proxy routes, and backend APIs. It also captures discovered gaps and the restoration sequence.

## 1) Feature Inventory (Active + Legacy)

### Active production UI
- `tools/vrs_reservations.html`
  - Server-side reservations list with sort, status filters, property filter, and search.
  - Real-time stay context widgets (arriving today / departing today).
  - Expandable reservation detail rows.
  - Reservation Hub tabs: overview, internal notes, guest messages, work orders, damage claims, rental agreement.
  - Actions: check-in and check-out via booking lifecycle endpoints.
  - Damage Command Center: claim list, status progression, draft generation, approval/send helpers.
  - Agreement helpers: open contract PDF, copy signing link.

### Legacy reference UI (HTML dashboard)
- `fortress-guest-platform/frontend/dashboard/index.html`
  - Prior reservations table surface (`#page-reservations`).
  - Basic search and status filter.
  - "Add Reservation" button and table skeleton loading.
  - Simpler than current production page; useful as fallback reference.

### Legacy reference UI (Next.js dashboard)
- `fortress-guest-platform/frontend-next/src/app/(dashboard)/reservations/page.tsx`
  - List + calendar tab architecture.
  - Drawer-style reservation details (guest/property/details/pricing/lifecycle).
  - Local filtering and sorting.
  - Payment CTA using payment-intent endpoint when balance due exists.
  - Useful for parity checks and UX ideas, but not primary production path.

## 2) UI -> Proxy -> Backend Contract Map

### Core reservation flow
| Capability | UI Call | Proxy Route (`master_console.py`) | Backend Route |
|---|---|---|---|
| List reservations | `/api/vrs/reservations` | `GET /api/vrs/reservations` | `GET /api/reservations/` |
| Arrivals today | `/api/vrs/reservations/arriving/today` | `GET /api/vrs/reservations/arriving/today` | `GET /api/reservations/arriving/today` |
| Departures today | `/api/vrs/reservations/departing/today` | `GET /api/vrs/reservations/departing/today` | `GET /api/reservations/departing/today` |
| Reservation detail | `/api/vrs/reservations/{id}` | `GET /api/vrs/reservations/{id}` | `GET /api/reservations/{id}` |
| Full reservation hub payload | `/api/vrs/reservations/{id}/full` | `GET /api/vrs/reservations/{id}/full` | `GET /api/reservations/{id}/full` |
| Patch reservation fields | `/api/vrs/reservations/{id}` | `PATCH /api/vrs/reservations/{id}` | `PATCH /api/reservations/{id}` |
| Check in | `/api/vrs/booking/reservations/{id}/check-in` | `POST /api/vrs/booking/reservations/{id}/check-in` | `POST /api/booking/reservations/{id}/check-in` |
| Check out | `/api/vrs/booking/reservations/{id}/check-out` | `POST /api/vrs/booking/reservations/{id}/check-out` | `POST /api/booking/reservations/{id}/check-out` |

### Reservation-adjacent booking and reporting
| Capability | Proxy Route | Backend Route |
|---|---|---|
| Calendar by property | `GET /api/vrs/booking/calendar/{property_id}` | `GET /api/booking/calendar/{property_id}` |
| Occupancy | `GET /api/vrs/booking/reservations/occupancy` | `GET /api/booking/reservations/occupancy` |
| Arrivals window | `GET /api/vrs/booking/reservations/arrivals` | `GET /api/booking/reservations/arrivals` |
| Departures window | `GET /api/vrs/booking/reservations/departures` | `GET /api/booking/reservations/departures` |
| Reservation search API | `GET /api/vrs/booking/reservations/search` | `GET /api/booking/reservations/search` |
| Create reservation (staff) | `POST /api/vrs/booking/reservations/create` | `POST /api/booking/reservations/create` |

### Reservation integration and owner views
| Capability | Proxy Route | Backend Route |
|---|---|---|
| Streamline reservation preview | `GET /api/vrs/integrations/streamline/reservations` | `GET /api/integrations/streamline/reservations` |
| Streamline reservation detail by confirmation code | `GET /api/vrs/integrations/reservation/{confirmation_code}/detail` | `GET /api/integrations/reservation/{confirmation_code}/detail` |
| Notes backfill | `POST /api/vrs/integrations/notes/backfill` | `POST /api/integrations/notes/backfill` |
| Agreements backfill | `POST /api/vrs/integrations/agreements/backfill` | `POST /api/integrations/agreements/backfill` |
| Prices backfill | `POST /api/vrs/integrations/prices/backfill` | `POST /api/integrations/prices/backfill` |
| Owner reservations | `GET /api/vrs/owner/reservations/{owner_id}` | `GET /api/owner/reservations/{owner_id}` |

## 3) Gaps Found and Priority

### P1 (fixed in this recovery pass)
- Proxy lacked reservation-adjacent routes that already existed in backend:
  - staff create reservation,
  - Streamline reservation preview/detail,
  - reservation backfill helpers (notes/agreements/prices),
  - owner reservations.
- Result: functionality existed but was unreachable from the Command Center VRS proxy surface.

### P2 (needs runtime verification)
- Confirm all new proxy routes return expected response envelopes through authenticated browser/session flow.
- Confirm `vrs_reservations.html` uses only supported proxy calls under current auth constraints.

### P3 (optional parity enhancements)
- Compare current `vrs_reservations.html` UX to legacy Next.js calendar/list split and payment CTA.
- Add only if needed after production parity validation.

## 4) Restoration Phases

### Phase 1 - Recover access paths (completed)
1. Reconnect missing proxy paths for reservation-adjacent backend capabilities.
2. Keep all calls within `/api/vrs/*` from Command Center.

### Phase 2 - Validate runtime behavior
1. Load `/vrs/reservations`.
2. Validate list/filter/search/sort.
3. Expand reservation details and load hub tabs.
4. Run check-in/check-out on test-safe reservation.
5. Hit reservation integration and owner routes via proxy endpoints.

### Phase 3 - Legacy parity review
1. Compare active page behavior with:
   - `frontend/dashboard/index.html` reservations panel,
   - `frontend-next/.../reservations/page.tsx`.
2. Reintroduce only features that are missing and still desired.

## 5) Verification Checklist

- `GET /vrs/reservations` renders without client errors.
- `GET /api/vrs/reservations` returns data with sorting/filtering.
- `GET /api/vrs/reservations/{id}/full` returns guest/property/messages/work_orders/damage_claims/rental_agreement.
- `POST /api/vrs/booking/reservations/{id}/check-in` succeeds on valid status.
- `POST /api/vrs/booking/reservations/{id}/check-out` succeeds on valid status.
- `POST /api/vrs/booking/reservations/create` creates reservation for staff flow.
- `GET /api/vrs/integrations/streamline/reservations` returns preview payload.
- `GET /api/vrs/integrations/reservation/{confirmation_code}/detail` resolves details.
- `POST /api/vrs/integrations/notes/backfill` runs.
- `POST /api/vrs/integrations/agreements/backfill` runs.
- `POST /api/vrs/integrations/prices/backfill` runs.
- `GET /api/vrs/owner/reservations/{owner_id}` returns owner-scoped rows.
