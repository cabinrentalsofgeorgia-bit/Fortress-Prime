# Cluster Network Canonical Baseline — 2026-04-30

**Branch:** `chore/spark-5-6-fabric-cutover-prep-2026-04-30`
**Source:** `docs/operational/spark-network-baseline-2026-04-30/spark-{104,100,105,106,109,115}.txt`
**Driver:** Two new fs.com cables arriving today; spark-5 + spark-6 fabric cutover prep needs canonical reference derived from working sparks 1/2/3/4.

---

## 1. Canonical parity table (sparks 1/2/3/4)

| Item | spark-1 (104) | spark-2 (100) | spark-3 (105) | spark-4 (106) | **CANONICAL** |
|---|---|---|---|---|---|
| Kernel | 6.17.0-1014-nvidia | 6.17.0-1014-nvidia | 6.17.0-1014-nvidia | 6.17.0-1014-nvidia | **6.17.0-1014-nvidia** |
| mlx5_core srcversion | `89EEAF32656D79A2DACFFD3` | `89EEAF32656D79A2DACFFD3` | `89EEAF32656D79A2DACFFD3` | `89EEAF32656D79A2DACFFD3` | **`89EEAF32656D79A2DACFFD3`** |
| ConnectX firmware | `28.45.4028` | `28.45.4028` | `28.45.4028` | `28.45.4028` | **`28.45.4028`** |
| Mellanox PCI device | ConnectX-7 ×4 (00:00.0/.1, 02:00.0/.1) | ConnectX-7 ×4 | ConnectX-7 ×4 | ConnectX-7 ×4 | **ConnectX-7 ×4** |
| Fabric A subnet | `10.10.10.0/24` (.1) | `10.10.10.0/24` (.2) | `10.10.10.0/24` (.3) | `10.10.10.0/24` (.4) | **`10.10.10.0/24`** |
| Fabric A interface | `enp1s0f0np0` | `enp1s0f0np0` | `enp1s0f0np0` | `enp1s0f0np0` | **`enp1s0f0np0`** |
| Fabric B subnet | `10.10.11.0/24` (.1) | `10.10.11.0/24` (.2) | `10.10.11.0/24` (.3) | `10.10.11.0/24` (.4) | **`10.10.11.0/24`** |
| Fabric B interface | `enP2p1s0f1np1` | `enP2p1s0f1np1` | `enP2p1s0f1np1` | `enP2p1s0f1np1` | **`enP2p1s0f1np1`** |
| Fabric MTU | 9000 (A+B) | 9000 (A+B) | 9000 (A+B) | 9000 (A+B) | **9000** |
| Fabric netplan filename | `99-mellanox-roce.yaml` | `99-mellanox-roce.yaml` | `99-mellanox-roce.yaml` | `99-mellanox-roce.yaml` | **`99-mellanox-roce.yaml`** |
| Mgmt LAN interface | `enP7s7` | `enP7s7` | `enP7s7` | `enP7s7` | **`enP7s7`** |
| Mgmt LAN subnet | `192.168.0.0/24` | `192.168.0.0/24` | `192.168.0.0/24` | `192.168.0.0/24` | **`192.168.0.0/24`** (gw `192.168.0.1`, NS `8.8.8.8 1.1.1.1`) |
| Bonding / LACP | none | none | none | none | **none — dual-subnet, not bonded** |
| net.core.default_qdisc | fq_codel | fq_codel | fq_codel | fq_codel | **fq_codel** |
| **net.core.rmem_max** | 536870912 | 536870912 | **212992** ⚠ | 536870912 | **DIVERGES** — sparks 1/2/4 = 536M; spark-3 = kernel default |
| **net.core.wmem_max** | 536870912 | 536870912 | **212992** ⚠ | 536870912 | **DIVERGES** — same pattern |
| **net.ipv4.tcp_rmem** | `4096 87380 268435456` | `4096 87380 268435456` | `4096 131072 33554432` ⚠ | `4096 87380 268435456` | **DIVERGES** |
| **net.ipv4.tcp_wmem** | `4096 65536 268435456` | `4096 65536 268435456` | `4096 16384 4194304` ⚠ | `4096 65536 268435456` | **DIVERGES** |
| net.core.netdev_max_backlog | 1000 | **250000** ⚠ | 1000 | 1000 | **DIVERGES** — only spark-2 tuned |
| **net.ipv4.tcp_congestion_control** | bbr | bbr | **cubic** ⚠ | bbr | **DIVERGES** — spark-3 untuned |

