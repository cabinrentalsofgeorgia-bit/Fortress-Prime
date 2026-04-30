# F5 Root Cause Investigation Surface — Cluster Egress Sustained-Transfer Failure to xfiles.ngc.nvidia.com

**Date:** 2026-04-29
**Branch:** `chore/f5-root-cause-investigation-2026-04-29`
**Driver:** 2026-04-29 llama-nemotron-embed deployment surfaced cluster network defect — small TLS to NGC works, sustained transfers from `xfiles.ngc.nvidia.com` fail with `DownloadFileSizeMismatch`. F1 + F2 + F4 stacked do NOT fix.
**Status:** Diagnosis only. Fix surface is operator-side at the **TP-Link ER8411 web UI (`http://192.168.0.1`)**. No configuration is changed by this PR.
**Tracking:** Issue #303
**Cross-references:**
- F2 fix: `docs/operational/briefs/iptables-mss-persistence-brief.md`
- Cluster network topology: `docs/architecture/shared/cluster-network-topology.md`
- W3 workaround: `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`

---

## 1. Mission

Run the §4 diagnostic plan from a cluster spark, capture evidence pointing at one of the candidate root causes, and codify the W3 workaround. Apply no fix in this PR — fix surface is the **TP-Link ER8411 web UI** (operator-side, after operator review of this investigation).

## 2. Topology correction (vs. original brief)

The original F5 brief (`/home/admin/f5-root-cause-investigation-brief.md`) attributed the cluster egress middlebox to "Mikrotik". That was incorrect. Verified topology:

| Device | Role | Address |
|---|---|---|
| **TP-Link ER8411 Omada Pro VPN Router** | Internet egress, NAT, DHCP/DNS, firewall, DPI/IPS surface | `192.168.0.1` (default gw) |
| **Mikrotik CRS812 switch** | **Fast fabric only** — 100 G ConnectX-6 between sparks (`10.10.10.0/24`, `10.10.11.0/24`, MTU 9000, BBR, ~93 Gbps verified) | not in egress path |

**Verification of ER8411 at `192.168.0.1`:**
- ARP: `192.168.0.1 dev enP7s7 lladdr 98:ba:5f:5c:fe:4a` — OUI `98:ba:5f` resolves to **TP-Link Systems Inc.** (macvendors.com)
- Web UI fingerprint: `http://192.168.0.1/` redirects to `/webpages/login.html` — Omada Pro signature path
- First hop on every external traceroute: `192.168.0.1` (mtr `0.0% loss`, ~0.3 ms)

**Mikrotik switch is NOT in the internet-egress path.** No Mikrotik DPI / firewall hypothesis applies to F5.

**No active VPN tunnels** (OpenVPN previously deferred for Tailscale; Tailscale exit-node routing ruled out below). Re-introducing OpenVPN is future work outside F5 scope.

## 3. Investigation host

Diagnostics ran from the spark whose `hostname` is `spark-node-2` (mgmt IP `192.168.0.100`, fabric A `10.10.10.2`, fabric B `10.10.11.2`, Tailscale `100.80.122.100`). The naming inversion between Linux hostname / SSH alias / Tailscale device name is documented in `project_spark_network_topology.md`. Operator should verify diagnostics line up with the spark they intended.

## 4. Evidence captured

### 4.1 DNS resolution comparison

| Host | Local resolver | 8.8.8.8 |
|---|---|---|
| `api.ngc.nvidia.com` | 52.33.59.115, 184.33.29.243 | 52.33.59.115, 184.33.29.243 |
| `xfiles.ngc.nvidia.com` | 3.171.171.{52,54,119,128} | 3.171.171.{52,54,119,128} |

ASN lookup (Team Cymru DNS):
- 52.33.59.115 → AS16509 / 52.32.0.0/14 (Amazon)
- 184.33.29.243 → AS16509 / 184.32.0.0/14 (Amazon)
- 3.171.171.0/22 → AS16509 (Amazon CloudFront)

**Finding:** No split-DNS. Both endpoints terminate inside Amazon AS16509. Different /22 prefixes — consistent with different CloudFront PoP / S3 origin clusters but same operator (AWS).

### 4.2 Path comparison (mtr report mode + tracepath)

