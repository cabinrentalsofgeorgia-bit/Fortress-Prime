#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIFT_PY="${ROOT_DIR}/fortress-guest-platform/.uv-venv/bin/python"

overall=0

line() {
  printf '%-5s %s\n' "$1" "$2"
}

ok() {
  line "OK" "$1"
}

warn() {
  line "WARN" "$1"
}

fail() {
  line "FAIL" "$1"
  overall=1
}

have() {
  command -v "$1" >/dev/null 2>&1
}

check_repo_drift() {
  if [[ ! -x "$DRIFT_PY" ]]; then
    fail "drift alarm python missing at $DRIFT_PY"
    return
  fi
  local output
  if output="$("$DRIFT_PY" "${ROOT_DIR}/tools/drift_alarm.py" --dry-run 2>&1)"; then
    if grep -q "No drift detected" <<<"$output"; then
      ok "Fortress repo drift clean"
    else
      warn "drift alarm completed but did not report a clean repo"
      printf '%s\n' "$output"
    fi
  else
    fail "drift alarm failed"
    printf '%s\n' "$output"
  fi
}

check_services() {
  local failed
  failed="$(systemctl --failed --no-legend --no-pager 2>/dev/null || true)"
  if [[ -z "$failed" ]]; then
    ok "systemd has no failed units"
  else
    fail "systemd has failed units"
    printf '%s\n' "$failed"
  fi

  local unit
  for unit in \
    fortress-telemetry.service \
    fortress-watcher.service \
    fortress-nightly-finetune.timer \
    k3s.service \
    tailscaled.service; do
    if systemctl is-active --quiet "$unit"; then
      ok "$unit active"
    else
      fail "$unit not active"
    fi
  done
}

check_k3s() {
  if ! have kubectl; then
    warn "kubectl not installed or not on PATH"
    return
  fi
  local nodes not_ready
  if ! nodes="$(kubectl get nodes --no-headers 2>&1)"; then
    fail "kubectl get nodes failed"
    printf '%s\n' "$nodes"
    return
  fi
  not_ready="$(awk '$2 != "Ready" {print $1 ":" $2}' <<<"$nodes")"
  if [[ -z "$not_ready" ]]; then
    ok "k3s nodes Ready ($(wc -l <<<"$nodes" | tr -d ' '))"
  else
    fail "k3s has non-Ready nodes: $not_ready"
  fi
}

check_spark_aliases() {
  local alias host
  for alias in spark-1 spark-1-fabric spark-1-p2p spark-1-mgmt spark-1-ts \
    spark-2 spark-2-mgmt spark-2-ts \
    spark-3 spark-3-mgmt spark-3-ts \
    spark-4 spark-4-mgmt spark-4-ts \
    spark-5 spark-5-ts spark-5-mgmt \
    spark-6 spark-6-ts spark-6-mgmt; do
    if host="$(ssh -o BatchMode=yes -o ConnectTimeout=4 "$alias" 'hostname' 2>/dev/null)"; then
      ok "SSH alias $alias -> $host"
    else
      warn "SSH alias $alias not reachable"
    fi
  done
}

check_storage_and_lan() {
  local target
  for target in 192.168.0.1 192.168.0.112 192.168.0.113 192.168.0.114; do
    if ping -c 1 -W 1 "$target" >/dev/null 2>&1; then
      ok "LAN ping $target"
    else
      warn "LAN ping $target failed"
    fi
  done

  if mountpoint -q /mnt/fortress_nas; then
    ok "NAS mount present at /mnt/fortress_nas"
    local nas_line nas_used
    nas_line="$(df -h /mnt/fortress_nas | tail -1)"
    nas_used="$(awk '{gsub(/%/, "", $5); print $5}' <<<"$nas_line")"
    if (( nas_used >= 90 )); then
      warn "NAS capacity ${nas_used}% used ($(awk '{print $4}' <<<"$nas_line") free)"
    else
      ok "NAS capacity ${nas_used}% used ($(awk '{print $4}' <<<"$nas_line") free)"
    fi
  else
    fail "NAS mount missing at /mnt/fortress_nas"
  fi

  local root_line root_used
  root_line="$(df -h / | tail -1)"
  root_used="$(awk '{gsub(/%/, "", $5); print $5}' <<<"$root_line")"
  if (( root_used >= 85 )); then
    warn "Spark-2 root disk ${root_used}% used ($(awk '{print $4}' <<<"$root_line") free)"
  else
    ok "Spark-2 root disk ${root_used}% used ($(awk '{print $4}' <<<"$root_line") free)"
  fi
}

check_tailscale() {
  if ! have tailscale; then
    warn "tailscale command not installed"
    return
  fi
  if ! tailscale status --peers=false >/dev/null 2>&1; then
    fail "local Tailscale is not healthy"
    return
  fi
  ok "local Tailscale running"

  local peer
  for peer in \
    100.127.241.36 \
    100.96.44.85 \
    100.125.35.42 \
    100.96.13.99 \
    100.71.225.76 \
    100.66.180.7; do
    if tailscale ping -c 1 --timeout=2s "$peer" >/dev/null 2>&1; then
      ok "Tailscale peer $peer reachable"
    else
      warn "Tailscale peer $peer not reachable"
    fi
  done

  if tailscale ping -c 1 --timeout=2s 100.89.109.96 >/dev/null 2>&1; then
    ok "Synology Tailscale 100.89.109.96 reachable"
  else
    warn "Synology Tailscale 100.89.109.96 offline; parked for local DSM repair"
  fi
}

check_mac_mini() {
  local disk
  if disk="$(ssh \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=5 \
    root@100.66.180.7 \
    'df -h /System/Volumes/Data | tail -1' 2>/dev/null)"; then
    ok "Mac mini reachable over Tailscale"
    local mac_used
    mac_used="$(awk '{gsub(/%/, "", $5); print $5}' <<<"$disk")"
    if (( mac_used >= 90 )); then
      warn "Mac mini Data disk ${mac_used}% used ($(awk '{print $4}' <<<"$disk") free)"
    else
      ok "Mac mini Data disk ${mac_used}% used ($(awk '{print $4}' <<<"$disk") free)"
    fi
  else
    warn "Mac mini root SSH over Tailscale not reachable"
  fi
}

main() {
  echo "Fortress stack health - $(date -Is)"
  echo "root: $ROOT_DIR"
  check_repo_drift
  check_services
  check_k3s
  check_spark_aliases
  check_storage_and_lan
  check_tailscale
  check_mac_mini
  exit "$overall"
}

main "$@"
