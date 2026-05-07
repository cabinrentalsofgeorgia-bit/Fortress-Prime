# Read-Only System Discovery

Status: completed as a local read-only repository audit on 2026-05-07.

## Scope

Audited local checkouts and documentation for Fortress Legal topology without deploying, touching production, altering Supabase, changing auth, printing secrets, or reading `.auth` contents.

## Findings

| Question | Finding |
| --- | --- |
| Canonical repo | `cabinrentalsofgeorgia-bit/Fortress-Prime` is the canonical operational repo for current Fortress Legal work. |
| Canonical branch | `release/fortress-legal-canonicalization` is the active branch observed in the main checkout. |
| Production domain | `https://crog-ai.com`. |
| Known matter route | `/legal/cases/fortress-legal-production-review`. |
| Command-center owner | `fortress-guest-platform/apps/command-center`, package `@fortress/command-center`. |
| Runtime path | Docs indicate Cloudflare Tunnel to self-hosted Next.js on port `3005`; Vercel project metadata also exists and must be treated as deployment ambiguity. |
| Vercel project | Existing docs identify `crog-ai-command-center`; no deploy was run. |
| Supabase project | Existing docs identify `Fortress Legal Production`; ref redacted as `hms...liap`. |
| Auth model | Next.js BFF plus backend auth, `fortress_session` cookie, bearer/cookie bridging. |
| Checker | `scripts/verification/check-crog-fortress-ui.mjs`. |
| UI routes | `/legal`, `/legal/cases/[slug]`, `/legal/cases/[slug]/war-room`, `/legal/cases/[slug]/deposition/[targetId]/print`, `/legal/council`, `/legal/email-intake`. |
| Test/build gates | `npm ci`, `npm test`, `npm run lint`, `npm run typecheck`, `npm run build` from `fortress-guest-platform` are the baseline gates from the prior known-good checkpoint. |

## Repositories Observed

| Local checkout | Remote | Classification |
| --- | --- | --- |
| `/home/admin/Fortress-Prime` | `cabinrentalsofgeorgia-bit/Fortress-Prime` | Canonical active monorepo; dirty main checkout, do not stage from it. |
| `/home/admin/fortress-legal-production` | `cabinrentalsofgeorgia-bit/fortress-legal-app` | Clean split app checkout; active/unknown, not feature-equivalent to canonical unless migration is approved. |
| `/home/admin/fortress-legal-production-work/fortress-legal-app` | `cabinrentalsofgeorgia-bit/fortress-legal-app` | Dirty split app checkout; do not stage from it. |
| `/home/admin/fortress-legal-production-work/fortress-legal-wiki` | `cabinrentalsofgeorgia-bit/fortress-legal-wiki` | Dirty split wiki checkout; do not stage from it. |
| `cabinrentalsofgeorgia-bit/fortress-legal` | not found as a local checkout in this audit | Unknown; remote listed by operator but not locally inspected. |

## Blockers And Ambiguities

- Main canonical checkout is dirty with unrelated CROG backend, Market Club, Hedge Fund, rollback artifact, and docs changes.
- Root `fortress-guest-platform/package.json` at the audited checkpoint still shows broad turbo scripts; the prior baseline stabilization branch narrows command-center scripts, but that branch is not merged into this checkpoint.
- Existing docs contain both Vercel metadata and self-hosted Cloudflare Tunnel runtime evidence.
- Live runtime process state was not inspected because this audit remained repo-local and non-mutating.
- `cabinrentalsofgeorgia-bit/fortress-legal` was not present as a local checkout.

## Commands Used

Representative command classes:

- `find` for repo, route, config, and checker discovery.
- `git status -sb`, `git branch -vv`, `git log --oneline -5`, `git remote -v`, `git worktree list`.
- `rg` with `.git`, `.auth`, `.env*`, `.next`, rollback artifacts, and `node_modules` excluded where possible.

## Secret Handling

No `.auth` file contents were read. No cookies, tokens, auth headers, passwords, Supabase keys, DB URLs, or service secrets were printed into this document.
