-- ============================================================
-- Deep Entity Swarm Alpha — batch monitoring queries
-- Campaign: deep_entity_swarm_alpha  |  Limit: 50
-- ============================================================

-- 1) Job lifecycle: did ARQ pick it up cleanly?
SELECT
    id,
    job_name,
    status,
    attempts,
    error_text,
    started_at,
    finished_at,
    finished_at - started_at AS wall_time,
    result_json->>'scanned_count'       AS scanned,
    result_json->>'recycled_count'      AS recycled,
    result_json->>'dead_classified_count' AS dead,
    result_json->>'published_messages'  AS published
FROM async_job_runs
WHERE job_name = 'run_deep_entity_swarm'
ORDER BY created_at DESC
LIMIT 5;


-- 2) Status transition summary for the alpha batch
SELECT
    status,
    grounding_mode,
    COUNT(*)                           AS row_count,
    ROUND(AVG(grade_score)::numeric, 4) AS avg_grade,
    ROUND(MIN(grade_score)::numeric, 4) AS min_grade,
    ROUND(MAX(grade_score)::numeric, 4) AS max_grade
FROM seo_redirect_remap_queue
WHERE campaign = 'deep_entity_swarm_alpha'
   OR (reviewed_by = 'deep_entity_swarm'
       AND grounding_mode = 'dead_content_404')
GROUP BY status, grounding_mode
ORDER BY status, grounding_mode;


-- 3) Recycled rows waiting for God Head grading (proposed by swarm, not yet graded)
SELECT
    id,
    source_path,
    proposed_destination_path,
    extracted_entities,
    rationale,
    grade_score,
    status,
    updated_at
FROM seo_redirect_remap_queue
WHERE campaign = 'deep_entity_swarm_alpha'
  AND status = 'proposed'
ORDER BY updated_at DESC;


-- 4) Dead content classifications (natural 404)
SELECT
    id,
    source_path,
    current_destination_path,
    review_note,
    updated_at
FROM seo_redirect_remap_queue
WHERE grounding_mode = 'dead_content_404'
  AND reviewed_by = 'deep_entity_swarm'
ORDER BY updated_at DESC
LIMIT 50;


-- 5) After God Head re-grades: promoted vs rejected breakdown
SELECT
    status,
    COUNT(*)                            AS cnt,
    ROUND(AVG(grade_score)::numeric, 4) AS avg_score,
    ROUND(MIN(grade_score)::numeric, 4) AS min_score,
    ROUND(MAX(grade_score)::numeric, 4) AS max_score
FROM seo_redirect_remap_queue
WHERE campaign = 'deep_entity_swarm_alpha'
  AND grade_score IS NOT NULL
GROUP BY status
ORDER BY status;


-- 6) Full audit trail: every row the swarm touched, ordered by outcome
SELECT
    id,
    source_path,
    proposed_destination_path,
    grounding_mode,
    status,
    grade_score,
    CASE
        WHEN status = 'superseded' AND grounding_mode = 'dead_content_404'
            THEN 'DEAD → 404'
        WHEN status = 'proposed'
            THEN 'RECYCLED → awaiting God Head'
        WHEN status = 'promoted'
            THEN 'CLEARED 0.95 → Growth Deck'
        WHEN status = 'rejected'
            THEN 'RE-REJECTED by God Head'
        ELSE status
    END AS outcome,
    extracted_entities,
    updated_at
FROM seo_redirect_remap_queue
WHERE campaign = 'deep_entity_swarm_alpha'
   OR (reviewed_by = 'deep_entity_swarm'
       AND grounding_mode = 'dead_content_404')
ORDER BY
    CASE status
        WHEN 'promoted'   THEN 1
        WHEN 'proposed'   THEN 2
        WHEN 'rejected'   THEN 3
        WHEN 'superseded' THEN 4
        ELSE 5
    END,
    grade_score DESC NULLS LAST;
