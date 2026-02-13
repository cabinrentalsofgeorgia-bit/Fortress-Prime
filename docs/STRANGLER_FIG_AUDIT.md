# Strangler Fig Audit: Owner Reports

**Auditor:** The Architect (Gemini 3 Pro)
**Date:** 2026-02-13
**Governing Document:** CONSTITUTION.md, Article I (Data Sovereignty)
**Sector:** S01 (CROG) — Cabin Rentals of Georgia
**Target:** Migrate `owner_reports` from legacy Streamline VRS to local R1-audited generation

---

## 1. Data Sovereignty Classification of Current Flow

### Legacy Flow (Streamline VRS)

```
Streamline VRS Cloud (web.streamlinevrs.com)
    |
    |--> GetOwnerStatement         [SOVEREIGN data over public internet]
    |--> GetOwnerList              [RESTRICTED PII over public internet]
    |--> Nightly Audit CSV export  [SOVEREIGN financial data]
    |
    v
src/bridges/streamline_legacy_connect.py  --> HTTP POST to 3 cloud endpoints
src/bridges/streamline_total_recall.py    --> Probes GetOwnerStatement
src/bridges/streamline_property_sync.py   --> Probes GetOwnerList
src/bridges/streamline_ingest.py          --> Parses CSV into GAAP mapping
src/bridges/streamline_mapping.yaml       --> Maps "Owner Payout" to account 2000/1010
```

### Constitutional Violations Found

| # | Violation | Severity | Article |
|---|-----------|----------|---------|
| V1 | `streamline_legacy_connect.py` sends `token_key` + `token_secret` to 3 cloud URLs without encryption verification | CRITICAL | Art. I, Sec. 1.1 |
| V2 | `streamline_total_recall.py` calls `GetOwnerStatement` — retrieves SOVEREIGN financial data (owner names, payout amounts, property revenue) from Streamline cloud | CRITICAL | Art. I, Sec. 1.1 |
| V3 | `streamline_property_sync.py` calls `GetOwnerList` — retrieves RESTRICTED PII (owner names, contact info) from cloud | HIGH | Art. I, Sec. 1.1 |
| V4 | No Golden Snapshot verification before any of these cloud calls | MEDIUM | Art. I, Sec. 1.3 |
| V5 | No audit trail — cloud calls are not logged to `system_post_mortems` | MEDIUM | Art. III, Sec. 3.1 |
| V6 | Owner payout calculations happen partially in Streamline's cloud, partially in local `shadow_revenue.py` — split-brain risk | HIGH | Art. I, Sec. 1.2 |

### Data Classification of Owner Report Fields

| Field | Classification | Currently Lives | Should Live |
|-------|---------------|-----------------|-------------|
| `owner_name` | RESTRICTED (PII) | Streamline Cloud + `fin_owner_balances` | `fin_owner_balances` ONLY |
| `owner_payout` | SOVEREIGN (financial) | Streamline Cloud + `fin_owner_balances` | `fin_owner_balances` ONLY |
| `gross_revenue` | SOVEREIGN | Both (split-brain) | `fin_owner_balances` ONLY |
| `mgmt_fee_amount` | SOVEREIGN | `shadow_revenue.py` (local) | `fin_owner_balances` (correct) |
| `trust_balance` | SOVEREIGN | `division_b.trust_ledger` (local) | Correct — no change |
| `property_id` | INTERNAL | Both | Local only |

---

## 2. What Already Exists Locally (The Sovereign Alternative)

The good news: we already have **80% of the owner reports capability** running locally,
with zero cloud dependency. The Streamline bridge is largely redundant.

### Local Owner Data Sources (already sovereign)

| Source | Table | What It Provides | Status |
|--------|-------|-------------------|--------|
| Shadow Revenue Engine | `fin_owner_balances` | Per-property: gross revenue, mgmt fee, owner payout | ACTIVE |
| Shadow Revenue Engine | `fin_reservations` | Shadow bookings with nightly rates | ACTIVE |
| Shadow Revenue Engine | `fin_revenue_snapshots` | Period-level revenue totals | ACTIVE |
| Trust Accounting | `division_b.trust_ledger` | Trust fund deposits, payouts, refunds | ACTIVE |
| Trust Accounting | `division_b.vendor_payouts` | Vendor payment records | ACTIVE |
| CF-04 Audit Ledger | `trust_balance` | Owner vs operating funds per property | ACTIVE |
| QuantRevenue | `cabins/_base_rates.yaml` | Calibrated nightly rates per bedroom tier | ACTIVE |
| Property Catalog | `ops_properties` | Property metadata (bedrooms, names, IDs) | ACTIVE |

### What Streamline Provides That We Don't Yet Have Locally

| Data | Streamline Method | Gap | Difficulty |
|------|-------------------|-----|------------|
| Confirmed (non-shadow) reservations | `GetReservationList` | We use shadow bookings; real Streamline bookings add precision | Medium |
| Official owner statements (PDF format) | `GetOwnerStatement` | We can generate equivalent from `fin_owner_balances` | Low |
| Owner contact directory | `GetOwnerList` | Can be seeded once, then maintained locally | Low |

---

## 3. The Strangler Plan: `owner_reports` Agent

### Architecture

