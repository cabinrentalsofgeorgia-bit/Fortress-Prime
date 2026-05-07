# Fortress Legal Runtime Lineage

Status: runtime topology certification snapshot on 2026-05-07.

## Known Production Identity

- Production domain: `https://crog-ai.com`.
- Known matter: `Fortress Legal Production Review`.
- Known matter slug: `fortress-legal-production-review`.
- Production UI path: `/legal/cases/fortress-legal-production-review`.

## Certified Runtime Finding

Read-only live inspection on Spark-2 certifies this production lineage:

1. `crog-ai.com` is the staff Command Center surface.
2. Active Cloudflare Tunnel config at `/etc/cloudflared/config.yml` maps `crog-ai.com`, `www.crog-ai.com`, and `console.crog-ai.com` to `http://127.0.0.1:3005`.
3. `cloudflared.service` is active and runs `/usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run`.
4. `crog-ai-frontend.service` is active and owns the production Next.js process on port `3005`.
5. The production frontend process is `next-server (v16.1.6)`, PID observed as `1228481`, with cwd `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.
6. The systemd unit starts `node server.js` from that standalone directory with `PORT=3005`, `NODE_ENV=production`, and `APP_MODE=command_center`.
7. Unauthenticated HEAD checks showed `https://crog-ai.com/login` returning Cloudflare plus Next.js headers, and `http://127.0.0.1:3005/login` returning the same Next.js login shell directly.
8. Command-center `/api/*` route handlers proxy to the backend and preserve or synthesize `fortress_session` authentication for backend calls.

Authoritative runtime path:

```text
Client browser
  -> Cloudflare edge for crog-ai.com
  -> cloudflared.service on Spark-2
  -> /etc/cloudflared/config.yml ingress
  -> http://127.0.0.1:3005
  -> crog-ai-frontend.service
  -> self-hosted Next.js standalone command-center
```

## Vercel Evidence

Vercel evidence exists, but it is not the certified live `crog-ai.com` attachment:

- The dirty canonical worktree contains Vercel metadata for `crog-ai-command-center`.
- The clean legal worktree did not contain `.vercel/project.json` or `vercel.json`.
- Historical docs record Vercel deploy attempts, deployment URLs, provider rollback notes, and protected generated deployment URLs.
- Live local inspection certifies Cloudflare Tunnel to self-hosted Next.js as the active `crog-ai.com` path.
- Classify Vercel as **deployment metadata / historical and preview provider evidence**, not the authoritative live custom-domain runtime, until a future read-only DNS/provider check proves otherwise.
- Do not deploy to Vercel or promote any deployment without explicit operator authorization and a fresh topology check.

## Deployment Lineage

- Active frontend service: `crog-ai-frontend.service`.
- Active frontend working directory: `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.
- Active frontend start command: `node server.js`.
- Active build artifact observed under `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next`.
- Active build ID observed in both `.next/BUILD_ID` and the standalone copy: `AfD8fzAOkRu8zUWZdKx5o`.
- Active backend service for the main app is `fortress-backend.service`, currently overridden to `/home/admin/Fortress-Prime-runtime-main-20260504/fortress-guest-platform`.
- `fortress-console.service` owns the Python console surface on port `9800`, and Cloudflare maps `fortress.crog-ai.com` and `api.crog-ai.com` to that port.

Read-only deployment-lineage certification on 2026-05-07 added these findings:

- The active `.next`, `.next/standalone`, and `.next/standalone/apps/command-center` paths are direct directories in the dirty canonical checkout, not symlinks.
- The active standalone artifact is mutable in place because systemd starts directly from the canonical repo checkout.
- `required-server-files.json`, `server.js`, and the standalone `package.json` embed or match the autonomous rehearsal build root `/home/admin/Fortress-Prime-autonomous-rehearsal/fortress-guest-platform`.
- The autonomous rehearsal worktree was on `release/fortress-legal-autonomous-rehearsal` at `94acc38b0 test(legal): add autonomous rehearsal validation logs` during inspection.
- Hash comparison showed the active `required-server-files.json`, active standalone `server.js`, and active standalone `package.json` match the autonomous rehearsal worktree artifact.
- Hash comparison showed the active `BUILD_ID` files differ from the current autonomous rehearsal worktree artifact and from the identified rollback artifact.
- The strongest certified provenance is therefore **partial artifact lineage to the autonomous rehearsal build path and code/config artifact**, not a complete one-to-one mapping from active build ID to source commit.

Known BUILD_ID observations:

```text
active canonical runtime: AfD8fzAOkRu8zUWZdKx5o
autonomous rehearsal current artifact: 2o8_XYPPF0faEQyRSlG7w
identified autonomous rollback artifact: Rvgc1arjQgphH0NE2rT4e
```

Active deployment mechanism status:

- Service manager: systemd.
- Frontend unit: `crog-ai-frontend.service`.
- Runtime command: `node server.js`.
- Runtime directory: canonical checkout standalone output.
- Symlink strategy: none observed for the active frontend artifact.
- Promotion command: not certified.
- Restart window: journal evidence confirms service activity around the May 7 build/restart window, but the exact authorized promotion command sequence was not certified.

Rollback status:

- Timestamped rollback artifacts exist under the canonical command-center `.next.rollback-*` paths.
- Runtime-main rollback directories also exist under `/home/admin/Fortress-Prime-runtime-main-20260504/`.
- The autonomous rehearsal evidence records rollback artifact creation at `/home/admin/Fortress-Prime-runtime-main-20260504/autonomous-rehearsal-rollback-20260507-083505-autonomous-rehearsal`.
- No authoritative rollback restore command or rollback validation checklist was certified in this pass.

## Target Immutable Runtime Design

Future production runtime should move away from the dirty canonical checkout and use an immutable release root:

```text
/home/admin/releases/fortress-legal/
  releases/
    <timestamp>-<commit>-<buildid>/
  current -> releases/<active-release>
  previous -> releases/<previous-release>
  evidence/
  rollback/
  logs/
