# F5 Follow-Up — Per-Spark NGC Sustained-Transfer Pattern

**Date:** 2026-04-29
**Branch:** `chore/f5-per-spark-ngc-pattern-2026-04-29`
**Stacks on:** PR #304 (F5 investigation surface), Issue #303 (F5 P3)
**Driver:** PR #304 ran from SSH alias `spark-2` which resolved to host `spark-node-1` (naming inversion). This brief re-runs the diagnostic by **IP literal** on every reachable spark to determine whether F5 is cluster-wide (Pattern A), single-spark (B), or grouped (C).

**Topology note (per PR #304 follow-up commit `a1915cb54`):** The egress middlebox at `192.168.0.1` is the **TP-Link ER8411 Omada Pro VPN Router** (verified via ARP OUI `98:ba:5f` = TP-Link Systems Inc., and Omada Pro UI signature `/webpages/login.html`). The Mikrotik CRS812 is fast-fabric-only (`10.10.10/24` + `10.10.11/24`, MTU 9000) and NOT in the internet-egress path. The original brief's "Mikrotik" labeling is corrected accordingly throughout this doc — every spark egress goes through the ER8411.
**Status:** Diagnosis only. Fix is operator-side.

---

## 1. Discipline: IP literals only

All SSH commands in this brief use `admin@192.168.0.10X` literals. **No SSH aliases used.** Per MASTER-PLAN principle "Use IP literals when SSH alias divergence suspected" — that is the entire premise of this follow-up.

Each probe captured `hostname` to confirm the IP → host mapping at run time.

## 2. Per-spark identity confirmation

| Brief label | Mgmt IP | Reported `hostname` | Reachable | SSH auth |
|---|---|---|---|---|
| spark-1 | 192.168.0.104 | `spark-node-1` | ✓ | OK |
| spark-2 | 192.168.0.100 | `spark-node-2` | ✓ | OK |
| spark-3 | 192.168.0.105 | `spark-3` | ✓ | OK |
| spark-4 | 192.168.0.106 | `Spark-4` | ✓ | OK |
| spark-5 | 192.168.0.109 (per `/etc/hosts`) | — | TCP/22 OK | **REJECTED** (publickey for admin and gary) |
| spark-6 | 192.168.0.115 (per `/etc/hosts`) | — | TCP/22 OK | **REJECTED** (host key new; auth still rejected after accept-new) |

**Naming inversion confirmed:** SSH alias `spark-2` (per `~/.ssh/config`) maps to `192.168.0.104`, whose `hostname` is `spark-node-1` (operator labels it spark-1 in the IP map). PR #304 ran from this host. The mapping the operator uses in this brief (and in the per-IP labels above) is internally consistent.

**Audit gap (spark-5 + spark-6):** Both reachable on TCP/22 but admin's SSH key is not enrolled on either; alternate user `gary` also rejected. Operator must enroll the key (or hand a working credential) before autonomous diagnostics on these sparks become possible. Per brief stop conditions, treated as gap, not failure.

## 3. Probe definition (run identically on each reachable spark)

Per the brief §3–§8. Single shell script `/tmp/per-spark-probe.sh` piped over SSH to each spark by IP literal:

1. `hostname` + `ip -4 addr show | grep 192.168`
2. `mtr -n -c 2 -r -w xfiles.ngc.nvidia.com` and same for `speed.cloudflare.com` (`traceroute` not installed; `mtr` substituted)
3. `curl ... speed.cloudflare.com/__down?bytes=50000000` (50 MB sustained)
4. `curl ... releases.ubuntu.com/22.04.5/ubuntu-22.04.5-live-server-amd64.iso -r 0-104857599` (100 MB Ubuntu range download — brief's URL `releases.ubuntu.com/24.04/...` returned 404; substituted 22.04.5 LTS path)
5. `curl ... api.ngc.nvidia.com/v2/org/nim` (NGC api anonymous probe)
6. `curl -I ... xfiles.ngc.nvidia.com/` (xfiles HEAD)
7. `curl ... xfiles.ngc.nvidia.com/ -r 0-10485759` (10 MB anonymous range request to xfiles)
8. Cleanup `/tmp/*.bin`

**Limitation reconfirmed from PR #304:** anonymous probes cannot exercise the actual `DownloadFileSizeMismatch` failure mode (which requires auth'd NGC weight pull). What §3.7 measures is whether the connection completes at all — not whether sustained auth'd transfer would succeed.

## 4. Comparison table

| Spark | Egress hops 1–3 | CF 50 MB | Ubuntu 100 MB | NGC api anon | xfiles HEAD | xfiles range 10 MB anon |
|---|---|---|---|---|---|---|
| spark-1 (104, `spark-node-1`) | 192.168.0.1 (TP-Link ER8411 egress, OUI `98:ba:5f`) → 69.128.80.1 → 69.128.248.142 | **PASS** 83 MB/s, http 200 | **PASS** 73 MB/s, http 206 | http 401, 115 B | http 403, 146 B | http 403, 146 B (range rejected; small body returned) |
| spark-2 (100, `spark-node-2`) | same | **PASS** 95 MB/s, http 200 | **PASS** 71 MB/s, http 206 | http 401, 117 B | http 403, 146 B | http 403, 146 B |
| spark-3 (105, `spark-3`) | same | **PASS** 95 MB/s, http 200 | **PASS** 69 MB/s, http 206 | http 401, 115 B | http 403, 146 B | http 403, 146 B |
| spark-4 (106, `Spark-4`) | same | **PASS** 90 MB/s, http 200 | **PASS** 70 MB/s, http 206 | http 401, 117 B | http 403, 146 B | http 403, 146 B |
| spark-5 (109) | — | gap | gap | gap | gap | gap |
| spark-6 (115) | — | gap | gap | gap | gap | gap |

**Bandwidth consumed:** ~150 MB × 4 sparks ≈ **600 MB total** (within 2 GB cap).

## 5. Pattern determination

### Pattern attribution: **Pattern A (cluster-wide identical behavior)** — at the anonymous-probe level

Evidence supporting A:
- All 4 reachable sparks egress through identical first-3-hop path (192.168.0.1 TP-Link ER8411 → 69.128.80.1 ISP → 69.128.248.142 ISP backbone)
- All 4 sparks PASS Cloudflare 50 MB sustained at 83–95 MB/s
- All 4 sparks PASS Ubuntu 100 MB sustained at 69–73 MB/s
- All 4 sparks return identical 403/146-byte response from xfiles HEAD and range request — TCP/TLS path to xfiles works equivalently from all
- No per-spark divergence at the anonymous-probe level

Evidence against B (single-spark):
- Zero variance in measurements between sparks. If B were true, at least one spark would show a different connection profile.

Evidence against C (group/VLAN):
- All 4 sparks share identical ER8411 first-hop and identical ISP-edge hop. There is no observed grouping that could give different sparks different egress treatment in this dataset.

### What this dataset does NOT confirm

Anonymous xfiles HEAD/range requests succeed on all sparks (with 403 — destination reachable, just unauthorized). The actual reported failure mode is `DownloadFileSizeMismatch` on **auth'd** weight pulls. This dataset cannot exercise that failure path.

So: **Pattern A is the most consistent attribution given uniform anonymous behavior**, but confirmation that the auth'd failure is also uniform requires the operator to re-run an actual `ngc registry model download-version` from each spark with `NGC_CLI_API_KEY` exported. If all four sparks fail identically on auth'd pull, Pattern A is locked in; if they diverge, the conclusion shifts.

Until that auth'd cross-check runs, Pattern A is the **provisional** attribution.

## 6. Recommended operator action ranking (Pattern A)

If operator confirms Pattern A via auth'd cross-check, ranked by efficiency (aligned to PR #304 follow-up commit `a1915cb54` topology correction):

1. **TP-Link ER8411 web UI inspection** (highest yield): cluster-wide uniform behavior is consistent with a router/firewall-tier policy at the egress middlebox. The ER8411 is the only operator-side device between the cluster and the ISP. Walk the Omada Pro UI:
    - **Application Control logs / rules** — any application category that includes NVIDIA / cloud-storage / file-download with throttle or block rule active
    - **IPS logs** — pattern-match false positives on NGC traffic (xfiles 3.171.171.0/22)
    - **Bandwidth Control / QoS** — queue assignments that may rate-limit specific destinations
    - **Connections table / state count** — current vs configured maximum
    - **Firewall ACL** — any rule referencing nvidia / xfiles / 3.171.171.0/22 / dst-port 443

2. **Upstream NGC / xfiles CloudFront IP-policy investigation** (second yield, often highest leverage when ER8411 walk is clean): cluster's WAN-egress IP may be classified by NGC origin / xfiles CloudFront for some reason (bot detection, ASN policy, prior abuse signal). Operator should:
    - Note the cluster's outbound IP from `curl https://api.ipify.org`
    - Check if a different egress IP (operator Mac via different ISP / phone hotspot) succeeds on auth'd pull from the same NGC creds
    - Contact NGC support with the cluster outbound IP if upstream policy is suspected

3. **Auth'd tcpdump capture during real failing pull** (parked from PR #304): operator runs `NGC_CLI_API_KEY=... ngc registry model download-version ...` while `tcpdump` captures from the spark to see RST mid-stream / window collapse / consistent byte-offset RST signature.

4. **Lowest priority — sysctl swap** (BBR → CUBIC): only if 1–3 are inconclusive. Reversible. Per PR #304 evidence (705 MB Fastly + 100 MB Ubuntu PASS), this is unlikely to be the root cause.

**Note:** Mikrotik admin UI inspection is **NOT in this list.** Per the topology correction in `a1915cb54`, the Mikrotik CRS812 is fabric-only and not in the internet-egress path. PR #304's original "Mikrotik admin UI" recommendation is superseded.

If operator confirms B or C instead of A via auth'd cross-check, this ranking changes:
- **B (single spark):** focus on the failing spark's host stack — interface MTU, MSS clamp, sysctl, conntrack, iptables. Compare working spark configs to failing.
- **C (grouped):** check if failing sparks share an ER8411 LAN port / VLAN / MAC reservation — operator-side topology check at the ER8411.

## 7. Spark-5 / Spark-6 audit gap

Both sparks reachable on TCP/22 but admin's SSH key not enrolled. To close the gap:

1. Operator runs `ssh-copy-id admin@192.168.0.109` and `ssh-copy-id admin@192.168.0.115` from a host with the admin private key
2. OR operator confirms which user account is provisioned on those sparks (memory `project_phase5b_spark1_audit.md` referenced spark-1 NIM migration, suggesting these may be newer additions to the cluster with different bootstrap state)

After enrollment, re-run `/tmp/per-spark-probe.sh` on each. If they show same Pattern A behavior, attribution is locked. If they diverge, that's evidence of a topology grouping (Pattern C), since they would be the newest / differently-bootstrapped sparks.

## 8. What this PR does NOT do

- No router / switch / Mikrotik / ER8411 configuration change
- No spark host network stack modification (no sysctl, no iptables, no route, no MTU change)
- No service modification
- No PR #304 doc modification (this is a separate follow-up doc)
- No authenticated NGC capture (still operator follow-up per PR #304)
- No SSH key enrollment on spark-5 / spark-6 (operator-side)

## 9. References

- PR #304 — F5 investigation surface: `docs/operational/briefs/f5-root-cause-investigation-2026-04-29.md`
- W3 workaround runbook: `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`
- F5 issue: #303
- Cluster network topology: `docs/architecture/shared/cluster-network-topology.md`

---

End of follow-up.
