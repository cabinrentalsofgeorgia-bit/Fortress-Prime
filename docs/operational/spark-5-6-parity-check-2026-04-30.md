# Spark-5 + Spark-6 Parity Check vs Canonical — 2026-04-30

**Branch:** `chore/spark-5-6-fabric-cutover-prep-2026-04-30`
**Canonical reference:** `docs/operational/cluster-network-canonical-baseline-2026-04-30.md`
**Source data:** `docs/operational/spark-network-baseline-2026-04-30/spark-{109,115}.txt`

---

## 1. Spark-5 (`192.168.0.109`) — delta vs canonical

| Item | Canonical | Spark-5 actual | Delta | Severity | Remediation |
|---|---|---|---|---|---|
| Kernel | 6.17.0-1014-nvidia | 6.17.0-1014-nvidia | match | — | none |
| mlx5_core srcversion | `89EEAF...FFD3` | `89EEAF...FFD3` | match | — | none |
| ConnectX firmware | `28.45.4028` | (not captured — admin lacks sudo NOPASSWD on spark-5) | **unverified** | LOW | re-run `sudo ethtool -i` after operator grants NOPASSWD or via direct console |
| ConnectX hardware | ConnectX-7 ×4 PCI functions | ConnectX-7 ×4 PCI functions ✓ | match | — | none — hardware fully present |
| Fabric A interface | `enp1s0f0np0` | **`enp1s0f1np1`** ⚠ | **DIFFERENT INTERFACE** | HIGH | netplan rewrite — see §1.1 |
| Fabric A subnet | `10.10.10.0/24` | `10.10.10.5/24` | subnet match, host-specific .5 ✓ | — | keep |
| Fabric B interface | `enP2p1s0f1np1` | (unconfigured for fabric; instead has `192.168.0.111/24` mis-bound) | **MIS-BOUND** | HIGH | remove `192.168.0.111/24`; assign `10.10.11.5/24 + mtu 9000` |
| Fabric B subnet | `10.10.11.0/24` | **MISSING** ⚠ | DIFFERENT | HIGH | add fabric B in netplan |
| Fabric MTU | 9000 (A+B) | 9000 on `enp1s0f1np1`; 1500 on `enP2p1s0f1np1` | partial | HIGH | set both fabric ports to MTU 9000 |
| Fabric netplan filename | `99-mellanox-roce.yaml` | `60-connectx-fabric.yaml` (different name + layout) | naming drift | LOW | rename for cluster consistency, or leave |
| ConnectX port `enp1s0f0np0` link state | UP @ 100 Gbps | DOWN ⚠ | DIFFERENT | HIGH | physical cable check — port not connected (or cable bad) |
| ConnectX port `enP2p1s0f0np0` link state | UP (canonical: idle, but link UP) | DOWN | DIFFERENT | MED | one of the spark-5 cables today goes here for fabric A canonical; second cable goes to `enP2p1s0f1np1` for fabric B |
| sysctl `tcp_congestion_control` | bbr | **cubic** ⚠ | DIFFERENT | MED | align with canonical (out of scope for this PR — separate sysctl drift issue) |
| sysctl `rmem_max` | 536870912 | 212992 | DIFFERENT | MED | same as above |
| sysctl `tcp_rmem` middle | 87380 | 131072 | DIFFERENT | LOW | same as above |
| BRAIN service | n/a (spark-1 ran sovereign-8B) | `fortress-nim-brain.service` running, `:8100` HEALTHY | — | preserve through cutover |

### 1.1 Spark-5 net effect of cable cutover today

Operator plugs **2 new cables** into spark-5 ConnectX ports + Mikrotik 200 G port. Post-cutover state should match canonical:

- `enp1s0f0np0` — fabric A — `10.10.10.5/24` MTU 9000 (was: down)
- `enP2p1s0f1np1` — fabric B — `10.10.11.5/24` MTU 9000 (was: mis-bound to 192.168.0.111)
- `enp1s0f1np1` — currently has 10.10.10.5/24; either (a) cable that's already plugged stays in same port and the IP migrates to the canonical port `enp1s0f0np0` after rewire, or (b) the existing cable stays and we accept the canonical-divergent port assignment. **Operator decision needed at cutover time.**
- `enP2p1s0f0np0` — idle (canonical: not configured by `99-mellanox-roce.yaml`)

