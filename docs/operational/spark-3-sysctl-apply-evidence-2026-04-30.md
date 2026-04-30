# PR #318 sysctl apply — spark-3 evidence pack

**Date:** 2026-04-30 10:15–10:18 EDT
**Branch:** `chore/pr-318-spark-3-sysctl-apply-2026-04-30`
**Stacks on:** PR #318 (sysctl/TCP alignment brief)
**Driver:** Operator greenlight 2026-04-30 to apply PR #318 canonical
sysctl on **spark-3 only** (spark-4 verified canonical per recon;
spark-5/6 deferred).

This PR commits the apply transcript. **Do NOT merge** — surface for
operator review.

---

## 1. Pre-existing-file finding

`/etc/sysctl.d/99-network-tuning.conf` was **already present** on
spark-3, dated 2026-04-25 14:22, 170 bytes, root:root, mode 644.
Content was **byte-for-byte identical to PR #318 §2 canonical**:

```
net.core.rmem_max=536870912
net.core.wmem_max=536870912
net.ipv4.tcp_rmem=4096 87380 268435456
net.ipv4.tcp_wmem=4096 65536 268435456
net.ipv4.tcp_congestion_control=bbr
```

But the runtime sysctl values were **kernel default** (cubic + 208 KiB).
Either the file was created without an immediate `sysctl --system`, or
a subsequent boot's `systemd-sysctl.service` ran but did not pick up
the new file's effect (no journal entries from this boot for
`systemd-sysctl.service` were available).

Apply path: file content already correct → file write step was a
no-op equivalent. The `sudo sysctl --system` on spark-3 caused the
runtime to re-read all `/etc/sysctl.d/*.conf` files, with
`99-network-tuning.conf` as the last writer for these 5 keys (loaded
before `99-sysctl.conf` symlink to `/etc/sysctl.conf`, which is
empty).

Lexical apply order verified via `sysctl --system` output:

```
* Applying /etc/sysctl.d/10-bufferbloat.conf ...
* Applying /etc/sysctl.d/10-network-security.conf ...
* Applying /etc/sysctl.d/20-nvidia-defaults.conf ...
* Applying /etc/sysctl.d/99-network-tuning.conf ...
* Applying /etc/sysctl.d/99-sysctl.conf ...
* Applying /etc/sysctl.conf ...
net.core.rmem_max = 536870912
net.core.wmem_max = 536870912
```

---

## 2. PRE-state (before apply)

```
net.ipv4.tcp_congestion_control = cubic
net.core.rmem_max = 212992
net.core.wmem_max = 212992
net.ipv4.tcp_rmem = 4096	131072	33554432
net.ipv4.tcp_wmem = 4096	16384	4194304
---tcp_bbr module---
(unloaded — no entry in lsmod)
```

## 3. POST-state (after `sudo sysctl --system`)

```
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 536870912
net.core.wmem_max = 536870912
net.ipv4.tcp_rmem = 4096	87380	268435456
net.ipv4.tcp_wmem = 4096	65536	268435456
---tcp_bbr module---
tcp_bbr                20480  2
```

**All 5 keys at canonical target.** `tcp_bbr.ko` auto-loaded on first
write to `tcp_congestion_control=bbr` (refcount 2 = the live SSH +
test sockets using it).

## 4. PRE → POST diff

```
1,5c1,5
< net.ipv4.tcp_congestion_control = cubic
< net.core.rmem_max = 212992
< net.core.wmem_max = 212992
< net.ipv4.tcp_rmem = 4096	131072	33554432
< net.ipv4.tcp_wmem = 4096	16384	4194304
---
> net.ipv4.tcp_congestion_control = bbr
> net.core.rmem_max = 536870912
> net.core.wmem_max = 536870912
> net.ipv4.tcp_rmem = 4096	87380	268435456
> net.ipv4.tcp_wmem = 4096	65536	268435456
6a7
> tcp_bbr                20480  2
```

## 5. NCCL/fabric smoke

Fresh TCP socket from spark-3 (10.10.10.3, fabric A) to spark-2
(10.10.10.2:22), inspected via `ss -tin dst 10.10.10.2` while the
socket was live:

```
ESTAB 43  0  10.10.10.3:33574  10.10.10.2:22
   bbr wscale:14,14 rto:200 rtt:0.197/0.098 ato:40
   mss:8948 pmtu:9000 rcvmss:536 advmss:8948 cwnd:10
   bbr:(bw:0bps,mrtt:0.197,pacing_gain:1,cwnd_gain:1)
   send 3633705584bps  pacing_rate 10384587152bps
   minrtt:0.197  snd_wnd:65536
```

Confirms:
- ✅ congestion control = `bbr` on fresh socket
- ✅ window-scale `wscale:14,14` (uses larger buffers)
- ✅ `pmtu:9000` jumbo frames working on fabric A
- ✅ pacing_rate ≈ 10.4 Gbps on a single SSH stream
- ✅ tcp_bbr module loaded and in active use

## 6. Reboot survivability

`/etc/sysctl.d/99-network-tuning.conf` is read by
`systemd-sysctl.service` at boot. Service is enabled on spark-3.
**No additional unit work needed.** Persistence path matches PR #318
§3.5.

## 7. Hard-stop checks

| Stop condition | Result |
|---|---|
| Pre-state already shows target values | ❌ NOT triggered (pre-state was cubic/208K) |
| Any sysctl key write fails | ❌ NOT triggered (`sysctl --system` exited 0; all 5 keys applied) |
| Post-state diverges from intent | ❌ NOT triggered (every key matches canonical) |

All clear. Apply complete.

## 8. Out of scope

- spark-4 apply: skipped per recon (spark-4 already canonical)
- spark-5 apply: deferred (spark-5 fabric B cable cutover pending)
- spark-6 apply: deferred (spark-6 ConnectX hardware question open)

---

## 9. Full transcript

`/tmp/pr-318-spark-3-apply-20260430_101545.log` (also
`/tmp/sysctl-spark-3-PRE-20260430_101545.txt`,
`/tmp/sysctl-spark-3-POST-20260430_101545.txt`,
`/tmp/spark3-existing-conf.txt`,
`/tmp/spark3-sysctl-trace.txt`).

Transcripts retained on spark-2 for reproducibility but not committed
(per Fortress-Prime convention — `/tmp/` is ephemeral; this evidence
doc is the durable record).

---

End of evidence.
