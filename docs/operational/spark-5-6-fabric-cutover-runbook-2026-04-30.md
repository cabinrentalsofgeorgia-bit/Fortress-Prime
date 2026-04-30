# Spark-5 + Spark-6 Fabric Cutover Runbook — 2026-04-30

**Branch:** `chore/spark-5-6-fabric-cutover-prep-2026-04-30`
**Hardware arriving today:** 2× cables from fs.com.
**Operator-execute.** This runbook is the step-by-step sequence; no agent-side execution.

**Pre-reads (in order):**
1. `docs/operational/cluster-network-canonical-baseline-2026-04-30.md` — what spark-5/6 should look like
2. `docs/operational/spark-5-6-parity-check-2026-04-30.md` — current deltas
3. `docs/operational/spark-6-driver-remediation-2026-04-30.md` — spark-6 hardware blocker
4. `docs/operational/spark-5-target-netplan-2026-04-30.yaml` — target netplan for spark-5
5. `docs/operational/spark-6-target-netplan-2026-04-30.yaml` — target netplan for spark-6
6. `src/operational/validate-fabric-cutover.sh` — validation script

---

## 1. Pre-cutover health snapshot (run before touching anything)

```bash
# From any operator shell with cluster network access:
bash src/operational/validate-fabric-cutover.sh > /tmp/fabric-pre-cutover.log 2>&1
```

Capture timestamp. Most rows expected to PASS for sparks 1/2/3/4. Spark-5 fabric B expected FAIL (currently mis-bound). Spark-6 fabric A + B expected FAIL.

Key services that must stay green throughout:
- BRAIN on spark-5:8100 (Llama-3.3-Nemotron-Super-49B)
- vision-NIM on spark-3:8101
- embed-NIM on spark-3:8102
- LiteLLM gateway on spark-2:8002
- Qdrant on spark-2:6333
- Qdrant-VRS on spark-4:6333

## 2. Spark-6 cutover (do FIRST — lower risk, no live service)

### 2.1 Pre-flight — ConnectX hardware verification

🛑 **GATING STEP. Do NOT plug cables into spark-6 until this passes.**

```bash
ssh admin@192.168.0.115 'lspci -nn | grep -i mellanox | wc -l'
```

- If output is `4` → hardware present, proceed to §2.2.
- If output is `0` → hardware absent. Follow `docs/operational/spark-6-driver-remediation-2026-04-30.md` Steps 1–5.
  - Plugging cables anyway will leave them physically connected to Mikrotik but with no NIC at the spark-6 end. Fabric will not activate.
  - **Defer spark-6 cabling until hardware blocker resolved.** Continue with spark-5 cutover (§3) regardless.

### 2.2 Plug cables

- Cable A: spark-6 ConnectX port matching `enp1s0f0np0` ↔ Mikrotik 200G port (aggregated)
- Cable B: spark-6 ConnectX port matching `enP2p1s0f1np1` ↔ Mikrotik 200G port (aggregated)

Identify physical port-to-name mapping by following the same convention as on spark-1 (operator already has the wiring map).

### 2.3 Verify mlx5_core enumerates new interfaces

```bash
ssh admin@192.168.0.115 'ip -d link show | grep -E "enp1s0f|enP2p1s0f"'
```

Expect 4 interfaces: `enp1s0f0np0`, `enp1s0f1np1`, `enP2p1s0f0np0`, `enP2p1s0f1np1`. The cabled ones should show `state=UP`. The uncabled ones may show `state=DOWN` — that's fine.

### 2.4 Apply target netplan

```bash
# On spark-6:
sudo cp /tmp/99-mellanox-roce.yaml /etc/netplan/99-mellanox-roce.yaml
sudo chmod 600 /etc/netplan/99-mellanox-roce.yaml
sudo chown root:root /etc/netplan/99-mellanox-roce.yaml
sudo netplan generate
sudo netplan apply
```

