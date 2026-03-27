-- Run during a maintenance window after cleaning overlapping occupying reservations.
-- Preview overlaps:
--
-- SELECT a.id, a.property_id, a.check_in_date, a.check_out_date, a.status,
--        b.id, b.check_in_date, b.check_out_date, b.status
-- FROM reservations a
-- JOIN reservations b
--   ON a.property_id = b.property_id
--  AND a.id < b.id
--  AND a.status IN ('confirmed', 'checked_in', 'pending_payment')
--  AND b.status IN ('confirmed', 'checked_in', 'pending_payment')
--  AND a.check_in_date < b.check_out_date
--  AND a.check_out_date > b.check_in_date;

CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE reservations
  DROP CONSTRAINT IF EXISTS reservations_no_overlap_occupying;

ALTER TABLE reservations
  ADD CONSTRAINT reservations_no_overlap_occupying
  EXCLUDE USING gist (
    property_id WITH =,
    daterange(check_in_date, check_out_date, '[)') WITH &&
  )
  WHERE (status IN ('confirmed', 'checked_in', 'pending_payment'));
