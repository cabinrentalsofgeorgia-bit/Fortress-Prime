# SPARK3 Shared GPU Runbook

**Node:** spark-3 (192.168.0.105, label "Ocular")
**Role:** Vision specialist (llama3.2-vision:90b primary). Shared with Financial GPU workloads under marker-file gating.

---

## Overview

spark-3 hosts a single physical GPU. Vision inference (Ollama) and Financial batch GPU jobs share this resource. To prevent contention, all GPU jobs source a guard script before starting. The guard writes a named marker file and refuses to run if the opposing marker is present.

---

## Guard scripts

Located at `/mnt/fortress_nas/spark3/`:

| Script | Marker written | Blocks if present |
|---|---|---|
| `vision_guard.sh` | `VISION_BUSY` | `FINANCIAL_BUSY` |
| `financial_guard.sh` | `FINANCIAL_BUSY` | `VISION_BUSY` |
| `janitor_stale_markers.sh` | — | — |

### Usage

Source at the top of any spark-3 GPU job **before** allocating GPU memory:

```bash
# In a vision job running on spark-3:
source /mnt/fortress_nas/spark3/vision_guard.sh
# ... rest of the job

# In a financial GPU job (run via nrun_gpu or direct ssh to spark-3):
source /mnt/fortress_nas/spark3/financial_guard.sh
# ... rest of the job
```

If the opposing marker is present, the guard logs "DEFERRED" to `gating.log` and exits non-zero. The calling script should propagate this exit code so the operator sees the deferral clearly.

### Marker format

Each marker file contains a single line: `<PID> <ISO-timestamp>`

Example: `1234567 2026-04-21T08:30:00Z`

### Cleanup

Guards register `trap 'rm -f $MARKER' EXIT INT TERM` — the marker is removed on normal exit, SIGINT (Ctrl-C), or SIGTERM. This handles most crash paths as long as the parent shell is alive. If the process is killed with SIGKILL, the marker persists and the janitor will flag it.

---

## Janitor

`janitor_stale_markers.sh` scans for markers older than 12 hours. It logs a warning but **does NOT auto-delete** — an operator must decide whether the job legitimately ran long or the marker is orphaned.

**Cron (spark-2, 4am daily):**
```
0 4 * * * bash /mnt/fortress_nas/spark3/janitor_stale_markers.sh >> /mnt/fortress_nas/spark3/gating.log 2>&1
```

**Notification:** Set `NTFY_TOPIC=<your-topic>` in the cron environment to receive push notifications via ntfy.sh when stale markers are found.

**Manual check:**
```bash
ls -la /mnt/fortress_nas/spark3/
cat /mnt/fortress_nas/spark3/gating.log | tail -20
```

**Manual marker removal** (after verifying the holding process is dead):
```bash
rm /mnt/fortress_nas/spark3/VISION_BUSY      # or FINANCIAL_BUSY
```

---

## Routing context (Iron Dome v6)

The Ollama model registry routes vision inference to spark-3 via `tier_routing.vision: ["spark-3", "spark-1"]`. The vision tier uses llama3.2-vision:90b. This Ollama traffic is managed by the model_registry probe and does not use the guard scripts.

The guard scripts are for **manual or batch GPU jobs** (e.g. financial ML inference, embedding generation) that allocate GPU memory directly outside of Ollama. These are the workloads that would conflict with active vision inference.

---

## Incident response

1. Check if a guard process is still running: `pgrep -a -f "financial_guard\|vision_guard"`
2. Check gating.log for recent ACQUIRED/RELEASED events
3. If marker is orphaned (process dead), remove manually and note in the log
4. If contention caused an OOM, check `dmesg | grep -i oom` on spark-3
