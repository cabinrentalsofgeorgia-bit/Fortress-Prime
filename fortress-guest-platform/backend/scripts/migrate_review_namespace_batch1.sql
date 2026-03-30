-- Namespace alignment batch for archived testimonial reviews.
-- Scope: 14 default items + precedent anchor `adventures-outlaw-ridge`.
-- Goal: move review assets out of the `/properties/*` namespace and into `/reviews/*`
-- without assuming the live ledger schema is perfectly in sync with the ORM model.

BEGIN;

WITH review_targets(slug, review_path, legacy_archive_path, legacy_property_path, original_slug) AS (
  VALUES
    ('honeymoon-majestic-lake-cabin', '/reviews/honeymoon-majestic-lake-cabin', '/reviews/archive/honeymoon-majestic-lake-cabin', '/properties/honeymoon-majestic-lake-cabin', '/testimonial/honeymoon-majestic-lake-cabin'),
    ('proposal-romantic-cabin', '/reviews/proposal-romantic-cabin', '/reviews/archive/proposal-romantic-cabin', '/properties/proposal-romantic-cabin', '/testimonial/proposal-romantic-cabin'),
    ('memories-blue-ridge-etched-the-soul-forever', '/reviews/memories-blue-ridge-etched-the-soul-forever', '/reviews/archive/memories-blue-ridge-etched-the-soul-forever', '/properties/memories-blue-ridge-etched-the-soul-forever', '/testimonial/memories-blue-ridge-etched-the-soul-forever'),
    ('vacationing-with-cabin-rentals-georgia', '/reviews/vacationing-with-cabin-rentals-georgia', '/reviews/archive/vacationing-with-cabin-rentals-georgia', '/properties/vacationing-with-cabin-rentals-georgia', '/testimonial/vacationing-with-cabin-rentals-georgia'),
    ('taking-our-north-georgia-memories-home', '/reviews/taking-our-north-georgia-memories-home', '/reviews/archive/taking-our-north-georgia-memories-home', '/properties/taking-our-north-georgia-memories-home', '/testimonial/taking-our-north-georgia-memories-home'),
    ('moving-to-the-north-ga-mountains', '/reviews/moving-to-the-north-ga-mountains', '/reviews/archive/moving-to-the-north-ga-mountains', '/properties/moving-to-the-north-ga-mountains', '/testimonial/moving-to-the-north-ga-mountains'),
    ('amazing-time-this-luxury-cabin', '/reviews/amazing-time-this-luxury-cabin', '/reviews/archive/amazing-time-this-luxury-cabin', '/properties/amazing-time-this-luxury-cabin', '/testimonial/amazing-time-this-luxury-cabin'),
    ('memories-made-the-north-georgia-mountains-blue-ridge-ga', '/reviews/memories-made-the-north-georgia-mountains-blue-ridge-ga', '/reviews/archive/memories-made-the-north-georgia-mountains-blue-ridge-ga', '/properties/memories-made-the-north-georgia-mountains-blue-ridge-ga', '/testimonial/memories-made-the-north-georgia-mountains-blue-ridge-ga'),
    ('home-away-from-home-blue-ridge', '/reviews/home-away-from-home-blue-ridge', '/reviews/archive/home-away-from-home-blue-ridge', '/properties/home-away-from-home-blue-ridge', '/testimonial/home-away-from-home-blue-ridge'),
    ('relaxation-blue-ridge-luxury-cabin', '/reviews/relaxation-blue-ridge-luxury-cabin', '/reviews/archive/relaxation-blue-ridge-luxury-cabin', '/properties/relaxation-blue-ridge-luxury-cabin', '/testimonial/relaxation-blue-ridge-luxury-cabin'),
    ('honeymoon-blue-ridge-ga', '/reviews/honeymoon-blue-ridge-ga', '/reviews/archive/honeymoon-blue-ridge-ga', '/properties/honeymoon-blue-ridge-ga', '/testimonial/honeymoon-blue-ridge-ga'),
    ('beauty-the-blue-ridge-mountains', '/reviews/beauty-the-blue-ridge-mountains', '/reviews/archive/beauty-the-blue-ridge-mountains', '/properties/beauty-the-blue-ridge-mountains', '/testimonial/beauty-the-blue-ridge-mountains'),
    ('fabulous-family-fun-with-cabin-rentals-georgia', '/reviews/fabulous-family-fun-with-cabin-rentals-georgia', '/reviews/archive/fabulous-family-fun-with-cabin-rentals-georgia', '/properties/fabulous-family-fun-with-cabin-rentals-georgia', '/testimonial/fabulous-family-fun-with-cabin-rentals-georgia'),
    ('wifes-birthday-getaway-blue-ridge', '/reviews/wifes-birthday-getaway-blue-ridge', '/reviews/archive/wifes-birthday-getaway-blue-ridge', '/properties/wifes-birthday-getaway-blue-ridge', '/testimonial/wifes-birthday-getaway-blue-ridge'),
    ('adventures-outlaw-ridge', '/reviews/adventures-outlaw-ridge', '/reviews/archive/adventures-outlaw-ridge', '/properties/adventures-outlaw-ridge', '/testimonial/adventures-outlaw-ridge')
),
normalized_queue AS (
  UPDATE seo_patch_queue AS q
  SET
    target_type = 'archive_review',
    property_id = NULL,
    target_slug = t.slug,
    fact_snapshot = jsonb_strip_nulls(
      COALESCE(q.fact_snapshot, '{}'::jsonb)
      || jsonb_build_object(
        'archive_slug', t.slug,
        'archive_path', t.review_path,
        'page_path', t.review_path,
        'canonical_path', t.review_path,
        'original_slug', COALESCE(NULLIF(q.fact_snapshot->>'original_slug', ''), t.original_slug)
      )
    ),
    approved_payload = jsonb_strip_nulls(
      COALESCE(q.approved_payload, '{}'::jsonb)
      || jsonb_build_object(
        'page_path', t.review_path,
        'canonical_path', t.review_path
      )
    ),
    review_note = CASE
      WHEN POSITION('Namespace alignment batch1' IN COALESCE(q.review_note, '')) > 0 THEN q.review_note
      WHEN COALESCE(q.review_note, '') = '' THEN 'Namespace alignment batch1: normalized archived review from property namespace to /reviews namespace.'
      ELSE q.review_note || E'\nNamespace alignment batch1: normalized archived review from property namespace to /reviews namespace.'
    END,
    updated_at = NOW()
  FROM review_targets AS t
  WHERE
    q.target_slug = t.slug
    OR COALESCE(q.fact_snapshot->>'archive_slug', '') = t.slug
    OR COALESCE(q.fact_snapshot->>'archive_path', '') IN (t.legacy_property_path, t.legacy_archive_path, t.review_path)
    OR COALESCE(q.fact_snapshot->>'page_path', '') IN (t.legacy_property_path, t.legacy_archive_path, t.review_path)
    OR COALESCE(q.fact_snapshot->>'canonical_path', '') IN (t.legacy_property_path, t.legacy_archive_path, t.review_path)
    OR COALESCE(q.approved_payload->>'page_path', '') IN (t.legacy_property_path, t.legacy_archive_path, t.review_path)
    OR COALESCE(q.approved_payload->>'canonical_path', '') IN (t.legacy_property_path, t.legacy_archive_path, t.review_path)
  RETURNING q.id, q.target_slug
)
SELECT COUNT(*) AS normalized_row_count
FROM normalized_queue;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'seo_patch_queue'
      AND column_name = 'page_path'
  ) THEN
    EXECUTE $sql$
      WITH review_targets(slug, review_path, legacy_archive_path, legacy_property_path) AS (
        VALUES
          ('honeymoon-majestic-lake-cabin', '/reviews/honeymoon-majestic-lake-cabin', '/reviews/archive/honeymoon-majestic-lake-cabin', '/properties/honeymoon-majestic-lake-cabin'),
          ('proposal-romantic-cabin', '/reviews/proposal-romantic-cabin', '/reviews/archive/proposal-romantic-cabin', '/properties/proposal-romantic-cabin'),
          ('memories-blue-ridge-etched-the-soul-forever', '/reviews/memories-blue-ridge-etched-the-soul-forever', '/reviews/archive/memories-blue-ridge-etched-the-soul-forever', '/properties/memories-blue-ridge-etched-the-soul-forever'),
          ('vacationing-with-cabin-rentals-georgia', '/reviews/vacationing-with-cabin-rentals-georgia', '/reviews/archive/vacationing-with-cabin-rentals-georgia', '/properties/vacationing-with-cabin-rentals-georgia'),
          ('taking-our-north-georgia-memories-home', '/reviews/taking-our-north-georgia-memories-home', '/reviews/archive/taking-our-north-georgia-memories-home', '/properties/taking-our-north-georgia-memories-home'),
          ('moving-to-the-north-ga-mountains', '/reviews/moving-to-the-north-ga-mountains', '/reviews/archive/moving-to-the-north-ga-mountains', '/properties/moving-to-the-north-ga-mountains'),
          ('amazing-time-this-luxury-cabin', '/reviews/amazing-time-this-luxury-cabin', '/reviews/archive/amazing-time-this-luxury-cabin', '/properties/amazing-time-this-luxury-cabin'),
          ('memories-made-the-north-georgia-mountains-blue-ridge-ga', '/reviews/memories-made-the-north-georgia-mountains-blue-ridge-ga', '/reviews/archive/memories-made-the-north-georgia-mountains-blue-ridge-ga', '/properties/memories-made-the-north-georgia-mountains-blue-ridge-ga'),
          ('home-away-from-home-blue-ridge', '/reviews/home-away-from-home-blue-ridge', '/reviews/archive/home-away-from-home-blue-ridge', '/properties/home-away-from-home-blue-ridge'),
          ('relaxation-blue-ridge-luxury-cabin', '/reviews/relaxation-blue-ridge-luxury-cabin', '/reviews/archive/relaxation-blue-ridge-luxury-cabin', '/properties/relaxation-blue-ridge-luxury-cabin'),
          ('honeymoon-blue-ridge-ga', '/reviews/honeymoon-blue-ridge-ga', '/reviews/archive/honeymoon-blue-ridge-ga', '/properties/honeymoon-blue-ridge-ga'),
          ('beauty-the-blue-ridge-mountains', '/reviews/beauty-the-blue-ridge-mountains', '/reviews/archive/beauty-the-blue-ridge-mountains', '/properties/beauty-the-blue-ridge-mountains'),
          ('fabulous-family-fun-with-cabin-rentals-georgia', '/reviews/fabulous-family-fun-with-cabin-rentals-georgia', '/reviews/archive/fabulous-family-fun-with-cabin-rentals-georgia', '/properties/fabulous-family-fun-with-cabin-rentals-georgia'),
          ('wifes-birthday-getaway-blue-ridge', '/reviews/wifes-birthday-getaway-blue-ridge', '/reviews/archive/wifes-birthday-getaway-blue-ridge', '/properties/wifes-birthday-getaway-blue-ridge'),
          ('adventures-outlaw-ridge', '/reviews/adventures-outlaw-ridge', '/reviews/archive/adventures-outlaw-ridge', '/properties/adventures-outlaw-ridge')
      )
      UPDATE seo_patch_queue AS q
      SET page_path = t.review_path
      FROM review_targets AS t
      WHERE
        q.target_slug = t.slug
        OR q.page_path IN (t.legacy_property_path, t.legacy_archive_path, t.review_path);
    $sql$;
  END IF;