`api.ngc.nvidia.com` (mtr):
```
1. 192.168.0.1     0.0%   (TP-Link ER8411 — confirmed via ARP OUI + Omada UI)
2. 69.128.80.1     0.0%   (ISP edge)
3. 69.128.248.142  0.0%   (ISP backbone)
4. 64.50.238.86    0.0%
5. 108.166.240.72  0.0%
6. ???           100.0%   (target / ICMP-filtered)
```

`xfiles.ngc.nvidia.com` (mtr):
```
1. 192.168.0.1     0.0%   (TP-Link ER8411)
2. 69.128.80.1     0.0%   (ISP edge)
3. 69.128.248.142  0.0%   (ISP backbone)
4-8. ???         100.0%   (ICMP-filtered)
9. 3.171.171.119   0.0%   (CloudFront PoP)
```

`tracepath` confirms `pmtu 1420` host-side and same ISP-edge / backbone hops out of ER8411 to both endpoints.

**Finding:** Hops 1–3 identical. Both endpoints leave through the **same TP-Link ER8411 + same ISP backbone hop**. Path divergence happens at hop 4+, inside AWS. ICMP filtering on intermediate xfiles hops is normal CDN behavior.

Mac-side comparison: pending operator (out of scope for autonomous investigation).

### 4.3 tcpdump captures

Limitation surfaced in autonomous run: `admin@spark-2` does not have `NGC_CLI_API_KEY` configured. Without auth, the actual `DownloadFileSizeMismatch` failure mode cannot be reproduced from a non-operator shell. **Auth'd capture during a failing weights pull is operator follow-up.** Captured anonymously:

#### 4.3a Anonymous probes to xfiles (4 sequential connections + 1 range-request attempt, ~5 s window)

- 4 SYN / SYN-ACK / clean FIN closures
- 0 RST mid-stream
- Server MSS = 1380 (sane post-clamp)
- 403 responses delivered cleanly (146 byte XML body each)
- Total 109 packets, flag distribution: `[.]` 48, `[P.]` 44, `[F.]` 8, `[S]` 4, `[S.]` 4, `[R]` 0

#### 4.3b Long-lived idle TLS session to xfiles (60 s)

- TLS handshake completed (cert chain validates: `CN=ngc.nvidia.com`, signed by Amazon RSA 2048 M01 → Amazon Root CA 1)
- 403 served immediately by CloudFront (PoP `ATL59-P13`)
- Connection held open for ~55 s idle
- RST received from `3.171.171.119:443` after ~55 s

**Interpretation of 4.3b RST:** Likely normal CloudFront keep-alive idle timeout (CloudFront default 60 s). Not strong evidence of an ER8411-side middlebox kill. Without auth'd capture during actual sustained data transfer, we cannot observe consistent-byte-offset RST signatures or window-collapse patterns characteristic of DPI.

PCAP files NOT committed (per brief hard-constraint, sanitization risk). Stored on spark-2 at `~/f5-investigation-2026-04-29/` for operator review.

### 4.4 ER8411 admin UI inspection

Out of scope for autonomous investigation (operator-side). Operator action items in §6.

### 4.5 Tailscale state

```
HostName:        spark-node-1   (Tailscale device name; inverted from Linux hostname)
TailscaleIPs:    [100.127.241.36, fd7a:115c:a1e0::fd39:f124]
ExitNode:        False
ExitNodeOption:  False
Active:          False
DERP nearest:    Miami (17.7 ms)
```

Routing table:
- `default via 192.168.0.1 dev enP7s7 proto static` (primary, wired through ER8411)
- `default via 10.0.0.1 dev wlP9s9 proto dhcp metric 600` (WiFi backup, lower priority)
- `tailscale0` table 52: only `100.x` peer IPs, **no `0.0.0.0/0` via tunnel**

**Finding: Tailscale exit-node routing RULED OUT.** No tunneled internet-bound traffic. NGC-bound packets leave via wired `enP7s7 → 192.168.0.1` (ER8411).

### 4.6 Sustained-transfer comparison (multi-CDN)

All curl tests run from spark-2 through ER8411. Caps: 60 s timeout, 500 MB max each (range request used where Content-Length exceeded cap).

