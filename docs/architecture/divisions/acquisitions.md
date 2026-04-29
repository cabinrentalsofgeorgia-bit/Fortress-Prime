# Division: Acquisitions (Sector 02 — "Fortress Development")

Owner: Gary Mitchell Knight (operator); Architect-persona AI agent
Status: **active** (per atlas) — but architecture-foundation coverage is **stub**; needs operator input
Spark allocation:
- **Current:** Spark 2 (tenant of the monorepo, co-tenant with control plane + CROG-VRS + Financial + Wealth)
- **Target (locked 2026-04-29 by ADR-004):** **Spark 2 (PERMANENT)** — Acquisitions stays on spark-2 with the control plane permanently. The previous "Spark 4 PLANNED" target under ADR-001 is canceled by ADR-004; Spark 4 wipes and joins the inference cluster instead. Logical isolation (Postgres role, schema, ARQ queue) replaces the planned physical isolation; both are early-stage divisions and dedicated-spark blast-radius isolation is operator-judged overkill.
Last updated: 2026-04-29

## Purpose (per `fortress_atlas.yaml`)

Active real estate development operations. Lot construction, septic engineering, surveyor coordination, permit tracking. Manages the full lifecycle from land acquisition to Certificate of Occupancy.

## Key data stores (per atlas)

### Postgres

- `engineering.projects`, `engineering.drawings`, `engineering.permits`, `engineering.inspections`
- `engineering.mep_systems`, `engineering.compliance_log`
- `engineering.change_orders`, `engineering.rfis`, `engineering.submittals`, `engineering.punch_items`
- `engineering.cost_estimates`
- `public.properties`, `public.asset_docs`, `public.property_events`, `public.real_estate_intel`

### Qdrant

- `email_embeddings` filtered by `division=REAL_ESTATE`

### NAS

- `/mnt/fortress_nas/Business_Prime/`

## Key services consumed

Likely consumers (per atlas + observation; needs verification):

- [Captain](../shared/captain-email-intake.md) — surveyor + contractor email capture
- [Sentinel](../shared/sentinel-nas-walker.md) — engineering doc indexing
- County GIS (manual integration today, no bridge)

## Key services exposed

Per atlas:

- `division_engineering/`
- `division_real_estate/`

(Existence of these directories needs verification against current main HEAD.)

## Open questions for operator

- Is "acquisitions" the same as the atlas's "DEV / Fortress Development" sector, or is it a parent division covering both DEV (engineering) and a separate land-acquisition track?
- Is there an active project file structure on NAS we should walk to identify current matters (Lot 9, etc.)?
- Are `engineering.*` schema tables actually present in `fortress_prod` today, or are they aspirational? (atlas could be ahead of schema migrations)
- Do `division_engineering/` and `division_real_estate/` directories exist in current main HEAD, or are they planned modules?
- What integrations beyond County GIS (planning portal, surveyor APIs, contractor invoicing) are in scope?
- Does this division consume legal docs (zoning compliance, easement filings) from `fortress-legal` via a defined cross-flow, or ad-hoc?
- Status — atlas says active; operational reality may differ (paused, partial, or pre-MVP)

## Cross-references

- Atlas entry: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml) Sector 02 (DEV)
- Existing test files: `backend/tests/test_acquisition_*.py` (suggests acquisitions has live code; needs review)

Last updated: 2026-04-26
