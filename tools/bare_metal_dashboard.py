#!/usr/bin/env python3
"""
FORTRESS PRIME — Bare Metal System Health Dashboard
=====================================================
Real-time 4-node cluster health: GPU, CPU, RAM, Disk, Processes, Services.
Auto-refreshes every 10 seconds via SSE (Server-Sent Events).

Architecture:
    FastAPI backend collects metrics from all 4 DGX Spark nodes via SSH.
    Single-page HTML frontend with live-updating gauges and process tables.
    Runs on port 9876 (replacing any existing dashboard on that port).

Usage:
    cd /home/admin/Fortress-Prime
    ./venv/bin/python tools/bare_metal_dashboard.py

    Open: http://192.168.0.100:9876
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

from fortress_auth import apply_fortress_security, require_auth, get_psql_env

# ─── Configuration ────────────────────────────────────────────────────────────

NODES = {
    "captain":   {"ip": "192.168.0.100", "role": "API Gateway / Swarm Manager",  "local": True},
    "muscle":    {"ip": "192.168.0.104", "role": "Heavy Inference / DGX Worker",  "local": False},
    "ocular":    {"ip": "192.168.0.105", "role": "Inference / Swarm Worker",      "local": False},
    "sovereign": {"ip": "192.168.0.106", "role": "Inference / Swarm Worker",      "local": False},
}

# GB10 unified memory per node (128 GB total, ~128000 MiB)
GPU_TOTAL_MIB = 128 * 1024  # 131072 MiB

SERVICES = {
    "Mission Control": {"url": "http://localhost:8080/api/version",     "port": 8080},
    "Command Center":  {"url": "http://localhost:9800/api/health",      "port": 9800},
    "Nginx Wolfpack":  {"url": "http://localhost/health",               "port": 80},
    "Claude Proxy":    {"url": "http://127.0.0.1:5100/health",         "port": 5100},
    "Qdrant":          {"url": "http://localhost:6333/healthz",         "port": 6333},
    "ChromaDB":        {"url": "http://localhost:8020/api/v2/heartbeat","port": 8020},
    "Prometheus":      {"url": "http://localhost:9090/-/healthy",       "port": 9090},
    "Grafana":         {"url": "http://localhost:3000/api/health",      "port": 3000},
    "Portainer":       {"url": "http://localhost:8888/api/status",      "port": 8888},
    "Legal CRM":       {"url": "http://localhost:9878/api/health",      "port": 9878},
    "Classifier":      {"url": "http://localhost:9877/api/health",      "port": 9877},
    "Guest Platform":  {"url": "http://localhost:8100/health",           "port": 8100},
}

QDRANT_KEY = os.getenv("QDRANT_API_KEY", "")

log = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [DASH] %(message)s")

app = FastAPI(title="Fortress Bare Metal Dashboard")

# Fortress enterprise security: JWT auth, CORS whitelist, rate limiting, security headers
apply_fortress_security(app)

# ─── Metric Collection ────────────────────────────────────────────────────────

def _run(cmd: str, timeout: int = 5) -> str:
    """Run a local shell command."""
    try:
        return subprocess.check_output(cmd, shell=True, timeout=timeout,
                                        stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return ""


def _ssh(ip: str, cmd: str, timeout: int = 5) -> str:
    """Run command on remote node via SSH.
    Uses single quotes to prevent local shell from interpreting $vars."""
    try:
        # Escape any single quotes in the command
        safe_cmd = cmd.replace("'", "'\\''")
        return subprocess.check_output(
            f"ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no -o BatchMode=yes admin@{ip} '{safe_cmd}'",
            shell=True, timeout=timeout, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""


def _collect_node(name: str, info: dict) -> dict:
    """Collect all metrics from a single node."""
    ip = info["ip"]
    is_local = info.get("local", False)
    run = _run if is_local else lambda cmd, t=5: _ssh(ip, cmd, t)

    node = {
        "name": name, "ip": ip, "role": info["role"],
        "online": False, "gpu": {}, "cpu": {}, "ram": {}, "disk": {},
        "processes": [], "docker_containers": [], "ollama_models": [],
    }

    # ── Uptime / Online check ──
    uptime_raw = run("uptime -s")
    if not uptime_raw:
        return node
    node["online"] = True
    node["uptime"] = run("uptime -p")

    # ── CPU ──
    load = run("cat /proc/loadavg")
    if load:
        parts = load.split()
        node["cpu"]["load_1m"] = float(parts[0])
        node["cpu"]["load_5m"] = float(parts[1])
        node["cpu"]["load_15m"] = float(parts[2])
    cpu_count = run("nproc")
    node["cpu"]["cores"] = int(cpu_count) if cpu_count else 0

    # CPU usage per-core summary
    cpu_pct = run("grep 'cpu ' /proc/stat | awk '{u=$2+$4; t=$2+$4+$5; if(t>0) printf \"%.1f\", u*100/t; else print \"0\"}'")
    node["cpu"]["usage_pct"] = float(cpu_pct) if cpu_pct else 0

    # ── RAM ──
    mem = run("free -b | awk '/^Mem:/ {print $2,$3,$4,$7}'")
    if mem:
        parts = mem.split()
        total, used, free_mem, avail = [int(x) for x in parts]
        node["ram"]["total_gb"] = round(total / 1e9, 1)
        node["ram"]["used_gb"] = round(used / 1e9, 1)
        node["ram"]["free_gb"] = round(free_mem / 1e9, 1)
        node["ram"]["avail_gb"] = round(avail / 1e9, 1)
        node["ram"]["pct"] = round(used / total * 100, 1) if total > 0 else 0

    # ── Disk ──
    disk = run("df -B1 / | awk 'NR==2 {print $2,$3,$4,$5}'")
    if disk:
        parts = disk.split()
        total_d, used_d, avail_d = int(parts[0]), int(parts[1]), int(parts[2])
        node["disk"]["total_gb"] = round(total_d / 1e9, 0)
        node["disk"]["used_gb"] = round(used_d / 1e9, 0)
        node["disk"]["avail_gb"] = round(avail_d / 1e9, 0)
        node["disk"]["pct"] = parts[3].replace("%", "")

    # ── GPU (nvidia-smi — full telemetry) ──
    smi = run("nvidia-smi")
    if smi:
        temp_match = re.search(r'(\d+)C', smi)
        node["gpu"]["temp_c"] = int(temp_match.group(1)) if temp_match else 0
        node["gpu"]["total_mib"] = GPU_TOTAL_MIB

        # Power draw (e.g. "14W" or "14.02 W")
        pwr_match = re.search(r'(\d+)W\s*/', smi) or re.search(r'(\d+)W\s', smi)
        node["gpu"]["power_w"] = int(pwr_match.group(1)) if pwr_match else 0

        # P-state
        pstate_match = re.search(r'(P\d+)', smi)
        node["gpu"]["pstate"] = pstate_match.group(1) if pstate_match else "?"

        # GPU VRAM from process table
        vram_matches = re.findall(r'(\d+)MiB \|', smi)
        gpu_used = sum(int(m) for m in vram_matches)
        node["gpu"]["used_mib"] = gpu_used
        node["gpu"]["pct"] = round(gpu_used / GPU_TOTAL_MIB * 100, 1)

        # Detailed GPU query
        gpu_csv = run("nvidia-smi --query-gpu=driver_version,utilization.gpu,clocks.gr,clocks.max.gr --format=csv,noheader,nounits")
        if gpu_csv:
            parts = [p.strip() for p in gpu_csv.split(",")]
            if len(parts) >= 4:
                node["gpu"]["driver"] = parts[0]
                try:
                    node["gpu"]["util_pct"] = int(parts[1])
                except (ValueError, TypeError):
                    node["gpu"]["util_pct"] = 0
                try:
                    node["gpu"]["clock_mhz"] = int(parts[2])
                except (ValueError, TypeError):
                    node["gpu"]["clock_mhz"] = 0
                try:
                    node["gpu"]["clock_max_mhz"] = int(parts[3])
                except (ValueError, TypeError):
                    node["gpu"]["clock_max_mhz"] = 0

        # GPU processes
        gpu_procs = run("nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader")
        for line in gpu_procs.splitlines():
            if line.strip():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    node["gpu"].setdefault("processes", []).append({
                        "pid": parts[0],
                        "name": parts[1].split("/")[-1],
                        "vram_mib": parts[2].replace(" MiB", ""),
                    })

    # ── System thermals (hwmon sensors) ──
    node["thermals"] = {}
    thermal_cmd = (
        "for d in /sys/class/hwmon/hwmon*/; do "
        "n=$(cat ${d}name 2>/dev/null); "
        "t=$(cat ${d}temp1_input 2>/dev/null); "
        "if [ -n \"$t\" ]; then echo \"$n $t\"; fi; "
        "done"
    )
    thermal_out = run(thermal_cmd)
    for line in thermal_out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            sensor_name = parts[0]
            try:
                temp_mc = int(parts[1])
                temp_c = round(temp_mc / 1000, 1)
                # Group: keep first of each type
                if sensor_name not in node["thermals"]:
                    node["thermals"][sensor_name] = temp_c
            except (ValueError, TypeError):
                pass

    # ── NAS mount (Captain only) ──
    if is_local:
        nas = run("df -B1 /mnt/fortress_nas 2>/dev/null | awk 'NR==2 {print $2,$3,$4,$5}'")
        if nas:
            parts = nas.split()
            if len(parts) >= 4:
                node["nas"] = {
                    "total_gb": round(int(parts[0]) / 1e9, 0),
                    "used_gb": round(int(parts[1]) / 1e9, 0),
                    "avail_gb": round(int(parts[2]) / 1e9, 0),
                    "pct": parts[3].replace("%", ""),
                }

    # ── Top processes (by CPU) ──
    ps_out = run("ps aux --sort=-%cpu | head -12")
    for line in ps_out.splitlines()[1:]:  # Skip header
        parts = line.split(None, 10)
        if len(parts) >= 11:
            node["processes"].append({
                "user": parts[0],
                "pid": parts[1],
                "cpu": parts[2],
                "mem": parts[3],
                "vsz_mb": round(int(parts[4]) / 1024, 0),
                "rss_mb": round(int(parts[5]) / 1024, 0),
                "command": parts[10][:80],
            })

    # ── Ollama models (always fetch from Captain — network reachable) ──
    ollama_tags = _run(f"curl -s --connect-timeout 2 http://{ip}:11434/api/tags")
    if ollama_tags:
        try:
            data = json.loads(ollama_tags)
            for m in data.get("models", []):
                node["ollama_models"].append({
                    "name": m["name"],
                    "size_gb": round(m.get("size", 0) / 1e9, 1),
                    "family": m.get("details", {}).get("family", ""),
                    "params": m.get("details", {}).get("parameter_size", ""),
                })
        except json.JSONDecodeError:
            pass

    # ── Docker containers (local only) ──
    if is_local:
        docker_out = run('docker ps --format "{{.Names}}|{{.Status}}|{{.Ports}}" 2>/dev/null')
        for line in docker_out.splitlines():
            parts = line.split("|", 2)
            if len(parts) >= 2:
                node["docker_containers"].append({
                    "name": parts[0],
                    "status": parts[1],
                    "ports": parts[2] if len(parts) > 2 else "",
                })

    return node


def _collect_services() -> list:
    """Check service endpoints."""
    results = []
    for name, info in SERVICES.items():
        try:
            out = subprocess.check_output(
                f'curl -s --connect-timeout 3 -o /dev/null -w "%{{http_code}}" {info["url"]}',
                shell=True, timeout=5, stderr=subprocess.DEVNULL
            ).decode().strip()
            status = "online" if out in ("200", "204") else f"http_{out}"
        except Exception:
            status = "offline"
        results.append({"name": name, "port": info["port"], "status": status})
    return results


def _collect_db_stats() -> dict:
    """Get database statistics."""
    stats = {"postgres": {}, "qdrant": {}}

    # Postgres
    try:
        psql_cmd = get_psql_env()
        out = _run(
            f'{psql_cmd} -t -c '
            '"SELECT \'email_archive\', count(*) FROM email_archive UNION ALL '
            'SELECT \'finance_invoices\', count(*) FROM finance_invoices UNION ALL '
            'SELECT \'market_intel\', count(*) FROM market_intel UNION ALL '
            'SELECT \'model_telemetry\', count(*) FROM model_telemetry UNION ALL '
            'SELECT \'guest_leads\', count(*) FROM guest_leads"',
            timeout=10
        )
        for line in out.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 2 and parts[1].isdigit():
                stats["postgres"][parts[0]] = int(parts[1])
    except Exception:
        pass

    # Qdrant
    headers = f'-H "api-key: {QDRANT_KEY}"' if QDRANT_KEY else ""
    for col in ["email_embeddings", "fortress_knowledge", "legal_library"]:
        try:
            out = _run(f'curl -s {headers} http://localhost:6333/collections/{col}', timeout=5)
            data = json.loads(out)
            stats["qdrant"][col] = {
                "points": data.get("result", {}).get("points_count", 0),
                "status": data.get("result", {}).get("status", "unknown"),
            }
        except Exception:
            stats["qdrant"][col] = {"points": 0, "status": "error"}

    return stats


def collect_all() -> dict:
    """Collect metrics from all sources."""
    t0 = time.time()

    # Collect nodes in parallel using threads
    from concurrent.futures import ThreadPoolExecutor
    nodes = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_collect_node, name, info): name for name, info in NODES.items()}
        for f in futures:
            name = futures[f]
            try:
                nodes[name] = f.result(timeout=15)
            except Exception as e:
                nodes[name] = {"name": name, "online": False, "error": str(e)}

    services = _collect_services()
    db_stats = _collect_db_stats()

    elapsed = time.time() - t0
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "collected_in_ms": round(elapsed * 1000),
        "nodes": nodes,
        "services": services,
        "databases": db_stats,
    }


# ─── API Endpoints ────────────────────────────────────────────────────────────

_dash_start = time.time()

@app.get("/health")
async def health_simple():
    """Lightweight health probe — no SSH, no metrics collection."""
    return {
        "status": "healthy",
        "service": "fortress-bare-metal-dashboard",
        "uptime_seconds": round(time.time() - _dash_start, 1),
    }

@app.get("/api/health")
async def api_health():
    data = collect_all()
    nodes_ok = all(
        n.get("online", False) for n in data.get("nodes", {}).values()
    )
    services_ok = all(
        s.get("status") == "online" for s in data.get("services", [])
    )
    status = "healthy" if (nodes_ok and services_ok) else "degraded"
    return {
        "status": status,
        "service": "fortress-bare-metal-dashboard",
        "uptime_seconds": round(time.time() - _dash_start, 1),
        **data,
    }


@app.get("/api/stream")
async def api_stream(request: Request):
    """SSE endpoint for live metrics."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            data = await asyncio.get_event_loop().run_in_executor(None, collect_all)
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(10)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/logs/{container}")
async def api_logs(container: str, lines: int = 50):
    """Get recent Docker container logs."""
    safe = re.sub(r'[^a-zA-Z0-9_\-.]', '', container)
    out = _run(f'docker logs --tail {min(lines, 200)} {safe} 2>&1', timeout=10)
    return {"container": safe, "lines": out.splitlines()[-min(lines, 200):]}


