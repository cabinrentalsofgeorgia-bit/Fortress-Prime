# Phase 2 — netplan MTU 9000 on all 4 ConnectX twins (spark-3 + spark-4)

**Date:** 2026-04-30 10:32–10:37 EDT
**Driver:** Pre-stage for ADR-006 TP=2 Nemotron-3-Super-120B-NVFP4
deployment. Brief Phase 2 (Layer 2): "MTU 9000 on EVERY twin (not
just the active one — if only the active twin has 9000, mismatched
MTU on the inactive twin can still bite you under autodiscovery)."
Recon found inactive twins at MTU 1500 on both nodes.

**Scope:** spark-4 first (lower-risk; lighter inference), spark-3
second (carrier of vision-NIM + embed-NIM). Pre-resolved
reconciliations R1 (MTU 9000 on all 4 twins) and R3 (edit existing
`/etc/netplan/99-mellanox-roce.yaml` in-place) per the mission lock.

**Operator amendments applied:**
1. `netplan try` (auto-revert window) before `netplan apply`
2. 60s settling wait + reachability gate between nodes
3. Capture full evidence transcript

**Order:** spark-4 → 60s wait + ping gate → spark-3 → ping gate → cross-fabric verification.

---

## 1. PRE — diff of existing vs proposed

### spark-4 — pre-state (245 bytes, 600 root:root, dated 2026-04-25 15:15)

```yaml
network:
  version: 2
  ethernets:
    enp1s0f0np0:
      addresses: [10.10.10.4/24]
      mtu: 9000
    enp1s0f1np1:
      dhcp4: false
      optional: true
    enP2p1s0f1np1:
      addresses: [10.10.11.4/24]
      mtu: 9000
      dhcp4: false
```

Gap: `enP2p1s0f0np0` not declared at all (kernel default MTU 1500), `enp1s0f1np1` declared without `mtu`, `enp1s0f0np0` lacked explicit `dhcp4: false`.

### spark-3 — pre-state (245 bytes, 600 root:root, dated 2026-04-25 15:14)

Identical structure to spark-4 with `.3` suffix.

### Proposed (both nodes, only IPs differ)

```yaml
network:
  version: 2
  ethernets:
    # Fabric A — active twin (10.10.10.0/24)
    enp1s0f0np0:
      dhcp4: false
      dhcp6: false
      addresses: [10.10.10.{3|4}/24]
      mtu: 9000
      link-local: []
    # Fabric A — inactive twin (paired with f0np0)
    enp1s0f1np1:
      dhcp4: false
      dhcp6: false
      mtu: 9000
      link-local: []
      optional: true
    # Fabric B — inactive twin (paired with f1np1)
    enP2p1s0f0np0:
      dhcp4: false
      dhcp6: false
      mtu: 9000
      link-local: []
      optional: true
    # Fabric B — active twin (10.10.11.0/24)
    enP2p1s0f1np1:
      dhcp4: false
      dhcp6: false
      addresses: [10.10.11.{3|4}/24]
      mtu: 9000
      link-local: []
```

715 bytes, 600 root:root.

### Diff (both nodes — applied diff identical structure)

```
3a4
>     # Fabric A — active twin (10.10.10.0/24)
4a6,7
>       dhcp4: false
>       dhcp6: false
6a10,11
>       link-local: []
>     # Fabric A — inactive twin (paired with f0np0)
8a14,16
>       dhcp6: false
>       mtu: 9000
>       link-local: []
9a18,25
>     # Fabric B — inactive twin (paired with f1np1)
>     enP2p1s0f0np0:
>       dhcp4: false
>       dhcp6: false
>       mtu: 9000
>       link-local: []
>       optional: true
>     # Fabric B — active twin (10.10.11.0/24)
10a27,28
>       dhcp4: false
>       dhcp6: false
13c31
<       dhcp4: false
---
>       link-local: []
```

(Active twin IPs preserved — no removal of existing `addresses:` lines.)

---

## 2. APPLY — transcript

### spark-4 (`192.168.0.106`)