| Test | Endpoint / CDN | Bytes transferred | Time | Throughput | Result |
|---|---|---|---|---|---|
| Cloudflare 50 MB | `speed.cloudflare.com` (Cloudflare) | 50,000,000 | 0.53 s | **94 MB/s** (≈753 Mbps) | **PASS** |
| Ubuntu ISO range 0-499 MB | `releases.ubuntu.com/24.04/ubuntu-24.04.4-live-server-amd64.iso` (Canonical CDN) | 500,000,000 | 5.43 s | **92 MB/s** (≈736 Mbps) | **PASS** |
| HF model — sentence-transformers/all-mpnet-base-v2 | `huggingface.co/.../model.safetensors` (Cloudflare-fronted HF) | 437,971,872 | 4.19 s | **104 MB/s** (≈836 Mbps) | **PASS** |
| HF model range 0-499 MB — BAAI/bge-large-en-v1.5 | `huggingface.co/.../model.safetensors` | 500,000,000 | 4.49 s | **111 MB/s** (≈892 Mbps) | **PASS** |
| GitHub/Fastly 705 MB (prior run) | `github.com/ollama/ollama/releases/download/...` (Fastly) | 705,000,000 | ~10 s | **70 MB/s** | **PASS** |
| `xfiles.ngc.nvidia.com` unauth | (CloudFront 3.171.171.0/22) | 146 B (403 XML) | n/a | small response only — N/A for sustained | n/a |
| `xfiles.ngc.nvidia.com` auth'd weight pull | (CloudFront, NGC artifacts) | (operator follow-up; reproducible per brief §2.2) | n/a | n/a | **FAIL — DownloadFileSizeMismatch** |

**Failure surface:** Cluster sustains 90–110 MB/s through ER8411 to **Cloudflare, Canonical, Hugging Face/Cloudflare, and GitHub/Fastly**. Failure is **NGC-only** (specifically `xfiles.ngc.nvidia.com` on `3.171.171.0/22`).

### 4.7 MSS clamp + PMTU evidence

Spark-2 stack:
```
# iptables OUTPUT chain rule 2 (F2):
TCPMSS  tcp flags:0x06/0x02  TCPMSS clamp to PMTU
# (active: 1120 packets / 67 KB clamped at observation time)

# Host MTU: 1420 (F4 — set on enP7s7)
# TCP congestion control: bbr
# nf_conntrack: 1101 / 655360 (well under spark-2 limit; ER8411 conntrack unknown)
```

`ping -M do` DF-sweep to xfiles: host stack does not emit packets >1420 (consistent with F4). Larger DF probes show `transmitted 0 received` — local interface refuses, not in-path PMTU drops.

`tracepath -n xfiles.ngc.nvidia.com` reports `pmtu 1420` source-side and no asymmetric reduction along the path. ICMP frag-needed responses are not observed in §4.3 captures, but neither is evidence of double-clamp from ER8411 advertising a smaller MSS than spark-2.

**Finding:** **No double-clamp evidence** in available data. Host-side MSS clamp (F2) is functioning. PMTU is 1420 across the path. Operator follow-up: auth'd tcpdump during failing pull would show ER8411-clamp signatures (if any) on SYN-ACK return.

## 5. Candidate root cause ranking (corrected for ER8411 + no VPN tunnels)

Ranked by strength of evidence in §4. Original brief candidate list reordered for ER8411-as-egress; **Mikrotik DPI** and **VPN tunnel asymmetric routing** removed (no longer applicable).

### Most likely → least likely

#### 1. Destination-specific issue at NGC origin / xfiles CloudFront edge

**Why #1 (strong evidence):** Multi-CDN sustained transfers — Cloudflare, Canonical, Hugging Face, GitHub/Fastly — all PASS at 90–110 MB/s through the same ER8411. Failure tracks tightly to `xfiles.ngc.nvidia.com` (3.171.171.0/22) only. If ER8411 were applying generic policy (DPI / IPS / category-throttle / conntrack / BBR-interaction), at least one of the multi-CDN tests would also degrade.

Possible mechanisms at the destination:
- Cluster's outbound IP triggered NGC's bot/scraper detection
- ASN- or prefix-based rate limiting at CloudFront origin policy
- NGC-side authentication tier delivers truncated bodies for cluster's outbound IP for some classification reason
- CloudFront signed-URL validity window mismatch (cluster clock skew?)

**How operator confirms:** Re-run the failing pull from the cluster while simultaneously running the same NGC CLI command from a clean-internet machine on the same outbound IP via SOCKS proxy — if both fail, destination-side; if cluster fails and proxy succeeds, path-side.

