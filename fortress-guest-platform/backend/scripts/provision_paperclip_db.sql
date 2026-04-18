-- Provision the isolated Paperclip control-plane database on host-native PostgreSQL 16.
-- Intended for psql:
--   psql -v paperclip_admin_password='REPLACE_WITH_ROTATED_SECRET' -f provision_paperclip_db.sql postgres
--
-- Idempotent:
-- - creates or updates the paperclip_admin role
-- - creates paperclip_db if missing
-- - reasserts ownership and public-access restrictions on every run

\if :{?paperclip_admin_password}
\else
\echo 'paperclip_admin_password variable is required'
\quit 1
\endif

SELECT format(
  'CREATE ROLE paperclip_admin LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT',
  :'paperclip_admin_password'
)
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_catalog.pg_roles
  WHERE rolname = 'paperclip_admin'
)\gexec

SELECT format(
  'ALTER ROLE paperclip_admin WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT',
  :'paperclip_admin_password'
)
WHERE EXISTS (
  SELECT 1
  FROM pg_catalog.pg_roles
  WHERE rolname = 'paperclip_admin'
)\gexec

SELECT 'CREATE DATABASE paperclip_db OWNER paperclip_admin ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_catalog.pg_database
  WHERE datname = 'paperclip_db'
)\gexec

ALTER DATABASE paperclip_db OWNER TO paperclip_admin;
REVOKE ALL ON DATABASE paperclip_db FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE paperclip_db TO paperclip_admin;

\connect paperclip_db

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO paperclip_admin;
ALTER SCHEMA public OWNER TO paperclip_admin;

COMMENT ON DATABASE paperclip_db IS
  'Paperclip control-plane state for agent conversations, task state, and audit logs. Isolated from fortress_prod and fortress_shadow.';

COMMENT ON ROLE paperclip_admin IS
  'Paperclip schema owner and migration role for paperclip_db only.';
