# F5 Root Cause Investigation Surface — Cluster Egress Sustained-Transfer Failure to xfiles.ngc.nvidia.com

**Date:** 2026-04-29
**Branch:** `chore/f5-root-cause-investigation-2026-04-29`
**Driver:** 2026-04-29 llama-nemotron-embed deployment surfaced cluster network defect — small TLS to NGC works, sustained transfers from `xfiles.ngc.nvidia.com` fail with `DownloadFileSizeMismatch`. F1 + F2 + F4 stacked do NOT fix.
**Status:** Diagnosis only. Fix requires Mikrotik admin UI or Tailscale admin console access (operator-side).
**Tracking:** Issue #303
**Cross-references:**
- F2 fix: `docs/operational/briefs/iptables-mss-persistence-brief.md`
- Cluster network topology: `docs/architecture/shared/cluster-network-topology.md`
- W3 workaround: `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`

---

## 1. Mission

Run the §3 diagnostic plan on a cluster spark, capture evidence pointing at one of the 5 candidate root causes, and codify the W3 workaround. Apply no fix in this PR — fix surface is operator-side (Mikrotik admin UI / Tailscale admin console).

## 2. Investigation host

All in-cluster diagnostics ran from the host reachable via SSH alias `spark-2` (per `~/.ssh/config`). Notes on naming:
- SSH alias `spark-2` → `192.168.0.104`
- Linux `hostname` on that box: `spark-node-1`
- Tailscale device name: `spark-1` (Tailscale IP `100.127.241.36`)
- Memory note `project_spark_network_topology.md` already documents this naming inversion between SSH config and Tailscale.

The brief literal `192.168.0.100` is NOT this host (per `/etc/hosts` it maps to `spark-node-2-mgmt`). Investigation used SSH alias `spark-2` because that is the name the brief refers to colloquially and is the documented operator handle. Operator should verify diagnostics line up with the spark they intended.

## 3. Evidence captured

### 3.1 DNS resolution comparison

| Host | Local resolver | 8.8.8.8 |
|---|---|---|
| `api.ngc.nvidia.com` | 52.33.59.115, 184.33.29.243 | 52.33.59.115, 184.33.29.243 |
| `xfiles.ngc.nvidia.com` | 3.171.171.{52,54,119,128} | 3.171.171.{52,54,119,128} |

ASN lookup (Team Cymru DNS):
- 52.33.59.115 → AS16509 / 52.32.0.0/14 (Amazon)
- 184.33.29.243 → AS16509 / 184.32.0.0/14 (Amazon, Akamai-fronted historically but ASN reports Amazon)
- 3.171.171.0/22 → AS16509 (Amazon CloudFront)

**Finding:** No split-DNS. Both endpoints terminate inside Amazon AS16509. Different /22 prefixes — consistent with different CloudFront PoP / S3 origin clusters but same operator (AWS).

### 3.2 Path comparison (mtr report mode, 3 probes per hop)

`api.ngc.nvidia.com`:
```
1. 192.168.0.1     0.0% (Mikrotik)
2. 69.128.80.1     0.0% (ISP edge)
3. 69.128.248.142  0.0% (ISP backbone)
4. 64.50.238.86    0.0%
5. 108.166.240.72  0.0%
6. ???           100.0% (target / ICMP-filtered)
```

`xfiles.ngc.nvidia.com`:
```
1. 192.168.0.1     0.0% (Mikrotik)
2. 69.128.80.1     0.0% (ISP edge)
3. 69.128.248.142  0.0% (ISP backbone)
4-8. ???         100.0% (ICMP-filtered)
9. 3.171.171.119   0.0% (CloudFront PoP)
```

**Finding:** Hops 1–3 identical. Both endpoints leave the operator's network through the **same Mikrotik gateway and same ISP backbone hop**. Path divergence happens at hop 4+, inside AWS. ICMP filtering on xfiles intermediate hops is normal CDN behavior, not evidence of an operator-side middlebox.

Mac-side comparison: pending operator (out of scope for autonomous investigation).

### 3.3 tcpdump captures

Limitation surfaced in autonomous run: `admin@spark-2` does not have `NGC_CLI_API_KEY` configured. Without auth, the actual `DownloadFileSizeMismatch` failure mode cannot be reproduced from a non-operator shell. **Auth'd capture during a failing weights pull is operator follow-up.** What we did capture:

#### 3.3a Anonymous probes to xfiles (4 sequential connections + 1 range-request attempt, ~5s window)