**The brief says "1 cable to 1 Mikrotik 200G port → 2 cables post-cutover".** Interpretation: spark-5 currently has 1 cable into Mikrotik on `enp1s0f1np1`. Post-cutover, 2 cables into Mikrotik 200G — one for fabric A, one for fabric B. Both should land on the canonical ports (`enp1s0f0np0` for A, `enP2p1s0f1np1` for B) so the netplan can be uniform. If cabling lands differently for hardware reasons, netplan must adapt.

## 2. Spark-6 (`192.168.0.115`) — delta vs canonical

| Item | Canonical | Spark-6 actual | Delta | Severity | Remediation |
|---|---|---|---|---|---|
| Kernel | 6.17.0-1014-nvidia | 6.17.0-1014-nvidia | match | — | none |
| mlx5_core srcversion | `89EEAF...FFD3` | `89EEAF...FFD3` | match | — | none — driver loaded but bound to nothing |
| **ConnectX hardware** | **ConnectX-7 ×4 PCI functions** | **(none — `lspci -nn \| grep -i mellanox` returns empty)** ⚠ | **HARDWARE ABSENT** | **🛑 BLOCKER** | **operator must verify physical install in chassis** — see §2.1 |
| ConnectX firmware | `28.45.4028` | n/a | n/a | n/a | unverifiable until hardware present |
| Fabric A interface | `enp1s0f0np0` | n/a | n/a | n/a | no NIC to bind to |
| Fabric B interface | `enP2p1s0f1np1` | n/a | n/a | n/a | no NIC to bind to |
| Mgmt LAN | `enP7s7 192.168.0.X/24` | `enP7s7 192.168.0.115/24` ✓ | match | — | none |
| Active fabric ports | n/a (all 4 ports UP on canonical) | none — only `enP7s7` (mgmt), `wlP9s9` (WiFi), `tailscale0`, `docker0` enumerated | DIFFERENT | 🛑 | per §2.1 |
| sysctl tuning | bbr + 536M | cubic + 212k | DIFFERENT | MED (same as spark-3/5 drift) | out of scope; separate sysctl alignment issue |

### 2.1 🛑 STOP CONDITION — Spark-6 ConnectX hardware not present

`lspci -nn | grep -i mellanox` returns `(no mellanox PCI device found)` on spark-6. The kernel modules (`mlx5_core`, `mlx5_ib`, `mlx5_fwctl`, `mlxfw`) **are loaded** — but they have no PCI device to bind to.

Possible causes (in priority order for operator to check):
1. **ConnectX-7 adapter not physically installed** in spark-6's chassis. The other 5 sparks all have it; spark-6 was previously documented as the "spark-6 cable is the gating physical blocker for ADR-003 Phase 3" (per master plan §6.5). The blocker may actually be the **adapter**, not the cable.
2. Adapter is installed but in an inactive PCIe slot (BIOS configuration).
3. Adapter is installed and PCIe-enumerated but at a path the kernel can't see (`dmesg | grep -i mlx` would surface).
4. Hardware fault — adapter installed but not recognized by BIOS.

### 2.2 What this means for today's cutover

**Plugging cables into spark-6 today will not activate fabric on spark-6** if the adapter is absent. The cables will physically connect to the Mikrotik switch, but spark-6 has no NIC for them to terminate at. Fabric A and Fabric B will remain empty for spark-6.

**Operator must verify hardware before / during / after cabling:**
- Before: power off spark-6, open chassis, confirm ConnectX-7 adapter is present in the expected PCIe slot.
- If adapter is present but `lspci` doesn't see it: re-seat. Boot. Re-check `lspci`.
- If adapter is absent: hardware procurement. Cable cutover for spark-6 deferred until hardware is installed.

If the adapter is genuinely missing, today's cabling is partially wasted on spark-6 — the ports plug into Mikrotik, but spark-6 stays out of the fabric until hardware is added.

## 3. Summary — what cutover today can and cannot accomplish

| Spark | Hardware ready? | Cable cutover today: | Post-cutover fabric state |
|---|---|---|---|
| spark-5 | ✓ ConnectX-7 ×4 present | YES — 2 cables go in; netplan needs rewrite | Both fabric A + fabric B should activate **if** netplan applied |
| spark-6 | ❌ no Mellanox in lspci | YES (cables plug in) but **NO ACTIVATION** | Fabric A + fabric B remain absent until adapter install resolved |

---

End of parity check.
