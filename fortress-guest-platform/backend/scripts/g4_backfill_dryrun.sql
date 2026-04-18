-- =============================================================================
-- G.4 — Backfill Gary Knight's reservations + linked guests
--       fortress_guest → fortress_shadow for Q1 2026
-- =============================================================================
-- DRY-RUN FORM: ROLLBACK at end. Gary changes to COMMIT manually.
--
-- Scope: Gary Knight (sl_owner_id 146514), 3 active properties,
--        check_in_date 2026-01-01 to 2026-03-31 inclusive.
--
-- Source: fortress_guest (via dblink)
-- Target: fortress_shadow
--
-- Property UUID mapping (guest → shadow):
--   Fallen Timber Lodge:
--     1781fd69-a7e3-4df6-9216-c6152c9c19b6 → 93b2253d-7ae4-4d6f-8be2-125d33799c88
--   Cherokee Sunrise on Noontootla Creek:
--     099f273a-6d2b-4eeb-9474-80fd89c18071 → 50a9066d-fc2e-44c4-a716-25adb8fbad3e
--   Serendipity on Noontootla Creek:
--     bdef1b0d-8c7c-4126-a9d9-249b3d6b2621 → 63bf8847-9990-4a36-9943-b6c160ce1ec4
--
-- Schema handling:
--   guest.phone_number → shadow.phone (column alias)
--   guest.created_at/updated_at/access_code_valid_*: TIMESTAMP → TIMESTAMPTZ cast
--   shadow.guest_email / guest_name / guest_phone: JOIN guests table to populate
--   shadow.is_owner_booking: DEFAULT false (no guest equivalent)
--   shadow.tax_breakdown, security_deposit_payment_method_id: NULL (no guest equivalent)
--   guest.tenant_id, pricing_*: NOT mapped (no shadow equivalent)
--
-- Conflict handling: ON CONFLICT DO NOTHING for both tables.
-- =============================================================================

BEGIN;

CREATE TEMP TABLE backfill_audit (
  step        TEXT,
  table_name  TEXT,
  inserted    INTEGER,
  skipped     INTEGER
);

-- ─── Step 0: establish dblink connection ─────────────────────────────────────
SELECT dblink_connect('fguest', 'postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_guest');

-- ─── Step 1: backfill guests ─────────────────────────────────────────────────
-- Identify unique guests linked to Gary's Q1 2026 reservations.
-- fortress_guest.guests.phone_number → fortress_shadow.guests.phone

WITH source_guests AS (
  SELECT DISTINCT ON (g.id)
    g.id,
    g.phone_number       AS phone,     -- column rename
    g.email,
    g.first_name,
    g.last_name,
    NULL::text           AS phone_number_secondary,
    NULL::text           AS email_secondary,
    g.language_preference,
    g.opt_in_marketing,
    g.preferred_contact_method,
    g.total_stays,
    g.total_messages_sent,
    g.total_messages_received,
    NULL::numeric        AS average_rating,
    g.last_stay_date,
    g.created_at::timestamptz,
    g.updated_at::timestamptz
  FROM dblink('fguest', $$
    SELECT g.id, g.phone_number, g.email, g.first_name, g.last_name,
           g.language_preference, g.opt_in_marketing, g.preferred_contact_method,
           g.total_stays, g.total_messages_sent, g.total_messages_received,
           g.last_stay_date, g.created_at, g.updated_at
    FROM guests g
    WHERE g.id IN (
      SELECT DISTINCT guest_id FROM reservations
      WHERE check_in_date >= '2026-01-01'
        AND check_in_date < '2026-04-01'
        AND property_id IN (
          '1781fd69-a7e3-4df6-9216-c6152c9c19b6',
          '099f273a-6d2b-4eeb-9474-80fd89c18071',
          'bdef1b0d-8c7c-4126-a9d9-249b3d6b2621'
        )
    )
  $$) AS g(
    id uuid, phone_number text, email text, first_name text, last_name text,
    language_preference text, opt_in_marketing boolean, preferred_contact_method text,
    total_stays integer, total_messages_sent integer, total_messages_received integer,
    last_stay_date date, created_at timestamp, updated_at timestamp
  )
),
ins_guests AS (
  INSERT INTO guests (
    id, phone, email, first_name, last_name,
    language_preference, opt_in_marketing, preferred_contact_method,
    total_stays, total_messages_sent, total_messages_received,
    last_stay_date, created_at, updated_at
  )
  SELECT
    id, phone, email, first_name, last_name,
    language_preference, opt_in_marketing, preferred_contact_method,
    total_stays, total_messages_sent, total_messages_received,
    last_stay_date, created_at, updated_at
  FROM source_guests
  ON CONFLICT (id) DO NOTHING
  RETURNING 1
)
INSERT INTO backfill_audit VALUES (
  '1', 'guests',
  (SELECT COUNT(*) FROM ins_guests),
  (SELECT COUNT(*) FROM source_guests) - (SELECT COUNT(*) FROM ins_guests)
);