```

Future systemd target:

```ini
WorkingDirectory=/home/admin/releases/fortress-legal/current
ExecStart=/usr/bin/node server.js
```

Design requirements:

- `current` must point to an immutable, complete standalone artifact.
- `previous` must point to the prior known-good release before `current` changes.
- Release directory names must include timestamp, source commit, and BUILD_ID.
- Evidence must capture source branch, source commit, clean worktree status, node/npm versions, package-lock hash, build command, BUILD_ID, artifact hashes, smoke results, operator approval, timestamp, and rollback target.
- Rollback must switch to an already-certified immutable release, not a dirty checkout.
- No future service file change, symlink switch, restart, or artifact replacement is authorized by this design document alone.

## Contradictions And Drift

- `crog-ai-backend/README.md` still claims `Vercel (React frontend at crog-ai.com)`, which contradicts the certified live self-hosted topology.
- `fortress-guest-platform/apps/command-center/README.md` still contains default "Deploy on Vercel" template language.
- Active `/etc/cloudflared/config.yml` includes `staging-api.crog-ai.com -> http://127.0.0.1:8026`; the repo documentation copy under `fortress-guest-platform/infra/gateway/config.yml` does not include that active mapping.
- Historical production evidence docs include Vercel deploy and rollback procedures. Treat those as historical/provider notes, not current live attachment proof.

## Remaining Ambiguity

- The exact source commit that produced active build ID `AfD8fzAOkRu8zUWZdKx5o` remains uncertified.
- The exact build-generation command that produced active build ID `AfD8fzAOkRu8zUWZdKx5o` remains uncertified.
- The exact promotion procedure from clean build output into the active standalone directory remains uncertified.
- The exact rollback restore command and rollback smoke sequence remain uncertified.
- Vercel may still host protected deployment URLs, but those URLs are not certified as the live `crog-ai.com` path.
- Multiple Next.js processes are active on Spark-2 for other surfaces; only `crog-ai-frontend.service` on port `3005` is certified as the `crog-ai.com` command-center runtime.

## Runtime Boundaries

Agents must not:

- Deploy.
- Restart production services.
- Edit active Cloudflare config.
- Alter DNS.
- Mutate auth, RLS, storage, Supabase, or production data.
- Ingest real legal documents.
- Touch CROG-VRS, Hedge Fund, or Market Club systems.

## Read-Only Health Automation

Safe local health automation exists for observation only:

- `scripts/ops/fortress-legal-health.sh`
- `scripts/ops/spark2-control-plane-health.sh`

These scripts are allowed to inspect:

- hostname, uptime, disk, and memory,
- git branch, commit, and status for the current repo,
- operational docs presence,
- read-only service active state for `cloudflared`, `crog-ai-frontend`, `fortress-backend`, and `fortress-console`,
- listening status for ports `3005`, `9800`, `8000`, and `8026`,
- unauthenticated local HTTP endpoints.

These scripts are not deployment tools. They must not read `.auth`, print secrets, restart services, mutate systemd, switch symlinks, replace artifacts, mutate DB/Supabase, mutate Cloudflare/DNS, mutate auth, or write production data.

## Required Future Update

Before any production-facing build or promotion, update this file with:

- exact source commit,
- exact package built,
- exact deployment target,
- exact artifact hash manifest,
- exact promotion command,
- exact rollback target,
- exact rollback command,
- explicit operator approval reference.

Required future certification steps:

- Map active build ID to a source commit and artifact provenance.
- Reconcile `crog-ai-backend/README.md` and command-center template README language.
- Reconcile the Cloudflare repo documentation copy with active `/etc/cloudflared/config.yml`, including `staging-api.crog-ai.com`, in an explicitly approved infra-docs task.
- Define the non-mutating smoke checklist and rollback evidence checklist before any production approval request.
- Design and review immutable release scripts before any production migration.
- Execute a dry-run-only migration rehearsal in a clean non-production path before requesting approval to move systemd to `/home/admin/releases/fortress-legal/current`.