@app.get("/api/processes/{node}")
async def api_processes(node: str, limit: int = 30):
    """Get full process list from a node."""
    if node not in NODES:
        return {"error": "Unknown node"}
    info = NODES[node]
    run = _run if info.get("local") else lambda cmd, t=10: _ssh(info["ip"], cmd, t)
    out = run(f"ps aux --sort=-%cpu | head -{min(limit+1, 100)}")
    procs = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 10)
        if len(parts) >= 11:
            procs.append({
                "user": parts[0], "pid": parts[1],
                "cpu": parts[2], "mem": parts[3],
                "rss_mb": round(int(parts[5]) / 1024, 0),
                "command": parts[10],
            })
    return {"node": node, "processes": procs}


@app.get("/api/model/{node}/{model_name:path}")
async def api_model_detail(node: str, model_name: str):
    """Get Ollama model details."""
    if node not in NODES:
        return {"error": "Unknown node"}
    ip = NODES[node]["ip"]
    out = _run(f'curl -s --connect-timeout 3 http://{ip}:11434/api/show -d \'{{"name":"{model_name}"}}\'', timeout=10)
    try:
        data = json.loads(out)
        return {
            "node": node, "model": model_name,
            "parameters": data.get("parameters", ""),
            "template": data.get("template", "")[:500],
            "details": data.get("details", {}),
            "size": data.get("size", 0),
            "modelfile": data.get("modelfile", "")[:1000],
        }
    except Exception:
        return {"error": "Failed to fetch model info"}


@app.get("/api/search")
async def api_search(q: str = ""):
    """Search across all nodes: processes, containers, models, services."""
    if not q or len(q) < 2:
        return {"results": []}
    q_lower = q.lower()
    results = []
    data = await asyncio.get_event_loop().run_in_executor(None, collect_all)

    # Search processes
    for node_name, node in data["nodes"].items():
        if not node.get("online"):
            continue
        for p in node.get("processes", []):
            if q_lower in p.get("command", "").lower() or q_lower in p.get("pid", ""):
                results.append({
                    "type": "process", "node": node_name,
                    "pid": p["pid"], "command": p["command"],
                    "cpu": p["cpu"], "mem": p["mem"],
                })
        # Search GPU processes
        for gp in node.get("gpu", {}).get("processes", []):
            if q_lower in gp.get("name", "").lower() or q_lower in gp.get("pid", ""):
                results.append({
                    "type": "gpu_process", "node": node_name,
                    "pid": gp["pid"], "name": gp["name"],
                    "vram_mib": gp["vram_mib"],
                })
        # Search models
        for m in node.get("ollama_models", []):
            if q_lower in m["name"].lower():
                results.append({
                    "type": "model", "node": node_name,
                    "name": m["name"], "size_gb": m["size_gb"],
                    "params": m.get("params", ""),
                })
        # Search containers
        for c in node.get("docker_containers", []):
            if q_lower in c["name"].lower():
                results.append({
                    "type": "container", "node": node_name,
                    "name": c["name"], "status": c["status"],
                })

    # Search services
    for s in data.get("services", []):
        if q_lower in s["name"].lower():
            results.append({"type": "service", "name": s["name"], "port": s["port"], "status": s["status"]})

    # Search DB tables
    for table, count in data.get("databases", {}).get("postgres", {}).items():
        if q_lower in table.lower():
            results.append({"type": "pg_table", "name": table, "rows": count})
    for col, info in data.get("databases", {}).get("qdrant", {}).items():
        if q_lower in col.lower():
            results.append({"type": "qdrant_collection", "name": col, "points": info.get("points", 0)})

    return {"query": q, "count": len(results), "results": results[:50]}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


