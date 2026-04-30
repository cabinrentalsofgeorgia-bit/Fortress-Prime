# Spark-6 ConnectX Hardware Remediation — 2026-04-30

**Status:** 🛑 BLOCKER for fabric activation on spark-6.
**Source finding:** `docs/operational/spark-5-6-parity-check-2026-04-30.md` §2.1.
**Driver issue?** No — `mlx5_core`, `mlx5_ib`, `mlx5_fwctl`, `mlxfw` modules are loaded on spark-6 (`lsmod | grep ^mlx` returns 4 entries). The kernel driver is fine.
**Hardware issue?** Yes — `lspci -nn | grep -i mellanox` returns no PCI device. The adapter is either not installed, not seated correctly, or BIOS-disabled.

---

## 1. Diagnostic priority order (operator side, physical access required)

### Step 1 — confirm `lspci` finding from a fresh boot
Sometimes a transient PCIe enumeration failure clears on reboot. Power-cycle spark-6, then re-check:
```
ssh admin@192.168.0.115 'lspci -nn | grep -i mellanox | wc -l'
```
Expect **4** if hardware is OK. If still 0, proceed.

### Step 2 — `dmesg` inspection
Look for any PCIe enumeration error or mlx5_core load complaint at boot:
```
ssh admin@192.168.0.115 'sudo dmesg | grep -iE "mlx|connectx|pci.*15b3" | head -30'
```
Vendor ID `15b3` = Mellanox / NVIDIA. If kernel saw the device but failed to bind, dmesg will show why. If kernel never saw it, dmesg is silent.

### Step 3 — physical chassis check
Power off spark-6, open chassis. Verify:
- Is a ConnectX-7 adapter physically installed? The other 5 sparks (1/2/3/4/5) all show ConnectX-7 ×4 PCI functions in `lspci`.
- Is it in the same PCIe slot as on the working sparks?
- Are PCIe pins clean? Re-seat to be safe.

### Step 4 — BIOS check
- PCIe slot enabled in BIOS?
- Boot. Re-check `lspci`.

### Step 5 — if hardware is genuinely absent
Procurement: ConnectX-7 adapter (Mellanox MT2910 family, vendor:device `15b3:1021`, single 4-port adapter as installed on sparks 1/2/3/4/5). Brief mentions cables arriving from fs.com today; if adapter isn't in the same shipment, this is a separate procurement item.

## 2. Module load (driver path) — for completeness

If driver were missing (it isn't, on spark-6), the load command would be:
```
sudo modprobe mlx5_core
```

Spark-6 already has all 4 expected modules loaded (`mlx5_core`, `mlx5_ib`, `mlx5_fwctl`, `mlxfw`). No driver remediation needed.

## 3. Firmware update path (only relevant once hardware present)

The cluster-canonical firmware is `28.45.4028` (per `docs/operational/cluster-network-canonical-baseline-2026-04-30.md` §1). Once spark-6 has visible Mellanox PCI devices, verify firmware match:
```
sudo ethtool -i enp1s0f0np0 | grep firmware-version
```

If firmware diverges from `28.45.4028`:
- NVIDIA-supplied firmware update tool: `mlxfwmanager` (part of MFT — Mellanox Firmware Tools)
- Or operating-system supplied firmware blob loaded by `mlx5_core` at module init

This is operator-side. Out of scope for today's cable cutover.

## 4. When to run

Sequence relative to today's cable cutover:

1. **Before plugging cables into spark-6:** complete Step 1–4 above. If adapter is genuinely absent, skip cables for spark-6 — defer cutover until adapter installed.
2. **If adapter present but `lspci` not seeing it:** re-seat, reboot, recheck. Don't plug cables until lspci shows 4 entries.
3. **If lspci shows 4 entries:** plug cables, apply target netplan from `docs/operational/spark-6-target-netplan-2026-04-30.yaml`, validate.

## 5. Validation post-remediation

```
ssh admin@192.168.0.115 'lspci -nn | grep -i mellanox | wc -l'
# expect 4

ssh admin@192.168.0.115 'ls /sys/class/net/ | grep -E "enp1s0f|enP2p1s0f"'
# expect 4 interface names matching canonical

ssh admin@192.168.0.115 'sudo ethtool -i enp1s0f0np0 | grep firmware-version'
# expect: firmware-version: 28.45.4028 (or document divergence)

ping -c 3 -W 1 10.10.10.6
ping -c 3 -W 1 10.10.11.6
# both should succeed from spark-2 after netplan apply
```

If all 5 pass → spark-6 fabric is live and aligned with canonical.

---

End of remediation plan.
