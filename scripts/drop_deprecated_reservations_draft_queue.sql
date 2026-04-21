-- drop_deprecated_reservations_draft_queue.sql
--
-- Standalone cleanup script for fortress_db.reservations_draft_queue.
-- This table was the original sink for the reservations@ IMAP watcher.
-- It was deprecated when the email pipeline landed (PR #101-#104).
-- The write path was nullified in src/ingest_reservations_imap.py.
-- Last verified write: 2026-04-20 18:14 UTC (>48h before this script).
--
-- Run as miner_bot against fortress_db:
--   psql -h 127.0.0.1 -U miner_bot -d fortress_db -f scripts/drop_deprecated_reservations_draft_queue.sql
--
-- STOP: Gary runs this manually. Claude does not execute it.

BEGIN;

-- Guard 1: confirm table exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'reservations_draft_queue'
    ) THEN
        RAISE EXCEPTION 'reservations_draft_queue does not exist — already dropped or wrong database. Aborting.';
    END IF;
END;
$$;

-- Guard 2: confirm no writes in the last 48h
DO $$
DECLARE
    last_write timestamptz;
    cutoff     timestamptz := now() - interval '48 hours';
BEGIN
    SELECT MAX(created_at) INTO last_write FROM reservations_draft_queue;
    IF last_write IS NOT NULL AND last_write > cutoff THEN
        RAISE EXCEPTION
            'Recent write detected: last_write=% cutoff=%. Table may still be active. Aborting.',
            last_write, cutoff;
    END IF;
END;
$$;

-- Diagnostic: show row count before drop
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT COUNT(*) INTO n FROM reservations_draft_queue;
    RAISE NOTICE 'reservations_draft_queue contains % row(s). Proceeding with DROP.', n;
END;
$$;

-- The actual drop
DROP TABLE IF EXISTS reservations_draft_queue;

-- Confirm
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'reservations_draft_queue'
    ) THEN
        RAISE NOTICE 'OK — reservations_draft_queue dropped successfully.';
    ELSE
        RAISE EXCEPTION 'DROP TABLE did not take effect. Check for dependent objects.';
    END IF;
END;
$$;

COMMIT;
