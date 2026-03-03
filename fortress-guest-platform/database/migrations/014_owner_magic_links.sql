-- =============================================================================
-- Migration 014: Passwordless Owner Authentication (Magic Link Token Vault)
-- =============================================================================
-- Stores only SHA-256 hashes of magic link tokens, never raw tokens.
-- If the database is compromised, the links remain useless.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS owner_magic_tokens (
    id              SERIAL PRIMARY KEY,
    token_hash      TEXT UNIQUE NOT NULL,
    owner_email     TEXT NOT NULL,
    sl_owner_id     TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    used_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_owner_magic_token_hash ON owner_magic_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_owner_magic_email ON owner_magic_tokens(owner_email);

GRANT SELECT, INSERT, UPDATE ON owner_magic_tokens TO fgp_app;
GRANT USAGE, SELECT ON SEQUENCE owner_magic_tokens_id_seq TO fgp_app;

COMMIT;
