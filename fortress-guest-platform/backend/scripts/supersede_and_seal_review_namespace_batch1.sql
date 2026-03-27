-- Supersede stale duplicates and approve the 15 fresh /reviews namespace records.
-- This script is intentionally explicit: it targets the known duplicate IDs and
-- the exact 15 fresh proposal IDs that were staged in review_namespace_batch1.json.

BEGIN;

DO $$
DECLARE
  fresh_count integer;
BEGIN
  SELECT COUNT(*)
  INTO fresh_count
  FROM seo_patch_queue
  WHERE id IN (
    '666c5a57-c5a9-4a2c-83da-1b887359549f',
    'b5fbb199-7526-4458-9599-4061c68a7f18',
    '1779f151-4db2-4439-a998-b1d6813e4135',
    '6b83f2f9-96f5-4dc7-9421-0f2dedbff435',
    '5f55caf8-3e70-49a4-971e-ed0b5f23868b',
    'ad703302-6052-4035-b5e6-ef69a56f1e74',
    'b59b207b-ca92-4fb0-8696-54c77e5db11c',
    '73b45361-6074-4693-8535-6969364b0c68',
    '264caa4f-b8e5-4fca-9fd7-be8708d518f4',
    '4909cf88-ece0-4fc2-92e2-998ac99fee32',
    '038820fb-0774-4ec5-80e1-11408a467775',
    '82114011-5a2c-4bbb-a95d-d2c56816ceb0',
    '35a716db-71aa-4378-9f48-7984830a72d8',
    '56ff44ab-c456-4333-8bcf-c82433078097',
    'c460d5d2-05c9-41a4-bb13-df9df05cca42'
  )
    AND target_type = 'archive_review'
    AND status IN ('proposed', 'needs_revision');

  IF fresh_count <> 15 THEN
    RAISE EXCEPTION 'Expected 15 fresh review proposals ready for approval, found %', fresh_count;
  END IF;
END $$;

WITH stale_rows(id, slug, note) AS (
  VALUES
    (
      '5f0f2877-f2b8-4a1c-aeb0-603721ee8e0d'::uuid,
      'honeymoon-majestic-lake-cabin',
      'Namespace seal batch1: superseded prior RESTORE_OP_2026 approval in favor of the /reviews namespace-aligned archive_review payload.'
    ),
    (
      '7d25239b-7862-48c1-ba51-0fca214af7d1'::uuid,
      'adventures-outlaw-ridge',
      'Namespace seal batch1: superseded older duplicate proposal in favor of the latest /reviews namespace-aligned archive_review payload.'
    )
)
UPDATE seo_patch_queue AS q
SET
  status = 'superseded',
  review_note = CASE
    WHEN COALESCE(q.review_note, '') = '' THEN s.note
    WHEN POSITION(s.note IN q.review_note) > 0 THEN q.review_note
    ELSE q.review_note || E'\n' || s.note
  END,
  updated_at = NOW()
FROM stale_rows AS s
WHERE q.id = s.id;

