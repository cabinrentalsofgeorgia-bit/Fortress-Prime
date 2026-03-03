# Dependency Compatibility Matrix

This matrix defines the hybrid dependency contract for Fortress Prime.

## Shared Baseline (root `requirements.txt`)

- `fastapi`: `>=0.128,<0.129`
- `pydantic`: `>=2.12,<3.0`
- `pydantic-settings`: `>=2.12,<3.0`
- `httpx`: `>=0.28,<0.29`
- `aiohttp`: `>=3.13,<4.0`
- `cryptography`: `>=46,<47`
- `PyJWT`: `>=2.11,<3.0`

## Service Overrides

### Fortress Guest Platform

Source: `fortress-guest-platform/requirements.txt`

- Keeps service-level pins for app stability.
- Transitional auth stack currently includes `python-jose` plus `PyJWT`.
- `passlib` removed; `bcrypt` is canonical.

### CROG Gateway

Source: `crog-gateway/requirements.txt`

- Keeps tighter pins due to gateway behavior sensitivity.
- Must remain within major-compatibility of baseline for FastAPI/Pydantic/httpx/aiohttp.

## Rules

1. Add shared libraries to root baseline first.
2. Add service-only libraries to service override files.
3. Any major-version divergence from baseline must include compatibility test evidence.
