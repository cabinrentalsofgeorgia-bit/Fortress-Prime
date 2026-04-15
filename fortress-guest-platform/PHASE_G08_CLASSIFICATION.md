# Phase G.0.8 — File Classification Table
**Generated:** 2026-04-15  
**Git root:** `/home/admin/Fortress-Prime/` (paths relative to fortress-guest-platform/ below)

---

## BUCKET A — Phase A-F Backend (commit to new branch)

### Alembic migrations (Phase A-F chain only)
| File | Phase | Notes |
|---|---|---|
| `backend/alembic/versions/d1e2f3a4b5c6_phase_a_owner_ledger_foundation.py` | A | Creates owner_balance_periods, properties.renting_state |
| `backend/alembic/versions/f8e1d2c3b4a5_phase_a5_offboard_historical_properties.py` | A.5 | Data migration |
| `backend/alembic/versions/c1a8f3b7e2d4_add_commission_rate_to_magic_tokens.py` | E infra | Adds commission_rate to owner_magic_tokens |
| `backend/alembic/versions/a3b5c7d9e1f2_add_is_owner_booking_to_reservations.py` | B | Adds is_owner_booking to reservations |
| `backend/alembic/versions/c9e2f4a7b1d3_add_owner_charges_table.py` | C | Creates owner_charges |
| `backend/alembic/versions/f1e2d3c4b5a6_add_voided_paid_by_to_balance_periods.py` | D | Adds voided_at/voided_by/paid_by to owner_balance_periods |
| `backend/alembic/versions/e7c3f9a1b5d2_owner_statement_infrastructure.py` | E infra | Adds commission_rate/streamline_owner_id to OPA; creates owner_statement_sends |
| `backend/alembic/versions/e5a1_add_owner_address_and_property_group.py` | E.5a | Mailing address columns on OPA; property_group on properties |
| `backend/alembic/versions/e5b2_add_address_to_owner_magic_tokens.py` | E.5b | Mailing address columns on owner_magic_tokens |
| `backend/alembic/versions/e5merge01_merge_phase_d_and_fees_for_e5.py` | E merge | No-op merge point |
| `backend/alembic/versions/e6a1_add_property_address_city_state_postal.py` | E.6 | city/state/postal_code on properties (HEAD) |

### Models
| File | Notes |
|---|---|
| `backend/models/owner_balance_period.py` | OwnerBalancePeriod ORM model |
| `backend/models/owner_charge.py` | OwnerCharge ORM model |
| `backend/models/owner_payout.py` | OwnerPayoutAccount / owner_statement_sends model |

### Services
| File | Notes |
|---|---|
| `backend/services/balance_period.py` | Balance period helpers |
| `backend/services/ledger.py` | Multi-bucket tax resolver (statement computation support) |
| `backend/services/statement_workflow.py` | Statement lifecycle state machine |
| `backend/services/statement_computation.py` | Compute owner statement from ledger |
| `backend/services/statement_comparison.py` | Crog vs Streamline comparison |
| `backend/services/statement_pdf.py` | PDF renderer |
| `backend/services/statement_backfill.py` | Historical statement backfill |
| `backend/services/owner_emails.py` | Statement email send service |
| `backend/services/owner_onboarding.py` | Owner invite/accept flow |
| `backend/services/payout_scheduler.py` | Payout schedule management |

### APIs
| File | Notes |
|---|---|
| `backend/api/admin_statements.py` | Already staged (A) from G.0.7 |
| `backend/api/admin_statements_workflow.py` | Statement lifecycle endpoints (9 routes) |
| `backend/api/admin_charges.py` | Owner charge CRUD (5 routes) |
| `backend/api/admin_payouts.py` | Owner disbursement management (payout schedule, sweep) |

### Tasks
| File | Notes |
|---|---|
| `backend/tasks/statement_jobs.py` | ARQ cron jobs for statement generation + email send |

### Tests
| File | Notes |
|---|---|
| `backend/tests/test_phase_a_owner_ledger.py` | Phase A tests |
| `backend/tests/test_phase_b_revenue_fixes.py` | Phase B tests |
| `backend/tests/test_phase_c_owner_charges.py` | Phase C tests |
| `backend/tests/test_phase_d_statement_workflow.py` | Phase D tests |
| `backend/tests/test_phase_e_pdf.py` | Phase E PDF tests |
| `backend/tests/test_phase_e5_parity.py` | Phase E.5 parity tests |
| `backend/tests/test_phase_e51_hygiene.py` | Phase E.51 hygiene tests |
| `backend/tests/test_phase_e6_visual_parity.py` | Phase E.6 visual parity tests |
| `backend/tests/test_phase_f_cron.py` | Phase F cron tests |
| `backend/tests/test_owner_statement_phase1.py` | Phase 1 integration tests |
| `backend/tests/test_owner_statement_phase1_5.py` | Phase 1.5 tests |
| `backend/tests/test_owner_statement_phase2.py` | Phase 2 integration tests |
| `backend/tests/test_owner_statement_phase3.py` | Phase 3 integration tests |
| `backend/tests/test_ledger.py` | Tax/ledger math tests (Phase A-F support) |
| `backend/tests/synthetic_gauntlet.py` | AI-generated payout math stress test |
| `backend/tests/fixtures/` | Test fixtures dir (crog_output PDFs + streamline_reference) |

