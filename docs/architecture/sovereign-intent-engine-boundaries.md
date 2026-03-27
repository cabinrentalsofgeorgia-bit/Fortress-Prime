# Sovereign Intent Engine — Compliance Boundaries (Strike 9 Scope)

## Purpose

Support **first-party**, **consented** engagement signals so Fortress can score intent and drive **Sovereign Nudge** (offers, chat prompts) **without** covert PII harvesting.

## Non-negotiable (will not implement here)

- **Ghost capture** of email, phone, or payment fields **before submit** or without **affirmative consent**.
- **Silent fingerprint → PII stitching** across sessions (e.g. hardware hash retro-linked to identity without legal basis).
- **Mouse/keystroke exfiltration** at high frequency to the ledger.

## Allowed

| Layer | Behavior |
|--------|-----------|
| **Postgres** | `storefront_intent_events`: **HMAC session fingerprint**, coarse `event_type`, optional `property_slug`, **sanitized** `meta` JSON (PII keys rejected), `consent_marketing` flag on event. Server may append **`funnel_hold_started`** only after successful checkout hold. **`storefront_session_guest_links`** records fingerprint→`guest_id` at the same time (post-submit). **Strike 11:** `POST /api/storefront/concierge/resolve` may add links + **`concierge_identity_resolved`** only when the payload includes **`consent_recovery_contact: true`** (UI checkbox on `/book`). |
| **FastAPI** | `POST /api/storefront/intent/event`, `GET /api/storefront/intent/nudge` — **public** (storefront only); rate limits recommended at Cloudflare. |
| **Next.js** | BFF under `/api/storefront/intent/*` forwarding to backend (same-origin browser calls). |
| **UI** | **SovereignNudge**: opt-in marketing consent in-component; polls nudge eligibility **only** after consent; dismiss persists via `nudge_dismissed` event. |

## Recovery strikes (SMS / email)

Use existing **Twilio** / email infrastructure **only** for **opted-in** marketing or **transactional** messages with clear **STOP**/unsubscribe — not driven by pre-submit field capture.

## Data retention

Define retention (e.g. 90 days) and DSR deletion in ops runbooks; not enforced in code in v1.

## Domains

- **Storefront** (`cabin-rentals-of-georgia.com`): intent endpoints + nudge.
- **Staff** (`crog-ai.com`): no Stalker surface; **Funnel HQ** (`GET /api/telemetry/funnel-hq`) aggregates intent rows for leakage + recovery — staff JWT only.
