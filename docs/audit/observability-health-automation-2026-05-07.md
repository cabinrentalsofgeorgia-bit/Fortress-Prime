# Observability Health Automation - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-legal-next`.
Branch: `feature/fortress-legal-next`.
Mode: read-only observability and health automation.

## Objective

Create safe read-only health tooling for Fortress Legal and the Spark-2 control plane without deploying, restarting services, mutating systemd, changing Cloudflare/DNS, mutating DB/Supabase, mutating auth, touching `.auth`, or requiring authenticated checker state.

## Scripts

Created:

- `scripts/ops/fortress-legal-health.sh`
- `scripts/ops/spark2-control-plane-health.sh`

## Checks Included

Both scripts report:

- hostname,
- UTC timestamp,
- uptime,
- disk usage,
- memory usage,
- current repo branch, commit, and status,
- required operational docs presence,
- read-only service status for:
  - `cloudflared.service`,
  - `crog-ai-frontend.service`,
  - `fortress-backend.service`,
  - `fortress-console.service`,
- read-only listening-port checks for:
  - `3005`,
  - `9800`,
  - `8000`,
  - `8026`,
- unauthenticated local HTTP HEAD checks.

The Spark-2 control-plane script also checks the external control-plane runbooks under `/home/admin/ops/runbooks`.

## Safety Behavior

- Scripts are read-only by default.
- Scripts do not deploy.
- Scripts do not restart services.
- Scripts do not call mutating `systemctl` actions.
- Scripts do not switch symlinks.
- Scripts do not replace artifacts.
- Scripts do not read `.auth`; they only report whether an `.auth` path is present without descending into it.
- Scripts do not require auth state.
- Scripts redact secret-like key/value output.
- Optional or uncertified service/port/HTTP failures are warnings.
- Missing required docs or invalid repo state are hard failures.
- Final status lines are explicit:
  - `FORTRESS_LEGAL_HEALTH_STATUS=...`
  - `SPARK2_CONTROL_PLANE_HEALTH_STATUS=...`

## Health Endpoints

Unauthenticated local checks:

- `http://127.0.0.1:3005/login`
- `http://127.0.0.1:9800/`
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8026/health`

These checks do not send auth headers, cookies, tokens, request bodies, DB writes, or legal/customer data.

## Production Mutation Statement

No deploys, service restarts, systemd mutations, symlink switches, artifact replacements, DB/Supabase mutations, Cloudflare/DNS mutations, auth mutations, `.auth` reads, production data mutations, CROG-VRS mutations, Hedge Fund mutations, or Market Club mutations were performed.
