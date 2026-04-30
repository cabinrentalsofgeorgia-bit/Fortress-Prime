**Priority:** P3
**Status:** Diagnosis only; fix is operator-side at the **TP-Link ER8411 web UI** (`http://192.168.0.1`).

2026-04-29 llama-nemotron-embed deployment surfaced cluster network defect: small TLS requests work cleanly to NGC; sustained data transfers from `xfiles.ngc.nvidia.com` fail with `DownloadFileSizeMismatch`. Three MTU-related remediations (F1, F2, F4) stacked do NOT fix.

## Topology correction (vs. original brief)

The original F5 brief attributed cluster egress to "Mikrotik". That was wrong. Verified topology:

| Device | Role |
|---|---|
| **TP-Link ER8411 Omada Pro VPN Router** at `192.168.0.1` | Internet egress, NAT, DHCP/DNS, firewall, DPI/IPS surface |
| **Mikrotik CRS812 switch** | Fast fabric only (10.10.10/24 + 10.10.11/24, MTU 9000, BBR, ~93 Gbps verified). Not in egress path. |

Verification: ARP `192.168.0.1 lladdr 98:ba:5f:5c:fe:4a` (OUI = TP-Link Systems Inc.); web UI `/webpages/login.html` = Omada Pro signature.

No active VPN tunnels (Tailscale exit-node ruled out below; OpenVPN deferred for Tailscale).

## Pattern (multi-CDN comparison through ER8411)

| Endpoint | CDN | Bytes | Throughput | Result |
|---|---|---|---|---|
| `api.ngc.nvidia.com` (small JSON) | NGC | ~1 KB | n/a | PASS |
| `nvcr.io` image pull | NGC images | multi-MB layers | n/a | PASS with retries |
| `speed.cloudflare.com` 50 MB | Cloudflare | 50 MB | 94 MB/s | **PASS** |
| `releases.ubuntu.com` (range 0-499 MB) | Canonical CDN | 500 MB | 92 MB/s | **PASS** |
| `huggingface.co` all-mpnet-base-v2 | HF / Cloudflare | 438 MB | 104 MB/s | **PASS** |
| `huggingface.co` bge-large (range 0-499 MB) | HF / Cloudflare | 500 MB | 111 MB/s | **PASS** |
| GitHub release tarball 705 MB | Fastly | 705 MB | 70 MB/s | **PASS** |
| `xfiles.ngc.nvidia.com` (sustained data) | NGC / CloudFront 3.171.171.0/22 | multi-GB | n/a | **FAIL — DownloadFileSizeMismatch** |

**Failure surface = NGC-only.** Cluster sustains 90–110 MB/s through the same ER8411 egress to four other CDNs.

## Candidate root causes (ranked by evidence)

1. **Destination-specific issue at NGC origin / xfiles CloudFront edge** — strongest evidence (multi-CDN PASS rules out generic ER8411 policy)
2. **ER8411 Application Control / DPI selectively classifying NGC** — moderate (Omada Pro DPI category lists could selectively touch "model distribution"; pattern fits)
3. **ER8411 IPS rule false-positive on sustained NVIDIA blob downloads** — moderate (sustained-binary heuristic could trip)
4. **ER8411 Bandwidth Control / QoS application-category throttling** — weaker (broad cap ruled out by multi-CDN; narrow category-specific cap possible)
5. **Asymmetric routing / IP policy at AWS edge** — moderate (path identical operator-side, divergence at AWS hop 4+)
6. **MSS double-clamp interaction (ER8411 + spark-2 host clamp)** — weak (no current double-clamp evidence)
7. ~~Conntrack exhaustion on ER8411~~ — near-ruled-out by multi-CDN PASS
8. ~~Tailscale exit-node routing~~ — RULED OUT (`ExitNode: False`, no `0.0.0.0/0` via tailnet)
9. ~~BBR vs CUBIC interaction~~ — RULED OUT by multi-CDN PASS

Dropped from original brief: **Mikrotik DPI** (Mikrotik not in egress path), **VPN tunnel asymmetric routing** (no active tunnels).

## Investigation surface

Full diagnostic plan, captured evidence, MSS/PMTU data: `docs/operational/briefs/f5-root-cause-investigation-2026-04-29.md`
Until F5 lands, W3 workaround in effect: `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`

## Required to fix

- **TP-Link ER8411 web UI access** (`http://192.168.0.1`, operator credentials) — primary
- Operator Mac for traceroute comparison
- NGC CLI credentials in cluster shell for auth'd tcpdump capture during failing pull

## Recommended next operator action (priority order)

1. **ER8411 web UI inspection** (~15 min):
   - Application Control → check rules matching source `192.168.0.0/24`; disable for cluster sources or add explicit allow for `3.171.171.0/22` + `*.ngc.nvidia.com`
   - IPS / Threat Management → Logs → filter for failing-pull window (operator captures wall-clock time before reproducing); look for hits on `xfiles`, `nvidia`, `model-distribution`, sustained-transfer heuristics
   - Bandwidth Control → confirm no rule throttles cluster sources or `3.171.171.0/22` by application category
   - Status → Connections → confirm not pegged vs `Max Sessions`
   - Firewall → ACL / NAT → check for any explicit rule referencing nvidia / xfiles / `3.171.171.0/22`
   - Capture screenshots / config dump
2. Different-spark cross-check (~5 min) — try small NGC pull from a different spark; if it works, IP-policy at xfiles destination
3. Operator Mac-side traceroute comparison
4. Auth'd tcpdump during real failing pull (RST mid-stream, retransmit walls, ICMP frag-needed, window collapse, RST at consistent byte offset = DPI)
5. Only if 1–4 inconclusive: BBR→CUBIC sysctl swap (reversible)

## Until F5 fix lands

- All NIM pulls go through W3 (operator pulls on Mac, scp to NAS)
- Cluster cannot batch-pull TIER 1 NeMo Retriever family autonomously
- Phase 2 BRAIN cluster expansion blocked on this if multi-NIM deployment becomes urgent
- TIER 1 batch-pull becomes operator-paced rather than agent-paced

## Cross-references

- F2 fix (TLS handshake MSS clamp, retained): `docs/operational/briefs/iptables-mss-persistence-brief.md`
- Cluster network topology: `docs/architecture/shared/cluster-network-topology.md`
- W3 codification: `docs/operational/runbooks/w3-nim-pull-workaround-runbook.md`
- Investigation surface: `docs/operational/briefs/f5-root-cause-investigation-2026-04-29.md`