-- ─── Step 2: backfill reservations ───────────────────────────────────────────
-- UUID mapping: property_id guest → shadow via CASE expression.
-- guest_email / guest_name / guest_phone populated by re-joining against
-- fortress_shadow.guests (which was just inserted above).
-- access_code_valid_from/until: TIMESTAMP → TIMESTAMPTZ cast.
-- is_owner_booking: default false (guests booking, not owner stays).

WITH source_resv AS (
  SELECT
    r.id,
    r.confirmation_code,
    r.guest_id,
    -- Property UUID mapping: guest UUID → shadow UUID
    CASE r.property_id::text
      WHEN '1781fd69-a7e3-4df6-9216-c6152c9c19b6'
        THEN '93b2253d-7ae4-4d6f-8be2-125d33799c88'::uuid
      WHEN '099f273a-6d2b-4eeb-9474-80fd89c18071'
        THEN '50a9066d-fc2e-44c4-a716-25adb8fbad3e'::uuid
      WHEN 'bdef1b0d-8c7c-4126-a9d9-249b3d6b2621'
        THEN '63bf8847-9990-4a36-9943-b6c160ce1ec4'::uuid
    END AS property_id_shadow,
    r.check_in_date,
    r.check_out_date,
    r.num_guests,
    r.num_adults,
    r.num_children,
    r.num_pets,
    r.special_requests,
    r.status,
    r.access_code,
    r.access_code_valid_from::timestamptz,
    r.access_code_valid_until::timestamptz,
    r.booking_source,
    r.total_amount,
    r.paid_amount,
    r.balance_due,
    r.nightly_rate,
    r.cleaning_fee,
    r.pet_fee,
    r.damage_waiver_fee,
    r.service_fee,
    r.tax_amount,
    r.nights_count,
    r.price_breakdown,
    r.currency,
    r.digital_guide_sent,
    r.pre_arrival_sent,
    r.access_info_sent,
    r.mid_stay_checkin_sent,
    r.checkout_reminder_sent,
    r.post_stay_followup_sent,
    r.guest_rating,
    r.guest_feedback,
    r.internal_notes,
    r.streamline_notes,
    r.streamline_financial_detail,
    r.security_deposit_required,
    r.security_deposit_amount,
    r.security_deposit_status,
    r.security_deposit_stripe_pi,
    r.security_deposit_updated_at::timestamptz,
    r.streamline_reservation_id,
    r.created_at::timestamptz,
    r.updated_at::timestamptz
  FROM dblink('fguest', $$
    SELECT
      id, confirmation_code, guest_id, property_id,
      check_in_date, check_out_date, num_guests, num_adults, num_children,
      num_pets, special_requests, status, access_code,
      access_code_valid_from, access_code_valid_until,
      booking_source, total_amount, paid_amount, balance_due,
      nightly_rate, cleaning_fee, pet_fee, damage_waiver_fee,
      service_fee, tax_amount, nights_count, price_breakdown,
      currency, digital_guide_sent, pre_arrival_sent, access_info_sent,
      mid_stay_checkin_sent, checkout_reminder_sent, post_stay_followup_sent,
      guest_rating, guest_feedback, internal_notes,
      streamline_notes, streamline_financial_detail,
      security_deposit_required, security_deposit_amount,
      security_deposit_status, security_deposit_stripe_pi,
      security_deposit_updated_at,
      streamline_reservation_id, created_at, updated_at
    FROM reservations
    WHERE check_in_date >= '2026-01-01'
      AND check_in_date < '2026-04-01'
      AND property_id IN (
        '1781fd69-a7e3-4df6-9216-c6152c9c19b6',
        '099f273a-6d2b-4eeb-9474-80fd89c18071',
        'bdef1b0d-8c7c-4126-a9d9-249b3d6b2621'
      )
  $$) AS r(
    id uuid, confirmation_code text, guest_id uuid, property_id uuid,
    check_in_date date, check_out_date date, num_guests int, num_adults int,
    num_children int, num_pets int, special_requests text, status text,
    access_code text, access_code_valid_from timestamp, access_code_valid_until timestamp,
    booking_source text, total_amount numeric, paid_amount numeric, balance_due numeric,
    nightly_rate numeric, cleaning_fee numeric, pet_fee numeric, damage_waiver_fee numeric,
    service_fee numeric, tax_amount numeric, nights_count int, price_breakdown jsonb,
    currency text, digital_guide_sent bool, pre_arrival_sent bool, access_info_sent bool,
    mid_stay_checkin_sent bool, checkout_reminder_sent bool, post_stay_followup_sent bool,
    guest_rating int, guest_feedback text, internal_notes text,
    streamline_notes jsonb, streamline_financial_detail jsonb,
    security_deposit_required bool, security_deposit_amount numeric,
    security_deposit_status text, security_deposit_stripe_pi text,
    security_deposit_updated_at timestamp,
    streamline_reservation_id text, created_at timestamp, updated_at timestamp
  )
),
ins_resv AS (
  INSERT INTO reservations (
    id, confirmation_code, guest_id, property_id,
    guest_email, guest_name, guest_phone,
    check_in_date, check_out_date, num_guests, num_adults, num_children,
    num_pets, special_requests, status, access_code,
    access_code_valid_from, access_code_valid_until,
    booking_source, total_amount, paid_amount, balance_due,
    nightly_rate, cleaning_fee, pet_fee, damage_waiver_fee,
    service_fee, tax_amount, nights_count, price_breakdown,
    currency, digital_guide_sent, pre_arrival_sent, access_info_sent,
    mid_stay_checkin_sent, checkout_reminder_sent, post_stay_followup_sent,
    guest_rating, guest_feedback, internal_notes,
    streamline_notes, streamline_financial_detail,
    security_deposit_required, security_deposit_amount,
    security_deposit_status, security_deposit_stripe_pi,
    security_deposit_updated_at,
    streamline_reservation_id, created_at, updated_at,
    is_owner_booking
  )
  SELECT
    sr.id, sr.confirmation_code, sr.guest_id, sr.property_id_shadow,
    -- Populate denormalized guest columns from fortress_shadow.guests
    COALESCE(g.email, '')                                AS guest_email,
    COALESCE(CONCAT_WS(' ', g.first_name, g.last_name), '') AS guest_name,
    g.phone                                              AS guest_phone,
    sr.check_in_date, sr.check_out_date, sr.num_guests, sr.num_adults, sr.num_children,
    sr.num_pets, sr.special_requests, sr.status, sr.access_code,
    sr.access_code_valid_from, sr.access_code_valid_until,
    sr.booking_source, sr.total_amount, sr.paid_amount, sr.balance_due,
    sr.nightly_rate, sr.cleaning_fee, sr.pet_fee, sr.damage_waiver_fee,
    sr.service_fee, sr.tax_amount, sr.nights_count, sr.price_breakdown,
    sr.currency, sr.digital_guide_sent, sr.pre_arrival_sent, sr.access_info_sent,
    sr.mid_stay_checkin_sent, sr.checkout_reminder_sent, sr.post_stay_followup_sent,
    sr.guest_rating, sr.guest_feedback, sr.internal_notes,
    sr.streamline_notes, sr.streamline_financial_detail,
    sr.security_deposit_required, sr.security_deposit_amount,
    sr.security_deposit_status, sr.security_deposit_stripe_pi,
    sr.security_deposit_updated_at,
    sr.streamline_reservation_id, sr.created_at, sr.updated_at,
    false AS is_owner_booking
  FROM source_resv sr
  LEFT JOIN guests g ON g.id = sr.guest_id
  ON CONFLICT (confirmation_code) DO NOTHING
  RETURNING 1
)
INSERT INTO backfill_audit VALUES (
  '2', 'reservations',
  (SELECT COUNT(*) FROM ins_resv),
  (SELECT COUNT(*) FROM source_resv) - (SELECT COUNT(*) FROM ins_resv)
);