# ─── HTML Dashboard ───────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fortress Prime</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,100..900;1,14..32,100..900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --f:'Inter',system-ui,-apple-system,sans-serif;
  --mono:'SF Mono',ui-monospace,'Cascadia Code','JetBrains Mono',Menlo,monospace;
  --bg:#000;--s1:#0d0d0d;--s2:#161616;--s3:#1e1e1e;--s4:#272727;
  --tx:#ececec;--tx2:#8e8e93;--tx3:#58585e;
  --brd:rgba(255,255,255,.07);--brd2:rgba(255,255,255,.04);
  --blue:#0a84ff;--green:#30d158;--orange:#ff9f0a;--red:#ff453a;
  --purple:#bf5af2;--teal:#64d2ff;--pink:#ff375f;--yellow:#ffd60a;
  --indigo:#5e5ce6;
  --r-cpu-a:#0a84ff;--r-cpu-b:#5ac8fa;
  --r-ram-a:#30d158;--r-ram-b:#63e6be;
  --r-gpu-a:#bf5af2;--r-gpu-b:#ff6482;
  --r-dsk-a:#ff9f0a;--r-dsk-b:#ffd60a;
}
html{font-size:16px;background:#000}
body{font-family:var(--f);background:var(--bg);color:var(--tx);
  -webkit-font-smoothing:antialiased;line-height:1.4;overflow-x:hidden;
  font-feature-settings:'cv01' 1,'cv02' 1,'ss01' 1}
::selection{background:rgba(10,132,255,.3)}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:3px}
a{color:var(--blue);text-decoration:none}

/* ── CLICKABLE ───────────────────────────────────────────────────── */
.clickable{cursor:pointer;transition:all .15s ease}
.clickable:hover{opacity:.8}
.clickable:active{transform:scale(.98)}
.arrow{display:inline-block;font-size:11px;color:var(--tx3);margin-left:4px;
  transition:transform .15s}
.clickable:hover .arrow{transform:translateX(2px);color:var(--tx2)}