END $$;

-- Optional Council re-sync preflight:
-- Uncomment if you want these rows to re-enter review with a fresh approval cycle.
-- WITH review_targets(slug) AS (
--   VALUES
--     ('honeymoon-majestic-lake-cabin'),
--     ('proposal-romantic-cabin'),
--     ('memories-blue-ridge-etched-the-soul-forever'),
--     ('vacationing-with-cabin-rentals-georgia'),
--     ('taking-our-north-georgia-memories-home'),
--     ('moving-to-the-north-ga-mountains'),
--     ('amazing-time-this-luxury-cabin'),
--     ('memories-made-the-north-georgia-mountains-blue-ridge-ga'),
--     ('home-away-from-home-blue-ridge'),
--     ('relaxation-blue-ridge-luxury-cabin'),
--     ('honeymoon-blue-ridge-ga'),
--     ('beauty-the-blue-ridge-mountains'),
--     ('fabulous-family-fun-with-cabin-rentals-georgia'),
--     ('wifes-birthday-getaway-blue-ridge'),
--     ('adventures-outlaw-ridge')
-- )
-- UPDATE seo_patch_queue AS q
-- SET
--   status = 'proposed',
--   reviewed_by = NULL,
--   approved_payload = '{}'::jsonb,
--   approved_at = NULL,
--   deployed_at = NULL,
--   updated_at = NOW()
-- FROM review_targets AS t
-- WHERE q.target_slug = t.slug
--   AND q.target_type = 'archive_review';