---

## BUCKET B — Phase G.0.x Reports + Scripts (commit to new branch)

| File | Notes |
|---|---|
| `SYSTEM_ORIENTATION.md` | G.0.5 full system discovery |
| `PHASE_G0_REPORT.md` | G.0 frontend discovery |
| `PHASE_G1_REPORT.md` | G.1 cleanup (wrong DB — superseded) |
| `PHASE_G06_REPORT.md` | G.0.6 doc reconciliation report |
| `PHASE_A_REPORT.md` | Phase A per-phase report |
| `PHASE_A5_REPORT.md` | Phase A.5 report |
| `PHASE_B_REPORT.md` | Phase B report |
| `PHASE_B5_REPORT.md` | Phase B.5 report |
| `PHASE_C_REPORT.md` | Phase C report |
| `PHASE_D_REPORT.md` | Phase D report |
| `PHASE_E_REPORT.md` | Phase E report |
| `PHASE_E5_REPORT.md` | Phase E.5 report |
| `PHASE_E51_REPORT.md` | Phase E.51 report |
| `PHASE_E6_REPORT.md` | Phase E.6 report |
| `PHASE_F_REPORT.md` | Phase F report |
| `DISCOVERY_REPORT_OWNER_STATEMENTS.md` | Initial discovery |
| `GAP_REMEDIATION_REPORT.md` | Gap remediation |
| `INFRASTRUCTURE_CHECK.md` | Infrastructure check |
| `NOTES.md` | Phase A-F deferred items (CROG_STATEMENTS_PARALLEL_MODE, Phase G prerequisites) |
| `PROPERTIES_RECONCILIATION.md` | Property reconciliation |
| `STATEMENT_MATH_AUDIT.md` | Statement math audit |
| `STATEMENT_MATH_OWNER_BOOKING_AUDIT.md` | Owner booking audit |
| `backend/scripts/g1_cleanup_test_statement_data.sql` | Early G.1 cleanup script (wrong DB — superseded by g1_5_cleanup_fortress_shadow.sql) |

---

## BUCKET C — Pre-existing Unrelated Modifications (LEAVE ALONE — M files + unrelated ?? files)

### Modified tracked files (M) — all left as-is
| Pattern | Count | Notes |
|---|---|---|
| `apps/command-center/src/**` | ~25 files | Pre-existing CC UI work |
| `apps/storefront/src/**` | ~6 files | Pre-existing storefront work |
| `backend/api/command_c2.py`, `damage_claims.py`, `hunter.py`, `legal_cases.py`, `legal_council.py`, `owner_portal.py`, `reservation_webhooks.py`, `reservations.py`, `seo_patches.py`, `stripe_webhooks.py`, `system_health.py`, `telemetry.py`, `workorders.py` | 13 files | Backend API modifications (mixed concerns) |
| `backend/core/public_api_paths.py`, `worker.py` | 2 files | Core modifications |
| `backend/integrations/channel_adapters.py`, `streamline_vrs.py`, `stripe_payments.py` | 3 files | Integration modifications |
| `backend/main.py` | 1 file | Includes Phase A-F router mounts AND other work — too mixed to safely commit in isolation |
| `backend/models/__init__.py`, `acquisition.py`, `content.py`, `damage_claim.py`, `financial_primitives.py`, `pricing.py`, `property.py`, `reservation.py`, `trust_ledger.py`, `workorder.py` | 10 files | Model modifications |
| `backend/requirements.txt` | 1 file | Mixed new dependencies |
| `backend/schemas/folio.py` | 1 file | |
| `backend/services/ai_router.py`, `booking_hold_service.py`, `direct_booking.py`, `ediscovery_agent.py`, `email_service.py`, `housekeeping_service.py`, `legal_council.py`, `legal_extractor.py`, `pricing_service.py`, `research_scout.py`, `reservation_engine.py`, `sovereign_inventory_manager.py`, `streamline_client.py`, `worker_hardening.py` | 14 files | Service modifications |
| `backend/tests/test_direct_booking_property_availability.py`, `test_fast_quote_local_ledger.py`, `test_scout_action_router_db_integration.py`, `test_sovereign_inventory_manager.py` | 4 files | Modified existing tests |
| `backend/vrs/application/event_consumer.py`, `backend/vrs/infrastructure/event_bus.py` | 2 files | VRS modifications |
| `backend/workers/event_consumer.py` | 1 file | |
| `deploy/systemd/fgp-frontend.service`, `fortress-frontend.service` | 2 files | Systemd modifications |
| `run.py` | 1 file | |
| `.cursorrules`, `.env.example`, `.gitignore`, `apps/storefront/.gitignore`, `apps/command-center/next.config.ts`, `apps/command-center/package.json`, `apps/storefront/next.config.ts` | 7 files | Config/build modifications |

