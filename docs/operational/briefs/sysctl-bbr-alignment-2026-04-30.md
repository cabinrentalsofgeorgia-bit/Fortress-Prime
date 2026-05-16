# Cluster sysctl/TCP alignment — bbr + 512MiB buffers on all sparks

**Date:** 2026-04-30
**Status:** PROPOSED — doc-only PR; awaiting operator authorization for the apply step
**Driver:** Pre-stage for ADR-006 TP=2 cutover (NCCL/RDMA over fabric A
performance) and Phase 3 hot-replica TP=2+1 (cross-node tensor exchange).
Read-only delta probe 2026-04-30 confirms 3 of 6 sparks ship with kernel
default `cubic` + 212 KiB receive buffers, far below what 100 Gbps
ConnectX fabric needs.

This brief is the **plan**, not the **apply**. The PR commits the
proposed `99-network-tuning.conf` content + apply procedure; the
actual `sudo cp` + `sysctl --system` lands in a separate authorized PR
or operator-executed runbook.

**Stacks on:** ADR-006 (LOCKED on main as commit 25dcd11d5),
ADR-003/004 inference cluster topology.

---

## 1. Current state — read-only delta probe (2026-04-30)

| Spark | IP | tcp_cc | rmem_max | wmem_max | tcp_rmem (max) | tcp_wmem (max) | Status |
|---|---|---|---|---|---|---|---|
| spark-1 | 192.168.0.104 | bbr | 512 MiB | 512 MiB | 256 MiB | 256 MiB | ✅ canonical |
| spark-2 | 192.168.0.100 | bbr | 512 MiB | 512 MiB | 256 MiB | 256 MiB | ✅ canonical |
| **spark-3** | 192.168.0.105 | **cubic** | **208 KiB** | **208 KiB** | **32 MiB** | **4 MiB** | ❌ kernel default |
| spark-4 | 192.168.0.106 | bbr | 512 MiB | 512 MiB | 256 MiB | 256 MiB | ✅ canonical |
| **spark-5** | 192.168.0.109 | **cubic** | **208 KiB** | **208 KiB** | **32 MiB** | **4 MiB** | ❌ kernel default |
| **spark-6** | 192.168.0.115 | **cubic** | **208 KiB** | **208 KiB** | **32 MiB** | **4 MiB** | ❌ kernel default |

Kernel module `tcp_bbr` is **available and unloaded** on all 6 sparks
(verified `modinfo tcp_bbr` returns the .ko on every host). No module
build needed; sysctl write loads the module.

Default qdisc = `fq_codel` on all 6 sparks. ✅ no change needed.

`net.ipv4.tcp_mtu_probing = 0` on all 6 sparks. Documented but not
changed by this brief (see §5 open question).

### Why this matters

ConnectX-7 fabric runs at 100 Gbps. Bandwidth-delay product (BDP) at
0.3 ms intra-rack RTT and 100 Gbps:

```
BDP = 12.5 GB/s × 0.0003 s = 3.75 MB
```

With `tcp_rmem = 32 MiB` we're nominally fine for steady-state TCP.
But:
- `rmem_max = 208 KiB` caps **per-socket** allocations regardless of
  what `tcp_rmem` advertises. Any application using `setsockopt(SO_RCVBUF)`
  hits 208 KiB.
