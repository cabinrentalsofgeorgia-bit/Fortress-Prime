# NIM endpoint redirect — spark-5 (Gate 1 consolidation)

**Date:** 2026-04-24
**Target:** `http://192.168.0.109:8100` (LAN, spark-5)
**Supersedes:** `http://192.168.0.104:8000` (spark-2 / `fortress-nim-sovereign`)
**Done by:** live `.env` edit on spark-1 + worker restart. `.env` is
gitignored — this doc is the audit artifact.

## What changed

Three runtime env vars in
`fortress-guest-platform/.env` on spark-1:

| Variable | Before | After |
|---|---|---|
| `NIM_SOVEREIGN_URL` | `http://192.168.0.104:8000` | `http://192.168.0.109:8100` |
| `LEGAL_NIM_ENDPOINT` | `http://192.168.0.104:8000` | `http://192.168.0.109:8100` |
| `SOVEREIGN_DISTILL_ADAPTER_URL` | (unset → config default `127.0.0.1:8100/v1`, gated off) | `http://192.168.0.109:8100/v1` |

Pre-edit `.env` backup saved to
`fortress-guest-platform/.env.bak.nim-redirect-20260424_120648`.

## Addressing decision

LAN IP `192.168.0.109` preferred over Tailscale hostname `spark-5` /
`spark-5.taildd4879.ts.net` / Tailscale IP `100.96.13.99`:

- Median LAN health-probe latency **1.137 ms** vs Tailscale median
  **1.834 ms** — 1.61× faster.
- Worst-case (cold): LAN 2.490 ms vs Tailscale 17.051 ms.
- LAN removes the Tailscale mesh dependency — one fewer failure
  domain under the legal inference path.
- Note: there is no LAN hostname for spark-5 in `/etc/hosts` or
  `~/.ssh/config` today; the IP is written literally.

## Live verification

- `http://192.168.0.109:8100/v1/health/ready` → HTTP 200
  `"Service is ready."` (2.7 ms).
- `/v1/models` → lists `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8`
  with `max_model_len=32768`.
- Post-restart probe of `legal_council`'s effective env:
  `POST /v1/chat/completions` returned HTTP 200 with a valid
  Nemotron `<think>…` trace in 2.48 s.

## Tests

`backend/tests/test_nim_migration.py` previously hardcoded the
legacy IP in three `test_default_points_to_spark1` / -`config_default_is_spark1`
assertions. Those three line-level updates ship in this PR
(104 → 109). The remaining test assertions, probe fixtures, and the
"spark-1 IP" *comments* are intentionally untouched — the deeper
rework (assert against `cfg.nim_sovereign_url` instead of a
hardcoded IP; correct the naming comments) belongs in the
hostname-convention cleanup PR.

After edit: **11/11 green** in `test_nim_migration.py`.

## Out of scope

- `fortress-nim-brain.service` on spark-1 has **not** been stopped
  in this PR. Stopping that service (freeing the GPU for the
  CourtListener ingest via nomic) is the next operation, now
  unblocked by the redirect.
- `backend/core/config.py` still has
  `nim_sovereign_url: str = Field(default="http://192.168.0.104:8000")`.
  That default is only surfaced when both `NIM_SOVEREIGN_URL` and
  `LEGAL_NIM_ENDPOINT` are absent from `.env`. Not corrected here
  to keep the PR minimal; belongs in the hostname-convention
  cleanup PR.
- `ai_router.py:45` default `SOVEREIGN_DISTILL_ADAPTER_URL` stays
  at `127.0.0.1:8100/v1` in code — gated off by
  `SOVEREIGN_DISTILL_ADAPTER_PCT=0`. `.env` now supplies the real
  value; default only matters if the env var is ever removed.

## Rollback

```bash
cp /home/admin/Fortress-Prime/fortress-guest-platform/.env.bak.nim-redirect-20260424_120648 \
   /home/admin/Fortress-Prime/fortress-guest-platform/.env
sudo systemctl restart fortress-arq-worker
git revert <this merge sha>
```
