-- MarketClub Hedge Fund Signals release hardening verification.
--
-- This file is intentionally read-only. Run with:
-- psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f deploy/sql/marketclub_release_hardening_verification.sql

SELECT
    current_database() AS database_name,
    current_user AS connected_as,
    now() AS checked_at;

SELECT version_num
FROM hedge_fund.alembic_version_crog_ai
ORDER BY version_num;

SELECT
    object_name,
    object_kind,
    object_exists
FROM (
    VALUES
        ('hedge_fund.verify_promotion_dry_run(TEXT,TEXT)', 'function',
            to_regprocedure('hedge_fund.verify_promotion_dry_run(TEXT,TEXT)') IS NOT NULL),
        ('hedge_fund.execute_guarded_signal_promotion(UUID,TEXT,TEXT,TEXT)', 'function',
            to_regprocedure('hedge_fund.execute_guarded_signal_promotion(UUID,TEXT,TEXT,TEXT)') IS NOT NULL),
        ('hedge_fund.rollback_guarded_signal_promotion(UUID,TEXT,TEXT)', 'function',
            to_regprocedure('hedge_fund.rollback_guarded_signal_promotion(UUID,TEXT,TEXT)') IS NOT NULL),
        ('hedge_fund.acknowledge_signal_promotion_alert(TEXT,TEXT,TEXT,TEXT)', 'function',
            to_regprocedure('hedge_fund.acknowledge_signal_promotion_alert(TEXT,TEXT,TEXT,TEXT)') IS NOT NULL),
        ('hedge_fund.signal_health_model_divergence(TEXT,TEXT,INTEGER)', 'function',
            to_regprocedure('hedge_fund.signal_health_model_divergence(TEXT,TEXT,INTEGER)') IS NOT NULL),
        ('hedge_fund.signal_promotion_dry_run_acceptances', 'table',
            to_regclass('hedge_fund.signal_promotion_dry_run_acceptances') IS NOT NULL),
        ('hedge_fund.signal_promotion_executions', 'table',
            to_regclass('hedge_fund.signal_promotion_executions') IS NOT NULL),
        ('hedge_fund.signal_promotion_execution_rows', 'table',
            to_regclass('hedge_fund.signal_promotion_execution_rows') IS NOT NULL),
        ('hedge_fund.signal_promotion_alert_acknowledgements', 'table',
            to_regclass('hedge_fund.signal_promotion_alert_acknowledgements') IS NOT NULL),
        ('hedge_fund.v_signal_promotion_lifecycle_timeline', 'view',
            to_regclass('hedge_fund.v_signal_promotion_lifecycle_timeline') IS NOT NULL),
        ('hedge_fund.v_signal_promotion_reconciliation', 'view',
            to_regclass('hedge_fund.v_signal_promotion_reconciliation') IS NOT NULL),
        ('hedge_fund.v_signal_promotion_post_execution_monitoring', 'view',
            to_regclass('hedge_fund.v_signal_promotion_post_execution_monitoring') IS NOT NULL),
        ('hedge_fund.v_signal_promotion_post_execution_alerts', 'view',
            to_regclass('hedge_fund.v_signal_promotion_post_execution_alerts') IS NOT NULL),
        ('hedge_fund.v_signal_health_active_promotions', 'view',
            to_regclass('hedge_fund.v_signal_health_active_promotions') IS NOT NULL),
        ('hedge_fund.v_signal_health_at_risk_signals', 'view',
            to_regclass('hedge_fund.v_signal_health_at_risk_signals') IS NOT NULL),
        ('hedge_fund.v_signal_health_execution_outcomes', 'view',
            to_regclass('hedge_fund.v_signal_health_execution_outcomes') IS NOT NULL)
) AS objects(object_name, object_kind, object_exists)
ORDER BY object_kind, object_name;

SELECT
    n.nspname AS schema_name,
    c.relname AS table_name,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced
FROM pg_class c
JOIN pg_namespace n
  ON n.oid = c.relnamespace
WHERE n.nspname = 'hedge_fund'
  AND c.relname IN (
    'market_signals',
    'signal_shadow_review_decisions',
    'signal_promotion_dry_run_acceptances',
    'signal_promotion_executions',
    'signal_promotion_execution_rows',
    'signal_promotion_alert_acknowledgements',
    'signal_operator_memberships'
  )
ORDER BY c.relname;

SELECT
    table_schema,
    table_name,
    grantee,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'hedge_fund'
  AND table_name IN (
    'market_signals',
    'signal_shadow_review_decisions',
    'signal_promotion_dry_run_acceptances',
    'signal_promotion_executions',
    'signal_promotion_execution_rows',
    'signal_promotion_alert_acknowledgements',
    'v_signal_promotion_lifecycle_timeline',
    'v_signal_promotion_reconciliation',
    'v_signal_promotion_post_execution_monitoring',
    'v_signal_promotion_post_execution_alerts',
    'v_signal_health_active_promotions',
    'v_signal_health_at_risk_signals',
    'v_signal_health_execution_outcomes'
  )
  AND grantee IN ('PUBLIC', 'crog_ai_app')
ORDER BY table_name, grantee, privilege_type;

SELECT
    n.nspname AS schema_name,
    p.proname AS function_name,
    pg_get_function_arguments(p.oid) AS arguments,
    p.prosecdef AS security_definer,
    has_function_privilege('crog_ai_app', p.oid, 'EXECUTE') AS crog_ai_app_can_execute
FROM pg_proc p
JOIN pg_namespace n
  ON n.oid = p.pronamespace
WHERE n.nspname = 'hedge_fund'
  AND p.proname IN (
    'verify_promotion_dry_run',
    'execute_guarded_signal_promotion',
    'rollback_guarded_signal_promotion',
    'acknowledge_signal_promotion_alert',
    'signal_health_model_divergence'
  )
ORDER BY p.proname, arguments;

SELECT
    acceptance_id,
    idempotency_key,
    count(*) AS execution_count
FROM hedge_fund.signal_promotion_executions
GROUP BY acceptance_id, idempotency_key
HAVING count(*) > 1
ORDER BY execution_count DESC;

SELECT
    e.id AS execution_id,
    e.acceptance_id,
    cardinality(e.inserted_market_signal_ids) AS execution_inserted_id_count,
    count(r.market_signal_id)::INTEGER AS audited_row_count,
    e.rollback_status,
    e.rolled_back_at
FROM hedge_fund.signal_promotion_executions e
LEFT JOIN hedge_fund.signal_promotion_execution_rows r
  ON r.execution_id = e.id
GROUP BY
    e.id,
    e.acceptance_id,
    e.inserted_market_signal_ids,
    e.rollback_status,
    e.rolled_back_at
ORDER BY e.created_at DESC
LIMIT 20;

SELECT
    status,
    count(*) AS reconciliation_count
FROM hedge_fund.v_signal_promotion_reconciliation
GROUP BY status
ORDER BY status;

SELECT
    health_status,
    count(*) AS active_promotion_count
FROM hedge_fund.v_signal_health_active_promotions
GROUP BY health_status
ORDER BY health_status;
