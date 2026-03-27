#!/usr/bin/env bash
set -euo pipefail

# Fortress Prime cluster audit runner.
# Executes a consistent hardware + RDMA bundle on each target node.

NODES=("${@:-}")
if [[ ${#NODES[@]} -eq 0 ]]; then
  NODES=("10.10.10.1" "10.10.10.2" "10.10.10.3" "10.10.10.4")
fi

SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

REMOTE_BUNDLE='
echo "HOST=$(hostname)"
echo "TIME_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "--- GPU_TOPO ---"
nvidia-smi topo -m || true
echo "--- GPU_LIST ---"
nvidia-smi -L || true
echo "--- GPU_MEMORY ---"
nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader || true
echo "--- HOST_MEMORY ---"
free -h || true
echo "--- RDMA_LINKS ---"
rdma link show || true
echo "--- ETH_LINKS ---"
for dev in enp1s0f0np0 enp1s0f1np1 enP2p1s0f0np0 enP2p1s0f1np1; do
  if ip link show "$dev" >/dev/null 2>&1; then
    echo "[$dev]"
    ethtool "$dev" 2>/dev/null | sed -n "1,18p" || true
  fi
done
'

for node in "${NODES[@]}"; do
  echo "============================================================"
  echo "NODE: $node"
  echo "============================================================"
  if [[ "$node" == "localhost" || "$node" == "127.0.0.1" ]]; then
    bash -lc "$REMOTE_BUNDLE"
    continue
  fi
  if ! ssh "${SSH_OPTS[@]}" "$node" "$REMOTE_BUNDLE"; then
    echo "ERROR: unable to audit $node (connectivity/auth)."
  fi
  echo
done