- 4 SYN / SYN-ACK / clean FIN closures
- 0 RST mid-stream
- Server MSS = 1380 (sane post-clamp)
- 403 responses delivered cleanly (146 byte XML body each)
- Total 109 packets, flag distribution: `[.]` 48, `[P.]` 44, `[F.]` 8, `[S]` 4, `[S.]` 4, `[R]` 0

#### 3.3b Long-lived idle TLS session to xfiles (60s)

- TLS handshake completed (cert chain validates: `CN=ngc.nvidia.com`, signed by Amazon RSA 2048 M01 → Amazon Root CA 1)
- 403 served immediately by CloudFront (POP `ATL59-P13`)
- Connection held open for ~55s idle
- RST received from `3.171.171.119:443` after ~55s

**Interpretation of 3.3b RST:** Likely normal CloudFront keep-alive idle timeout (CloudFront default 60s). Not strong evidence of operator-side middlebox kill. Without auth'd capture during actual sustained data transfer, we cannot observe consistent-byte-offset RST signatures or window-collapse patterns.

PCAP files NOT committed (per brief hard-constraint, sanitization risk). Stored on spark-2 at `~/f5-investigation-2026-04-29/` for operator review.

### 3.4 Mikrotik admin UI inspection

Out of scope for autonomous investigation (operator-side). Operator action items in §5.

### 3.5 Tailscale state

```
HostName:        spark-node-1
TailscaleIPs:    [100.127.241.36, fd7a:115c:a1e0::fd39:f124]
ExitNode:        False
ExitNodeOption:  False
Active:          False
DERP nearest:    Miami (17.7ms)
```

Routing table:
- `default via 192.168.0.1 dev enP7s7 proto static` (primary, wired)
- `default via 10.0.0.1 dev wlP9s9 proto dhcp metric 600` (WiFi backup, lower priority)
- `tailscale0` table 52: only `100.x` peer IPs, **no `0.0.0.0/0` via tunnel**

**Finding: Tailscale exit-node routing RULED OUT.** No tunneled internet-bound traffic. NGC-bound packets leave via wired enP7s7 → 192.168.0.1.

### 3.6 Sustained-transfer comparison

| Test | Endpoint | Size | Result | Speed |
|---|---|---|---|---|
| Cloudflare control | `speed.cloudflare.com/__down?bytes=10000000` | 10 MB | **PASS** | 44 MB/s |
| Cloudflare medium | `speed.cloudflare.com/__down?bytes=50000000` | 50 MB | **PASS** | 83 MB/s |
| AWS CloudFront alt (HF dataset) | `huggingface.co/.../test.jsonl` | 446 KB | PASS | 4 MB/s |
| Fastly CDN large | `github.com/ollama/ollama/releases/download/v0.1.0/ollama-linux-amd64` | **705 MB** | **PASS** | **70 MB/s** |
| xfiles unauth | `xfiles.ngc.nvidia.com/` | 146 B 403 | small response only — N/A for sustained |
| xfiles auth'd weight pull | (operator follow-up) | multi-GB | reported FAIL (DownloadFileSizeMismatch) per brief §2.2 |

**Finding: cluster CAN sustain 705 MB at 70 MB/s** through the same Mikrotik gateway. The failure is NOT a generic sustained-transfer problem.

## 4. Candidate root cause ranking

Ranked by the strength of the evidence in §3:

### Most likely → least likely

#### 1. Destination-specific issue at NGC origin / xfiles CloudFront edge

**Why this rises to #1:** 705 MB Fastly + 50 MB Cloudflare both succeeded through the same Mikrotik path. If the operator's middlebox were applying generic DPI / conntrack / BBR-interaction policy, those would also fail. The failure tracks tightly to `xfiles.ngc.nvidia.com` (3.171.171.0/22).

Possible mechanisms at the destination:
- Cluster's outbound IP triggered NGC's bot/scraper detection
- ASN- or prefix-based rate limiting at CloudFront origin policy
- NGC-side authentication tier delivers truncated bodies for cluster's outbound IP for some classification reason
- CloudFront signed-URL validity window mismatch (cluster clock skew?)

**How operator confirms:** Re-run the failing pull from the cluster while simultaneously running the same NGC CLI command from a clean-internet machine on the same outbound IP via a SOCKS proxy — if both fail, it's destination-side; if cluster fails and proxy succeeds, it's path-side.

#### 2. Mikrotik selectively filtering on xfiles SNI / hostname / specific destination prefix

