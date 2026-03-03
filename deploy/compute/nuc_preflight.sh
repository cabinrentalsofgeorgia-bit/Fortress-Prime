#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/nodes.env"
ALLOWED_PROFILES=("swarm" "hydra" "embeddings" "inference")

log() { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*"; }
warn() { echo "WARN: $*" >&2; }
fail() { echo "ERROR: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf "%s" "$s"
}

profile_allowed() {
  local profile="$1"
  local allowed
  for allowed in "${ALLOWED_PROFILES[@]}"; do
    if [[ "$profile" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}

validate_profile_value() {
  local profile="$1"
  local source="$2"
  [[ -n "$profile" ]] || return 0
  if ! profile_allowed "$profile"; then
    fail "${source}: invalid profile '${profile}'. Allowed: ${ALLOWED_PROFILES[*]}"
  fi
}

validate_env_and_nodes() {
  [[ -n "${DGX_SSH_USER:-}" ]] || fail "DGX_SSH_USER must be set in nodes.env"
  [[ -n "${DGX_NODES:-}" ]] || fail "DGX_NODES must be set or resolvable from SPARK_01_IP..SPARK_04_IP"
  [[ -n "${NGC_API_KEY:-}" ]] || fail "NGC_API_KEY must be set (nodes.env or project .env) for NIM authentication"
  validate_profile_value "${DGX_COMPOSE_PROFILE:-}" "DGX_COMPOSE_PROFILE"

  local -A seen_nodes=()
  local raw
  local host
  local count=0
  IFS=',' read -r -a _dgx_nodes <<< "${DGX_NODES}"
  for raw in "${_dgx_nodes[@]}"; do
    host="$(trim "$raw")"
    [[ -n "$host" ]] || continue
    if [[ -n "${seen_nodes[$host]:-}" ]]; then
      fail "DGX_NODES contains duplicate host '${host}'"
    fi
    seen_nodes["$host"]=1
    count=$((count + 1))
  done
  (( count > 0 )) || fail "DGX_NODES resolved to zero valid hosts"

  if [[ -n "${DGX_NODE_PROFILES:-}" ]]; then
    local pair key val
    IFS=',' read -r -a _pairs <<< "${DGX_NODE_PROFILES}"
    for pair in "${_pairs[@]}"; do
      pair="$(trim "$pair")"
      [[ -n "$pair" ]] || continue
      [[ "$pair" == *:* ]] || fail "DGX_NODE_PROFILES entry '${pair}' is invalid; expected host:profile"
      key="$(trim "${pair%%:*}")"
      val="$(trim "${pair#*:}")"
      [[ -n "$key" ]] || fail "DGX_NODE_PROFILES has empty host in '${pair}'"
      [[ -n "${seen_nodes[$key]:-}" ]] || fail "DGX_NODE_PROFILES references unknown host '${key}'"
      validate_profile_value "$val" "DGX_NODE_PROFILES(${key})"
    done
  fi
}

load_env() {
  [[ -f "$ENV_FILE" ]] || fail "missing ${ENV_FILE}. Copy nodes.env.example to nodes.env."
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  if [[ -n "${NODE_INVENTORY_FILE:-}" && -f "${NODE_INVENTORY_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${NODE_INVENTORY_FILE}"
  fi
  if [[ -z "${DGX_NODES:-}" ]]; then
    DGX_NODES="${SPARK_01_IP:-},${SPARK_02_IP:-},${SPARK_03_IP:-},${SPARK_04_IP:-}"
  fi
  if [[ -z "${NGC_API_KEY:-}" ]]; then
    local project_env="${SCRIPT_DIR}/../../.env"
    if [[ -f "$project_env" ]]; then
      NGC_API_KEY="$(awk -F= '/^NGC_API_KEY=/{sub(/^[^=]*=/,""); gsub(/^"|"$/, ""); print; exit}' "$project_env")"
    fi
  fi
}

ssh_check() {
  local host="$1"
  local user="${DGX_SSH_USER:?DGX_SSH_USER not set}"
  local port="${DGX_SSH_PORT:-22}"
  local timeout="${SSH_CONNECT_TIMEOUT_SECONDS:-8}"
  ssh -p "$port" -o BatchMode=yes -o ConnectTimeout="$timeout" "${user}@${host}" "echo ok" >/dev/null 2>&1
}

remote_check() {
  local host="$1"
  local user="${DGX_SSH_USER:?DGX_SSH_USER not set}"
  local port="${DGX_SSH_PORT:-22}"
  local timeout="${SSH_CONNECT_TIMEOUT_SECONDS:-8}"
  ssh -p "$port" -o BatchMode=yes -o ConnectTimeout="$timeout" "${user}@${host}" "$2"
}

retry_check() {
  local host="$1"
  local label="$2"
  local cmd="$3"
  local retries="${SSH_RETRIES:-5}"
  local backoff="${SSH_RETRY_BACKOFF_SECONDS:-2}"
  local attempt=1
  while (( attempt <= retries )); do
    if remote_check "$host" "$cmd" >/dev/null 2>&1; then
      return 0
    fi
    warn "${host}: ${label} failed attempt ${attempt}/${retries}"
    sleep "$backoff"
    attempt=$((attempt + 1))
    backoff=$((backoff * 2))
  done
  return 1
}

reason_for_stage() {
  local stage="$1"
  case "$stage" in
    ssh) echo "ssh_unreachable" ;;
    architecture) echo "node_not_arm64" ;;
    nas_mount) echo "nas_mount_not_remote_nfs" ;;
    image_arch) echo "image_digest_not_arm64" ;;
    docker_nvidia_cmds) echo "docker_or_nvidia_missing" ;;
    nvidia_runtime) echo "nvidia_runtime_validation_failed" ;;
    *) echo "unknown_failure" ;;
  esac
}

