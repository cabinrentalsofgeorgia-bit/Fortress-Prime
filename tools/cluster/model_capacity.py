#!/usr/bin/env python3
"""
Fortress Prime cluster memory sizing helper.

Usage:
  python3 tools/cluster/model_capacity.py --node-mem-gib 121 --nodes 4 --reserve-os-gib 128
"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Cluster model memory sizing")
    parser.add_argument("--node-mem-gib", type=float, required=True, help="Per-node host memory in GiB")
    parser.add_argument("--nodes", type=int, required=True, help="Node count")
    parser.add_argument("--reserve-os-gib", type=float, default=128.0, help="Total cluster reserve for OS/DB")
    parser.add_argument("--model-target-gib", type=float, default=380.0, help="Desired model+KV target")
    args = parser.parse_args()

    total = args.node_mem_gib * args.nodes
    usable = total - args.reserve_os_gib
    delta = usable - args.model_target_gib

    print(f"nodes={args.nodes}")
    print(f"node_mem_gib={args.node_mem_gib:.2f}")
    print(f"cluster_total_gib={total:.2f}")
    print(f"reserve_os_gib={args.reserve_os_gib:.2f}")
    print(f"usable_for_model_gib={usable:.2f}")
    print(f"target_model_plus_kv_gib={args.model_target_gib:.2f}")

    if delta >= 0:
        print(f"status=PASS (headroom_gib={delta:.2f})")
    else:
        print(f"status=FAIL (shortfall_gib={abs(delta):.2f})")


if __name__ == "__main__":
    main()