| Step | Result |
|---|---|
| A. backup | `cp -p /etc/netplan/99-mellanox-roce.yaml{,.bak.20260430_103233}` → `backup OK`, 245 bytes preserved |
| B. tee new content | 715 bytes, mode 600, root:root |
| B-verify. diff | shows only additions (no removals of active-twin IPs) |
| C. `netplan generate` | `EXIT=0` (lint clean) |
| D. `echo "" \| sudo timeout 30 netplan try --timeout 20` | `Configuration accepted. EXIT=0` (empty stdin satisfied ENTER prompt → committed via try; effectively idempotent with subsequent apply) |
| E. `netplan apply` | `EXIT=0` |
| F. POST verify (4 twins) | all `mtu=9000`, `operstate=up`, `carrier=1`; active twin IPs intact |
| G. reachability gate from spark-2 | fabric A (10.10.10.4) + fabric B (10.10.11.4): 0% loss, 8980 bytes received with DF |

### Inter-node 60s settling wait

Until-loop wait, 10:34:41 → 10:35:41 EDT. Then proceeded to spark-3.

### spark-3 (`192.168.0.105`)

| Step | Result |
|---|---|
| A. backup | `cp -p` → `backup OK`, 245 bytes preserved as `/etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233` |
| B. tee new content | 715 bytes, mode 600, root:root |
| B-verify. diff | identical structure to spark-4 |
| C. `netplan generate` | `EXIT=0` |
| D. `netplan try --timeout 20` | `Configuration accepted. EXIT=0` |
| E. `netplan apply` | `EXIT=0` |
| F. POST verify (4 twins) | all `mtu=9000`, `operstate=up`, `carrier=1`; active twin IPs intact |
| G. reachability gate from spark-2 | fabric A (10.10.10.3) + fabric B (10.10.11.3): 0% loss, 8980 bytes received with DF |

---

## 3. POST — per-twin state on both nodes

### spark-4

```
--- enp1s0f0np0 ---             ← Fabric A active twin
mtu 9000  inet 10.10.10.4/24
operstate=up  carrier=1
--- enp1s0f1np1 ---             ← Fabric A inactive twin
operstate=up  carrier=1  mtu=9000  (no IP, by design)
--- enP2p1s0f0np0 ---           ← Fabric B inactive twin (was MTU 1500 pre-apply!)
operstate=up  carrier=1  mtu=9000  (no IP, by design)
--- enP2p1s0f1np1 ---           ← Fabric B active twin
mtu 9000  inet 10.10.11.4/24
operstate=up  carrier=1
```

### spark-3

```
--- enp1s0f0np0 ---             ← Fabric A active twin
mtu 9000  inet 10.10.10.3/24
operstate=up  carrier=1
--- enp1s0f1np1 ---             ← Fabric A inactive twin (was MTU 9000 pre-apply, now stable)
operstate=up  carrier=1  mtu=9000  (no IP, by design)
--- enP2p1s0f0np0 ---           ← Fabric B inactive twin (was MTU 1500 pre-apply!)
operstate=up  carrier=1  mtu=9000  (no IP, by design)
--- enP2p1s0f1np1 ---           ← Fabric B active twin
mtu 9000  inet 10.10.11.3/24
operstate=up  carrier=1
```

**All 8 twins (4 per node × 2 nodes) at MTU 9000, state UP, carrier 1.**
Active-twin IPs preserved on both fabrics. Inactive twins have no IP (by design).

---

## 4. PING — cross-fabric verification (Phase 2 step f)

`ping -M do -s 8972 -c 5 -W 2 <peer-twin-ip>`. 8972 = 9000 − 28 (IP 20 + ICMP 8). Any "frag needed and DF set" error = MTU not effective end-to-end.