WITH fresh_rows(id, slug) AS (
  VALUES
    ('666c5a57-c5a9-4a2c-83da-1b887359549f'::uuid, 'adventures-outlaw-ridge'),
    ('b5fbb199-7526-4458-9599-4061c68a7f18'::uuid, 'amazing-time-this-luxury-cabin'),
    ('1779f151-4db2-4439-a998-b1d6813e4135'::uuid, 'beauty-the-blue-ridge-mountains'),
    ('6b83f2f9-96f5-4dc7-9421-0f2dedbff435'::uuid, 'fabulous-family-fun-with-cabin-rentals-georgia'),
    ('5f55caf8-3e70-49a4-971e-ed0b5f23868b'::uuid, 'home-away-from-home-blue-ridge'),
    ('ad703302-6052-4035-b5e6-ef69a56f1e74'::uuid, 'honeymoon-blue-ridge-ga'),
    ('b59b207b-ca92-4fb0-8696-54c77e5db11c'::uuid, 'honeymoon-majestic-lake-cabin'),
    ('73b45361-6074-4693-8535-6969364b0c68'::uuid, 'memories-blue-ridge-etched-the-soul-forever'),
    ('264caa4f-b8e5-4fca-9fd7-be8708d518f4'::uuid, 'memories-made-the-north-georgia-mountains-blue-ridge-ga'),
    ('4909cf88-ece0-4fc2-92e2-998ac99fee32'::uuid, 'moving-to-the-north-ga-mountains'),
    ('038820fb-0774-4ec5-80e1-11408a467775'::uuid, 'proposal-romantic-cabin'),
    ('82114011-5a2c-4bbb-a95d-d2c56816ceb0'::uuid, 'relaxation-blue-ridge-luxury-cabin'),
    ('35a716db-71aa-4378-9f48-7984830a72d8'::uuid, 'taking-our-north-georgia-memories-home'),
    ('56ff44ab-c456-4333-8bcf-c82433078097'::uuid, 'vacationing-with-cabin-rentals-georgia'),
    ('c460d5d2-05c9-41a4-bb13-df9df05cca42'::uuid, 'wifes-birthday-getaway-blue-ridge')
)
UPDATE seo_patch_queue AS q
SET
  status = 'approved',
  reviewed_by = 'system:namespace-seal',
  review_note = 'Namespace seal batch1: approved after /reviews namespace alignment and duplicate cleanup.',
  approved_payload = jsonb_build_object(
    'title', COALESCE(q.proposed_title, ''),
    'meta_description', COALESCE(q.proposed_meta_description, ''),
    'h1', COALESCE(q.proposed_h1, ''),
    'intro', COALESCE(q.proposed_intro, ''),
    'faq', COALESCE(q.proposed_faq, '[]'::jsonb),
    'json_ld', COALESCE(q.proposed_json_ld, '{}'::jsonb),
    'target_keyword', COALESCE(q.target_keyword, ''),
    'campaign', COALESCE(q.campaign, 'default'),
    'rubric_version', COALESCE(q.rubric_version, 'v1'),
    'page_path', COALESCE(q.fact_snapshot->>'page_path', q.fact_snapshot->>'archive_path', '/reviews/' || q.target_slug),
    'canonical_path', COALESCE(q.fact_snapshot->>'canonical_path', q.fact_snapshot->>'archive_path', '/reviews/' || q.target_slug)
  ),
  approved_at = NOW(),
  updated_at = NOW()
FROM fresh_rows AS f
WHERE q.id = f.id
  AND q.status IN ('proposed', 'needs_revision');

COMMIT;

WITH target_slugs(slug) AS (
  VALUES
    ('honeymoon-majestic-lake-cabin'),
    ('proposal-romantic-cabin'),
    ('memories-blue-ridge-etched-the-soul-forever'),
    ('vacationing-with-cabin-rentals-georgia'),
    ('taking-our-north-georgia-memories-home'),
    ('moving-to-the-north-ga-mountains'),
    ('amazing-time-this-luxury-cabin'),
    ('memories-made-the-north-georgia-mountains-blue-ridge-ga'),
    ('home-away-from-home-blue-ridge'),
    ('relaxation-blue-ridge-luxury-cabin'),
    ('honeymoon-blue-ridge-ga'),
    ('beauty-the-blue-ridge-mountains'),
    ('fabulous-family-fun-with-cabin-rentals-georgia'),
    ('wifes-birthday-getaway-blue-ridge'),
    ('adventures-outlaw-ridge')
)
SELECT
  q.target_slug,
  q.status,
  q.reviewed_by,
  q.approved_at,
  q.fact_snapshot->>'archive_path' AS archive_path,
  q.approved_payload->>'page_path' AS approved_page_path
FROM seo_patch_queue AS q
JOIN target_slugs AS t
  ON t.slug = q.target_slug
ORDER BY q.target_slug, q.updated_at DESC, q.created_at DESC;