**Why mid-rank:** Same Mikrotik passed 705 MB Fastly. For this to be the root cause, the Mikrotik would need a host-specific or prefix-specific filter — possible but unusual. The MTU work (F1/F2/F4) hints PMTU-discovery may be broken on the path to 3.171.171.x specifically, suggesting middlebox involvement of *some* kind.

**How operator confirms:** Mikrotik admin UI → `IP → Firewall → Filter Rules`. Look for any rule referencing `xfiles`, `nvidia`, `3.171.171.0/22`, `dst-port 443` with content matching, or any L7-protocol rule. Also `IP → Firewall → Layer7 Protocols`.

#### 3. Asymmetric routing at AWS edge (cluster-IP-policy at CloudFront)

**Why mid-rank:** Path on operator side is identical to both endpoints. Divergence is at AWS hop 4+. CloudFront may pin xfiles requests to a specific PoP that has a different reachability profile from cluster's IP than the api PoP.

**How operator confirms:** From a different cluster spark (different Tailscale IP / outbound NAT mapping if the Mikrotik does any), retry the failing pull. If a different spark works, it's IP-policy at the destination.

#### 4. Conntrack exhaustion on Mikrotik

**RULED OUT (or near-ruled-out):** A 705 MB sustained transfer through the same Mikrotik succeeded with no observed throttling. Conntrack exhaustion would degrade ANY new connection, not just connections to xfiles.

Operator can still verify: Mikrotik admin → `IP → Firewall → Connections` → check active count vs configured `nf_conntrack_max`. Bump if pegged. But evidence does not point here.

#### 5. BBR vs CUBIC interaction with middlebox

**RULED OUT:** 705 MB Fastly + 50 MB Cloudflare succeeded with the current host congestion-control choice. If BBR were misbehaving with the Mikrotik for sustained streams, we would have seen it in those large transfers. Sysctl swap not warranted by evidence.

## 5. Recommended next operator action (priority order)

1. **Mikrotik admin UI inspection** (15 min): log in to Mikrotik (`192.168.0.1` or Winbox), check `IP → Firewall → Filter Rules`, `Layer7 Protocols`, `Mangle`, `NAT` for any rule referencing nvidia / xfiles / `3.171.171.0/22`. Also check `IP → Firewall → Connections` count vs `/system resource` conntrack max. Capture screenshots / config dump.

2. **Different-spark cross-check** (5 min): from a different spark (different SSH alias, different outbound NAT mapping potentially), attempt a small NGC weights pull. If it works, the issue is IP-specific at xfiles destination — escalate to NGC support with cluster outbound IP.

3. **Operator Mac-side traceroute comparison**: run `traceroute -n -m 20 xfiles.ngc.nvidia.com` from the Mac. If Mac path skips a hop the cluster has, that hop is the suspect.

4. **Auth'd tcpdump capture during real failing pull**: re-run §3.3 with `NGC_CLI_API_KEY` exported and the actual failing `ngc registry model download-version ...` command running. Look for: RST mid-stream, repeated retransmissions hitting a wall, ICMP "fragmentation needed", TCP window collapse to zero, RST at consistent byte offset (DPI signature).

5. **Only if 1–4 inconclusive:** consider sysctl BBR→CUBIC swap (§4.5 of original brief). Reversible.

## 6. What this PR does NOT do

- **No Mikrotik configuration change** (operator-side only)
- **No Tailscale configuration change** (operator-side only)
- **No sysctl change** (BBR→CUBIC swap is a candidate fix, not part of investigation)
- **No revert of F1, F2, F4** (harmless, stay in place)
- **No service / NIM / LiteLLM / Qdrant modification**

## 7. Workaround in effect

Until F5 lands: **W3 — operator pulls NIM weights on Mac, scp to NAS canonical cache**. See `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`.

Operational implications:
- All NIM pulls go through operator Mac
- Cluster cannot autonomously refresh NIM weights
- TIER 1 batch-pull becomes operator-paced rather than agent-paced
- Multi-spark pulls serialized through operator's home internet bandwidth
- Image pulls (multi-MB nvcr.io) work with retries; weight pulls (multi-GB blobs) require Mac path

## 8. Diagnostic artifacts (not committed)

PCAPs from §3.3 stored on spark-2 at `~/f5-investigation-2026-04-29/`:
- `f5-xfiles.pcap` (109 packets, anonymous probes)
- `f5-tls-long.pcap` (22 packets, 60s idle session)

Both are anonymous (no auth headers, no API keys). Operator may inspect with `tcpdump -r` or `wireshark`. They do NOT exercise the failing-pull mode and are kept off-PR per brief sanitization constraint.

---

End of investigation surface.