(Source: `docs/operational/spark-6-target-netplan-2026-04-30.yaml` second YAML block, scp'd to `/tmp/99-mellanox-roce.yaml` on spark-6.)

### 2.5 Verify fabric reachability from spark-2

```bash
# From spark-2 (192.168.0.100):
ping -c 3 -W 1 10.10.10.6  # fabric A to spark-6
ping -c 3 -W 1 10.10.11.6  # fabric B to spark-6
```

Both expected to succeed. If either fails:
- Re-check `ip -d link show` on spark-6 for `state=UP` and `mtu 9000`
- Check Mikrotik aggregated port for spark-6's MAC addresses
- Defer further investigation; spark-6 not on critical-path for today

## 3. Spark-5 cutover (BRAIN serving — minimize downtime)

### 3.1 Pre-flight — confirm BRAIN healthy

```bash
curl -sS --max-time 5 http://192.168.0.109:8100/v1/health/ready
# expect: {"object":"health.response","message":"ready","status":"ready"}
```

If BRAIN is degraded BEFORE cutover, halt and surface — don't compound the issue.

### 3.2 Confirm 192.168.0.111 dependency search returns clean

```bash
ssh admin@192.168.0.100 'sudo grep -rn "192\.168\.0\.111" /etc /home/admin/Fortress-Prime 2>/dev/null | head -5'
```

If result is empty (or only matches in `.bak`/comments), the mis-bound IP is safely dropped. If result has live config references, address those first.

### 3.3 Plug cables

- Cable A: spark-5 ConnectX port matching `enp1s0f0np0` ↔ Mikrotik 200G port (aggregated)
- Cable B: spark-5 ConnectX port matching `enP2p1s0f1np1` ↔ Mikrotik 200G port (aggregated)

(Spark-5 currently has 1 cable in `enp1s0f1np1`. Operator decision: leave that cable in place and add 2 new cables for canonical ports — temporarily 3 cables, then remove the legacy one — OR re-route the existing cable to canonical port `enp1s0f0np0` and add only 1 new cable to `enP2p1s0f1np1`. Whichever the cutover choreography supports without dropping BRAIN traffic.)

### 3.4 Verify new ports come up

```bash
ssh admin@192.168.0.109 'ip -d link show | grep -E "enp1s0f|enP2p1s0f" | head -8'
```

Expect canonical ports (`enp1s0f0np0`, `enP2p1s0f1np1`) `state=UP`.

### 3.5 Backup current spark-5 netplan + apply target

```bash
# On spark-5:
sudo cp /etc/netplan/60-connectx-fabric.yaml /etc/netplan/60-connectx-fabric.yaml.bak.$(date +%Y%m%d_%H%M%S)
sudo cp /tmp/99-mellanox-roce.yaml /etc/netplan/99-mellanox-roce.yaml
sudo chmod 600 /etc/netplan/99-mellanox-roce.yaml
sudo chown root:root /etc/netplan/99-mellanox-roce.yaml
# Optionally remove the old fabric file (after confirming new one is functional):
# sudo rm /etc/netplan/60-connectx-fabric.yaml
sudo netplan generate
sudo netplan apply
```

### 3.6 Verify BRAIN still serving

```bash
curl -sS --max-time 5 http://192.168.0.109:8100/v1/health/ready
# expect: {"status":"ready"} — same as 3.1
```

If BRAIN unreachable after netplan apply: roll back via `sudo cp 60-connectx-fabric.yaml.bak.<timestamp> 60-connectx-fabric.yaml; sudo netplan apply`. Investigate cause before retrying.

### 3.7 Verify fabric reachability from spark-2

```bash
# From spark-2:
ping -c 3 -W 1 10.10.10.5  # fabric A to spark-5
ping -c 3 -W 1 10.10.11.5  # fabric B to spark-5 (was mis-bound; should now work)
```

## 4. Post-cutover validation

```bash
# From any operator shell with cluster network access:
bash src/operational/validate-fabric-cutover.sh > /tmp/fabric-post-cutover.log 2>&1
diff /tmp/fabric-pre-cutover.log /tmp/fabric-post-cutover.log
```

Expected differences:
- Spark-5 fabric B (10.10.11.5): FAIL → PASS
- Spark-6 fabric A (10.10.10.6): FAIL → PASS (only if hardware present)
- Spark-6 fabric B (10.10.11.6): FAIL → PASS (only if hardware present)

Everything else (BRAIN/vision/embed/LiteLLM/Qdrant) should remain PASS.

## 5. Rollback (per-spark)

If post-cutover validation regresses a previously-working service:

```bash
# Spark-6 rollback (no service was running, so just remove the new file):
ssh admin@192.168.0.115 'sudo rm /etc/netplan/99-mellanox-roce.yaml && sudo netplan apply'

# Spark-5 rollback:
ssh admin@192.168.0.109 'sudo mv /etc/netplan/60-connectx-fabric.yaml.bak.<timestamp> /etc/netplan/60-connectx-fabric.yaml && sudo rm /etc/netplan/99-mellanox-roce.yaml && sudo netplan apply'
```

Then re-run §1 pre-snapshot to confirm rollback restored expected state.

## 6. After cutover lands

- Re-run `ray status` from spark-2; spark-5 worker still won't appear (Ray enablement is separate work, gated on operator decision per cluster-network-audit-2026-04-30.md §5 Gap 2).
- File issue if any sysctl drift surfaces in validation script (separate alignment work — out of cutover scope).

---

End of runbook.