COMMIT;

WITH review_targets(slug, review_path) AS (
  VALUES
    ('honeymoon-majestic-lake-cabin', '/reviews/honeymoon-majestic-lake-cabin'),
    ('proposal-romantic-cabin', '/reviews/proposal-romantic-cabin'),
    ('memories-blue-ridge-etched-the-soul-forever', '/reviews/memories-blue-ridge-etched-the-soul-forever'),
    ('vacationing-with-cabin-rentals-georgia', '/reviews/vacationing-with-cabin-rentals-georgia'),
    ('taking-our-north-georgia-memories-home', '/reviews/taking-our-north-georgia-memories-home'),
    ('moving-to-the-north-ga-mountains', '/reviews/moving-to-the-north-ga-mountains'),
    ('amazing-time-this-luxury-cabin', '/reviews/amazing-time-this-luxury-cabin'),
    ('memories-made-the-north-georgia-mountains-blue-ridge-ga', '/reviews/memories-made-the-north-georgia-mountains-blue-ridge-ga'),
    ('home-away-from-home-blue-ridge', '/reviews/home-away-from-home-blue-ridge'),
    ('relaxation-blue-ridge-luxury-cabin', '/reviews/relaxation-blue-ridge-luxury-cabin'),
    ('honeymoon-blue-ridge-ga', '/reviews/honeymoon-blue-ridge-ga'),
    ('beauty-the-blue-ridge-mountains', '/reviews/beauty-the-blue-ridge-mountains'),
    ('fabulous-family-fun-with-cabin-rentals-georgia', '/reviews/fabulous-family-fun-with-cabin-rentals-georgia'),
    ('wifes-birthday-getaway-blue-ridge', '/reviews/wifes-birthday-getaway-blue-ridge'),
    ('adventures-outlaw-ridge', '/reviews/adventures-outlaw-ridge')
)
SELECT
  q.id,
  q.target_type,
  q.target_slug,
  q.status,
  q.fact_snapshot->>'archive_path' AS archive_path,
  q.fact_snapshot->>'page_path' AS snapshot_page_path,
  q.approved_payload->>'page_path' AS approved_page_path
FROM seo_patch_queue AS q
JOIN review_targets AS t
  ON q.target_slug = t.slug
ORDER BY q.target_slug, q.updated_at DESC;