verify_digest_architecture_arm64() {
  local project_env="${SCRIPT_DIR}/../../.env"
  local output
  local status=0

  output="$(python3 - "$ENV_FILE" "$project_env" <<'PY'
import json
import os
import re
import subprocess
import sys

env_paths = [p for p in sys.argv[1:] if p and os.path.exists(p)]
digest_re = re.compile(r"^[^\s]+@sha256:[0-9a-f]{64}$")
refs = set()

for path in env_paths:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                _, value = line.split("=", 1)
                value = value.strip().strip('"').strip("'")
                if digest_re.match(value):
                    refs.add(value)
    except OSError:
        pass

if not refs:
    print("NO_DIGEST_REFS")
    sys.exit(0)

def has_arm64_platform(payload):
    found_arm64 = False
    found_platform = False

    def walk(obj):
        nonlocal found_arm64, found_platform
        if isinstance(obj, dict):
            platform = None
            descriptor = obj.get("Descriptor")
            if isinstance(descriptor, dict):
                platform = descriptor.get("platform")
            if not platform:
                platform = obj.get("platform")
            if isinstance(platform, dict):
                found_platform = True
                os_name = platform.get("os")
                arch = platform.get("architecture")
                if os_name == "linux" and arch in ("arm64", "aarch64"):
                    found_arm64 = True
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    return found_platform, found_arm64

bad = []
ok = []

for ref in sorted(refs):
    proc = subprocess.run(
        ["docker", "manifest", "inspect", "--verbose", ref],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        bad.append((ref, "manifest_lookup_failed"))
        continue
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        bad.append((ref, "manifest_json_parse_failed"))
        continue

    found_platform, found_arm64 = has_arm64_platform(payload)
    if not found_platform:
        bad.append((ref, "platform_not_declared"))
    elif not found_arm64:
        bad.append((ref, "arm64_platform_missing"))
    else:
        ok.append(ref)

if bad:
    for ref, reason in bad:
        print(f"BAD {ref} {reason}")
    sys.exit(2)

for ref in ok:
    print(f"OK {ref}")
PY
)" || status=$?

  if [[ -n "$output" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      log "digest-arch-check: ${line}"
    done <<< "$output"
  fi

  return "$status"
}

main() {
  require_cmd ssh
  require_cmd docker
  load_env
  validate_env_and_nodes
  require_cmd python3

  log "checking NUC controller prerequisites"
  command -v docker >/dev/null 2>&1 || fail "docker missing on NUC"
  log "NUC docker present"

  log "validating pinned image digests are ARM64-compatible"
  if ! verify_digest_architecture_arm64; then
    fail "digest architecture validation failed: one or more pinned images are not linux/arm64 or could not be verified"
  fi
  log "digest architecture validation passed"

  local total=0
  local reachable=0
  local healthy=0
  local -a node_results=()
  IFS=',' read -r -a dgx_nodes <<< "${DGX_NODES:?DGX_NODES not set}"

  for raw in "${dgx_nodes[@]}"; do
    local host
    host="$(trim "$raw")"
    [[ -n "$host" ]] || continue
    total=$((total + 1))

    log "preflight: ${host}"
    if ! retry_check "$host" "ssh" "echo ok"; then
      warn "${host}: ssh unreachable"
      node_results+=("${host}|failed|$(reason_for_stage ssh)")
      continue
    fi
    reachable=$((reachable + 1))

    if ! retry_check "$host" "node architecture" "arch=\$(uname -m); [ \"\$arch\" = \"aarch64\" ] || [ \"\$arch\" = \"arm64\" ]"; then
      warn "${host}: node architecture is not ARM64"
      node_results+=("${host}|failed|$(reason_for_stage architecture)")
      continue
    fi

    if ! retry_check "$host" "nas mount remote nfs" "line=\$(findmnt -T /mnt/fortress_nas -n -o SOURCE,FSTYPE 2>/dev/null || true); [ -n \"\$line\" ] || exit 1; src=\${line%% *}; fstype=\${line##* }; [ \"\$fstype\" = \"nfs\" ] || [ \"\$fstype\" = \"nfs4\" ] || exit 1; case \"\$src\" in /dev/*) exit 1 ;; esac"; then
      warn "${host}: /mnt/fortress_nas is not an active remote NFS mount"
      node_results+=("${host}|failed|$(reason_for_stage nas_mount)")
      continue
    fi

    if ! retry_check "$host" "docker+nvidia command presence" "command -v nvidia-smi >/dev/null 2>&1 && command -v docker >/dev/null 2>&1"; then
      warn "${host}: missing docker or nvidia-smi"
      node_results+=("${host}|failed|$(reason_for_stage docker_nvidia_cmds)")
      continue
    fi

    if ! retry_check "$host" "nvidia runtime" "docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null"; then
      warn "${host}: nvidia container runtime validation failed"
      node_results+=("${host}|failed|$(reason_for_stage nvidia_runtime)")
      continue
    fi

    healthy=$((healthy + 1))
    log "${host}: OK"
    node_results+=("${host}|ok|none")
  done

  log "preflight summary: total=${total}, reachable=${reachable}, healthy=${healthy}"
  echo "PREFLIGHT_SUMMARY total=${total} reachable=${reachable} healthy=${healthy}"
  local item host state reason
  for item in "${node_results[@]}"; do
    host="${item%%|*}"
    state="${item#*|}"
    state="${state%%|*}"
    reason="${item##*|}"
    echo "PREFLIGHT_NODE host=${host} state=${state} reason=${reason}"
  done
  if (( healthy < total )); then
    exit 2
  fi
}

main "$@"

