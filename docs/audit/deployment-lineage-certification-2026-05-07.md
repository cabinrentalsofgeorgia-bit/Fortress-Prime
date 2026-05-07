# Deployment Lineage Certification - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-legal-next`.
Branch: `feature/fortress-legal-next`.
Mode: read-only production lineage certification with docs-only updates.

## Objective

Certify deployment lineage and artifact provenance for the live `crog-ai.com` Fortress Legal command-center runtime without deploying, restarting services, replacing artifacts, mutating infrastructure, or touching production data.

## Certified Runtime Attachment

The live `crog-ai.com` path remains:

```text
Cloudflare Tunnel
  -> http://127.0.0.1:3005
  -> crog-ai-frontend.service
  -> Next.js standalone command-center
```

Active frontend service:

- Unit: `crog-ai-frontend.service`.
- Service manager: systemd.
- Runtime user: `admin`.
- Working directory: `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.
- Start command: `node server.js`.
- Runtime port: `3005`.
- Runtime mode: `NODE_ENV=production`, `APP_MODE=command_center`.

## Active Artifact

Active artifact root:

```text
/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next
```

Active standalone root:

```text
/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center
```

The active runtime path is a normal directory path in the canonical checkout. No symlink-based immutable release strategy was observed for the active frontend artifact.

Active build ID:

```text
AfD8fzAOkRu8zUWZdKx5o
```

The same active build ID was observed in both `.next/BUILD_ID` and the standalone `.next/BUILD_ID` copy.

## Provenance Findings

The active artifact contains evidence pointing to autonomous rehearsal build lineage:

- `required-server-files.json` embeds `appDir` under `/home/admin/Fortress-Prime-autonomous-rehearsal/fortress-guest-platform/apps/command-center`.
- `server.js` embeds `outputFileTracingRoot` and Turbopack root under `/home/admin/Fortress-Prime-autonomous-rehearsal/fortress-guest-platform`.
- The autonomous rehearsal worktree inspected at `/home/admin/Fortress-Prime-autonomous-rehearsal` was on `release/fortress-legal-autonomous-rehearsal`.
- The autonomous rehearsal worktree HEAD was `94acc38b0 test(legal): add autonomous rehearsal validation logs`.
- Committed autonomous rehearsal evidence includes successful command-center build logs and service-status evidence.

Hash comparison showed:

- Active `required-server-files.json` matched the autonomous rehearsal current artifact.
- Active standalone `server.js` matched the autonomous rehearsal current artifact.
- Active standalone `package.json` matched the autonomous rehearsal current artifact.
- Active `BUILD_ID` did not match the autonomous rehearsal current artifact.
- Active `BUILD_ID` did not match the identified autonomous rollback artifact.

Observed BUILD_ID values:

```text
active canonical runtime: AfD8fzAOkRu8zUWZdKx5o
autonomous rehearsal current artifact: 2o8_XYPPF0faEQyRSlG7w
identified autonomous rollback artifact: Rvgc1arjQgphH0NE2rT4e
```

Certification result: artifact provenance is partially certified. The active code/config artifact strongly maps to the autonomous rehearsal build path, but the active BUILD_ID is not mapped to a single source commit or recorded build command.

## Deployment Mechanism

Certified:

- systemd owns the runtime.
- `crog-ai-frontend.service` starts the active standalone artifact directly from the canonical checkout.
- Cloudflare Tunnel routes the public hostname to the local port.

Not certified:

- exact build-generation command that produced the active build ID,
- exact artifact copy/promotion command,
- exact operator approval event,
- exact restart command used during promotion,
- exact rollback restore command.

## Rollback Findings

Rollback artifacts exist:

- canonical command-center `.next.rollback-*` directories,
- runtime-main rollback directories under `/home/admin/Fortress-Prime-runtime-main-20260504/`,
- autonomous rehearsal rollback artifact at `/home/admin/Fortress-Prime-runtime-main-20260504/autonomous-rehearsal-rollback-20260507-083505-autonomous-rehearsal`.

Rollback is not fully certified because no authoritative restore command, service action, expected post-rollback BUILD_ID, or smoke checklist was found for the active artifact.

## Operational Risks

- The live frontend runtime is coupled to a dirty canonical worktree.
- The active artifact is mutable in place.
- No symlink-based immutable release strategy was observed.
- Active BUILD_ID provenance is incomplete.
- Promotion and rollback procedures remain partly undocumented.
- Rollback artifacts exist, but rollback execution readiness is not certified.

## Required Future Certification

Before any production promotion:

1. Build from a clean worktree.
2. Record source branch and commit.
3. Record package-manager root and build command.
4. Record generated BUILD_ID before promotion.
5. Generate and preserve an artifact hash manifest.
6. Create and record rollback artifact before replacement.
7. Record exact promotion command.
8. Record exact rollback restore command.
9. Run and record approved smoke checks.
10. Obtain explicit operator approval for production mutation.

## Production Mutation Statement

No deploys, production mutations, runtime restarts, service mutations, artifact replacements, Cloudflare/DNS mutations, DB/Supabase mutations, auth mutations, `.auth` access, or production data mutations were performed.