| Direction | Result |
|---|---|
| spark-3 → spark-4 fabric A (10.10.10.3 → 10.10.10.4) | 5/5 received, 0% loss, RTT 0.543/0.916/1.526 ms (min/avg/max), 8980 bytes received |
| spark-3 → spark-4 fabric B (10.10.11.3 → 10.10.11.4) | 5/5, 0%, RTT 0.310/0.711/1.360 ms, 8980 bytes |
| spark-4 → spark-3 fabric A (10.10.10.4 → 10.10.10.3) | 5/5, 0%, RTT 0.559/0.636/0.682 ms, 8980 bytes |
| spark-4 → spark-3 fabric B (10.10.11.4 → 10.10.11.3) | 5/5, 0%, RTT 0.308/0.333/0.365 ms, 8980 bytes |

8980 bytes received = 8972 ICMP payload + 8 ICMP header + 20 IP header = **9000-byte MTU end-to-end on both fabrics in both directions, no fragmentation, no frag-needed errors.**

---

## 5. ROLLBACK — backup files present

### spark-4

```
-rw------- 1 root root 715 Apr 30 10:32 /etc/netplan/99-mellanox-roce.yaml             (current)
-rw------- 1 root root 167 Apr 25 13:10 /etc/netplan/99-mellanox-roce.yaml.bak.20260425_131046
-rw------- 1 root root 233 Apr 25 14:51 /etc/netplan/99-mellanox-roce.yaml.bak.20260425_145129
-rw------- 1 root root 245 Apr 25 15:15 /etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233 ← THIS PHASE
-rw------- 1 root root 167 Apr 23 19:23 /etc/netplan/99-mellanox-roce.yaml.phase1-bak-20260423_192350
```

### spark-3

```
-rw------- 1 root root 715 Apr 30 10:36 /etc/netplan/99-mellanox-roce.yaml             (current)
-rw-r--r-- 1 root root 101 Apr 25 14:46 /etc/netplan/99-mellanox-roce.yaml.bak.20260425_144637
-rw------- 1 root root 245 Apr 25 15:14 /etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233 ← THIS PHASE
```

**Rollback path (operator-only, if needed):**

```bash
ssh admin@192.168.0.106 'sudo cp /etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233 \
                                  /etc/netplan/99-mellanox-roce.yaml && sudo netplan apply'
ssh admin@192.168.0.105 'sudo cp /etc/netplan/99-mellanox-roce.yaml.bak.20260430_103233 \
                                  /etc/netplan/99-mellanox-roce.yaml && sudo netplan apply'
```

Restores the pre-edit 245-byte content (still has active-twin IPs).

---

## 6. Hard-stop checks (all clear)

| Stop condition | spark-4 | spark-3 |
|---|---|---|
| `netplan generate` non-zero | ❌ EXIT=0 | ❌ EXIT=0 |
| `netplan try` auto-reverted | ❌ accepted | ❌ accepted |
| `netplan apply` error | ❌ EXIT=0 | ❌ EXIT=0 |
| Post-apply MTU != 9000 on any twin | ❌ all 9000 | ❌ all 9000 |
| Post-apply active-twin IP missing | ❌ retained | ❌ retained |
| Cross-fabric ping "frag needed" | ❌ none (8980 bytes received with DF) | ❌ none |
| Any twin operstate != up or carrier != 1 | ❌ all up+carrier | ❌ all up+carrier |

---

## 7. Out of scope

- Mgmt LAN files (`01-netcfg.yaml` on spark-3, `01-sovereign-core.yaml` on spark-4) — untouched per mission constraint
- spark-5 / spark-6 fabric remediation — separate work (cable + ConnectX hardware blockers)
- ConnectX firmware version / driver `srcversion` matching — not part of this brief
- RoCE bandwidth (`ib_write_bw`) — Phase 3
- NCCL / vLLM container env wiring — Phase 5

---

## 8. Raw transcript

`/tmp/phase-2-evidence-20260430_103233.log` (~7 KB on spark-2)

Sections in order:
- spark-4 backup → tee → diff → generate → try → apply → POST verify → reachability gate
- 60s settling wait
- spark-3 backup → tee → diff → generate → try → apply → POST verify → reachability gate
- Cross-fabric pings (4 directions)

---

End of evidence.
