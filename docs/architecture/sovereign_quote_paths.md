# Sovereign quote vs Streamline — data paths

This document maps authoritative pricing sources for checkout and staff tooling.

## Sovereign (local Postgres, no live Streamline on the request path)

| Surface | Module / symbol | Notes |
|--------|------------------|--------|
| Guest fast quote + hold snapshot | [`backend/services/fast_quote_service.py`](../../fortress-guest-platform/backend/services/fast_quote_service.py) `compute_fast_quote_breakdown`, `calculate_locked_fast_quote_breakdown`, `build_quote_snapshot` | Delegates to [`sovereign_quote_service.py`](../../fortress-guest-platform/backend/services/sovereign_quote_service.py). |
| Unified ledger math | [`backend/services/sovereign_quote_service.py`](../../fortress-guest-platform/backend/services/sovereign_quote_service.py) `compute_sovereign_quote` | Prefers `fees` / `property_fees` + `taxes` / `property_taxes` via [`pricing_service.py`](../../fortress-guest-platform/backend/services/pricing_service.py) when both are linked; otherwise [`quote_builder.py`](../../fortress-guest-platform/backend/services/quote_builder.py) `build_local_ledger_quote` from `properties.rate_card`. |
| Nightly rent (rate card) | [`quote_builder.py`](../../fortress-guest-platform/backend/services/quote_builder.py) `build_local_rent_quote` | Reads `Property.rate_card.rates`. |
| HTTP: storefront quote | [`direct_booking.py`](../../fortress-guest-platform/backend/api/direct_booking.py) `POST /api/direct-booking/quote` | Returns breakdown + optional signed quote flow via `POST /api/direct-booking/signed-quote`. |
| HTTP: calculator | [`fast_quote.py`](../../fortress-guest-platform/backend/api/fast_quote.py) `POST /api/quotes/calculate` | Pydantic `QuoteRequest` → `calculate_fast_quote` (SQL ledger path only; same fee/tax tables). |
| Checkout hold | [`booking_hold_service.py`](../../fortress-guest-platform/backend/services/booking_hold_service.py) `create_checkout_hold` | Persists `quote_snapshot` on `reservation_holds`; when `SOVEREIGN_QUOTE_SIGNING_KEY` is set, requires a verified signed quote payload on book. |

## Streamline (upstream rate card / calendar; not sovereign checkout authority)

| Surface | Module | Notes |
|--------|--------|--------|
| Deterministic quote | [`streamline_client.py`](../../fortress-guest-platform/backend/services/streamline_client.py) `get_deterministic_quote` | Uses `StreamlineVRS.fetch_property_rates` (cached). |
| HTTP | [`vrs_quotes.py`](../../fortress-guest-platform/backend/api/vrs_quotes.py) e.g. `POST /api/quotes/streamline/quote` | Transition / audit; not used for sealed direct-booking checkout. |

## ReservationEngine

[`reservation_engine.py`](../../fortress-guest-platform/backend/services/reservation_engine.py) `calculate_pricing` is a separate seasonal/extra-guest model. It is **not** the sovereign fee/tax line-item engine for `rate_card` / `fees` / `taxes` ledgers.