### Unrelated untracked files (leave alone for separate future commits)
| Pattern | Notes |
|---|---|
| `backend/alembic/versions/0de35771a5b6*.py`, `2c58318d85aa*.py`, `4757badd7918*.py`, `8bc70dafda91*.py`, `a1b2c3d4e5f6*.py`, `a2b3c4d5e6f7*.py`, `a7d2e9f4c1b8*.py`, `b2c4d6e8f0a1*.py`, `b3c4d5e6f7a8*.py`, `b4f7c9d2e1a3*.py`, `c4d5e6f7a8b9*.py`, `c8f2d1a4b7e3*.py`, `d07f15298db8*.py`, `d5e6f7a8b9c0*.py`, `d5f6a7b8c9d0*.py`, `e6f7a8b9c0d1*.py`, `f3a91b8c2e47*.py`, `f7a8b9c0d1e2*.py`, `f8e9d0c1b2a3*.py`, `f9e8d7c6b5a4*.py`, `g9a8b7c6d5e4*.py`, `h1-k6 range *.py` | Non-statement alembic migrations |
| `apps/command-center/src/app/(dashboard)/acquisition/`, `admin/payouts/`, other new CC pages | Frontend new pages |
| `apps/storefront/src/app/(owner)/`, new storefront components | Frontend new pages |
| `backend/agents/godhead_swarm.py`, `nemo_observer.py` | Agent files |
| `backend/api/acquisition_pipeline.py`, `activities.py`, `blogs.py`, `channel_mappings.py`, `cleaners.py`, `financial_approvals.py`, `internal_health.py`, `legacy_pages.py`, `legal_email_intake_api.py`, `shadow_router.py`, `storefront_*.py`, `tax_reports.py`, `trust_ledger_command_center.py`, `vendors.py` | New API files (not statement) |
| `backend/core/schema_audit.py` | |
| `backend/models/activity.py`, `blog.py`, `channel_mapping.py`, `cleaner.py`, `financial_approval.py`, `learned_rule.py`, `parity_audit.py`, `pending_sync.py`, `shadow_discrepancy.py`, `streamline_payload_vault.py`, `taylor_quote.py`, `vendor.py` | New model files (not statement) |

---

## BUCKET D — Junk to gitignore (not commit, not delete)

| File | Notes |
|---|---|
| `fortress-guest-platform/.env.backup` | Env backup |
| `fortress-guest-platform/.env.production.local` | Env production secret |
| `fortress-guest-platform/.env.telemetry_backup` | Env backup |
| `fortress-guest-platform/.vercelignore` | Vercel deploy ignore file |
| `check_duplicates.py` | One-off root script |
| `force_sync_schema.py` | One-off root script |
| `genesis_backfill.py` | One-off root script |
| `live_fire_test.py` | One-off root script |
| `patch_final_columns.py` | One-off root script |
| `backend/fix_missing_tables.py` | One-off fix script |
| `backend/fix_missing_tables_v2.py` | One-off fix script |
| `backend/robust_fix.py` | One-off fix script |
| `backend/sync_db.py` | One-off fix script |
| `backend/sync_db_all.py` | One-off fix script |
| `scripts/cancel_native_test_reservations.py` | One-off script |
| `scripts/e2e_sovereign_ledger_test.py` | One-off script |
| `scripts/trigger_reconcile_revenue.py` | One-off script |

---

## BUCKET E — Parent directory items (out of scope, document for separate decision)

All paths starting with `../` from fortress-guest-platform perspective. These are in `/home/admin/Fortress-Prime/` (the git root), not within the fortress-guest-platform/ subdirectory.

| Item | Notes |
|---|---|
| `config.py` (modified) | Parent-dir config, tracked in git |
| `.defcon_state` | Parent-dir runtime state file |
| `.env.bak_1775910533`, `.env.bak_1775910997` | Parent-dir env backups |
| `.litellm.env`, `.litellm.env.save`, `.litellm.envnano` | LiteLLM config files |
| `CLAUDE.md` | Project instructions at Fortress-Prime level |
| `cabin-rentals-of-georgia/` | Separate project directory |
| `deploy/systemd/fortress-nightly-finetune.service/timer/script` | New systemd units |
| `personas/legal/seat*.json` | Deleted persona files (D status) |
| `nohup.out`, `litellm_config.yaml`, `switch_defcon.sh` | Runtime/config files |
| `src/` (daemons etc.), `tools/` | Parent-dir Python tools |

**Action:** None in this phase. Gary to handle separately.

---

## Summary Counts

| Bucket | Count | Action |
|---|---|---|
| A (Phase A-F backend) | ~50 files | Commit in 7 logical chunks |
| B (Reports + scripts) | ~24 files | Commit in 1 chunk |
| C (leave alone) | ~90+ files | No action |
| D (gitignore) | ~17 items | Add to .gitignore |
| E (parent dir) | ~20+ items | Gary decision |
