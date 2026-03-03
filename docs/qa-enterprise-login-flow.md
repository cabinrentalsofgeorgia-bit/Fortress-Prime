# Enterprise QA Login Flow

This repository now supports front-door E2E authentication for Playwright using a dedicated service account.

## Canonical Login Contract

- URL: `POST http://localhost:9800/api/login`
- Content type: `application/json`
- Body:
  - `username`
  - `password`

The endpoint sets the real `fortress_session` cookie used by the Command Center.

## Playwright Wiring

- Global setup file: `fortress-guest-platform/frontend-next/playwright/global-setup.ts`
- Storage state output: `fortress-guest-platform/frontend-next/playwright/.auth/qa-session.json`
- Config entry: `fortress-guest-platform/frontend-next/playwright.config.ts`

Required environment variable:

- `QA_AUTOMATION_PASSWORD` (required)
- `QA_AUTOMATION_USERNAME` (optional, defaults to `qa-automation@crog-ai.com`)
- `QA_LOGIN_URL` (optional, defaults to `http://localhost:9800/api/login`)

## Service Account Provisioning

Provision or rotate the QA account with:

```bash
psql "$DATABASE_URL" \
  -v qa_password="$QA_AUTOMATION_PASSWORD" \
  -f schema/qa_automation_user.sql
```

The SQL script is idempotent and enforces least privilege:

- Username/email fixed to `qa-automation@crog-ai.com`
- Role fixed to `viewer`
- `web_ui_access = false`
- `vrs_access = false`

## Mutation Guardrail

`tools/master_console.py` now blocks all mutating requests (`POST`, `PATCH`, `PUT`, `DELETE`) from the QA automation account after login, except:

- `POST /api/login`
- `POST /api/logout`

This allows full front-door authentication while preventing data mutation in live environments.
