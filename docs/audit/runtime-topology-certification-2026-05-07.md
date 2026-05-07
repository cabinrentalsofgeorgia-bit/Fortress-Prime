# Runtime Topology Certification

Status: read-only certification completed on 2026-05-07.

## Scope

- Enterprise: Fortress Legal.
- Worktree: `/home/admin/Fortress-Prime-legal-next`.
- Branch: `feature/fortress-legal-next`.
- Production domain: `https://crog-ai.com`.
- Objective: certify actual runtime topology without production mutation.

## Commands And Evidence

Read-only inspection was performed with:

- `git status -sb`.
- `sed` reads of operational memory docs.
- `ss -ltnp`.
- `ps -eo pid,ppid,user,comm,args`.
- `systemctl list-units --type=service --all --no-pager`.
- `systemctl show` and `systemctl cat` with secret-bearing environment values redacted.
- `find` for Cloudflare, Vercel, and build artifact paths.
- `sed` reads of Cloudflare config with credential paths redacted.
- unauthenticated `curl -I` checks for `https://crog-ai.com/login`, `http://127.0.0.1:3005/login`, and `http://127.0.0.1:9800/`.

No credential JSON, cert, `.auth`, token, cookie, password, auth header, DB URL, or environment secret contents were read or printed.

## Runtime Processes Found

- `cloudflared.service`: active, running `/usr/bin/cloudflared --no-autoupdate --config /etc/cloudflared/config.yml tunnel run`.
- `crog-ai-frontend.service`: active, running `node server.js` from the command-center standalone directory.
- `next-server (v16.1.6)`, PID observed as `1228481`, cwd `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.
- `fortress-backend.service`: active, overridden to `/home/admin/Fortress-Prime-runtime-main-20260504/fortress-guest-platform`.
- `fortress-console.service`: active, Python console surface on port `9800`.

Multiple additional Next.js processes exist on Spark-2 for other surfaces. They are not certified as the live `crog-ai.com` command-center runtime.

## Port Mappings Found

- `0.0.0.0:3005`: `next-server (v16.1.6)`, certified command-center runtime.
- `0.0.0.0:3000`: another Next.js process, not certified as `crog-ai.com`.
- `0.0.0.0:9800`: `fortress-console.service` / `master_console.py`.
- `0.0.0.0:8000`: backend process for API/auth path.
- `127.0.0.1:8026`: separate CROG-AI backend service endpoint.

## Cloudflare Findings

Active loaded config: `/etc/cloudflared/config.yml`.

Certified mappings:

- `crog-ai.com -> http://127.0.0.1:3005`.
- `www.crog-ai.com -> http://127.0.0.1:3005`.
- `console.crog-ai.com -> http://127.0.0.1:3005`.
- `fortress.crog-ai.com -> http://127.0.0.1:9800`.
- `api.crog-ai.com -> http://127.0.0.1:9800`.
- `api.cabin-rentals-of-georgia.com -> http://127.0.0.1:8000`.
- `staging-api.crog-ai.com -> http://127.0.0.1:8026`.

The repo copy at `fortress-guest-platform/infra/gateway/config.yml` is documentation only and currently lacks the active `staging-api.crog-ai.com` mapping.

## Vercel Findings

- The clean legal worktree did not contain `.vercel/project.json` or `vercel.json`.
- The dirty canonical worktree contains Vercel metadata for `crog-ai-command-center`.
- Historical docs record Vercel deploys, protected generated deployment URLs, and rollback notes.
- Live system inspection certifies Cloudflare Tunnel to local Next.js as the active `crog-ai.com` path.

Classification: Vercel is historical/provider metadata and possible preview/protected deployment infrastructure. It is not certified as the live `crog-ai.com` runtime attachment.

## Deployment Lineage Findings

- Active frontend systemd unit: `crog-ai-frontend.service`.
- Active frontend working directory: `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.
- Active frontend start command: `node server.js`.
- Active build ID: `AfD8fzAOkRu8zUWZdKx5o`.
- Active build artifact timestamps are from 2026-05-07 around 08:34 EDT.
- Active backend path uses `/home/admin/Fortress-Prime-runtime-main-20260504/fortress-guest-platform`, not the clean legal worktree.

## Contradictions Discovered

- `crog-ai-backend/README.md` claims `Vercel (React frontend at crog-ai.com)`, which is stale.
- `fortress-guest-platform/apps/command-center/README.md` still contains default Vercel deployment template text.
- Several historical deployment docs describe Vercel production deploy and rollback paths; these are historical/provider notes and must not be treated as the certified live custom-domain attachment.
- Repo Cloudflare documentation copy is close for primary hosts but does not include the active `staging-api.crog-ai.com` mapping.

## Authoritative Runtime Path

```text
Browser request to https://crog-ai.com
  -> Cloudflare edge
  -> cloudflared.service on Spark-2
  -> /etc/cloudflared/config.yml
  -> http://127.0.0.1:3005
  -> crog-ai-frontend.service
  -> Next.js standalone command-center
```

## Remaining Ambiguity

- Exact source commit for active build ID `AfD8fzAOkRu8zUWZdKx5o` is not certified.
- Exact artifact promotion procedure into the active standalone directory is not certified.
- Vercel deployment URLs may still exist and be protected, but are not certified as the live `crog-ai.com` path.
- The active service reads environment files; their contents were intentionally not inspected.

## Production Risk Areas

- Active runtime is served from the dirty canonical worktree path, not from the clean execution worktree.
- Deployment documentation mixes Vercel provider language with self-hosted runtime facts.
- Any promotion appears to require artifact replacement and service restart, which is production mutation and requires explicit approval.
- Cloudflare documentation drift exists for at least `staging-api.crog-ai.com`.

## Required Future Certification Steps

- Map active build ID to a source commit.
- Document the exact approved artifact promotion and rollback procedure.
- Reconcile stale Vercel-only docs in a docs-only task.
- Reconcile the Cloudflare documentation copy with active config in an infra-docs task.
- Create auth-safe smoke checks that do not read `.auth` or print cookies/tokens.

## Production Mutation Statement

No deploys or production mutations were performed. No services were restarted. No DB/Supabase, Cloudflare/DNS, auth, `.auth`, production data, CROG-VRS, Hedge Fund, Market Club, or production runtime configuration was mutated.