- NCCL over TCP fallback (when RDMA unenumerable, e.g., spark-4 RDMA
  enumeration empty per Issue #294) needs ≥4 MiB to saturate 100 Gbps.
  208 KiB caps NCCL at <1 Gbps effective.
- `cubic` underperforms `bbr` on long-fat networks; bbr maintains BDP
  closer to optimum without bufferbloat.

The cluster's existing nodes (spark-1, 2, 4) were aligned at some point
during an earlier hand-tuning pass; spark-3, 5, 6 were skipped or never
re-tuned after a kernel upgrade reset them.

---

## 2. Canonical configuration (spark-1, spark-2, spark-4)

File `/etc/sysctl.d/99-network-tuning.conf` — verbatim content from
spark-1:

```ini
net.core.rmem_max=536870912
net.core.wmem_max=536870912
net.ipv4.tcp_rmem=4096 87380 268435456
net.ipv4.tcp_wmem=4096 65536 268435456
net.ipv4.tcp_congestion_control=bbr
```

(Spark-2 also has a `/etc/sysctl.d/99-sysctl.conf` containing weaker
values — `rmem_max=134217728`, etc. — but `99-network-tuning.conf` is
loaded later in lexical order on a `sysctl --system` run on spark-2's
config path, so the canonical 512 MiB values win. The proposal here
reuses the spark-1 single-file pattern, which is cleaner.)

---

## 3. Proposed apply procedure (operator authorizes execution separately)

For each of spark-3 (192.168.0.105), spark-5 (192.168.0.109), spark-6
(192.168.0.115):

### 3.1 Pre-apply snapshot (one line)

```bash
ssh admin@<IP> 'sysctl net.ipv4.tcp_congestion_control net.core.rmem_max net.core.wmem_max net.ipv4.tcp_rmem net.ipv4.tcp_wmem' | tee /tmp/sysctl-pre-<host>.txt
```

### 3.2 Drop the canonical file

```bash
ssh admin@<IP> 'sudo tee /etc/sysctl.d/99-network-tuning.conf >/dev/null <<EOF
net.core.rmem_max=536870912
net.core.wmem_max=536870912
net.ipv4.tcp_rmem=4096 87380 268435456
net.ipv4.tcp_wmem=4096 65536 268435456
net.ipv4.tcp_congestion_control=bbr
EOF
sudo chmod 644 /etc/sysctl.d/99-network-tuning.conf
sudo chown root:root /etc/sysctl.d/99-network-tuning.conf'
```

### 3.3 Apply (no reboot needed)

```bash
ssh admin@<IP> 'sudo sysctl --system 2>&1 | tail -10'
```

`sysctl --system` rereads all `/etc/sysctl.d/*.conf` files and applies
in order. Existing TCP connections continue with the old buffer
sizes; new connections pick up the new values.

### 3.4 Verify

```bash
ssh admin@<IP> 'sysctl net.ipv4.tcp_congestion_control net.core.rmem_max net.core.wmem_max net.ipv4.tcp_rmem net.ipv4.tcp_wmem'
```

Expected output (must match spark-1):

```
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 536870912
net.core.wmem_max = 536870912
net.ipv4.tcp_rmem = 4096	87380	268435456
net.ipv4.tcp_wmem = 4096	65536	268435456
```

### 3.5 Reboot survivability

`/etc/sysctl.d/99-network-tuning.conf` is read by systemd-sysctl on
boot via the `systemd-sysctl.service` unit (active out of the box on
all spark hosts). **No additional unit work needed.** `sysctl --system`
mimics what boot does.

### 3.6 Recommended order

1. **Spark-3 first** (lowest risk — vision NIM + embed NIM are HTTP
   workloads inside their containers; they don't depend on
   `setsockopt(SO_RCVBUF)` and won't notice).
2. **Spark-5 second** (BRAIN running on :8100 — same logic; existing
   connections continue, new connections use canonical values).
3. **Spark-6 last** (currently no inference workload — safest of the
   three).

Wait 5 minutes between each apply and re-verify with `sysctl` reads.

---

## 4. Risk matrix

| Risk | Likelihood | Mitigation |
|---|---|---|
| `sysctl --system` fails to apply (syntax error in dropped file) | Very low | The file content is identical to spark-1's; pre-tested. Verify with `sudo sysctl -p /etc/sysctl.d/99-network-tuning.conf` (loads just one file) before `--system` if extra-defensive |
| Buffer change causes spurious connection resets | Very low | Linux only changes per-socket buffers on new sockets; existing connections retain old values. In-flight legal-brain HTTP calls unaffected. |
| `bbr` interacts badly with congestion on a slow LAN link | Low | All 6 sparks live on Mikrotik switch + ConnectX fabric; no slow links involved. spark-1, 2, 4 have run bbr for weeks without incident. |
| File overwrites an existing `/etc/sysctl.d/99-network-tuning.conf` | Possible | Pre-apply check: `ssh admin@<IP> 'ls -la /etc/sysctl.d/99-network-tuning.conf 2>&1 \|\| echo "no-existing-file"'`. Currently absent on spark-3/5/6 per probe. |
| Post-reboot, file evaporates | Very low | Standard Ubuntu `systemd-sysctl.service` reads `/etc/sysctl.d/` at boot. Verified active on all 6 hosts. |

---

## 5. Open question (out of scope for this brief)

**`net.ipv4.tcp_mtu_probing = 0` on all 6 sparks.** ConnectX fabric
runs MTU 9000 (jumbo frames) on the dedicated 10.10.10.0/24 / 10.10.11.0/24
networks; mgmt LAN is MTU 1500. Setting `tcp_mtu_probing = 1` would
allow Linux to discover working MTU per-route, but it's also a
behavior change with PMTU-blackhole-recovery semantics. Document only;
not changed by this brief. **Operator decision needed if jumbo-frame
TCP between sparks ever degrades.**

---

## 6. Definition of done (this brief)

- [x] Read-only delta probe captured (2026-04-30; spark-3 retried after one timeout)
- [x] Canonical file content captured verbatim from spark-1
- [x] Apply procedure documented step-by-step
- [x] Verification commands documented
- [x] Reboot survivability confirmed (systemd-sysctl.service)
- [x] Risk matrix populated
- [x] Recommended order rationalized
- [ ] Operator authorizes apply on spark-3 / spark-5 / spark-6
- [ ] Apply executed (separate authorized step)
- [ ] Post-apply verification doc appended

---

## 7. Out of scope

- TCP MTU probing change (§5 open question)
- Other sysctl alignment beyond the 5 settings above (e.g.,
  `net.core.netdev_max_backlog`, `fs.aio-max-nr` — different on
  spark-2's `/etc/sysctl.d/99-sysctl.conf`; would need separate audit)
- The actual `sudo cp` + `sysctl --system` execution — separate
  authorized PR
- Issue #294 (spark-4 RDMA enumeration debug) — different layer
- NCCL_DEBUG=INFO instrumentation for ADR-006 cutover — covered in
  cutover brief

---

End of brief.
