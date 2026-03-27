# 004 Postgres Contract

## Runtime Boundary

Fortress Prime runs PostgreSQL 16 locally on the DGX host. The FastAPI runtime and PostgreSQL share the same machine boundary and communicate over loopback only.

- Host: `127.0.0.1`
- Port: `5432`
- External exposure: none
- Public ingress: prohibited
- Tunnel policy: Cloudflare Tunnels may front application traffic, but never direct database traffic

## Authorized Databases

Only these databases are in contract for the `fortress-guest-platform` runtime:

- `fortress_prod`: production booking, transactional, audit, and SEO workloads
- `fortress_shadow`: isolated staging and shadow verification environment

No SQLite fallback is permitted. No remote PostgreSQL host is permitted. No managed cloud database is permitted.

## Authentication

`pg_hba.conf` must enforce `scram-sha-256` for all Fortress Prime application roles. Password authentication is mandatory for both migration and runtime lanes.

- Local address scope: `127.0.0.1/32`
- Auth method: `scram-sha-256`
- Trust auth: prohibited
- Peer auth for application roles: prohibited

## Least-Privilege Roles

### `fortress_admin`

Use this role only for schema ownership and Alembic migrations.

- Owns application schemas and migration history objects
- Executes `alembic upgrade` and `alembic downgrade`
- May create, alter, and index tables
- Must not be used by the FastAPI request path

### `fortress_api`

Use this role only for the FastAPI runtime.

- Granted `SELECT`, `INSERT`, `UPDATE`, `DELETE` on application tables and sequences as required
- May execute transactional booking flows, advisory-lock workloads, and SEO queue processing
- Cannot `CREATE`, `ALTER`, `DROP`, or manage databases
- Cannot own Alembic artifacts

## Connection Contract

Environment variables:

- `POSTGRES_ADMIN_URI`: fortress_admin migration lane
- `POSTGRES_API_URI`: fortress_api runtime lane

Required URI rules:

- Host must be `127.0.0.1`
- Port must be `5432`
- Database must be `fortress_prod` or `fortress_shadow`
- Admin role must authenticate as `fortress_admin`
- Runtime role must authenticate as `fortress_api`

## Workload Intent

This contract is designed to support two concurrent pressure profiles on the same sovereign database stack:

- High-concurrency transactional booking flows: Fast Quote, reservation holds, checkout confirmation, and advisory locks
- Asynchronous SEO Swarm workloads: patch queues, rubric evaluation, redirect operations, and archive-safe content pipelines

The runtime pool must therefore favor low-latency reuse, bounded overflow, and explicit health checks over opportunistic autoconfiguration.

## Backup Routing

Daily logical backups route directly from the DGX host to the mounted Synology 1825+ NAS over the FastConnect X fabric.

- NAS mount root: `/mnt/fortress_nas/backups/postgres`
- Daily archive path: `/mnt/fortress_nas/backups/postgres/daily`
- Shadow archive path: `/mnt/fortress_nas/backups/postgres/shadow`
- Retention policy: enforced by host-side rotation job after successful archive verification

Recommended cron execution:

```cron
15 2 * * * /usr/bin/pg_dump --format=custom --file /mnt/fortress_nas/backups/postgres/daily/fortress_prod_$(date +\%Y\%m\%d).dump fortress_prod
45 2 * * * /usr/bin/pg_dump --format=custom --file /mnt/fortress_nas/backups/postgres/shadow/fortress_shadow_$(date +\%Y\%m\%d).dump fortress_shadow
```

The backup job must run on the DGX host, write directly to the mounted NAS target, and emit audit logs on both success and failure.
