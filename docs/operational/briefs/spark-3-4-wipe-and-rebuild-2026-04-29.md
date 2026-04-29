# Spark-3 + Spark-4 Wipe-and-Rebuild — Operational Brief

> **⚠ SUPERSEDED 2026-04-29 by ADR-004 Amendment v2 (retain-and-document).**
> See `docs/architecture/cross-division/ADR-004-app-vs-inference-boundary.md` § Amendment 2026-04-29 for the corrected disposition. The wipe-and-rebuild approach in this brief is **not the current plan**; spark-3 + spark-4 are retained as inference-cluster members with their existing workloads (ollama, qdrant-vrs, sensevoice) preserved. Service consolidation is gated on caller migration (P4). This brief is preserved as a durable record of the original plan; do not execute it.
>
> Companion docs: `docs/operational/incident-2026-04-29-ollama-removal.md`, `docs/operational/spark-3-4-retained-state-2026-04-29.md`.

**Date:** 2026-04-29
**Status:** SUPERSEDED 2026-04-29 (originally PLANNED — execution gated on Spark-6 cable cutover, ADR-003 Phase 2)
**Driver:** ADR-004 (LOCKED 2026-04-29) — original plan: Sparks 3/4 join the inference cluster via wipe-and-rebuild
**Target operator-execution date:** N/A — superseded

> **This brief describes the execution; it does not execute the wipe.** A separate operator-authorized session runs the wipe. Until then, this is a durable record of the plan.

---

## Pre-wipe inventory (BEFORE any wipe)

Run on each node, capture as a separate doc:

```bash
# spark-3 inventory
ssh admin@spark-3 'sudo systemctl list-units --type=service --state=active' > /tmp/spark-3-services.txt
ssh admin@spark-3 'docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"' > /tmp/spark-3-containers.txt
ssh admin@spark-3 'sudo -u postgres psql -l 2>/dev/null || echo "no postgres"' > /tmp/spark-3-postgres.txt
ssh admin@spark-3 'ls -la /home/admin /etc/fortress 2>/dev/null' > /tmp/spark-3-userdata.txt
ssh admin@spark-3 'df -h / /home /var' > /tmp/spark-3-disk.txt

# spark-4 inventory (same commands, spark-4 hostname)
ssh admin@spark-4 'sudo systemctl list-units --type=service --state=active' > /tmp/spark-4-services.txt
ssh admin@spark-4 'docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"' > /tmp/spark-4-containers.txt
ssh admin@spark-4 'sudo -u postgres psql -l 2>/dev/null || echo "no postgres"' > /tmp/spark-4-postgres.txt
ssh admin@spark-4 'ls -la /home/admin /etc/fortress 2>/dev/null' > /tmp/spark-4-userdata.txt
ssh admin@spark-4 'df -h / /home /var' > /tmp/spark-4-disk.txt
```

Output: `docs/operational/spark-3-4-pre-wipe-inventory-<DATE>.md` with both nodes' state side-by-side.

**STOP gate:** if either node has data not also durable elsewhere (NAS, spark-2 Postgres, repo), STOP. Surface to operator. Do not wipe until backed up.

### Known state from prior session work

- **Spark-3:** Vision NIM container (`nemotron-nano-12b-v2-vl`) per Iron Dome v6.1 audit; 69% RAM utilization noted at audit time.
- **Spark-4:** Qdrant VRS at `192.168.0.106:6333`, SenseVoice service, occasional CROG tmux scratch.

Both Vision NIM and Qdrant VRS need migration plans before wipe:

- **Vision NIM** moves to the inference cluster (re-deploy from NGC; container is recoverable).
- **Qdrant VRS** needs data export + import to spark-2 Qdrant (or new home) before spark-4 wipe.

---

## Phase order

### Phase A — Spark 4 wipe (do first; lighter load, lower risk)

1. Inventory captured + reviewed.
2. Qdrant VRS data exported to spark-2 (`192.168.0.100:6333`) or new Qdrant cluster destination.
3. SenseVoice migration plan (re-deploy elsewhere, or retire).
4. Confirm no active app traffic hits spark-4.
5. OS reinstall (Ubuntu 24 fresh) — same image as spark-5, ConnectX driver baseline.
6. NIM + Ray + Docker stack baseline matching spark-5.
7. Ray worker registration to spark-5 head.

### Phase B — Spark 3 wipe (after Phase A validated)

Spark-3 has Vision NIM that's known healthy — wipe second so the regenerated baseline is proven on Spark-4 first.

1. Inventory captured + reviewed.
2. Vision NIM container documented (image digest, env, health) for redeploy.
3. Confirm no active app traffic.
4. OS reinstall — same baseline as Phase A.
5. NIM + Ray + Docker stack.
6. Ray worker registration to spark-5 head.
7. Vision NIM redeployed (or retired if no longer needed).

---

## Hard constraints

- **DO NOT** wipe before Spark-6 cable lands and Phase 2 (TP=2 with Spark 5) is validated. The 4-node cluster needs 4 nodes on ConnectX fabric.
- **DO NOT** wipe both nodes simultaneously. Phase A first, validated, then Phase B.
- **DO NOT** wipe before pre-wipe inventory is committed to repo as a durable record.
- **DO NOT** wipe before Qdrant VRS data is verified-recoverable on the destination.
- **DO NOT** re-pull Phase 1 / Phase 2 NIM images blindly. Reference ADR-003 §pinning + the production validation report for image digests.
- **DO NOT** restart spark-5 NIM during the wipe — operator workflows depend on BRAIN being live throughout.

---

## Definition of done (per phase)

- Pre-wipe inventory committed to `docs/operational/spark-3-4-pre-wipe-inventory-<DATE>.md`.
- Data migration plan executed and verified (Qdrant VRS export → import; checksum match on chunk count + collection schema).
- OS reinstalled, ConnectX driver verified.
- NIM + Ray + Docker stack baseline matches spark-5.
- Ray worker successfully registered to spark-5 head (visible in `ray status`).
- Brief PR opened with: inventory diff (before/after), data migration verification, ray-cluster join confirmation.
- Operator approves cluster-join before next phase.

---

## Closing artifact (after both phases)

`docs/operational/spark-3-4-wipe-complete-<DATE>.md` records:

- Final 4-node inference cluster topology.
- Updated `infrastructure.md` DEFCON tier table.
- Phase 4 sizing decision recorded (TP=2 + TP=2 (default) vs TP=4 vs TP=2 + 2× single).
- Updated ADR-003 amendment noting 4-node cluster active.

---

## Cross-references

- ADR-004 (LOCKED 2026-04-29): `docs/architecture/cross-division/ADR-004-app-vs-inference-boundary.md`
- ADR-003 (LOCKED 2026-04-29): `docs/architecture/cross-division/ADR-003-inference-cluster-topology.md` — phased rollout context
- ADR-003 Phase 2 (cable cutover): the Spark-6 cable-land event that gates this wipe
- Iron Dome v6.1: `docs/IRON_DOME_ARCHITECTURE.md` — spark-3 Vision NIM context, spark-4 Qdrant VRS context

End of brief.
