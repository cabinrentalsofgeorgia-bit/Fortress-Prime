# 004 Postgres Contract

## Runtime Boundary

Fortress Prime runs PostgreSQL 16 on the sovereign DGX cluster. The FastAPI runtime connects over **loopback** when colocated with the database, or over the **dual-lane 200G RoCE backplane** (`10.101.1.0/30`, `10.101.2.0/30`) when traffic must use the data-tier fabric.

- **Allowed hosts**: `127.0.0.1`, `localhost`, `::1`, and the four backplane endpoints `10.101.1.1`, `10.101.1.2`, `10.101.2.1`, `10.101.2.2` (see `ALLOWED_POSTGRES_HOSTS` in `backend/core/config.py`).
- **Port**: `5432`
- **External exposure**: none on WAN; backplane is LAN-isolated point-to-point only.
- **Public ingress**: prohibited
- **Tunnel policy**: Cloudflare Tunnels may front application traffic, but never direct database traffic

## Authorized Databases

These databases are in contract on the host-native PostgreSQL 16 sovereign stack:

- `fortress_prod`: production booking, transactional, audit, and SEO workloads
- `fortress_shadow`: isolated staging and shadow verification environment
- `paperclip_db`: isolated Paperclip control-plane state for conversations, task state, approvals, and audit logs

No SQLite fallback is permitted. No managed cloud database is permitted. Remote hosts outside the allowed sovereign set are rejected at settings validation.

`paperclip_db` is a hard isolation boundary. Its roles, connection strings, backups, and migration ownership must remain separate from `fortress_prod` and `fortress_shadow`. No Fortress application runtime may reuse the Paperclip lane, and Paperclip must not share ownership or runtime credentials with the Fortress application databases.

## Authentication

`pg_hba.conf` must enforce `scram-sha-256` for all Fortress Prime application roles on every path (loopback, management LAN, Docker bridges, and RoCE backplane /30s). Password authentication is mandatory for both migration and runtime lanes.

- Loopback: `127.0.0.1/32`, `::1/128`
- Backplane: `10.101.1.0/30`, `10.101.2.0/30`
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

### `paperclip_admin`

Use this role only for Paperclip schema ownership and migrations inside `paperclip_db`.

- Owns the `paperclip_db` database and `public` schema
- Executes Paperclip schema migrations and extension setup inside `paperclip_db`
- Must not be used by `fortress-guest-platform` request paths
- Must not own objects in `fortress_prod` or `fortress_shadow`
- Must authenticate with `scram-sha-256`

## Connection Contract

Fortress application environment variables:

- `POSTGRES_ADMIN_URI`: fortress_admin migration lane
- `POSTGRES_API_URI`: fortress_api runtime lane

Required URI rules (enforced by Pydantic settings):

- Host must be in `ALLOWED_POSTGRES_HOSTS`
- Port must be `5432`
- Database must be `fortress_prod` or `fortress_shadow`
- Admin role must authenticate as `fortress_admin`
- Runtime role must authenticate as `fortress_api`

On the Captain (worker) host, production may set `.env.dgx` to use the backplane address of the PostgreSQL node (e.g. `10.101.1.2`) so DB I/O stays on the 200G data plane.

Paperclip is a separate control-plane lane. Its database connection must target `paperclip_db` with the dedicated `paperclip_admin` ownership path (and a future runtime role, if introduced) through deployment-specific secrets, not through `POSTGRES_ADMIN_URI` or `POSTGRES_API_URI`.

## Qdrant alignment

Vector traffic uses `QDRANT_URL` (client) and `QDRANT_HTTP_URL` (readiness probes in system health). For the same backplane cutover, point both at the Qdrant HTTP endpoint on the backplane host (e.g. `http://10.101.1.2:6333`) when the container publishes on all interfaces.

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
- Paperclip archive path: `/mnt/fortress_nas/backups/postgres/paperclip`
- Retention policy: enforced by host-side rotation job after successful archive verification

Recommended cron execution:

```cron
15 2 * * * /usr/bin/pg_dump --format=custom --file /mnt/fortress_nas/backups/postgres/daily/fortress_prod_$(date +\%Y\%m\%d).dump fortress_prod
45 2 * * * /usr/bin/pg_dump --format=custom --file /mnt/fortress_nas/backups/postgres/shadow/fortress_shadow_$(date +\%Y\%m\%d).dump fortress_shadow
20 3 * * * /usr/bin/pg_dump --format=custom --file /mnt/fortress_nas/backups/postgres/paperclip/paperclip_db_$(date +\%Y\%m\%d).dump paperclip_db
```

The backup job must run on the DGX host, write directly to the mounted NAS target, and emit audit logs on both success and failure.
