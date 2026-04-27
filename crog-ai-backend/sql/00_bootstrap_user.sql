-- ============================================================================
-- CROG-AI Database Bootstrap
-- ============================================================================
-- Creates the crog_ai_app role and grants it scoped access to the
-- hedge_fund schema in fortress_db.
--
-- Run this ONCE as a Postgres superuser before running any Alembic migration:
--
--   sudo -u postgres psql -d fortress_db -f sql/00_bootstrap_user.sql
--
-- After this completes, generate a strong password and set it:
--
--   sudo -u postgres psql -d fortress_db \
--       -c "ALTER ROLE crog_ai_app WITH PASSWORD '<strong-password-here>'"
--
-- Then store that password in .env as CROG_AI_DB_PASSWORD.
-- ============================================================================

DO $$
BEGIN
    IF current_database() != 'fortress_db' THEN
        RAISE EXCEPTION
            'This script must be run against fortress_db, not %',
            current_database();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crog_ai_app') THEN
        CREATE ROLE crog_ai_app
            WITH LOGIN
                 NOSUPERUSER
                 NOCREATEDB
                 NOCREATEROLE
                 NOINHERIT
                 NOREPLICATION
                 PASSWORD NULL;
        RAISE NOTICE 'Created role crog_ai_app (password must be set via ALTER ROLE)';
    ELSE
        RAISE NOTICE 'Role crog_ai_app already exists; password unchanged';
    END IF;
END $$;

GRANT CONNECT ON DATABASE fortress_db TO crog_ai_app;

GRANT USAGE  ON SCHEMA hedge_fund TO crog_ai_app;
GRANT CREATE ON SCHEMA hedge_fund TO crog_ai_app;

GRANT USAGE ON SCHEMA public TO crog_ai_app;
GRANT SELECT ON TABLE public.email_archive TO crog_ai_app;

ALTER DEFAULT PRIVILEGES FOR ROLE crog_ai_app IN SCHEMA hedge_fund
    GRANT ALL ON TABLES TO crog_ai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE crog_ai_app IN SCHEMA hedge_fund
    GRANT ALL ON SEQUENCES TO crog_ai_app;
ALTER DEFAULT PRIVILEGES FOR ROLE crog_ai_app IN SCHEMA hedge_fund
    GRANT ALL ON FUNCTIONS TO crog_ai_app;

\echo
\echo 'Role created: crog_ai_app'
\echo 'Schema access: hedge_fund (CREATE), public.email_archive (SELECT only)'
\echo 'Next step: ALTER ROLE crog_ai_app WITH PASSWORD ''...'''
\echo
