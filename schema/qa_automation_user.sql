-- Provision (or rotate) the enterprise QA automation account.
-- Usage:
--   psql "$DATABASE_URL" -v qa_password="$QA_AUTOMATION_PASSWORD" -f schema/qa_automation_user.sql
--
-- This script is idempotent:
-- - Creates the account if missing.
-- - Rotates password hash if account exists.
-- - Forces role and access flags to least-privilege values.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE fortress_users ADD COLUMN IF NOT EXISTS full_name VARCHAR(100);
ALTER TABLE fortress_users ADD COLUMN IF NOT EXISTS web_ui_access BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fortress_users ADD COLUMN IF NOT EXISTS vrs_access BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO fortress_users (
    username,
    email,
    password,
    role,
    is_active,
    full_name,
    web_ui_access,
    vrs_access
)
VALUES (
    'qa-automation@crog-ai.com',
    'qa-automation@crog-ai.com',
    crypt(:'qa_password', gen_salt('bf', 12)),
    'viewer',
    TRUE,
    'QA Automation',
    FALSE,
    FALSE
)
ON CONFLICT (username) DO UPDATE
SET
    email = EXCLUDED.email,
    password = crypt(:'qa_password', gen_salt('bf', 12)),
    role = 'viewer',
    is_active = TRUE,
    full_name = 'QA Automation',
    web_ui_access = FALSE,
    vrs_access = FALSE;

COMMIT;
