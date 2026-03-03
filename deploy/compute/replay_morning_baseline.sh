#!/usr/bin/env bash
set -euo pipefail

# Replays the manual "known-good morning" operator flow observed in bash history.
# Intended to run from Spark-01 / 192.168.0.100.

NODES="${NODES:-192.168.0.100 192.168.0.104 192.168.0.105 192.168.0.106}"
GPU_TEST_IMAGE="${GPU_TEST_IMAGE:-nvidia/cuda:12.2.2-base-ubuntu22.04}"
EXTRA_CONTAINER_ID="${EXTRA_CONTAINER_ID:-}"

echo "== [1/6] NAS mount baseline check =="
sudo bash bin/mount_nas.sh

echo
echo "== [2/6] GPU runtime validation on all nodes =="
for ip in ${NODES}; do
  echo "--- Testing GPU on node: ${ip} ---"
  ssh -o BatchMode=yes "admin@${ip}" \
    "sudo docker run --rm --gpus all ${GPU_TEST_IMAGE} nvidia-smi"
done

echo
echo "== [3/6] Port 8000 conflict cleanup (history baseline) =="
sudo lsof -i :8000 || true
if sudo docker ps --format '{{.Names}}' | grep -qx 'fortress-gateway'; then
  sudo docker stop fortress-gateway || true
  sudo docker rm fortress-gateway || true
fi

if [[ -n "${EXTRA_CONTAINER_ID}" ]]; then
  echo "Stopping explicit container id from baseline: ${EXTRA_CONTAINER_ID}"
  sudo docker stop "${EXTRA_CONTAINER_ID}" || true
  sudo docker rm "${EXTRA_CONTAINER_ID}" || true
fi

echo
echo "== [4/6] Post-cleanup port check =="
sudo lsof -i :8000 || true

echo
echo "== [5/6] Container status snapshot =="
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo
echo "== [6/6] nim-swarm recent logs =="
if sudo docker ps -a --format '{{.Names}}' | grep -qx 'nim-swarm'; then
  sudo docker logs --tail 50 nim-swarm || true
else
  echo "nim-swarm container not found."
fi

echo
echo "Baseline replay complete."
