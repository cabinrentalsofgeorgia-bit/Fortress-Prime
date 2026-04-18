
## Pre-commit secret hook

A client-side git hook scans staged files for secrets before every commit.
Run once after cloning:

```bash
.githooks/install.sh
```

This sets `core.hooksPath = .githooks` for this repo only (no global impact).

**What it blocks:**
- Fortress API keys (`sk-fortress-*`)
- NVIDIA API keys (`nvapi-*`)
- AWS access keys (`AKIA...`)
- Stripe live keys (`sk_live_*`)
- PEM private key blocks (RSA, EC, OpenSSH)
- The shared miner_bot DB credential
- Hardcoded `password="..."` literals

**Bypass** (intentional, e.g. scrub commit): `git commit --no-verify`

**Inline skip** for a known-safe line: append `# secret-hook:allow` to the line.

The drift alarm (`fortress-drift-alarm.timer`, every 6h) catches anything that
slips through via `--no-verify`.
