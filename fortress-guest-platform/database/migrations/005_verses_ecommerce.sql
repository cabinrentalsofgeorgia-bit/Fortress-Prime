-- ============================================================================
-- Migration 005: Verses in Bloom — Isolated E-Commerce Tenant Schema
--
-- Division 3 product catalog for the premium watercolor card brand.
-- Fully isolated in its own schema to enforce tenant boundary separation
-- from the guest-operations tables in the public schema.
-- ============================================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS verses_schema;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS verses_schema.products (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku             VARCHAR(50)  UNIQUE NOT NULL,
    title           VARCHAR(255) NOT NULL,
    seo_description TEXT,
    typography_metadata JSONB    NOT NULL DEFAULT '{}'::jsonb,
    image_metadata      JSONB    NOT NULL DEFAULT '{}'::jsonb,
    stock_level     INT          DEFAULT 0,
    status          VARCHAR(30)  DEFAULT 'draft',
    created_at      TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_verses_sku    ON verses_schema.products(sku);
CREATE INDEX IF NOT EXISTS idx_verses_status ON verses_schema.products(status);

COMMIT;