-- ─── Step 3: cleanup and audit ────────────────────────────────────────────────
SELECT dblink_disconnect('fguest');

-- Audit results
SELECT step, table_name, inserted, skipped FROM backfill_audit ORDER BY step;

-- Verification checks
SELECT COUNT(*) AS total_reservations_post FROM reservations;
SELECT COUNT(*) AS gary_q1_reservations FROM reservations
  WHERE property_id IN (
    '93b2253d-7ae4-4d6f-8be2-125d33799c88',  -- Fallen Timber Lodge
    '50a9066d-fc2e-44c4-a716-25adb8fbad3e',  -- Cherokee Sunrise
    '63bf8847-9990-4a36-9943-b6c160ce1ec4'   -- Serendipity
  )
  AND check_in_date >= '2026-01-01'
  AND check_in_date < '2026-04-01';
SELECT COUNT(*) AS gary_march_reservations FROM reservations
  WHERE property_id IN (
    '93b2253d-7ae4-4d6f-8be2-125d33799c88',
    '50a9066d-fc2e-44c4-a716-25adb8fbad3e',
    '63bf8847-9990-4a36-9943-b6c160ce1ec4'
  )
  AND check_in_date >= '2026-03-01'
  AND check_in_date < '2026-04-01';
SELECT COUNT(*) AS gary_opa FROM owner_payout_accounts WHERE id = 1824;

-- ─── DRY RUN: ROLLBACK — Gary changes to COMMIT manually ─────────────────────
ROLLBACK;