/* ── NAV ─────────────────────────────────────────────────────────── */
/* ── FORTRESS UNIFIED NAV ── */
.fn-bar{background:#0a0a0a;border-bottom:1px solid #1a1a1a;padding:0 16px;
  display:flex;align-items:center;height:36px;font-family:system-ui,-apple-system,sans-serif;
  position:sticky;top:0;z-index:9999;gap:0;flex-shrink:0;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.fn-home{display:flex;align-items:center;gap:6px;color:#fff;text-decoration:none;
  font-weight:700;font-size:12px;letter-spacing:.03em;padding:6px 12px 6px 0;
  border-right:1px solid #222;margin-right:4px;white-space:nowrap;transition:color .15s}
.fn-home:hover{color:#4ade80}
.fn-home svg{opacity:.6}
.fn-links{display:flex;align-items:center;gap:0;overflow-x:auto;scrollbar-width:none;flex:1}
.fn-links::-webkit-scrollbar{display:none}
.fn-link{display:flex;align-items:center;gap:5px;padding:8px 12px;color:#888;
  text-decoration:none;font-size:11px;font-weight:500;white-space:nowrap;
  border-bottom:2px solid transparent;transition:all .15s}
.fn-link:hover{color:#fff;background:rgba(255,255,255,.04)}
.fn-link.fn-active{color:#fff;border-bottom-color:#4ade80}
.fn-link .fn-icon{font-size:13px;opacity:.5}
@media(max-width:768px){.fn-link span:not(.fn-icon){display:none}}

nav{position:sticky;top:36px;z-index:100;height:48px;
  background:rgba(0,0,0,.72);backdrop-filter:saturate(180%) blur(20px);
  -webkit-backdrop-filter:saturate(180%) blur(20px);
  border-bottom:.5px solid var(--brd);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 28px}
nav .brand{font-weight:600;font-size:15px;letter-spacing:-.03em}
nav .right{display:flex;align-items:center;gap:14px}
.live{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--tx2);font-weight:500}
.pulse{width:6px;height:6px;border-radius:50%;background:var(--green);
  animation:pulse 2s ease infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(48,209,88,.4)}
  50%{box-shadow:0 0 0 5px rgba(48,209,88,0)}}
.sbtn{display:flex;align-items:center;gap:7px;padding:5px 12px;border-radius:8px;
  background:var(--s2);border:1px solid var(--brd);color:var(--tx3);cursor:pointer;
  font:12px var(--f);transition:.15s}
.sbtn:hover{border-color:rgba(255,255,255,.14);color:var(--tx2)}
.sbtn kbd{font:10px var(--f);opacity:.35;margin-left:6px}
.ts{font-size:11px;color:var(--tx3);font-variant-numeric:tabular-nums;font-weight:500}

/* ── PAGE ────────────────────────────────────────────────────────── */
.page{max-width:1440px;margin:0 auto;padding:0 28px 80px}

/* ── HERO ────────────────────────────────────────────────────────── */
.hero{padding:52px 0 12px;text-align:center}
.hero h1{font-size:44px;font-weight:700;letter-spacing:-.045em;
  background:linear-gradient(180deg,#fff 20%,rgba(255,255,255,.45) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{color:var(--tx3);font-size:14px;font-weight:400;letter-spacing:-.01em;margin-top:4px}

/* ── KPIs ────────────────────────────────────────────────────────── */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;
  margin:40px 0 56px;border-radius:18px;overflow:hidden;background:var(--brd2)}
.kpi{background:var(--s1);padding:26px 20px;text-align:center;cursor:pointer;
  transition:background .15s}
.kpi:hover{background:var(--s2)}
.kpi .n{font-size:34px;font-weight:700;letter-spacing:-.04em;
  font-variant-numeric:tabular-nums}
.kpi .l{font-size:10px;font-weight:600;text-transform:uppercase;
  letter-spacing:.1em;color:var(--tx3);margin-top:6px}
.kpi .s{font-size:11px;color:var(--tx2);margin-top:2px}
.kpi .arr{font-size:10px;color:var(--tx3);margin-top:8px;opacity:0;transition:.15s}
.kpi:hover .arr{opacity:1}

/* ── SECTION ─────────────────────────────────────────────────────── */
.sh{display:flex;align-items:baseline;justify-content:space-between;
  margin-bottom:18px;padding:0 2px}
.sh h2{font-size:26px;font-weight:700;letter-spacing:-.035em}
.sh .c{font-size:12px;color:var(--tx3);font-weight:500}

/* ── NODE ────────────────────────────────────────────────────────── */
.nodes{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-bottom:60px}
@media(max-width:900px){.nodes{grid-template-columns:1fr}}
.node{background:var(--s1);border-radius:18px;border:1px solid var(--brd);overflow:hidden;
  transition:border-color .15s,transform .15s}
.node:hover{border-color:rgba(255,255,255,.1);transform:translateY(-1px)}
.node.off{opacity:.3}
.ntop{padding:22px 26px 0;display:flex;justify-content:space-between;align-items:flex-start}
.nid .nn{font-size:20px;font-weight:700;letter-spacing:-.02em;text-transform:capitalize}
.nid .nr{font-size:11px;color:var(--tx3);margin-top:1px}
.nb{display:flex;flex-direction:column;align-items:flex-end;gap:4px}
.bd{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  padding:3px 9px;border-radius:100px}
.bd.on{background:rgba(48,209,88,.1);color:var(--green)}
.bd.off{background:rgba(255,69,58,.1);color:var(--red)}
.nip{font-family:var(--mono);font-size:10px;color:var(--tx3)}

/* ── RINGS ───────────────────────────────────────────────────────── */
.rings{display:flex;justify-content:center;gap:28px;padding:24px 16px 20px}
.rw{display:flex;flex-direction:column;align-items:center;gap:8px;cursor:pointer;
  transition:.15s}
.rw:hover{opacity:.85}
.rb{position:relative;width:82px;height:82px}
.rb svg{width:100%;height:100%;transform:rotate(-90deg)}
.rb .bg{fill:none;stroke:var(--s3);stroke-width:5.5}
.rb .fg{fill:none;stroke-width:5.5;stroke-linecap:round;
  transition:stroke-dashoffset .8s cubic-bezier(.4,0,.2,1)}
.rb .in{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center}
.rb .pv{font-size:17px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.rb .av{font-size:8px;color:var(--tx3);font-weight:500}
.rl{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--tx3)}

/* ── GPU BAR ─────────────────────────────────────────────────────── */
.gbar{display:grid;grid-template-columns:repeat(5,1fr);border-top:1px solid var(--brd2)}
.gc{padding:13px 0;text-align:center;border-right:1px solid var(--brd2);
  cursor:pointer;transition:background .12s}
.gc:last-child{border-right:none}
.gc:hover{background:var(--s2)}
.gc .v{font-size:15px;font-weight:700;font-variant-numeric:tabular-nums}
.gc .l{font-size:8px;font-weight:600;text-transform:uppercase;
  letter-spacing:.07em;color:var(--tx3);margin-top:2px}

/* ── NODE DETAILS ────────────────────────────────────────────────── */
.nd{padding:0 26px 18px}
.nds{margin-top:14px}
.ndt{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;
  color:var(--tx3);margin-bottom:8px;padding-top:12px;border-top:1px solid var(--brd2)}
.tags{display:flex;flex-wrap:wrap;gap:5px}
.tag{display:inline-flex;align-items:center;gap:5px;padding:4px 11px;
  border-radius:100px;font-size:11px;font-weight:500;
  background:var(--s2);border:1px solid var(--brd);cursor:pointer;transition:.12s}
.tag:hover{border-color:rgba(255,255,255,.16);background:var(--s3)}
.tag .ind{width:5px;height:5px;border-radius:50%}

/* Thermals */
.thm{display:flex;align-items:center;gap:8px;margin-bottom:5px;cursor:pointer;
  padding:3px 0;border-radius:4px;transition:.12s}
.thm:hover{background:var(--s2);margin:0 -6px;padding:3px 6px;margin-bottom:5px}
.thm .sn{font-family:var(--mono);font-size:10px;color:var(--tx3);width:72px;
  text-align:right;flex-shrink:0}
.thm .tk{flex:1;height:3px;border-radius:2px;background:var(--s3);overflow:hidden}
.thm .fl{height:100%;border-radius:2px;transition:width .5s}
.thm .dg{font-size:10px;font-weight:600;width:38px;text-align:right;
  font-variant-numeric:tabular-nums;flex-shrink:0}

/* Processes */
.pt{width:100%;font-size:11px;border-collapse:collapse}
.pt th{text-align:left;font-size:8px;font-weight:600;text-transform:uppercase;
  letter-spacing:.08em;color:var(--tx3);padding:5px 6px;border-bottom:1px solid var(--brd2)}
.pt td{padding:4px 6px;font-family:var(--mono);font-size:10px;color:var(--tx2);
  border-bottom:1px solid var(--brd2)}
.pt tr:last-child td{border-bottom:none}
.pt tr{cursor:pointer;transition:.12s}
.pt tr:hover td{background:var(--s2)}
.pt .cm{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* ── INFRASTRUCTURE ──────────────────────────────────────────────── */
.infra{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:768px){.infra{grid-template-columns:1fr}}
.panel{background:var(--s1);border-radius:18px;border:1px solid var(--brd);overflow:hidden}
.ph{padding:22px 26px 14px;font-size:16px;font-weight:600;letter-spacing:-.015em}
.pb{padding:0 26px 22px}

.svc{display:flex;align-items:center;justify-content:space-between;
  padding:11px 0;border-bottom:1px solid var(--brd2);cursor:pointer;transition:.12s}
.svc:last-child{border-bottom:none}
.svc:hover{opacity:.75}
.svc .nm{font-size:13px;font-weight:500}
.svc .po{font-family:var(--mono);font-size:10px;color:var(--tx3);margin-left:6px}
.svc .st{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
  padding:3px 9px;border-radius:100px}
.svc .st.on{background:rgba(48,209,88,.08);color:var(--green)}
.svc .st.off{background:rgba(255,69,58,.08);color:var(--red)}
.svc .arr{margin-left:8px}

.dbr{display:flex;align-items:center;padding:10px 0;
  border-bottom:1px solid var(--brd2);cursor:pointer;transition:.12s}
.dbr:last-child{border-bottom:none}
.dbr:hover{opacity:.75}
.dbr .di{width:26px;height:26px;border-radius:7px;display:flex;align-items:center;
  justify-content:center;font-size:11px;font-weight:700;margin-right:10px;flex-shrink:0}
.dbr .di.pg{background:rgba(10,132,255,.1);color:var(--blue)}
.dbr .di.qd{background:rgba(191,90,242,.1);color:var(--purple)}
.dbr .dn{font-size:12px;font-weight:500;flex:1}
.dbr .dc{font-family:var(--mono);font-size:12px;font-weight:600;color:var(--tx2);
  font-variant-numeric:tabular-nums;margin-right:6px}

/* ── SEARCH ──────────────────────────────────────────────────────── */
.sov{position:fixed;inset:0;z-index:500;background:rgba(0,0,0,.55);
  backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
  display:none;align-items:flex-start;justify-content:center;padding-top:16vh}
.sov.open{display:flex}
.scard{background:var(--s1);border:1px solid var(--brd);border-radius:14px;
  width:100%;max-width:560px;box-shadow:0 20px 60px rgba(0,0,0,.5);
  animation:su .2s cubic-bezier(.32,.72,0,1)}
.stop{display:flex;align-items:center;gap:10px;padding:14px 18px;
  border-bottom:1px solid var(--brd2)}
.stop svg{flex-shrink:0;color:var(--tx3)}
.stop input{flex:1;background:none;border:none;outline:none;
  font:15px var(--f);color:var(--tx)}
.stop input::placeholder{color:var(--tx3)}
.sres{max-height:400px;overflow-y:auto;padding:5px}
.sres:empty::after{content:'Search across the entire cluster\2026';
  display:block;padding:24px;text-align:center;color:var(--tx3);font-size:12px}
.sr{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;
  cursor:pointer;transition:.1s}
.sr:hover{background:var(--s2)}
.sri{width:30px;height:30px;border-radius:8px;display:flex;align-items:center;
  justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.sri.process{background:rgba(10,132,255,.1);color:var(--blue)}
.sri.gpu_process{background:rgba(191,90,242,.1);color:var(--purple)}
.sri.model{background:rgba(255,159,10,.1);color:var(--orange)}
.sri.container{background:rgba(100,210,255,.1);color:var(--teal)}
.sri.service{background:rgba(48,209,88,.1);color:var(--green)}
.sri.pg_table{background:rgba(10,132,255,.1);color:var(--blue)}
.sri.qdrant_collection{background:rgba(191,90,242,.1);color:var(--purple)}
.srb{flex:1;min-width:0}
.srb .p{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.srb .s{font-size:10px;color:var(--tx3)}
.srm{font-family:var(--mono);font-size:10px;color:var(--tx3);flex-shrink:0}

/* ── MODAL ───────────────────────────────────────────────────────── */
.mov{position:fixed;inset:0;z-index:400;background:rgba(0,0,0,.5);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  display:none;align-items:center;justify-content:center;padding:32px}
.mov.open{display:flex}
.mcard{background:var(--s1);border:1px solid var(--brd);border-radius:18px;
  width:100%;max-width:720px;max-height:82vh;display:flex;flex-direction:column;
  box-shadow:0 24px 80px rgba(0,0,0,.5);animation:su .22s cubic-bezier(.32,.72,0,1)}
.mh{display:flex;align-items:center;justify-content:space-between;
  padding:18px 24px;border-bottom:1px solid var(--brd2)}
.mh h3{font-size:16px;font-weight:600;letter-spacing:-.02em}
.mx{width:26px;height:26px;border-radius:50%;background:var(--s3);border:none;
  color:var(--tx2);display:flex;align-items:center;justify-content:center;
  cursor:pointer;font-size:14px;transition:.12s}
.mx:hover{background:var(--s4);color:var(--tx)}
.mb{flex:1;overflow-y:auto;padding:18px 24px 24px;-webkit-overflow-scrolling:touch}
.mf{width:100%;padding:9px 13px;border-radius:8px;background:var(--s2);
  border:1px solid var(--brd);font:13px var(--f);color:var(--tx);outline:none;
  margin-bottom:14px;transition:.15s}
.mf:focus{border-color:var(--blue);box-shadow:0 0 0 3px rgba(10,132,255,.15)}
.mf::placeholder{color:var(--tx3)}

/* ── DETAIL GRID (used inside modals) ────────────────────────────── */
.dgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
  gap:2px;border-radius:12px;overflow:hidden;background:var(--brd2);margin-bottom:16px}
.dcell{background:var(--s2);padding:14px 16px}
.dcell .dl{font-size:9px;font-weight:600;text-transform:uppercase;
  letter-spacing:.08em;color:var(--tx3);margin-bottom:4px}
.dcell .dv{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums}

/* mini bar used in drill-downs */
.mbar{height:4px;border-radius:2px;background:var(--s3);overflow:hidden;margin-top:6px}
.mbar .mfill{height:100%;border-radius:2px;transition:width .4s}

@keyframes su{from{opacity:0;transform:scale(.97) translateY(8px)}to{opacity:1;transform:none}}

@media(max-width:720px){
  .kpis{grid-template-columns:repeat(2,1fr)}
  .hero h1{font-size:30px}
  .rings{gap:14px}
  .rb{width:64px;height:64px}
  .rb .pv{font-size:14px}
  .nodes{grid-template-columns:1fr}
}
</style>
</head>
<body>

<!-- ─── FORTRESS UNIFIED NAV ─── -->
<div class="fn-bar">
  <a href="http://192.168.0.100:9800" class="fn-home">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
    FORTRESS PRIME
  </a>
  <div class="fn-links">
    <a href="http://192.168.0.100:9800" class="fn-link"><span class="fn-icon">&#9733;</span><span>Command Center</span></a>
    <a href="http://192.168.0.100:9878" class="fn-link"><span class="fn-icon">&#9878;</span><span>Legal CRM</span></a>
    <a href="http://192.168.0.100:9876" class="fn-link fn-active"><span class="fn-icon">&#9881;</span><span>System Health</span></a>
    <a href="http://192.168.0.100:9877" class="fn-link"><span class="fn-icon">&#9783;</span><span>Classifier</span></a>
    <a href="http://192.168.0.100:3000" class="fn-link"><span class="fn-icon">&#9776;</span><span>Grafana</span></a>
    <a href="http://192.168.0.100:8888" class="fn-link"><span class="fn-icon">&#9638;</span><span>Portainer</span></a>
    <a href="http://192.168.0.100:8080" class="fn-link"><span class="fn-icon">&#9798;</span><span>Mission Control</span></a>
  </div>
</div>

<nav>
  <span class="brand">System Health</span>
  <div class="right">
    <div class="live"><span class="pulse"></span>Live</div>
    <button class="sbtn" onclick="openSearch()">
      <svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
      Search <kbd>&#8984;K</kbd>
    </button>
    <span class="ts" id="ts">--:--:--</span>
  </div>
</nav>

<div class="page">
  <div class="hero">
    <h1>System Health</h1>
    <p>DGX Spark Cluster &mdash; 4 Nodes &middot; 512 GB Unified Memory &middot; GB10 Blackwell</p>
  </div>

  <div class="kpis">
    <div class="kpi clickable" onclick="drillKpi('nodes')"><div class="n" id="kN">--</div><div class="l">Nodes Online</div><div class="arr">View all nodes &rsaquo;</div></div>
    <div class="kpi clickable" onclick="drillKpi('ram')"><div class="n" id="kR">--</div><div class="l">RAM Used</div><div class="s" id="kRs">&nbsp;</div><div class="arr">Per-node breakdown &rsaquo;</div></div>
    <div class="kpi clickable" onclick="drillKpi('vram')"><div class="n" id="kV">--</div><div class="l">GPU VRAM</div><div class="s" id="kVs">&nbsp;</div><div class="arr">Per-node breakdown &rsaquo;</div></div>
    <div class="kpi clickable" onclick="drillKpi('temp')"><div class="n" id="kT">--</div><div class="l">Avg GPU Temp</div><div class="arr">Thermal details &rsaquo;</div></div>
  </div>

  <div class="sh"><h2>Compute</h2><span class="c" id="nc"></span></div>
  <div class="nodes" id="nodesG"></div>

  <div class="sh"><h2>Infrastructure</h2></div>
  <div class="infra">
    <div class="panel"><div class="ph">Services</div><div class="pb" id="svcP"></div></div>
    <div class="panel"><div class="ph">Data Stores</div><div class="pb" id="dbP"></div></div>
  </div>
</div>

<!-- SEARCH -->
<div class="sov" id="sov" onclick="if(event.target===this)closeSearch()">
  <div class="scard">
    <div class="stop">
      <svg width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
      <input id="sin" placeholder="Search processes, models, containers..." autocomplete="off" spellcheck="false"/>
    </div>
    <div class="sres" id="sres"></div>
  </div>
</div>

<!-- MODAL -->
<div class="mov" id="mov" onclick="if(event.target===this)closeModal()">
  <div class="mcard">
    <div class="mh"><h3 id="mt">Details</h3><button class="mx" onclick="closeModal()">&times;</button></div>
    <div class="mb" id="mbd"></div>
  </div>
</div>

<script>
let D=null;
const SVC_LINKS={'Mission Control':'http://192.168.0.100:8080','Grafana':'http://192.168.0.100:3000',
  'Prometheus':'http://192.168.0.100:9090','Qdrant':'http://192.168.0.100:6333/dashboard'};

/* ── SSE ─────────────────────────────────────────────────────────── */
function boot(){const es=new EventSource('/api/stream');
  es.onmessage=e=>{try{D=JSON.parse(e.data);render(D)}catch(x){console.error(x)}};
  es.onerror=()=>{document.getElementById('ts').textContent='reconnecting\u2026';
    setTimeout(()=>{es.close();boot()},5000)};
}
boot();

/* ── Ring SVG ────────────────────────────────────────────────────── */
function ring(pct,g1,g2,id){
  const r=36,c=2*Math.PI*r,off=c*(1-Math.min(pct,100)/100);
  return `<svg viewBox="0 0 82 82"><defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0%" stop-color="${g1}"/><stop offset="100%" stop-color="${g2}"/></linearGradient></defs>
    <circle class="bg" cx="41" cy="41" r="${r}"/><circle class="fg" cx="41" cy="41" r="${r}" stroke="url(#${id})"
    stroke-dasharray="${c}" stroke-dashoffset="${off}"/></svg>`;
}
function tc(t){return t<42?'var(--green)':t<60?'var(--orange)':'var(--red)'}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}

/* ── RENDER ──────────────────────────────────────────────────────── */
function render(d){
  document.getElementById('ts').textContent=new Date(d.timestamp).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const ns=Object.values(d.nodes),on=ns.filter(n=>n.online);
  let tR=0,uR=0,tV=0,uV=0,ts=[],mc=0,cc=0;
  on.forEach(n=>{tR+=n.ram?.total_gb||0;uR+=n.ram?.used_gb||0;
    tV+=(n.gpu?.total_mib||0)/1024;uV+=(n.gpu?.used_mib||0)/1024;
    if(n.gpu?.temp_c)ts.push(n.gpu.temp_c);
    mc+=(n.ollama_models||[]).length;cc+=(n.docker_containers||[]).length});

  document.getElementById('kN').textContent=`${on.length} / ${ns.length}`;
  document.getElementById('kR').textContent=`${Math.round(uR)} GB`;
  document.getElementById('kRs').textContent=`of ${Math.round(tR)} GB total`;
  document.getElementById('kV').textContent=`${Math.round(uV)} GB`;
  document.getElementById('kVs').textContent=`of ${Math.round(tV)} GB unified`;
  const aT=ts.length?Math.round(ts.reduce((a,b)=>a+b,0)/ts.length):0;
  document.getElementById('kT').innerHTML=aT?`${aT}<span style="font-size:18px;font-weight:400;color:var(--tx2)">&deg;C</span>`:'--';
  document.getElementById('nc').textContent=`${on.length} online \u00b7 ${mc} models \u00b7 ${cc} containers \u00b7 ${d.collected_in_ms||'?'}ms`;

  /* NODES */
  const g=document.getElementById('nodesG');g.innerHTML='';
  for(const[name,n]of Object.entries(d.nodes)){
    const el=document.createElement('div');el.className='node'+(n.online?'':' off');
    const cp=n.cpu?.usage_pct||0,rp=n.ram?.pct||0,gp=n.gpu?.pct||0,dp=parseFloat(n.disk?.pct||0);
    const u=name.slice(0,2)+Math.random().toString(36).slice(2,5);
    let h=`<div class="ntop"><div class="nid">
      <div class="nn clickable" onclick="showProcesses('${name}')">${name} <span class="arrow">&rsaquo;</span></div>
      <div class="nr">${n.role||''}</div></div>
      <div class="nb"><span class="bd ${n.online?'on':'off'}">${n.online?'Online':'Offline'}</span>
      <span class="nip">${n.ip}</span></div></div>`;
    if(!n.online){el.innerHTML=h;g.appendChild(el);continue}

    const rU=n.ram?.used_gb||0,rT=n.ram?.total_gb||0;
    const gU=Math.round((n.gpu?.used_mib||0)/1024),gT=Math.round((n.gpu?.total_mib||0)/1024);
    const dU=n.disk?.used_gb||0,dT=n.disk?.total_gb||0;

    h+=`<div class="rings">
      <div class="rw clickable" onclick="drillRing('${name}','cpu')"><div class="rb">${ring(cp,'var(--r-cpu-a)','var(--r-cpu-b)','c'+u)}
        <div class="in"><span class="pv">${Math.round(cp)}%</span><span class="av">${n.cpu?.cores||0} cores</span></div></div><div class="rl">CPU</div></div>
      <div class="rw clickable" onclick="drillRing('${name}','ram')"><div class="rb">${ring(rp,'var(--r-ram-a)','var(--r-ram-b)','r'+u)}
        <div class="in"><span class="pv">${Math.round(rp)}%</span><span class="av">${rU}/${rT}G</span></div></div><div class="rl">Memory</div></div>
      <div class="rw clickable" onclick="drillRing('${name}','gpu')"><div class="rb">${ring(gp,'var(--r-gpu-a)','var(--r-gpu-b)','g'+u)}
        <div class="in"><span class="pv">${Math.round(gp)}%</span><span class="av">${gU}/${gT}G</span></div></div><div class="rl">GPU</div></div>
      <div class="rw clickable" onclick="drillRing('${name}','disk')"><div class="rb">${ring(dp,'var(--r-dsk-a)','var(--r-dsk-b)','d'+u)}
        <div class="in"><span class="pv">${Math.round(dp)}%</span><span class="av">${dU}/${dT}G</span></div></div><div class="rl">Disk</div></div>
    </div>`;

    const gd=n.gpu||{};
    h+=`<div class="gbar">
      <div class="gc clickable" onclick="drillGpu('${name}','temp')"><div class="v" style="color:${tc(gd.temp_c||0)}">${gd.temp_c||'--'}&deg;</div><div class="l">Temp</div></div>
      <div class="gc clickable" onclick="drillGpu('${name}','power')"><div class="v">${gd.power_w||'--'}W</div><div class="l">Power</div></div>
      <div class="gc clickable" onclick="drillGpu('${name}','clock')"><div class="v">${gd.clock_mhz||'--'}</div><div class="l">MHz</div></div>
      <div class="gc clickable" onclick="drillGpu('${name}','pstate')"><div class="v">${gd.pstate||'?'}</div><div class="l">P-State</div></div>
      <div class="gc clickable" onclick="drillGpu('${name}','driver')"><div class="v">${gd.driver||'--'}</div><div class="l">Driver</div></div>
    </div>`;

    h+='<div class="nd">';
    if(n.ollama_models?.length){
      h+=`<div class="nds"><div class="ndt">Models</div><div class="tags">`;
      n.ollama_models.forEach(m=>{h+=`<span class="tag" onclick="event.stopPropagation();showModel('${name}','${m.name}')">
        <span class="ind" style="background:var(--orange)"></span>${m.name}
        <span style="color:var(--tx3);font-size:9px">${m.params||''}</span>
        <span class="arrow">&rsaquo;</span></span>`});
      h+='</div></div>'}

    if(n.docker_containers?.length){
      h+=`<div class="nds"><div class="ndt">Containers</div><div class="tags">`;
      n.docker_containers.forEach(c=>{const up=c.status.toLowerCase().includes('up');
        h+=`<span class="tag" onclick="event.stopPropagation();showLogs('${c.name}')">
        <span class="ind" style="background:${up?'var(--green)':'var(--red)'}"></span>${c.name}
        <span class="arrow">&rsaquo;</span></span>`});
      h+='</div></div>'}

    const th=n.thermals||{},tks=Object.keys(th);
    if(tks.length){
      h+=`<div class="nds"><div class="ndt">Thermals</div>`;
      tks.forEach(k=>{const v=th[k],pct=Math.min(v/105*100,100);
        h+=`<div class="thm" onclick="event.stopPropagation();drillThermal('${name}','${k}')">
          <span class="sn">${k}</span><div class="tk"><div class="fl" style="width:${pct}%;background:${tc(v)}"></div></div>
          <span class="dg" style="color:${tc(v)}">${v}&deg;</span></div>`});
      h+='</div>'}

    if(n.processes?.length){
      h+=`<div class="nds"><div class="ndt">Top Processes</div>
        <table class="pt"><thead><tr><th>PID</th><th>CPU</th><th>MEM</th><th>Command</th></tr></thead><tbody>`;
      n.processes.slice(0,5).forEach(p=>{
        h+=`<tr onclick="event.stopPropagation();showProcesses('${name}')">
          <td>${p.pid}</td><td>${p.cpu}%</td><td>${p.mem}%</td><td class="cm">${esc(p.command)}</td></tr>`});
      h+='</tbody></table></div>'}
    h+='</div>';
    el.innerHTML=h;g.appendChild(el);
  }

  /* SERVICES */
  const sp=document.getElementById('svcP');sp.innerHTML='';
  (d.services||[]).forEach(s=>{const ok=s.status==='online',lk=SVC_LINKS[s.name];
    sp.innerHTML+=`<div class="svc" onclick="drillService('${s.name}',${s.port},'${s.status}')">
      <div><span class="nm">${s.name}</span><span class="po">:${s.port}</span></div>
      <div><span class="st ${ok?'on':'off'}">${ok?'Operational':s.status}</span><span class="arrow">&rsaquo;</span></div></div>`});

  /* DATABASES */
  const dp=document.getElementById('dbP');dp.innerHTML='';
  Object.entries(d.databases?.postgres||{}).forEach(([t,c])=>{
    dp.innerHTML+=`<div class="dbr clickable" onclick="drillDb('postgres','${t}',${c})">
      <div class="di pg">P</div><span class="dn">${t}</span><span class="dc">${c.toLocaleString()}</span><span class="arrow">&rsaquo;</span></div>`});
  Object.entries(d.databases?.qdrant||{}).forEach(([col,info])=>{
    dp.innerHTML+=`<div class="dbr clickable" onclick="drillDb('qdrant','${col}',${info.points||0})">
      <div class="di qd">Q</div><span class="dn">${col}</span><span class="dc">${(info.points||0).toLocaleString()} pts</span><span class="arrow">&rsaquo;</span></div>`});
}

/* ── SEARCH ──────────────────────────────────────────────────────── */
let sTimer;
function openSearch(){document.getElementById('sov').classList.add('open');
  const i=document.getElementById('sin');i.value='';i.focus();document.getElementById('sres').innerHTML=''}
function closeSearch(){document.getElementById('sov').classList.remove('open')}
document.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='k'){e.preventDefault();openSearch()}
  if(e.key==='Escape'){closeSearch();closeModal()}});
document.getElementById('sin').addEventListener('input',e=>{
  clearTimeout(sTimer);const q=e.target.value.trim();
  if(q.length<2){document.getElementById('sres').innerHTML='';return}
  sTimer=setTimeout(()=>doSearch(q),180)});
async function doSearch(q){try{
  const r=await fetch(`/api/search?q=${encodeURIComponent(q)}`),data=await r.json();
  const box=document.getElementById('sres');
  if(!data.results?.length){box.innerHTML='<div style="padding:24px;text-align:center;color:var(--tx3);font-size:12px">No results</div>';return}
  const ic={process:'P',gpu_process:'G',model:'M',container:'C',service:'S',pg_table:'DB',qdrant_collection:'Q'};
  const lb={process:'Process',gpu_process:'GPU Process',model:'Model',container:'Container',service:'Service',pg_table:'Postgres',qdrant_collection:'Qdrant'};
  box.innerHTML=data.results.map(i=>{let pri=i.name||i.command||'',sec=`${lb[i.type]||i.type}${i.node?' \u00b7 '+i.node:''}`;
    let meta=i.pid||(i.rows!=null?i.rows.toLocaleString():'')||(i.points!=null?i.points.toLocaleString()+' pts':'')||(i.size_gb?i.size_gb+'GB':'')||'';
    return `<div class="sr" onclick="searchAct('${i.type}','${i.node||''}','${esc(pri)}')">
      <div class="sri ${i.type}">${ic[i.type]||'?'}</div>
      <div class="srb"><div class="p">${esc(pri)}</div><div class="s">${sec}</div></div>
      <div class="srm">${meta}</div></div>`}).join('')}catch(x){console.error(x)}}
function searchAct(type,node,name){closeSearch();
  if(type==='process'||type==='gpu_process')showProcesses(node);
  else if(type==='model')showModel(node,name);
  else if(type==='container')showLogs(name);
  else if(type==='service')drillService(name,0,'');
  else if(type==='pg_table')drillDb('postgres',name,0);
  else if(type==='qdrant_collection')drillDb('qdrant',name,0)}

/* ── MODAL ───────────────────────────────────────────────────────── */
function openModal(t,html){document.getElementById('mt').textContent=t;
  document.getElementById('mbd').innerHTML=html;document.getElementById('mov').classList.add('open')}
function closeModal(){document.getElementById('mov').classList.remove('open')}

/* ── KPI DRILL-DOWNS ─────────────────────────────────────────────── */
function drillKpi(type){
  if(!D)return;const ns=Object.entries(D.nodes);let h='<div class="dgrid">';
  if(type==='nodes'){
    ns.forEach(([name,n])=>{h+=`<div class="dcell clickable" onclick="showProcesses('${name}')">
      <div class="dl">${name}</div><div class="dv" style="color:${n.online?'var(--green)':'var(--red)'}">
      ${n.online?'Online':'Offline'}</div>
      ${n.online?`<div style="font-size:10px;color:var(--tx3);margin-top:4px">${n.uptime||''}</div>
      <div style="font-size:10px;color:var(--tx3)">${n.ip}</div>`:''}
      </div>`});
    h+='</div>';openModal('All Nodes',h)}
  else if(type==='ram'){
    ns.forEach(([name,n])=>{if(!n.online)return;const r=n.ram||{};const pct=r.pct||0;
      h+=`<div class="dcell clickable" onclick="drillRing('${name}','ram')">
        <div class="dl">${name}</div><div class="dv">${r.used_gb||0} GB</div>
        <div style="font-size:10px;color:var(--tx3)">of ${r.total_gb||0} GB &middot; ${Math.round(pct)}%</div>
        <div class="mbar"><div class="mfill" style="width:${pct}%;background:var(--green)"></div></div></div>`});
    h+='</div>';openModal('RAM per Node',h)}
  else if(type==='vram'){
    ns.forEach(([name,n])=>{if(!n.online)return;const g=n.gpu||{};
      const used=Math.round((g.used_mib||0)/1024),tot=Math.round((g.total_mib||0)/1024),pct=g.pct||0;
      h+=`<div class="dcell clickable" onclick="drillRing('${name}','gpu')">
        <div class="dl">${name}</div><div class="dv">${used} GB</div>
        <div style="font-size:10px;color:var(--tx3)">of ${tot} GB &middot; ${Math.round(pct)}%</div>
        <div class="mbar"><div class="mfill" style="width:${pct}%;background:var(--purple)"></div></div></div>`});
    h+='</div>';openModal('VRAM per Node',h)}
  else if(type==='temp'){
    ns.forEach(([name,n])=>{if(!n.online)return;const t=n.gpu?.temp_c||0;
      h+=`<div class="dcell clickable" onclick="drillGpu('${name}','temp')">
        <div class="dl">${name}</div><div class="dv" style="color:${tc(t)}">${t}&deg;C</div>
        <div style="font-size:10px;color:var(--tx3)">${n.gpu?.power_w||0}W &middot; ${n.gpu?.pstate||'?'}</div>
        <div class="mbar"><div class="mfill" style="width:${Math.min(t/100*100,100)}%;background:${tc(t)}"></div></div></div>`});
    h+='</div>';openModal('GPU Temperatures',h)}
}

/* ── RING DRILL-DOWN ─────────────────────────────────────────────── */
function drillRing(name,type){
  if(!D)return;const n=D.nodes[name];if(!n)return;
  let h='<div class="dgrid">';
  if(type==='cpu'){const c=n.cpu||{};
    h+=`<div class="dcell"><div class="dl">Usage</div><div class="dv">${c.usage_pct||0}%</div></div>
      <div class="dcell"><div class="dl">Cores</div><div class="dv">${c.cores||0}</div></div>
      <div class="dcell"><div class="dl">Load 1m</div><div class="dv">${c.load_1m||0}</div></div>
      <div class="dcell"><div class="dl">Load 5m</div><div class="dv">${c.load_5m||0}</div></div>
      <div class="dcell"><div class="dl">Load 15m</div><div class="dv">${c.load_15m||0}</div></div>`;
    h+='</div>';h+=`<div style="margin-top:12px"><a href="javascript:void(0)" onclick="showProcesses('${name}')" style="font-size:13px;font-weight:500">View all processes &rsaquo;</a></div>`;
    openModal(`${name} \u2014 CPU`,h)}
  else if(type==='ram'){const r=n.ram||{};
    h+=`<div class="dcell"><div class="dl">Used</div><div class="dv">${r.used_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Free</div><div class="dv">${r.free_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Available</div><div class="dv">${r.avail_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Total</div><div class="dv">${r.total_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Usage</div><div class="dv">${r.pct||0}%</div>
      <div class="mbar"><div class="mfill" style="width:${r.pct||0}%;background:var(--green)"></div></div></div>`;
    h+='</div>';openModal(`${name} \u2014 Memory`,h)}
  else if(type==='gpu'){const gd=n.gpu||{};
    const used=Math.round((gd.used_mib||0)/1024),tot=Math.round((gd.total_mib||0)/1024);
    h+=`<div class="dcell"><div class="dl">VRAM Used</div><div class="dv">${used} GB</div></div>
      <div class="dcell"><div class="dl">VRAM Total</div><div class="dv">${tot} GB</div></div>
      <div class="dcell"><div class="dl">Temp</div><div class="dv" style="color:${tc(gd.temp_c||0)}">${gd.temp_c||0}&deg;C</div></div>
      <div class="dcell"><div class="dl">Power</div><div class="dv">${gd.power_w||0}W</div></div>
      <div class="dcell"><div class="dl">Clock</div><div class="dv">${gd.clock_mhz||0} MHz</div></div>
      <div class="dcell"><div class="dl">Max Clock</div><div class="dv">${gd.clock_max_mhz||0} MHz</div></div>
      <div class="dcell"><div class="dl">P-State</div><div class="dv">${gd.pstate||'?'}</div></div>
      <div class="dcell"><div class="dl">Driver</div><div class="dv">${gd.driver||'--'}</div></div>`;
    h+='</div>';
    const procs=gd.processes||[];
    if(procs.length){h+=`<div style="margin-top:8px;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--tx3);margin-bottom:8px">GPU Processes</div>
      <table class="pt"><thead><tr><th>PID</th><th>Process</th><th>VRAM</th></tr></thead><tbody>`;
      procs.forEach(p=>{h+=`<tr><td>${p.pid}</td><td>${esc(p.name)}</td><td>${p.vram_mib} MiB</td></tr>`});
      h+='</tbody></table>'}
    openModal(`${name} \u2014 GPU`,h)}
  else if(type==='disk'){const dk=n.disk||{},nas=n.nas;
    h+=`<div class="dcell"><div class="dl">Used</div><div class="dv">${dk.used_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Available</div><div class="dv">${dk.avail_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Total</div><div class="dv">${dk.total_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">Usage</div><div class="dv">${dk.pct||0}%</div>
      <div class="mbar"><div class="mfill" style="width:${parseFloat(dk.pct||0)}%;background:var(--orange)"></div></div></div>`;
    if(nas){h+=`<div class="dcell"><div class="dl">NAS Used</div><div class="dv">${nas.used_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">NAS Total</div><div class="dv">${nas.total_gb||0} GB</div></div>
      <div class="dcell"><div class="dl">NAS Usage</div><div class="dv">${nas.pct||0}%</div>
      <div class="mbar"><div class="mfill" style="width:${parseFloat(nas.pct||0)}%;background:var(--teal)"></div></div></div>`}
    h+='</div>';openModal(`${name} \u2014 Storage`,h)}
}

/* ── GPU CELL DRILL-DOWN ─────────────────────────────────────────── */
function drillGpu(name,metric){
  if(!D)return;const n=D.nodes[name];if(!n||!n.gpu)return;const g=n.gpu;
  let h='<div class="dgrid">';
  if(metric==='temp'){
    h+=`<div class="dcell"><div class="dl">GPU Temp</div><div class="dv" style="color:${tc(g.temp_c||0)}">${g.temp_c||0}&deg;C</div></div>`;
    const th=n.thermals||{};Object.entries(th).forEach(([k,v])=>{
      h+=`<div class="dcell"><div class="dl">${k}</div><div class="dv" style="color:${tc(v)}">${v}&deg;C</div>
        <div class="mbar"><div class="mfill" style="width:${Math.min(v/100*100,100)}%;background:${tc(v)}"></div></div></div>`});
    h+='</div>';openModal(`${name} \u2014 Thermal Map`,h)}
  else if(metric==='power'){
    h+=`<div class="dcell"><div class="dl">Current</div><div class="dv">${g.power_w||0}W</div></div>
      <div class="dcell"><div class="dl">P-State</div><div class="dv">${g.pstate||'?'}</div></div>
      <div class="dcell"><div class="dl">Clock</div><div class="dv">${g.clock_mhz||0} MHz</div></div>`;
    h+='</div>';openModal(`${name} \u2014 Power`,h)}
  else if(metric==='clock'){
    h+=`<div class="dcell"><div class="dl">Current</div><div class="dv">${g.clock_mhz||0} MHz</div></div>
      <div class="dcell"><div class="dl">Maximum</div><div class="dv">${g.clock_max_mhz||0} MHz</div></div>
      <div class="dcell"><div class="dl">Utilization</div><div class="dv">${g.util_pct||0}%</div></div>`;
    h+='</div>';openModal(`${name} \u2014 Clock`,h)}
  else if(metric==='pstate'){
    h+=`<div class="dcell"><div class="dl">State</div><div class="dv">${g.pstate||'?'}</div></div>
      <div class="dcell"><div class="dl">Power</div><div class="dv">${g.power_w||0}W</div></div>
      <div class="dcell"><div class="dl">Utilization</div><div class="dv">${g.util_pct||0}%</div></div>`;
    h+='</div>';
    const procs=g.processes||[];
    if(procs.length){h+=`<div style="margin-top:8px;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--tx3);margin-bottom:8px">GPU Processes</div>
      <table class="pt"><thead><tr><th>PID</th><th>Process</th><th>VRAM</th></tr></thead><tbody>`;
      procs.forEach(p=>{h+=`<tr><td>${p.pid}</td><td>${esc(p.name)}</td><td>${p.vram_mib} MiB</td></tr>`});
      h+='</tbody></table>'}
    openModal(`${name} \u2014 P-State`,h)}
  else if(metric==='driver'){
    h+=`<div class="dcell"><div class="dl">Driver</div><div class="dv">${g.driver||'--'}</div></div>
      <div class="dcell"><div class="dl">GPU</div><div class="dv">GB10 Blackwell</div></div>
      <div class="dcell"><div class="dl">VRAM</div><div class="dv">128 GB Unified</div></div>
      <div class="dcell"><div class="dl">Architecture</div><div class="dv">Blackwell</div></div>`;
    h+='</div>';openModal(`${name} \u2014 GPU Info`,h)}
}

/* ── THERMAL DRILL-DOWN ──────────────────────────────────────────── */
function drillThermal(name,sensor){
  if(!D)return;const n=D.nodes[name];if(!n)return;const th=n.thermals||{};
  let h=`<div class="dgrid">`;
  Object.entries(th).forEach(([k,v])=>{const hi=k===sensor;
    h+=`<div class="dcell" style="${hi?'border:1px solid var(--blue);border-radius:10px':''}">
      <div class="dl">${k}</div><div class="dv" style="color:${tc(v)}">${v}&deg;C</div>
      <div class="mbar"><div class="mfill" style="width:${Math.min(v/100*100,100)}%;background:${tc(v)}"></div></div></div>`});
  h+=`</div>`;
  if(n.gpu?.temp_c){h+=`<div style="margin-top:12px;padding:14px 16px;background:var(--s2);border-radius:10px">
    <div style="font-size:10px;color:var(--tx3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">GPU</div>
    <div style="font-size:20px;font-weight:700;color:${tc(n.gpu.temp_c)}">${n.gpu.temp_c}&deg;C</div></div>`}
  openModal(`${name} \u2014 Thermals`,h)}

/* ── SERVICE DRILL-DOWN ──────────────────────────────────────────── */
function drillService(name,port,status){
  if(!D)return;
  const svc=D.services?.find(s=>s.name===name)||{name,port,status};
  const lk=SVC_LINKS[name];const ok=svc.status==='online';
  let h=`<div class="dgrid">
    <div class="dcell"><div class="dl">Service</div><div class="dv">${svc.name}</div></div>
    <div class="dcell"><div class="dl">Port</div><div class="dv">${svc.port}</div></div>
    <div class="dcell"><div class="dl">Status</div><div class="dv" style="color:${ok?'var(--green)':'var(--red)'}">${ok?'Operational':svc.status}</div></div>
  </div>`;
  if(lk){h+=`<a href="${lk}" target="_blank" style="display:inline-flex;align-items:center;gap:6px;
    padding:10px 18px;background:var(--blue);color:#fff;border-radius:10px;font-size:13px;font-weight:600;
    margin-top:8px;transition:.15s;text-decoration:none">Open ${name} &rsaquo;</a>`}
  openModal(name,h)}

/* ── DB DRILL-DOWN ───────────────────────────────────────────────── */
function drillDb(engine,name,count){
  let h=`<div class="dgrid">
    <div class="dcell"><div class="dl">Engine</div><div class="dv">${engine==='postgres'?'PostgreSQL':'Qdrant'}</div></div>
    <div class="dcell"><div class="dl">${engine==='postgres'?'Table':'Collection'}</div><div class="dv">${name}</div></div>
    <div class="dcell"><div class="dl">${engine==='postgres'?'Rows':'Points'}</div><div class="dv">${count.toLocaleString()}</div></div>
    <div class="dcell"><div class="dl">Database</div><div class="dv">${engine==='postgres'?'fortress_db':'localhost:6333'}</div></div>
  </div>`;
  if(engine==='postgres'){h+=`<div style="margin-top:12px;padding:14px;background:var(--s2);border-radius:10px">
    <div style="font-size:10px;color:var(--tx3);margin-bottom:6px">QUERY</div>
    <code style="font:11px var(--mono);color:var(--tx2)">SELECT count(*) FROM ${name};</code></div>`}
  else{const info=D?.databases?.qdrant?.[name]||{};
    h+=`<div style="margin-top:12px;padding:14px;background:var(--s2);border-radius:10px">
    <div style="font-size:10px;color:var(--tx3);margin-bottom:6px">STATUS</div>
    <div style="font-size:14px;font-weight:600;color:${info.status==='green'?'var(--green)':'var(--orange)'}">${info.status||'unknown'}</div></div>`}
  openModal(name,h)}

/* ── PROCESS / MODEL / LOG MODALS ────────────────────────────────── */
async function showProcesses(node){
  openModal(`${node} \u2014 Processes`,'<div style="text-align:center;padding:24px;color:var(--tx3)">Loading\u2026</div>');
  try{const r=await fetch(`/api/processes/${node}?limit=50`),data=await r.json();
    let h=`<input class="mf" placeholder="Filter processes\u2026" oninput="filt(this.value,'mpt')"/>`;
    h+=`<table class="pt" id="mpt"><thead><tr><th>PID</th><th>User</th><th>CPU%</th><th>MEM%</th><th>RSS</th><th>Command</th></tr></thead><tbody>`;
    (data.processes||[]).forEach(p=>{h+=`<tr><td>${p.pid}</td><td>${p.user}</td><td>${p.cpu}</td><td>${p.mem}</td><td>${p.rss_mb}M</td><td class="cm" style="max-width:300px">${esc(p.command)}</td></tr>`});
    h+='</tbody></table>';document.getElementById('mbd').innerHTML=h;
  }catch(x){document.getElementById('mbd').innerHTML=`<div style="color:var(--red);padding:20px">${x.message}</div>`}}

async function showModel(node,model){
  openModal(model,'<div style="text-align:center;padding:24px;color:var(--tx3)">Loading\u2026</div>');
  try{const r=await fetch(`/api/model/${node}/${model}`),data=await r.json();
    let h=`<div class="dgrid">`;
    h+=`<div class="dcell"><div class="dl">Node</div><div class="dv">${node}</div></div>`;
    h+=`<div class="dcell"><div class="dl">Size</div><div class="dv">${data.size?(data.size/1e9).toFixed(1)+' GB':'N/A'}</div></div>`;
    if(data.details)Object.entries(data.details).forEach(([k,v])=>{
      h+=`<div class="dcell"><div class="dl">${k}</div><div class="dv" style="font-size:13px">${v}</div></div>`});
    h+='</div>';
    if(data.parameters)h+=`<div style="margin-top:8px;font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--tx3);margin-bottom:6px">Parameters</div>
      <pre style="background:var(--s2);padding:14px;border-radius:10px;font:11px var(--mono);color:var(--tx2);overflow-x:auto;white-space:pre-wrap">${esc(data.parameters)}</pre>`;
    document.getElementById('mbd').innerHTML=h;
  }catch(x){document.getElementById('mbd').innerHTML=`<div style="color:var(--red);padding:20px">${x.message}</div>`}}

async function showLogs(container){
  openModal(`${container} \u2014 Logs`,'<div style="text-align:center;padding:24px;color:var(--tx3)">Loading\u2026</div>');
  try{const r=await fetch(`/api/logs/${container}?lines=100`),data=await r.json();
    let h=`<input class="mf" placeholder="Filter logs\u2026" oninput="filtL(this.value)"/>`;
    h+=`<div id="ll" style="font:10px/1.8 var(--mono);color:var(--tx2)">`;
    (data.lines||[]).forEach(l=>{h+=`<div class="lln" style="padding:1px 0;border-bottom:1px solid var(--brd2)">${esc(l)}</div>`});
    h+='</div>';document.getElementById('mbd').innerHTML=h;
  }catch(x){document.getElementById('mbd').innerHTML=`<div style="color:var(--red);padding:20px">${x.message}</div>`}}

function filt(q,id){document.querySelectorAll(`#${id} tbody tr`).forEach(r=>{
  r.style.display=r.textContent.toLowerCase().includes(q.toLowerCase())?'':'none'})}
function filtL(q){document.querySelectorAll('#ll .lln').forEach(l=>{
  l.style.display=l.textContent.toLowerCase().includes(q.toLowerCase())?'':'none'})}
</script>
</body>
</html>
"""


# ─── Lifecycle ────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup():
    log.info("Bare Metal Dashboard ready")


@app.on_event("shutdown")
async def _shutdown():
    log.info("Bare Metal Dashboard — clean shutdown")


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("  FORTRESS PRIME — Bare Metal Dashboard")
    log.info("  http://192.168.0.100:9876")
    log.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=9876, log_level="warning")