#### 2. ER8411 Application Control / DPI selectively classifying NGC

**Why mid-rank (moderate):** TP-Link Omada Pro ER8411 ships with **Application Control** (category-aware DPI) and **IPS** modules. The 705 MB Fastly + multi-CDN HF/Ubuntu/Cloudflare success rules out *generic* DPI throttling — but Application Control category lists could still selectively touch "AI/ML model distribution" or "NVIDIA NGC" if such a category exists in the firmware's signature database. The pattern (small response works, sustained transfer fails mid-stream) is consistent with category-classified DPI.

**How operator confirms:** ER8411 web UI (`http://192.168.0.1`) → **Application Control** → check for any rule matching source `192.168.0.0/24`. Look at category list, application list, and "Application-aware" routing rules. Either:
- Disable Application Control for source `192.168.0.0/24`, OR
- Add an explicit allow rule for outbound to `3.171.171.0/22` and `*.ngc.nvidia.com` ahead of any blocking rule.

#### 3. ER8411 IPS rule false-positive on sustained NVIDIA blob downloads

**Why mid-rank (moderate):** Same firmware family typically ships **IPS** signatures keyed off TLS SNI / certificate / payload heuristics. Sustained binary blob from a CDN PoP tagged "AI model weights" could plausibly trip a "data-exfiltration" or "binary-over-https" heuristic. The 705 MB Fastly success argues against generic IPS triggering on size, but signature-specific behavior is possible.

**How operator confirms:** ER8411 web UI → **IPS / Threat Management → Logs**. Filter logs for the failing-pull window (operator: capture wall-clock time of failing `ngc registry model download-version` before reproducing). Any signature hit naming `xfiles`, `nvidia`, `model-distribution`, or sustained-transfer heuristics is the smoking gun. Tune by exempting source `192.168.0.0/24` or destination `3.171.171.0/22`.

#### 4. ER8411 Bandwidth Control / QoS (application-category throttling)

**Why mid-rank (weaker):** Omada Pro **Bandwidth Control** can throttle by application category. If "model distribution" / "NVIDIA NGC" is a separately-managed category from generic file-download, sustained xfiles could see a hard ceiling while Cloudflare/Fastly/HF stay uncapped. Multi-CDN PASS data argues against a *broad* file-download cap; a *narrow* category-specific cap is possible.

**How operator confirms:** ER8411 web UI → **Bandwidth Control** → list rules. Confirm no rule matches NGC traffic specifically. If found, disable for `192.168.0.0/24` or for destination `3.171.171.0/22`.

#### 5. Asymmetric routing / IP policy at AWS edge (not ER8411-side)

**Why mid-rank (moderate):** Path on operator side is identical to both NGC endpoints. Divergence is at AWS hop 4+. CloudFront may pin xfiles requests to a PoP that has a different reachability profile from cluster's outbound IP than the api PoP.

**How operator confirms:** From a different cluster spark (different outbound NAT mapping if ER8411 does any), retry the failing pull. If a different spark works, IP-policy at the destination is the cause.

#### 6. MSS double-clamp interaction (ER8411 + spark-2 host clamp)

**Why mid-rank (weak):** Both spark-2 (F2 OUTPUT chain TCPMSS → PMTU) and ER8411 (default behavior on Omada Pro) likely clamp MSS. Multi-CDN passing argues against a generic double-clamp problem, but a destination-specific PMTU asymmetry to `3.171.171.0/22` is conceivable.

**How operator confirms:** Auth'd tcpdump during failing pull → inspect SYN/SYN-ACK MSS values and look for ICMP frag-needed not arriving. If MSS dropped to abnormally low value (e.g. 536 / 1280) on xfiles only, double-clamp is implicated.

#### 7. Conntrack exhaustion on ER8411

**RULED OUT (or near-ruled-out):** Multi-CDN sustained transfers at 90–110 MB/s in ~5 s windows succeeded with no observed throttling. Conntrack exhaustion would degrade ANY new connection. spark-2 conntrack is `1101 / 655360` — well under limit on the host side. ER8411 limit unknown but unlikely to be pegged with no active VPN tunnels consuming sessions.

Operator can still verify: ER8411 web UI → **Status → Connections** → check active count vs. configured `Max Sessions`. Bump if pegged. Evidence does not point here.

#### 8. Tailscale exit-node routing on sub-prefix

