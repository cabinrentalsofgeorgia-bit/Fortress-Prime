# Issue #303 — Comment to paste (per-spark follow-up)

The active GH PAT does not have `addComment` scope on this repo — same constraint the operator surfaced in commit `a1915cb54`. Operator should paste the body below as a comment on issue #303 once this PR is reviewed.

---

## F5 follow-up — per-spark NGC sustained-transfer pattern

Diagnostic re-run by IP literal across all reachable sparks (no SSH aliases — per the inverted-naming principle that broke PR #304's "spark-2" attribution). Doc: `docs/operational/briefs/f5-per-spark-pattern-2026-04-29.md`. Stacks on PR #304 + the topology correction in commit `a1915cb54` (192.168.0.1 = TP-Link ER8411, not Mikrotik; Mikrotik is fabric-only).

### Per-spark identity confirmation

| Brief label | Mgmt IP | `hostname` | Reachable | SSH auth |
|---|---|---|---|---|
| spark-1 | 192.168.0.104 | `spark-node-1` | ✓ | OK |
| spark-2 | 192.168.0.100 | `spark-node-2` | ✓ | OK |
| spark-3 | 192.168.0.105 | `spark-3` | ✓ | OK |
| spark-4 | 192.168.0.106 | `Spark-4` | ✓ | OK |
| spark-5 | 192.168.0.109 | — | TCP/22 OK | **REJECTED** (admin & gary) |
| spark-6 | 192.168.0.115 | — | TCP/22 OK | **REJECTED** (key not enrolled) |

### Anonymous-probe results across the 4 reachable sparks

All identical:
- Egress hops 1–3 same on all sparks: 192.168.0.1 (ER8411) → 69.128.80.1 → 69.128.248.142
- Cloudflare 50 MB sustained: PASS @ 83–95 MB/s on every spark
- Ubuntu 22.04.5 100 MB sustained range: PASS @ 69–73 MB/s on every spark
- NGC api anonymous: 401 (works) on every spark
- xfiles HEAD: 403 / 146 B (CloudFront, works) on every spark
- xfiles 10 MB anonymous range: 403 / 146 B on every spark

### Pattern attribution: Provisional Pattern A (cluster-wide)

All 4 sparks behave identically at the anonymous-probe level. Confirmation that the auth'd `DownloadFileSizeMismatch` failure is also cluster-wide requires operator to re-run `ngc registry model download-version` from each spark — the autonomous run did not have NGC creds.

### Recommended operator action ranking (Pattern A, aligned to topology correction)

1. **TP-Link ER8411 web UI walk** — Application Control / IPS logs / Bandwidth Control / Connections / Firewall ACL referencing nvidia / xfiles / 3.171.171.0/22
2. **Upstream NGC IP-policy check** — note cluster outbound IP, retry from a different egress (Mac via phone hotspot) with the same NGC creds
3. **Auth'd tcpdump during real failing pull** (parked from PR #304)
4. Lowest priority: BBR → CUBIC sysctl swap (reversible; unlikely root cause given 705 MB Fastly + 100 MB Ubuntu PASS)

Mikrotik admin UI inspection is **dropped** from the list per the topology correction in `a1915cb54`.

### Audit gap surfaced

Spark-5 (192.168.0.109) and Spark-6 (192.168.0.115) reachable on TCP/22 but admin SSH key not enrolled. Operator action needed: `ssh-copy-id admin@192.168.0.109` + `ssh-copy-id admin@192.168.0.115` from a host with the admin private key, or confirm provisioned user. After enrollment, re-run the per-spark probe and confirm Pattern A holds (or expose Pattern C).

PR: `chore/f5-per-spark-ngc-pattern-2026-04-29`. Merge BLOCKED on operator review.