## 2. Canonical netplan template (verbatim from sparks 1/2/3/4)

### 2.1 Mgmt LAN — `01-<role>-core.yaml` (filename varies by host)

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enP7s7:
      dhcp4: false
      addresses:
        - 192.168.0.<X>/24
      routes:
        - to: default
          via: 192.168.0.1
      nameservers:
        addresses: [8.8.8.8, 1.1.1.1]
```

### 2.2 Fabric — `99-mellanox-roce.yaml`

```yaml
network:
  version: 2
  ethernets:
    enp1s0f0np0:
      addresses: [10.10.10.<X>/24]
      mtu: 9000
    enp1s0f1np1:
      dhcp4: false
      optional: true
    enP2p1s0f1np1:
      addresses: [10.10.11.<X>/24]
      mtu: 9000
      dhcp4: false
```

(Note: `enp1s0f1np1` declared `optional: true, dhcp4: false` so DHCP is suppressed but the port is allowed to remain idle. `enP2p1s0f0np0` is not configured by this file — it's used as a `/30` link in a separate `/etc/systemd/network/` file on spark-1, free elsewhere.)

## 3. Divergence notes (canonical drift to surface)

### 3.1 Sysctl drift — spark-3 untuned

Spark-3 runs `cubic` congestion control + kernel-default TCP buffers (`rmem_max=212992`), while sparks 1/2/4 run `bbr` + 512 MiB buffers. This is a **production drift** — spark-3 hosts vision NIM (`:8101`) and embed NIM (`:8102`) that handle real traffic. Likely consequence: spark-3 inference latency and throughput are degraded vs the rest of the cluster.

**Recommendation:** out of scope for this PR (no sysctl changes per hard constraints). Surface as separate issue once this PR lands. Either (a) align spark-3 to the bbr+536M canonical, or (b) document that spark-3 deliberately runs default-tuned. Operator decision.

### 3.2 netdev_max_backlog drift — spark-2 has 250000

Spark-2 has `net.core.netdev_max_backlog = 250000` while the other 3 canonical sparks have `1000`. This is consistent with spark-2 being the control-plane node handling more concurrent connections (LiteLLM gateway, FastAPI backend, qdrant, etc.). Not a drift bug — likely intentional.

### 3.3 Spark-3 has both tcp_rmem and tcp_wmem at kernel defaults

Same root cause as §3.1 — likely spark-3 was provisioned without the cluster's `99-network-tuning.conf` sysctl drop-in. Alignment is operator decision, separately tracked.

## 4. Per-spark netplan filename inconsistency (cosmetic)

| Spark | Mgmt netplan filename | Fabric netplan filename |
|---|---|---|
| spark-1 | `01-node1-core.yaml` | `99-mellanox-roce.yaml` |
| spark-2 | `01-captain-core.yaml` | `99-mellanox-roce.yaml` |
| spark-3 | `01-netcfg.yaml` | `99-mellanox-roce.yaml` |
| spark-4 | `01-sovereign-core.yaml` | `99-mellanox-roce.yaml` |
| spark-5 (current) | `01-mgmt.yaml` + `60-connectx-fabric.yaml` | (different layout, see §5 of parity check) |

Mgmt filename varies by role; fabric filename is uniform on canonical. Spark-5 splits fabric into `60-connectx-fabric.yaml` rather than the canonical `99-mellanox-roce.yaml` filename. Functionally equivalent if content is right, but breaks naming convention.

---

End of canonical baseline.
