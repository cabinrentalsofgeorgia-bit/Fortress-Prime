# PHASE NAV.1 REPORT — Command Center Navigation Reorganization
Date: 2026-04-16

---

## 1. Previous Structure (5 sectors, duplicates identified)

| Sector | Items | Issues |
|---|---|---|
| SHADOW OPS | Fortress Prime, Checkout Parity, Iron Dome Ledger, System Health, NeMo Command Center, Admin Ops, Owner Statements, Owner Charges, Switch DEFCON Mode | Owner tools mixed with monitoring; Iron Dome items scattered |
| CROG-VRS | Operations Dashboard, Reservations & Calendar, Guest CRM, Communications, Property Fleet, **Cabin Profiles** (/properties duplicate), IoT Command, **Field Logistics** (/work-orders duplicate), Housekeeping Dispatch, Work Orders & Maintenance, Sovereign Treasury, Run Housekeeping Auto-Schedule | Two duplicate routes |
| PAPERCLIP AI | Adjudication Glass, Reactivation Hunter, Quotes, Dispatch Hunter Target, Dispatch Radar, Market Canary, Rule Engine, Sync Adjudication Ledger | Quotes misplaced here (finance tool) |
| FORTRESS LEGAL | Active Dockets, E-Discovery Vault, Email Intake, Agreements & Contracts, Damage Claims | Clean — no issues |
| STAKEHOLDERS | **Owner Statements** (duplicate of SHADOW OPS), **Owner Charges** (duplicate of SHADOW OPS), Growth Deck | Sector was essentially an owner duplicates bin |

**Duplicate routes identified:**
- `/properties` appeared twice: "Property Fleet" + "Cabin Profiles"
- `/work-orders` appeared twice: "Field Logistics" + "Work Orders & Maintenance"
- `/admin/statements` appeared in both SHADOW OPS and STAKEHOLDERS
- `/admin/owner-charges` appeared in both SHADOW OPS and STAKEHOLDERS

---

## 2. New Structure (7 sectors, sub-groups)

### 1. SHADOW OPS (COMMAND_ROLES) — strangler-fig monitoring
- Fortress Prime → /command
- Checkout Parity → /command/checkout-parity
- System Health → /system-health
- Switch DEFCON Mode → action (super_admin, isMono)

### 2. CROG-VRS (OPS_ROLES) — property management system
Sub-groups (ordered, comment-delineated — renderer is flat items[]):

**Operations:**
- Operations Dashboard → /analytics
- Reservations & Calendar → /reservations
- Guest CRM → /guests
- Communications → /messages

**Properties:**
- Property Fleet → /properties
- Housekeeping Dispatch → /housekeeping
- Work Orders & Maintenance → /work-orders
- IoT Command → /iot (isMono)
- Run Housekeeping Auto-Schedule → action (super_admin, ops_manager, isMono)

**Owner Management:**
- Onboard Owner → /admin (super_admin)
- Owner Statements → /admin/statements (COMMAND_ROLES)
- Owner Charges → /admin/owner-charges (COMMAND_ROLES)

**Finance:**
- Sovereign Treasury → /payments (super_admin, ops_manager, isMono)
- Quotes → /vrs/quotes (COMMAND_ROLES)

### 3. STAKEHOLDERS (COMMAND_ROLES) — property acquisition & business development
- Growth Deck → /analytics/insights
- Acquisition Pipeline → /acquisition/pipeline

### 4. PAPERCLIP AI (COMMAND_ROLES) — autonomous intelligence
- Adjudication Glass → /vrs
- Reactivation Hunter → /vrs/hunter
- Dispatch Radar → /ai-engine
- Market Canary → /intelligence
- Rule Engine → /automations (isMono)
- Sync Adjudication Ledger → action (isMono)
- Dispatch Hunter Target → action (isMono)

### 5. IRON DOME (COMMAND_ROLES) — email triage & routing
- Iron Dome Ledger → /prime (super_admin, isMono)
- NeMo Command Center → /nemo-command-center (super_admin, isMono)

### 6. FORTRESS LEGAL (LEGAL_ROLES) — legal operations [UNCHANGED]
- Active Dockets → /legal
- E-Discovery Vault → /vault
- Email Intake → /email-intake
- Agreements & Contracts → /agreements
- Damage Claims → /damage-claims

### 7. SYSTEM (super_admin) — admin infrastructure
- Admin Ops → /admin

---

## 3. Items Removed and Why

| Item | Route | Reason |
|---|---|---|
| Cabin Profiles | /properties | Exact duplicate of "Property Fleet" (same href) |
| Field Logistics | /work-orders | Exact duplicate of "Work Orders & Maintenance" (same href) |
| Owner Statements (SHADOW OPS) | /admin/statements | Moved to CROG-VRS Owner Management (single canonical location) |
| Owner Charges (SHADOW OPS) | /admin/owner-charges | Moved to CROG-VRS Owner Management (single canonical location) |
| Owner Statements (STAKEHOLDERS) | /admin/statements | Moved to CROG-VRS Owner Management (single canonical location) |
| Owner Charges (STAKEHOLDERS) | /admin/owner-charges | Moved to CROG-VRS Owner Management (single canonical location) |

**Retained (despite removal consideration):**
- `Run Housekeeping Auto-Schedule` (actionId: `auto-schedule-housekeeping`) — referenced in `command-search.tsx` lines 254, 962, 1143. Kept under CROG-VRS Properties.

---

## 4. Items Moved and Where

| Item | From | To |
|---|---|---|
| Iron Dome Ledger | SHADOW OPS | IRON DOME (new sector) |
| NeMo Command Center | SHADOW OPS | IRON DOME (new sector) |
| Admin Ops | SHADOW OPS | SYSTEM (new sector); also exposed as "Onboard Owner" in CROG-VRS Owner Management |
| Owner Statements | SHADOW OPS + STAKEHOLDERS (duplicated) | CROG-VRS Owner Management (single entry) |
| Owner Charges | SHADOW OPS + STAKEHOLDERS (duplicated) | CROG-VRS Owner Management (single entry) |
| Quotes | PAPERCLIP AI | CROG-VRS Finance (it's a booking/finance tool, not AI) |
| Growth Deck | STAKEHOLDERS | STAKEHOLDERS (retained, sector repurposed) |

---

## 5. Acquisition Pipeline Route Status

**FOUND.** Route exists at:
```
apps/command-center/src/app/(dashboard)/acquisition/pipeline/page.tsx
```
Included in STAKEHOLDERS as:
```
{ label: "Acquisition Pipeline", href: "/acquisition/pipeline", type: "route", allowedRoles: COMMAND_ROLES }
```

---

## 6. Build Verification

- `npx tsc --noEmit` → **0 errors**
- `npm run build` → **Success** (all routes compiled, standalone assets synced)
- `crog-ai-frontend.service` → **Restarted**

---

## 7. Confidence Rating

**9/10**

High confidence. Single-file change with no new routes, no backend changes, no renderer modifications. All role gates preserved. All actionIds preserved. All isMono flags preserved. All hrefs unchanged. Duplicate routes eliminated cleanly. The only judgment call was sub-group rendering strategy: chose comment-ordered flat items over separator NavItems (which would have rendered as disabled buttons in the current sidebar). Quotes moved to CROG-VRS Finance on the basis that it's a booking revenue tool, not an AI tool — this is a semantic improvement over the original placement.
