# Known-Good Network Map - 2026-05-03

This is the current operator-facing source of truth for the Fortress Spark, NAS,
Mac mini, and router paths. It uses the physical Spark labels, not the sometimes
confusing Linux hostnames.

## Spark Nodes

| Physical label | Linux hostname | Role | Preferred path | LAN / mgmt | Fabric | Tailscale | SSH aliases from Spark-2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Spark-1 | `spark-node-1` | k3s worker, legal/app migration host | LAN or fabric from Spark-2 | `192.168.0.104` | `10.10.10.1`, `10.101.2.1` p2p | `100.127.241.36` | `spark-1`, `spark-1-fabric`, `spark-1-p2p`, `spark-1-mgmt`, `spark-1-ts` |
| Spark-2 | `spark-node-2` | k3s control plane, Fortress app/control plane | local/fabric | `192.168.0.100` | `10.10.10.2` | `100.80.122.100` | `spark-2`, `spark-2-mgmt`, `spark-2-ts`, `spark2` |
| Spark-3 | `spark-3` | k3s worker | fabric | `192.168.0.105` | `10.10.10.3` | `100.96.44.85` | `spark-3`, `spark-3-mgmt`, `spark-3-ts` |
| Spark-4 | `Spark-4` | k3s worker | fabric | `192.168.0.106` | `10.10.10.4` | `100.125.35.42` | `spark-4`, `spark-4-mgmt`, `spark-4-ts` |
| Spark-5 | `spark-5` | healthy standalone GB10 spare/inference node | Tailscale remote, LAN local | `192.168.0.111` | not in k3s | `100.96.13.99` | `spark-5`, `spark-5-ts`, `spark-5-mgmt` |
| Spark-6 | `spark-6` | healthy standalone GB10 spare/inference node | Tailscale remote, LAN local | `192.168.0.115` | not in k3s | `100.71.225.76` | `spark-6`, `spark-6-ts`, `spark-6-mgmt` |

## Storage And Control Devices

| Device | Role | Healthy path | Tailscale state | Notes |
| --- | --- | --- | --- | --- |
| TP-Link router | LAN gateway | `192.168.0.1` | n/a | Spark-2 default route uses this gateway. |
| Synology DS1825 | NAS for Fortress data | `192.168.0.112`, `192.168.0.113`; NFS mount at `/mnt/fortress_nas` | `100.89.109.96` is offline | LAN, DSM, SMB, and NFS were healthy. Tailscale repair requires local DSM/package access. |
| Fortress Mac mini | Remote control / local bridge | `192.168.0.114` and `100.66.180.7` | online | Root SSH over Tailscale works. Disk was improved from about 4 GB free to about 22 GB free. |

## Current Known Warnings

- Synology Tailscale (`DS1825`, `100.89.109.96`) is offline. This is parked
  until the operator is local to DSM and can restart or re-authenticate the
  Tailscale package.
- Tailscale admin console still contains old/stale identities, including an old
  offline `spark-3` entry and `fortress-linux`. Do not delete from SSH; prune
  later from the Tailscale admin console after confirming ownership.
- k3s currently uses Spark-1 through Spark-4. Spark-5 and Spark-6 are healthy
  standalone nodes, not current k3s members.

## Validation Command

Run this from Spark-2:

```bash
tools/fortress_stack_health.sh
```

The script reports plain `OK`, `WARN`, or `FAIL` lines for repo drift, k3s,
critical services, Spark aliases, NAS LAN reachability, Mac mini reachability,
and key Tailscale peers.