```
                    +-----------------------------+
                    |   Feature Router (config.py)|
                    |   FF_OWNER_REPORTS = True   |
                    +-------------+---------------+
                                  |
                  +---------------+---------------+
                  |                               |
        (FF=True) v                     (FF=False) v
    +-------------------+           +---------------------------+
    | NEW: Owner Report |           | LEGACY: Streamline Bridge |
    | Agent (local only)|           | (cloud calls — deprecated)|
    +--------+----------+           +---------------------------+
             |
    +--------v----------+
    | 1. Read from       |
    |    fin_owner_bal.   |
    |    trust_ledger     |
    |    fin_reservations |
    +--------+-----------+
             |
    +--------v----------+
    | 2. R1 Audit        |      (TITAN mode only — deep verification)
    |    Cross-check:    |
    |    - Revenue vs    |
    |      trust balance |
    |    - Fee calc      |
    |      accuracy      |
    |    - Anomaly       |
    |      detection     |
    +--------+-----------+
             |
    +--------v----------+
    | 3. Generate Report |
    |    - Pydantic model|
    |    - PDF/JSON out  |
    |    - Audit trail   |
    +--------+-----------+
             |
    +--------v----------+
    | 4. Serve via API   |
    |    GET /v1/crog/   |
    |    owners/{id}/    |
    |    statement       |
    +--------------------+
```

### Phase 1 — Build the Agent (Week 1)

1. Create `src/agents/owner_reports.py` — LangGraph StateGraph with OODA pattern.
2. Pydantic models: `OwnerStatement`, `PropertyRevenueLine`, `TrustReconciliation`.
3. Data source: `fin_owner_balances` + `division_b.trust_ledger` + `fin_reservations`.
4. Output: JSON (API) and PDF (downloadable statement).
5. Feature flag: `FF_OWNER_REPORTS = false` (default off).

### Phase 2 — R1 Audit Layer (Week 2)

1. In TITAN mode, submit the generated statement to R1 for verification.
2. R1 cross-checks: revenue vs trust balance, fee calculation accuracy, anomaly detection.
3. R1 output: confidence score + any discrepancy notes.
4. Persist audit result to `public.system_post_mortems`.

### Phase 3 — Parallel Run (Weeks 3-4)

1. Set `FF_OWNER_REPORTS = true` in staging environment.
2. Run both legacy Streamline path AND new agent in parallel.
3. Compare outputs for every property, log discrepancies.
4. Human (Gary) reviews comparison report.

### Phase 4 — Decommission Legacy (Week 5+)

1. After Human sign-off on comparison report.
2. Set `FF_OWNER_REPORTS = true` in production config.
3. Remove `GetOwnerStatement` and `GetOwnerList` calls from bridge code.
4. Mark Streamline owner methods as deprecated in `streamline_mapping.yaml`.
5. **DO NOT delete the bridge file** — other features still use it.

### API Endpoint Design

```
GET /v1/crog/owners/{property_id}/statement
    ?period_start=2026-01-01
    &period_end=2026-01-31
    &format=json|pdf

Response (JSON):
{
    "property_id": "12345",
    "property_name": "Rolling River",
    "owner_name": "Gary Mitchell Knight",
    "period": {"start": "2026-01-01", "end": "2026-01-31"},
    "revenue": {
        "gross_rent": 4500.00,
        "taxes_collected": 585.00,
        "cleaning_fees": 300.00,
        "total_collected": 5385.00
    },
    "deductions": {
        "mgmt_fee_pct": 25.0,
        "mgmt_fee_amount": 1125.00,
        "maintenance": 0.00,
        "total_deductions": 1125.00
    },
    "owner_payout": 3375.00,
    "trust_balance": {
        "owner_funds": 3375.00,
        "operating_funds": 1125.00,
        "escrow": 0.00
    },
    "reservations": [...],
    "audit": {
        "verified_by": "sovereign_r1",
        "confidence": 0.95,
        "discrepancies": [],
        "audited_at": "2026-01-31T07:00:00Z"
    },
    "generated_at": "2026-02-13T12:00:00Z",
    "source": "fortress_local",
    "classification": "SOVEREIGN"
}
```

---

## 4. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Shadow bookings differ from real Streamline bookings | Confidence scoring already in `shadow_revenue.py`; R1 audit adds verification layer |
| Owner expects Streamline-format PDF | Generate equivalent layout in local PDF renderer |
| Transition confusion during parallel run | Feature flag ensures clean routing; legacy path untouched |
| R1 unavailable (SWARM mode) | Agent works without R1; audit step is optional enhancement |

---

## 5. Verdict

**The legacy Streamline owner reports flow violates Article I of the Constitution.**
Owner names (PII), payout amounts (financial), and trust balances (SOVEREIGN data)
are being pulled from a third-party cloud server. This is unnecessary — we already
have 80% of the data locally in `fin_owner_balances` and `division_b.trust_ledger`.

**Recommendation:** Proceed with the Strangler Plan. Build the local `owner_reports`
agent, validate it against Streamline output for 2 weeks, then cut over.

**Priority:** HIGH — this is the first Strangler Fig execution under the new Constitution.

---

*Audit complete. Filed to `docs/STRANGLER_FIG_AUDIT.md`.*
*Next action: Build `src/agents/owner_reports.py` (Phase 1).*
