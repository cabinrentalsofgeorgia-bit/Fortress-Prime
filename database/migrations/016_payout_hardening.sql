-- Migration 016: Payout Hardening (Continuous Liquidity Production Grade)
--
-- Extends payout_ledger with retry tracking, batch accumulation, and
-- webhook-driven status progression. Adds stripe_connect_events audit table.
-- ============================================================================

BEGIN;

-- 1. Drop and re-create the status CHECK constraint to include 'held' and 'settled'
ALTER TABLE payout_ledger DROP CONSTRAINT IF EXISTS payout_ledger_status_check;
ALTER TABLE payout_ledger ADD CONSTRAINT payout_ledger_status_check
    CHECK (status IN (
        'staged', 'held', 'processing', 'completed', 'settled', 'failed', 'manual'
    ));

-- 2. Add retry tracking
ALTER TABLE payout_ledger ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

-- 3. Add batch accumulation support
ALTER TABLE payout_ledger ADD COLUMN IF NOT EXISTS batch_id TEXT;

-- 4. Add idempotency key for Stripe (derived from confirmation_code)
ALTER TABLE payout_ledger ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

-- 5. Index for batch lookups and held accumulation queries
CREATE INDEX IF NOT EXISTS idx_payout_ledger_batch
    ON payout_ledger(batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_payout_ledger_held
    ON payout_ledger(property_id, status) WHERE status = 'held';

-- 6. Stripe Connect webhook event log (audit trail for every inbound event)
CREATE TABLE IF NOT EXISTS stripe_connect_events (
    id                  SERIAL PRIMARY KEY,
    stripe_event_id     TEXT NOT NULL UNIQUE,
    event_type          TEXT NOT NULL,
    account_id          TEXT,
    transfer_id         TEXT,
    payout_id           TEXT,
    amount              NUMERIC(12,2),
    status              TEXT,
    failure_code        TEXT,
    failure_message     TEXT,
    raw_payload         JSONB,
    processed_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sce_event_type
    ON stripe_connect_events(event_type);
CREATE INDEX IF NOT EXISTS idx_sce_transfer
    ON stripe_connect_events(transfer_id) WHERE transfer_id IS NOT NULL;

COMMIT;
