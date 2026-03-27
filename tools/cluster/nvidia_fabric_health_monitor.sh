#!/usr/bin/env bash
set -euo pipefail

# NVIDIA fabric health monitor for Spark cluster RoCE links.
# Alerts when active links drop below threshold (default 200Gbps).
#
# Usage:
#   tools/cluster/nvidia_fabric_health_monitor.sh
#   tools/cluster/nvidia_fabric_health_monitor.sh --watch 5
#   tools/cluster/nvidia_fabric_health_monitor.sh --nodes "192.168.0.104 192.168.0.100 192.168.0.101 192.168.0.102"

THRESHOLD_MBPS="${THRESHOLD_MBPS:-200000}"
WATCH_SECS=0
NODES="${NODES:-192.168.0.104 192.168.0.100 192.168.0.101 192.168.0.102}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --watch)
      WATCH_SECS="${2:-5}"
      shift 2
      ;;
    --nodes)
      NODES="${2:-$NODES}"
      shift 2
      ;;
    --threshold)
      THRESHOLD_MBPS="${2:-$THRESHOLD_MBPS}"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=6
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

check_node() {
  local node="$1"
  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  local out
  if ! out="$(ssh "${SSH_OPTS[@]}" "$node" '
    set -e
    host="$(hostname)"
    echo "HOST=$host"
    ibdev2netdev || true
    for dev in enp1s0f0np0 enp1s0f1np1 enP2p1s0f0np0 enP2p1s0f1np1; do
      if ip link show "$dev" >/dev/null 2>&1; then
        state="$(cat /sys/class/net/$dev/operstate 2>/dev/null || true)"
        speed_line="$(ethtool "$dev" 2>/dev/null | awk -F": *" "/Speed:/ {print \$2; exit}")"
        speed_num="$(echo "$speed_line" | tr -dc 0-9)"
        link_line="$(ethtool "$dev" 2>/dev/null | awk -F": *" "/Link detected:/ {print \$2; exit}")"
        echo "DEV=$dev STATE=$state SPEED=$speed_num LINK=$link_line"
      fi
    done
  ' 2>/dev/null)"; then
    echo "[$now] CRITICAL node=$node status=unreachable"
    return 2
  fi

  local host
  host="$(echo "$out" | awk -F= '/^HOST=/{print $2; exit}')"
  local alert=0
  local up_count=0

  while IFS= read -r line; do
    [[ "$line" == DEV=* ]] || continue
    dev="$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i ~ /^DEV=/){split($i,a,"="); print a[2]}}')"
    state="$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i ~ /^STATE=/){split($i,a,"="); print a[2]}}')"
    speed="$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i ~ /^SPEED=/){split($i,a,"="); print a[2]}}')"
    link="$(echo "$line" | awk '{for(i=1;i<=NF;i++) if($i ~ /^LINK=/){split($i,a,"="); print a[2]}}')"

    if [[ "$state" == "up" && "$link" == "yes" ]]; then
      up_count=$((up_count + 1))
      if [[ -n "$speed" && "$speed" -lt "$THRESHOLD_MBPS" ]]; then
        echo "[$now] ALERT host=$host node=$node dev=$dev speed=${speed}Mbps threshold=${THRESHOLD_MBPS}Mbps"
        alert=1
      fi
    fi
  done <<< "$out"

  if [[ "$up_count" -eq 0 ]]; then
    echo "[$now] ALERT host=$host node=$node status=no_active_roce_links"
    return 1
  fi

  if [[ "$alert" -eq 0 ]]; then
    echo "[$now] OK host=$host node=$node active_links=$up_count threshold=${THRESHOLD_MBPS}Mbps"
  fi
  return "$alert"
}

run_once() {
  local rc=0
  for node in $NODES; do
    if ! check_node "$node"; then
      rc=1
    fi
  done
  return "$rc"
}

if [[ "$WATCH_SECS" -gt 0 ]]; then
  while true; do
    run_once || true
    sleep "$WATCH_SECS"
  done
else
  run_once
fi
