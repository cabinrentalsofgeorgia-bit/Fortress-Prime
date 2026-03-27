#!/usr/bin/env bash
set -euo pipefail

# Brings known RoCE-related interfaces up and reports resulting RDMA state.
# Requires root privileges on target nodes.

NODES=("${@:-}")
if [[ ${#NODES[@]} -eq 0 ]]; then
  NODES=("10.10.10.1" "10.10.10.2" "10.10.10.3" "10.10.10.4")
fi

IFACES=(enp1s0f0np0 enp1s0f1np1 enP2p1s0f0np0 enP2p1s0f1np1)

SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

REMOTE_FIX='
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    echo "ERROR: must run as root or have sudo access"
    exit 1
  fi
else
  SUDO=""
fi

for dev in enp1s0f0np0 enp1s0f1np1 enP2p1s0f0np0 enP2p1s0f1np1; do
  if ip link show "$dev" >/dev/null 2>&1; then
    $SUDO ip link set "$dev" up || true
    $SUDO ethtool --set-fec "$dev" encoding rs >/dev/null 2>&1 || true
  fi
done

echo "HOST=$(hostname)"
echo "--- ETH_STATE ---"
ip -br link | awk "{print \$1,\$2}" | egrep "enp1s0f0np0|enp1s0f1np1|enP2p1s0f0np0|enP2p1s0f1np1" || true
echo "--- RDMA_STATE ---"
rdma link show || true
'

for node in "${NODES[@]}"; do
  echo "============================================================"
  echo "ROCE REMEDIATION NODE: $node"
  echo "============================================================"
  if ! ssh "${SSH_OPTS[@]}" "$node" "$REMOTE_FIX"; then
    echo "ERROR: remediation failed on $node"
  fi
  echo
done
