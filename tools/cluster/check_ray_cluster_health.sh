#!/usr/bin/env bash
set -euo pipefail

HEAD_IP="${HEAD_IP:-192.168.0.100}"
HEAD_ADDRESS="${HEAD_ADDRESS:-${HEAD_IP}:6390}"
DASHBOARD_ADDRESS="${DASHBOARD_ADDRESS:-http://${HEAD_IP}:8265}"
EXPECTED_NODES=("${HEAD_IP}" "192.168.0.104" "192.168.0.105" "192.168.0.106")
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=6
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

usage() {
  cat <<'EOF'
Usage:
  tools/cluster/check_ray_cluster_health.sh
  HEAD_IP=192.168.0.100 HEAD_ADDRESS=192.168.0.100:6390 tools/cluster/check_ray_cluster_health.sh
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

echo "== Fortress Ray Health =="
echo "Head IP: ${HEAD_IP}"
echo "Head Address: ${HEAD_ADDRESS}"
echo "Dashboard Address: ${DASHBOARD_ADDRESS}"
echo

echo "-- systemd --"
head_state="$(systemctl is-active fortress-ray-head.service)"
echo "head ${HEAD_IP}: fortress-ray-head.service=${head_state}"
if [[ "${head_state}" != "active" ]]; then
  echo "FAIL: head service is not active" >&2
  exit 1
fi

for node_ip in "${EXPECTED_NODES[@]:1}"; do
  worker_state="$(
    ssh "${SSH_OPTS[@]}" "${node_ip}" \
      "systemctl is-active fortress-ray-worker.service" 2>/dev/null
  )"
  echo "worker ${node_ip}: fortress-ray-worker.service=${worker_state}"
  if [[ "${worker_state}" != "active" ]]; then
    echo "FAIL: worker service is not active on ${node_ip}" >&2
    exit 1
  fi
done

echo
echo "-- ray status --"
ray status --address="${HEAD_ADDRESS}"

echo
echo "-- ray membership --"
membership_output="$(ray list nodes --format json --address "${DASHBOARD_ADDRESS}")"

MEMBERSHIP_JSON="${membership_output}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["MEMBERSHIP_JSON"])
for entry in payload:
    print(f'{entry["node_ip"]} {entry["state"]} node_id={entry["node_id"]}')
PY

alive_ips="$(
  MEMBERSHIP_JSON="${membership_output}" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["MEMBERSHIP_JSON"])
for ip in sorted({entry["node_ip"] for entry in payload if entry["state"] == "ALIVE"}):
    print(ip)
PY
)"

expected_ips="$(printf '%s\n' "${EXPECTED_NODES[@]}" | sort)"

if [[ "${alive_ips}" != "${expected_ips}" ]]; then
  echo
  echo "FAIL: Ray membership does not match expected nodes" >&2
  exit 1
fi

echo
echo "PASS: Ray cluster healthy on expected nodes."
