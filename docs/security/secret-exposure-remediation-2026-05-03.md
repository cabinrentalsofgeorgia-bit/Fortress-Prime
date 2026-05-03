# Secret Exposure Remediation - 2026-05-03

This document records the foundation-hardening secret cleanup. It intentionally does not include secret values.

## Changes Made

- Replaced tracked LiteLLM static `api_key` values with `os.environ/...` references.
- Replaced tracked database passwords and DSNs with required environment variable references.
- Replaced legacy CourtListener hardcoded API tokens with `COURTLISTENER_API_TOKEN`.
- Removed default/fallback auth values from legacy scripts.
- Hardened `.gitignore` for env files, key files, cert files, local LiteLLM config, and local SSL material.
- Normalized tracked `.env*.example` files to placeholder-only values.

## Credentials To Rotate

Rotate these credentials if they were ever active, copied from production, shared outside the operator host, or present in any pushed branch history:

- LiteLLM local route key now expected as `SOVEREIGN_LLM_API_KEY`.
- LiteLLM legal embedding key now expected as `SOVEREIGN_EMBED_API_KEY`.
- LiteLLM master key `LITELLM_MASTER_KEY` if any tracked/static value was ever used.
- CourtListener token now expected as `COURTLISTENER_API_TOKEN`.
- DGX inference key `DGX_INFERENCE_API_KEY` if the old fallback was accepted by any endpoint.
- Postgres users embedded in prior tracked files, including `fgp_app`, `fortress_api`, `analyst_reader`, and `miner_bot`.

- Streamline API credentials now expected as `STREAMLINE_API_KEY` and `STREAMLINE_API_SECRET` if the hydration scripts were ever run with tracked literals.
- Redis credentials used by batch tooling if any literal or copied runtime value was exposed.
- Any service credentials stored in ignored local `.env*` files that were moved out of the repo workspace.

## Local Secret Storage

Ignored local secret files from `/home/admin/Fortress-Prime` were moved to `/home/admin/.fortress-secrets/Fortress-Prime-2026-05-03/` with owner-only permissions. Future local secret files should live outside the repo workspace, preferably under `/home/admin/.fortress-secrets/` or `/etc/fortress/`. Runtime services should load them through explicit environment files, systemd credentials, Docker secrets, or the existing `deploy/secrets` loader.

## Follow-Up Gate

Before merging this hardening branch, run a dedicated scanner such as `gitleaks`, `trufflehog`, or `detect-secrets` across the current tree and commit history. Those tools were not installed on spark-2 during the initial audit.

## Gitleaks Scan Results

Run on 2026-05-03 with `ghcr.io/gitleaks/gitleaks:v8.30.1` and full redaction enabled.

- Current-tree scan of `/home/admin/Fortress-Prime-foundation-hardening`: 0 findings after remediation.
- Git-history scan of the same worktree: 335 redacted findings remain in prior commits/history.
- Redacted reports are stored outside the repo at `/tmp/fortress-secret-scan/gitleaks-dir.json` and `/tmp/fortress-secret-scan/gitleaks-git.json`.

High-risk history findings include prior OpenAI, Anthropic, GCP-like, JWT, and curl authorization header matches. Because history findings may have been pushed to GitHub, treat affected credentials as exposed and rotate them rather than relying on source cleanup alone.