**RULED OUT.** §4.5 confirms `ExitNode: False`, `Active: False`, no `0.0.0.0/0` via `tailscale0` in any routing table. NGC-bound packets leave via wired `enP7s7 → 192.168.0.1`.

#### 9. BBR vs CUBIC interaction with ER8411

**RULED OUT.** Multi-CDN tests succeeded with current host congestion-control (`bbr`). If BBR were misbehaving with ER8411 for sustained streams, we would have seen it in those large transfers. Sysctl swap not warranted by evidence.

#### Dropped from original brief (no longer applicable)

- **Mikrotik DPI** — Mikrotik is fast-fabric only, not in egress path.
- **VPN tunnel asymmetric routing** — no active tunnels (Tailscale not exit-noding; OpenVPN deferred).

## 6. Recommended next operator action (priority order)

1. **ER8411 web UI inspection** (~15 min) — log in to `http://192.168.0.1`, then walk:
   - **Application Control** — check for any rule matching source `192.168.0.0/24`. If present and not deliberately scoped, disable for cluster sources OR add an explicit allow for `3.171.171.0/22` + `*.ngc.nvidia.com` ahead of it.
   - **IPS / Threat Management → Logs** — filter for the wall-clock window of a known failing pull (operator captures timestamp before reproducing). Any signature hit on `xfiles`, `nvidia`, `model-distribution`, or sustained-transfer heuristics is the smoking gun.
   - **Bandwidth Control** — confirm no rule throttles `192.168.0.0/24` or destination `3.171.171.0/22` by application category.
   - **Status → Connections** — read active count vs. `Max Sessions`. Confirm not pegged.
   - **Firewall → ACL / NAT** — check for any explicit rule referencing `nvidia`, `xfiles`, `3.171.171.0/22`, or NGC.
   - Capture screenshots / config dump for evidence.

2. **Different-spark cross-check** (~5 min) — from a different spark (different SSH alias, potentially different outbound NAT mapping), attempt a small NGC weights pull. If it works, the issue is IP-specific at xfiles destination — escalate to NGC support with cluster outbound IP.

3. **Operator Mac-side traceroute comparison** — `traceroute -n -m 20 xfiles.ngc.nvidia.com` from the Mac. If Mac path skips a hop the cluster has, that hop is the suspect.

4. **Auth'd tcpdump capture during real failing pull** — re-run §4.3 with `NGC_CLI_API_KEY` exported and the actual failing `ngc registry model download-version ...` command running. Look for: RST mid-stream, repeated retransmissions hitting a wall, ICMP "fragmentation needed", TCP window collapse to zero, RST at consistent byte offset (DPI signature), SYN/SYN-ACK MSS asymmetry (double-clamp).

5. **Only if 1–4 inconclusive:** consider sysctl BBR→CUBIC swap (§4.5 of original brief). Reversible.

## 7. What this PR does NOT do

- **No ER8411 configuration change** (operator-side only)
- **No Mikrotik configuration change** (irrelevant to F5)
- **No Tailscale configuration change** (operator-side only; ruled out anyway)
- **No sysctl change** (BBR→CUBIC swap is a candidate fix, not part of investigation)
- **No revert of F1, F2, F4** (harmless, stay in place)
- **No service / NIM / LiteLLM / Qdrant modification**

## 8. Workaround in effect

Until F5 lands: **W3 — operator pulls NIM weights on Mac, scp to NAS canonical cache**. See `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`.

Operational implications:
- All NIM pulls go through operator Mac
- Cluster cannot autonomously refresh NIM weights
- TIER 1 batch-pull becomes operator-paced rather than agent-paced
- Multi-spark pulls serialized through operator's home internet bandwidth
- Image pulls (multi-MB nvcr.io) work with retries; weight pulls (multi-GB blobs) require Mac path

## 9. Diagnostic artifacts (not committed)

PCAPs from §4.3 stored on spark-2 at `~/f5-investigation-2026-04-29/`:
- `f5-xfiles.pcap` (109 packets, anonymous probes)
- `f5-tls-long.pcap` (22 packets, 60 s idle session)

Both are anonymous (no auth headers, no API keys). Operator may inspect with `tcpdump -r` or `wireshark`. They do NOT exercise the failing-pull mode and are kept off-PR per brief sanitization constraint.

---

End of investigation surface.
