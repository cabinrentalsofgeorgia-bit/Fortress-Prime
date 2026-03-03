#!/usr/bin/env bash
set -euo pipefail

log() { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

require_sudo() {
  command -v sudo >/dev/null 2>&1 || fail "sudo is required for DGX setup"
  sudo -n true >/dev/null 2>&1 || fail "passwordless sudo is required for non-interactive DGX setup"
}

ensure_ubuntu() {
  [[ -f /etc/os-release ]] || fail "cannot determine OS: /etc/os-release missing"
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || fail "unsupported OS '${ID:-unknown}': expected ubuntu"
  [[ -n "${VERSION_CODENAME:-}" ]] || fail "ubuntu VERSION_CODENAME not detected"
}

wait_for_apt_locks() {
  local timeout="${APT_LOCK_TIMEOUT_SECONDS:-120}"
  local interval=3
  local waited=0
  while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
    if (( waited >= timeout )); then
      fail "apt lock timeout after ${timeout}s"
    fi
    log "waiting for apt lock release (${waited}s/${timeout}s)"
    sleep "$interval"
    waited=$((waited + interval))
  done
}

ensure_docker_installed() {
  if command -v docker >/dev/null 2>&1; then
    return 0
  fi
  log "docker not found, installing docker-ce"
  wait_for_apt_locks
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  wait_for_apt_locks
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

ensure_nvidia_runtime() {
  require_cmd nvidia-smi
  ensure_docker_installed

  if ! command -v nvidia-ctk >/dev/null 2>&1; then
    log "installing nvidia-container-toolkit"
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
    wait_for_apt_locks
    sudo apt-get update -y
    sudo apt-get install -y nvidia-container-toolkit
  fi

  log "configuring docker for nvidia runtime"
  sudo nvidia-ctk runtime configure --runtime=docker || fail "nvidia-ctk runtime configure failed"
  sudo systemctl restart docker || fail "docker restart failed after nvidia runtime configuration"
  docker info >/dev/null 2>&1 || fail "docker is not healthy after restart"
  docker info --format '{{json .Runtimes}}' | grep -q nvidia || fail "nvidia runtime not present in docker info runtimes"

  log "validating nvidia runtime"
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null || fail "nvidia container runtime validation failed"
}

prepare_stack_dir() {
  local stack_dir="$1"
  sudo mkdir -p "$stack_dir"
  sudo chown "$USER":"$USER" "$stack_dir"
}

main() {
  local stack_dir="${1:-/opt/crog-fortress-ai}"
  log "starting DGX setup on $(hostname)"
  require_sudo
  ensure_ubuntu
  ensure_nvidia_runtime
  prepare_stack_dir "$stack_dir"
  log "DGX setup completed on $(hostname)"
}

main "$@"

