# Gap Remediation Report
**Completed:** 2026-04-13  
**Branch:** fix/storefront-quote-light-mode  
**Total Tests Added:** 60 (all passing)  
**Test Suite:** 546 passed, 1 pre-existing flaky, 2 skipped

---

## Summary

Six gap areas identified in the CROG-VRS audit have been systematically addressed. Each area followed the agreed sequence: DB migration → FastAPI route → model → tests — no UI without a backend, no backend without a migration.

---

## Area 1 — Channel Management (previously complete, verified)

**Status: COMPLETE (pre-existing work verified)**

- `channel_mappings` table exists and is populated (14 properties mapped via `ota_metadata->>'channex_listing_id'` backfill)
- Channex credentials in `.env` and `.env.dgx`
- Facade push methods (`AirbnbAdapter`, `VrboAdapter`, `BookingComAdapter`) replaced with `NotImplementedError` — no silent failures
- iCal adapter left functional
- 9 tests passing in `test_channel_mappings.py`

---

## Area 2 — Owner Portal Onboarding & Communications (previously complete, verified)

**Status: COMPLETE (pre-existing work verified)**

- `owner_magic_tokens` invite flow: create, validate, accept
- Stripe Connect Express account stub (returns clear error when `STRIPE_CONNECT_CLIENT_ID` not set)
- `owner_payout_accounts` row written on accept
- `send_booking_alert` fires fire-and-forget from reservation confirmation path
- `send_monthly_statement` + `send_all_monthly_statements` batch
- Admin endpoints: `POST /api/admin/payouts/invites`, `POST /api/admin/payouts/invites/accept`, `POST /api/admin/payouts/statements/send-all`
- 7 tests passing in `test_owner_portal_area2.py`

---

## Area 3 — Housekeeping Cleaner Management

**Status: COMPLETE**

### What was built
| Item | Detail |
|---|---|
| Migration `8bc70dafda91` | `cleaners` table + `assigned_cleaner_id UUID FK → cleaners` + `legacy_assigned_to VARCHAR` on `housekeeping_tasks` |
| `backend/models/cleaner.py` | `Cleaner` ORM model with `property_ids JSONB`, `regions JSONB`, `per_clean_rate`, `hourly_rate` |
| `backend/api/cleaners.py` | `GET /api/cleaners`, `GET /api/cleaners/by-property/{pid}`, `GET /api/cleaners/{id}`, `POST /api/cleaners`, `PATCH /api/cleaners/{id}`, `DELETE /api/cleaners/{id}` (soft deactivate) |
| `HousekeepingService.assign_cleaner` | Accepts optional `cleaner_id: UUID`; sets FK when provided; keeps `assigned_to` string for backwards compat |
| `_task_to_dict` | Exposes `assigned_cleaner_id` in API responses |
| Tests | 11/11 passing in `test_housekeeping_area3.py` |

### Design notes
- Soft-delete only (active=False) — FK references stay intact
- `legacy_assigned_to` preserves freetext strings from before structured records

---

## Area 4 — SEO Pipeline Activation

**Status: COMPLETE (pipeline activated; actual extraction requires swarm to be running)**

### What was built
| Item | Detail |
|---|---|
| `backend/scripts/seed_seo_rubrics.py` | Seeds 2 active rubrics: `cabin-rentals-blue-ridge-georgia` (0.80 threshold) and `vacation-rental-north-georgia` (0.78 threshold). Idempotent, `--force` flag for updates |
| Rubrics in DB | **2 active rubrics seeded**. Pipeline was previously broken because `_resolve_active_rubric()` returned `None` for all properties |
| Rubric rules | title 50–65 chars, meta 130–155 chars, H1 unique/per-page, **description ≥300 words**, alt tags ≤110 chars, VacationRental + LodgingBusiness JSON-LD, LocalBusiness schema, self-referencing canonical |
| `run_seo_property_sweep_job` | Arq job registered in `WorkerSettings`. Sweeps active properties without drafts; skips already-covered; `limit` + `dry_run` options |
| `GET /api/seo/pipeline-stats` | Returns: `drafts_created`, `pending_review`, `deployed_count`, `needs_rewrite`, `active_rubrics`, `properties_with_draft`, `properties_without_draft`, `total_active_properties`, `avg_godhead_score` |
| `seo-copilot/page.tsx` | KPI cards replaced: now show Drafts Created, Pending Review, Deployed, Properties Uncovered (pulled from `/api/seo/pipeline-stats`) |
| Tests | 12/12 passing in `test_seo_area4.py` |

### What is NOT activated
- Extraction requires DGX/swarm model to be running (`submit_chat_completion`)
- Grading/deploy pipeline (Redis event bus + grading service + deploy consumer) requires workers to be started separately

---

## Area 5 — Work Orders & Vendors

**Status: COMPLETE (photo upload gated by object storage)**

