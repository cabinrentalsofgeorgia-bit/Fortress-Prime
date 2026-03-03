-- =============================================================================
-- Migration 015: Owner Marketing Syndicate — Direct Booking Ad Escrow
-- =============================================================================
-- Fortress Prime | Cabin Rentals of Georgia
--
-- This migration:
--   1. Seeds Account 2400 (Owner Marketing Escrow) in the Iron Dome chart
--   2. Creates owner_marketing_preferences (per-property ad allocation %)
--   3. Creates marketing_attribution (MVP: admin-entered campaign metrics)
--
-- Accounting flow (Revenue Consumer Daemon):
--   When an owner opts in at X%, the daemon splits owner_share:
--     CR 2000 = owner_share * (1 - X/100)   (payout portion)
--     CR 2400 = owner_share * X/100          (marketing escrow)
--   Balance invariant: DR 1010 = CR 2000 + CR 2400 + CR 4100 + CR 2200
-- =============================================================================

BEGIN;

-- 1. Seed the Marketing Escrow liability account
INSERT INTO accounts (code, name, account_type, sub_type, normal_balance, description)
VALUES ('2400', 'Owner Marketing Escrow', 'Liability', 'Marketing', 'credit',
        'Funds earmarked from owner revenue share for direct-booking ad campaigns')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description;

-- 2. Per-property marketing allocation preferences
CREATE TABLE IF NOT EXISTS owner_marketing_preferences (
    id              SERIAL PRIMARY KEY,
    property_id     TEXT NOT NULL UNIQUE,
    marketing_pct   NUMERIC(5, 2) NOT NULL DEFAULT 0.00,
    enabled         BOOLEAN DEFAULT FALSE,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_by      TEXT DEFAULT 'owner',
    CONSTRAINT chk_mktg_pct_range CHECK (marketing_pct >= 0 AND marketing_pct <= 25)
);

CREATE INDEX IF NOT EXISTS idx_omp_property ON owner_marketing_preferences(property_id);

-- 3. Campaign attribution data (MVP: manual entry by admin/Taylor)
CREATE TABLE IF NOT EXISTS marketing_attribution (
    id                  SERIAL PRIMARY KEY,
    property_id         TEXT NOT NULL,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    ad_spend            NUMERIC(12, 2) DEFAULT 0,
    impressions         INTEGER DEFAULT 0,
    clicks              INTEGER DEFAULT 0,
    direct_bookings     INTEGER DEFAULT 0,
    gross_revenue       NUMERIC(12, 2) DEFAULT 0,
    roas                NUMERIC(8, 2) DEFAULT 0,
    campaign_notes      TEXT,
    entered_by          TEXT DEFAULT 'admin',
    created_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(property_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_ma_property ON marketing_attribution(property_id);
CREATE INDEX IF NOT EXISTS idx_ma_period   ON marketing_attribution(period_start, period_end);

COMMIT;
