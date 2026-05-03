# Remote Hardening Status - 2026-05-03

## Hardened Remotely

- Corrected Spark physical-label aliases so Spark-1 is `192.168.0.104`
  / `spark-node-1` and Spark-2 is `192.168.0.100` / `spark-node-2`.
- Added `docs/operational/known-good-network-map-2026-05-03.md` as the
  current source of truth for Spark, NAS, router, and Mac mini paths.
- Added `tools/fortress_stack_health.sh` for repeatable remote health checks.
- Added `fortress-stack-health.service` and `fortress-stack-health.timer` to
  run the health checker hourly from Spark-2 and keep results in systemd logs.
- Validated the repo drift alarm, k3s, Spark aliases, NAS LAN/mount, Tailscale
  peers, and core services from Spark-2.

## Current Known Warnings

- Synology DS1825 Tailscale entry `100.89.109.96` is offline. LAN, DSM, NFS,
  and SMB paths were healthy. Repair is parked until the operator is local to
  DSM and can restart or re-authenticate the Synology Tailscale package.
- Fortress Mac mini is reachable over Tailscale, but its Data volume remains
  tight. The latest remote check reported roughly 93% used and 16 GiB free.

## How To Check

Manual:

```bash
cd /home/admin/Fortress-Prime
tools/fortress_stack_health.sh
```

Timer status:

```bash
systemctl status fortress-stack-health.timer --no-pager
journalctl -u fortress-stack-health.service -n 120 --no-pager
```

## Build Gate

Before continuing major feature work, run:

```bash
cd /home/admin/Fortress-Prime
tools/fortress_stack_health.sh
```

Proceed if the only warnings are the parked Synology Tailscale repair and Mac
mini disk pressure. Stop and repair if repo drift, k3s readiness, NAS LAN mount,
or core Spark services fail.