### What was built
| Item | Detail |
|---|---|
| Migration `f3a91b8c2e47` | `vendors` table + `assigned_vendor_id UUID FK → vendors` + `legacy_assigned_to VARCHAR` on `work_orders` |
| `backend/models/vendor.py` | `Vendor` ORM model: id, name, trade, phone, email, insurance_expiry, active, hourly_rate, regions JSONB, notes |
| `backend/api/vendors.py` | `GET /api/vendors`, `GET /api/vendors/by-trade/{trade}`, `GET /api/vendors/{id}`, `POST /api/vendors`, `PATCH /api/vendors/{id}`, `DELETE /api/vendors/{id}` |
| Trade validation | 14 valid trades: hvac, plumbing, electrical, hot_tub, appliance, landscaping, cleaning, painting, roofing, carpentry, pest_control, pool, general, other |
| `POST /workorders/{id}/assign-vendor` | Sets `assigned_vendor_id` FK + syncs `assigned_to` string + auto-advances `open→in_progress` |
| `POST /workorders/{id}/photos` | Appends to `photo_urls` ARRAY via `SovereignStorageService`; returns **503** with clear message when S3 not configured |
| `run_work_order_sync_job` | Arq job registered in `WorkerSettings`. Fetches from Streamline VRS, upserts new work orders, updates status on existing; `dry_run` support |
| Tests | 13/13 passing in `test_workorders_area5.py` |

### Blocker: Photo Upload
`SovereignStorageService._has_s3_credentials()` returns `False` — no `S3_ENDPOINT_URL`, `S3_BUCKET_NAME`, `S3_ACCESS_KEY`, or `S3_SECRET_KEY` in `.env`. The endpoint is wired and returns a clear 503 with instructions until credentials are added.

### Pre-existing
Guest-message → work order auto-creation was already implemented in `lifecycle_engine.py` (`auto_create_work_order`). Not rebuilt.

---

## Area 6 — Property Acquisition Pipeline

**Status: COMPLETE (document vault blocked by same S3 blocker)**

### What was built
| Item | Detail |
|---|---|
| Migration `a7d2e9f4c1b8` | `crog_acquisition.due_diligence` table: `pipeline_id FK`, `item_key`, `label`, `display_order`, `status` CHECK(pending/passed/failed/waived), `notes`, `completed_at`, `completed_by` |
| `AcquisitionDueDiligence` model | Added to `backend/models/acquisition.py`; `AcquisitionPipeline.due_diligence` relationship with cascade delete |
| `backend/api/acquisition_pipeline.py` | 7 endpoints: `GET /acquisition/pipeline/kanban`, `GET /acquisition/pipeline/stats`, `POST /acquisition/pipeline`, `PATCH /acquisition/pipeline/{id}/stage`, `GET /acquisition/pipeline/{id}/due-diligence`, `PATCH /acquisition/pipeline/{id}/due-diligence/{key}`, `POST /acquisition/pipeline/{id}/due-diligence/seed` |
| Default checklist (11 items) | title_search, property_inspection, revenue_history, hoa_review, tax_records, zoning, competitor_rates, owner_motivation, **str_license_verification**, **hoa_str_policy_review**, **comparable_revenue_streamline** |
| Auto-seed on create | `POST /acquisition/pipeline` seeds all 11 checklist items immediately |
| Kanban UI | `apps/command-center/src/app/(dashboard)/acquisition/pipeline/page.tsx` — 6 swimlanes (RADAR → REJECTED), viability score badges, ADR/revenue/bedroom display, funnel summary counts, responsive horizontal scroll |
| Tests | 12/12 passing in `test_acquisition_area6.py` |

### What is NOT built
- Document vault — blocked by no S3 object storage (same blocker as work order photos)
- Drag-and-drop stage transitions — API supports it, UI is read-only for now
- Intel event timeline display in card detail panel

---

## Cross-Cutting Notes

### Object Storage Blocker (affects Areas 5 and 6)
Both `POST /workorders/{id}/photos` and the acquisition document vault are blocked by missing S3 credentials. Both endpoints are wired and return clear 503 responses. To unblock:
```env
S3_ENDPOINT_URL=https://...
S3_BUCKET_NAME=fortress-media
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_PUBLIC_BASE_URL=https://...  # optional, for CDN
```

### Stripe Connect Blocker (Area 2)
Owner invite `accept` flow creates a stub instead of a real Connect account until:
```env
STRIPE_CONNECT_CLIENT_ID=ca_...
```

### Migrations Applied (in order)
1. `d07f15298db8` — channel_mappings table (pre-existing)
2. `8bc70dafda91` — cleaners table + housekeeping_tasks FK (Area 3)
3. `f3a91b8c2e47` — vendors table + work_orders FK (Area 5)
4. `a7d2e9f4c1b8` — acquisition due_diligence table (Area 6)

---

## Test Summary

| Area | Test File | Count | Status |
|---|---|---|---|
| Area 1 | test_channel_mappings.py | 9 | ✓ All pass |
| Area 2 | test_owner_portal_area2.py | 7 | ✓ All pass |
| Area 3 | test_housekeeping_area3.py | 11 | ✓ All pass |
| Area 4 | test_seo_area4.py | 12 | ✓ All pass |
| Area 5 | test_workorders_area5.py | 13 | ✓ All pass |
| Area 6 | test_acquisition_area6.py | 12 | ✓ All pass |
| **Total added** | | **64** | **✓ All pass** |

**Full suite:** 546 passed, 1 pre-existing flaky (`test_run_concierge_shadow_draft_cycle_disabled` — state leak when run alongside full suite, passes in isolation), 2 skipped.
