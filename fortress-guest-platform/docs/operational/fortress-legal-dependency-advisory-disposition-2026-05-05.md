# Fortress Legal Dependency Advisory Disposition

Date: 2026-05-05
Status: PASS WITH MODERATE ACCEPTANCE EXPIRY

## Audit Commands

```text
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center
npm audit --json
npm audit --omit=dev --json
```

Python audit tooling was checked. `pip-audit` and `safety` were not installed on the runner, so no Python dependency audit result is claimed.

## Initial NPM Audit Result

Initial command-center audit found:

- `critical`: 1
- `high`: 3
- `moderate`: 4

Affected packages included `next`, `protobufjs`, `vite`, `path-to-regexp`, `hono`, `@hono/node-server`, `brace-expansion`, and `postcss`.

## Remediation Applied

The package manager fix path was applied, followed by a narrow direct upgrade:

- `next`: `16.1.6` to `16.2.4`
- `eslint-config-next`: `16.1.6` to `16.2.4`

This cleared all high and critical findings in the command-center audit.

## Post-Fix NPM Audit Result

Post-fix audit found:

- `critical`: 0
- `high`: 0
- `moderate`: 2

Remaining findings:

| Package | Severity | Direct/Transitive | Reachability | Disposition | Owner | Expiry |
| --- | --- | --- | --- | --- | --- | --- |
| `next` via internal `postcss` | moderate | direct package with transitive vulnerable dependency | production reachable as framework dependency; exploit is CSS stringify XSS class and no service-role/browser credential exposure was found | `ACCEPTED_WITH_EXPIRY` | Fortress Legal release operator | 2026-06-05 |
| `postcss` under `next` | moderate | transitive | production reachable through framework build/runtime dependency; audit suggested semver-major downgrade path, not a safe production upgrade | `ACCEPTED_WITH_EXPIRY` | Fortress Legal release operator | 2026-06-05 |

## Blocking Status

Blocking advisories: `NO`.

No high or critical advisories remain after remediation. The remaining moderate findings require review before or on 2026-06-05, or sooner if the framework publishes a non-breaking fixed path.
