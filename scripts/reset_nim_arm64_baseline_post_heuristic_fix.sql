-- reset_nim_arm64_baseline_post_heuristic_fix.sql
--
-- Removes the stale nim_arm64_probe_results baseline row for
-- llama-nemotron-embed-1b-v2 written on 2026-04-22 under the old
-- byte-size heuristic (which incorrectly returned ARM64_MANIFEST_MISMATCH
-- for a confirmed genuine aarch64 image).
--
-- After this script runs, the next cron execution (06:30 daily) will
-- write a fresh baseline under the corrected shared-layer-ratio heuristic,
-- which correctly returns ARM64_OK for this image.
--
-- See: docs/PHASE_ONE_AND_EMBED_INVESTIGATION_2026-04-22.md
-- Fixed by: fix/sentinel-heuristic-and-auth (PR to be merged by Gary)
--
-- Run as miner_bot against fortress_db:
--   psql -h 127.0.0.1 -U miner_bot -d fortress_db \
--     -f scripts/reset_nim_arm64_baseline_post_heuristic_fix.sql
--
-- STOP: Gary runs this manually post-merge. Claude does not execute it.

BEGIN;

-- Guard 1: confirm the table exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name   = 'nim_arm64_probe_results'
    ) THEN
        RAISE EXCEPTION
            'nim_arm64_probe_results does not exist — wrong database or table not yet created. Aborting.';
    END IF;
END;
$$;

-- Guard 2: confirm exactly one matching row (the stale baseline) exists
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT COUNT(*) INTO n
    FROM nim_arm64_probe_results
    WHERE image_path = 'nim/nvidia/llama-nemotron-embed-1b-v2'
      AND probe_date = '2026-04-22';

    IF n = 0 THEN
        RAISE EXCEPTION
            'No row found for llama-nemotron-embed-1b-v2 / 2026-04-22 — already deleted or wrong database. Aborting.';
    END IF;

    RAISE NOTICE 'Found % row(s) to delete for llama-nemotron-embed-1b-v2 / 2026-04-22. Proceeding.', n;
END;
$$;

-- Diagnostic: show the row before deletion
DO $$
DECLARE
    r record;
BEGIN
    SELECT * INTO r
    FROM nim_arm64_probe_results
    WHERE image_path = 'nim/nvidia/llama-nemotron-embed-1b-v2'
      AND probe_date = '2026-04-22'
    LIMIT 1;
    RAISE NOTICE 'Deleting row: probe_date=% image_path=% tag=% verdict=%',
        r.probe_date, r.image_path, r.tag, r.verdict;
END;
$$;

-- The actual delete
DELETE FROM nim_arm64_probe_results
WHERE image_path = 'nim/nvidia/llama-nemotron-embed-1b-v2'
  AND probe_date = '2026-04-22';

-- Confirm
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT COUNT(*) INTO n
    FROM nim_arm64_probe_results
    WHERE image_path = 'nim/nvidia/llama-nemotron-embed-1b-v2'
      AND probe_date = '2026-04-22';

    IF n > 0 THEN
        RAISE EXCEPTION 'DELETE did not remove all rows. % row(s) still present. Check for constraints.', n;
    END IF;

    RAISE NOTICE 'OK — stale baseline row deleted. Next cron run will establish a corrected baseline.';
END;
$$;

COMMIT;
