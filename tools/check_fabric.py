#!/usr/bin/env python3
"""
FORTRESS PRIME — Cluster Health Verification
==============================================
Checks GPU, fabric network, Docker services, and all critical services
across all 4 DGX Spark nodes.

Usage:
    ./venv/bin/python tools/check_fabric.py          # Full check
    ./venv/bin/python tools/check_fabric.py --quick   # Fast ping-only
    ./venv/bin/python tools/check_fabric.py --json    # Machine-readable output
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FABRIC_NODES, SPARK_01_IP

SERVICES = {
    "Postgres":   {"host": "localhost", "port": 5432},
    "Qdrant":     {"host": "localhost", "port": 6333},
    "Redis":      {"host": "localhost", "port": 6379},
    "Ollama":     {"host": "localhost", "port": 11434},
    "Nginx LB":   {"host": "localhost", "port": 80},
    "Grafana":    {"host": "localhost", "port": 3000},
    "Prometheus": {"host": "localhost", "port": 9090},
    "Loki":       {"host": "localhost", "port": 3100},
}


def _run(cmd: str, timeout: int = 5) -> str:
    try:
        return subprocess.check_output(
            cmd, shell=True, timeout=timeout, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return ""


def _ssh(ip: str, cmd: str, timeout: int = 5) -> str:
    return _run(
        f"ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no "
        f"-o BatchMode=yes admin@{ip} '{cmd}'",
        timeout=timeout,
    )


def check_node(name: str, info: dict) -> dict:
    """Check a single node's health."""
    mgmt_ip = info["mgmt"]
    fabric_ip = info["fabric"]
    is_local = mgmt_ip == SPARK_01_IP

    run = _run if is_local else lambda c, t=5: _ssh(mgmt_ip, c, t)

    result = {
        "name": name,
        "mgmt_ip": mgmt_ip,
        "fabric_ip": fabric_ip,
        "online": False,
        "gpu_temp": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "ollama_ok": False,
        "fabric_reachable": False,
    }

    uptime = run("uptime -s")
    if not uptime:
        return result
    result["online"] = True

    gpu = run("nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader 2>/dev/null")
    if gpu:
        result["gpu_temp"] = int(gpu)

    mem = run("free -g | grep Mem | awk '{print $3, $2}'")
    if mem:
        parts = mem.split()
        if len(parts) == 2:
            result["ram_used_gb"] = int(parts[0])
            result["ram_total_gb"] = int(parts[1])

    ollama = run("curl -s -o /dev/null -w '%{http_code}' http://localhost:11434/api/tags")
    result["ollama_ok"] = ollama == "200"

    fabric = _run(f"ping -c1 -W1 {fabric_ip} 2>/dev/null | grep -c '1 received'")
    result["fabric_reachable"] = fabric == "1"

    return result


def check_service(name: str, info: dict) -> dict:
    """Check if a service port is reachable."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        result = s.connect_ex((info["host"], info["port"]))
        return {"name": name, "port": info["port"], "status": "ok" if result == 0 else "down"}
    except Exception:
        return {"name": name, "port": info["port"], "status": "error"}
    finally:
        s.close()


def run_check(quick: bool = False) -> dict:
    """Run the full cluster health check."""
    t0 = time.time()

    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "nodes": {},
        "services": {},
        "summary": {"nodes_online": 0, "nodes_total": 4, "services_ok": 0, "services_total": 0},
    }

    for name, info in FABRIC_NODES.items():
        result = check_node(name, info)
        report["nodes"][name] = result
        if result["online"]:
            report["summary"]["nodes_online"] += 1

    if not quick:
        for name, info in SERVICES.items():
            result = check_service(name, info)
            report["services"][name] = result
            report["summary"]["services_total"] += 1
            if result["status"] == "ok":
                report["summary"]["services_ok"] += 1

    report["elapsed_ms"] = int((time.time() - t0) * 1000)
    return report


def print_report(report: dict):
    """Human-readable cluster health report."""
    print("=" * 60)
    print(f"  FORTRESS PRIME — Cluster Health Check")
    print(f"  {report['timestamp']}  ({report['elapsed_ms']}ms)")
    print("=" * 60)

    print(f"\n  Nodes: {report['summary']['nodes_online']}/{report['summary']['nodes_total']} online")
    for name, node in report["nodes"].items():
        status = "ONLINE" if node["online"] else "OFFLINE"
        gpu = f"{node['gpu_temp']}C" if node["gpu_temp"] else "N/A"
        ram = f"{node['ram_used_gb']}/{node['ram_total_gb']}GB" if node["ram_total_gb"] else "N/A"
        fabric = "OK" if node["fabric_reachable"] else "FAIL"
        ollama = "OK" if node["ollama_ok"] else "DOWN"
        print(f"    {name:12s}  {status:7s}  GPU:{gpu:5s}  RAM:{ram:10s}  Fabric:{fabric:4s}  Ollama:{ollama}")

    if report["services"]:
        ok = report["summary"]["services_ok"]
        total = report["summary"]["services_total"]
        print(f"\n  Services: {ok}/{total} healthy")
        for name, svc in report["services"].items():
            icon = "OK" if svc["status"] == "ok" else "DOWN"
            print(f"    {name:15s}  :{svc['port']:<5d}  {icon}")

    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fortress Cluster Health Check")
    parser.add_argument("--quick", action="store_true", help="Nodes only, skip services")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    report = run_check(quick=args.quick)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
