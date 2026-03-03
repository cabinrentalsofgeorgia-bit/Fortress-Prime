#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/nodes.env"
REMOTE_SETUP_SCRIPT="${SCRIPT_DIR}/dgx_remote_setup.sh"
ALLOWED_PROFILES=("swarm" "hydra" "embeddings" "inference")

log() { echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] $*"; }
warn() { echo "WARN: $*" >&2; }
fail() { echo "ERROR: $*" >&2; exit 1; }

require_local_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required local command: $1"
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

escape_single_quotes() {
  printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

profile_for_host() {
  local host="$1"
  local default_profile="${DGX_COMPOSE_PROFILE:-}"

  if [[ -z "${DGX_NODE_PROFILES:-}" ]]; then
    printf "%s" "$default_profile"
    return 0
  fi

  local pair
  IFS=',' read -r -a pairs <<< "${DGX_NODE_PROFILES}"
  for pair in "${pairs[@]}"; do
    pair="$(trim "$pair")"
    [[ -n "$pair" ]] || continue
    local key="${pair%%:*}"
    local val="${pair#*:}"
    key="$(trim "$key")"
    val="$(trim "$val")"
    if [[ "$key" == "$host" ]]; then
      printf "%s" "$val"
      return 0
    fi
  done

  printf "%s" "$default_profile"
}

ssh_run() {
  local host="$1"
  local cmd="$2"
  local retries="${SSH_RETRIES:-5}"
  local backoff="${SSH_RETRY_BACKOFF_SECONDS:-2}"
  local timeout="${SSH_CONNECT_TIMEOUT_SECONDS:-8}"
  local user="${DGX_SSH_USER:?DGX_SSH_USER not set}"
  local port="${DGX_SSH_PORT:-22}"

  local attempt=1
  while (( attempt <= retries )); do
    if ssh -p "$port" -o BatchMode=yes -o ConnectTimeout="$timeout" "${user}@${host}" "$cmd"; then
      return 0
    fi
    warn "ssh attempt ${attempt}/${retries} failed for ${host}"
    sleep "$backoff"
    attempt=$((attempt + 1))
    backoff=$((backoff * 2))
  done
  return 1
}

ssh_run_once() {
  local host="$1"
  local cmd="$2"
  local timeout="${SSH_CONNECT_TIMEOUT_SECONDS:-8}"
  local user="${DGX_SSH_USER:?DGX_SSH_USER not set}"
  local port="${DGX_SSH_PORT:-22}"
  ssh -p "$port" -o BatchMode=yes -o ConnectTimeout="$timeout" "${user}@${host}" "$cmd"
}

scp_push() {
  local src="$1"
  local host="$2"
  local dst="$3"
  local user="${DGX_SSH_USER:?DGX_SSH_USER not set}"
  local port="${DGX_SSH_PORT:-22}"
  scp -P "$port" -o BatchMode=yes -o ConnectTimeout="${SSH_CONNECT_TIMEOUT_SECONDS:-8}" "$src" "${user}@${host}:$dst"
}

ensure_nuc_is_lightweight() {
  log "validating NUC stays lightweight (no local DGX workloads)"
  if docker ps --format '{{.Names}} {{.Image}}' | grep -Eiq '(llama|vllm|text-generation|triton|nim|training)'; then
    warn "possible inference/training containers detected on NUC"
    warn "stop heavy containers on NUC to keep controller node lightweight"
  else
    log "no obvious heavy inference/training containers found on NUC"
  fi
}

bootstrap_dgx_node() {
  local host="$1"
  local stack_dir="${DGX_REMOTE_STACK_DIR:?DGX_REMOTE_STACK_DIR not set}"
  local compose_file="${DGX_COMPOSE_FILE:?DGX_COMPOSE_FILE not set}"
  local node_profile
  node_profile="$(profile_for_host "$host")"

  log "bootstrap start on ${host}"
  scp_push "$REMOTE_SETUP_SCRIPT" "$host" "/tmp/dgx_remote_setup.sh" || {
    warn "skipping ${host}: failed to copy setup script"
    return 11
  }

  if ! ssh_run "$host" "chmod +x /tmp/dgx_remote_setup.sh && /tmp/dgx_remote_setup.sh '$stack_dir'"; then
    warn "setup failed on ${host}"
    return 12
  fi

  if [[ -f "${SCRIPT_DIR}/${compose_file}" ]]; then
    scp_push "${SCRIPT_DIR}/${compose_file}" "$host" "${stack_dir}/${compose_file}" || {
      warn "failed to copy compose file to ${host}"
      return 13
    }
  else
    warn "compose file ${SCRIPT_DIR}/${compose_file} not found; skipping deploy on ${host}"
    return 14
  fi

  local profile_arg=""
  if [[ -n "$node_profile" ]]; then
    profile_arg="--profile ${node_profile}"
    log "${host}: using compose profile '${node_profile}'"
  fi

  if [[ -n "${CONTAINER_REGISTRY:-}" && -n "${CONTAINER_REGISTRY_USER:-}" && -n "${CONTAINER_REGISTRY_PASSWORD:-}" ]]; then
    ssh_run "$host" "echo '${CONTAINER_REGISTRY_PASSWORD}' | docker login '${CONTAINER_REGISTRY}' -u '${CONTAINER_REGISTRY_USER}' --password-stdin" || {
      warn "registry login failed on ${host}"
      return 15
    }
  fi

  local ngc_key_escaped
  ngc_key_escaped="$(escape_single_quotes "${NGC_API_KEY}")"
  if ! ssh_run "$host" "cd '${stack_dir}' && NGC_API_KEY='${ngc_key_escaped}' docker compose -f '${compose_file}' ${profile_arg} pull && NGC_API_KEY='${ngc_key_escaped}' docker compose -f '${compose_file}' ${profile_arg} up -d"; then
    warn "compose deploy failed on ${host}"
    return 16
  fi

  if [[ "${DGX_POST_DEPLOY_HEALTHCHECK:-true}" == "true" ]]; then
    local hc_timeout="${DGX_HEALTHCHECK_TIMEOUT_SECONDS:-600}"
    local hc_interval="${DGX_HEALTHCHECK_POLL_SECONDS:-5}"
    local elapsed=0
    local health_cmd="
cd '${stack_dir}' && ids=\$(NGC_API_KEY='${ngc_key_escaped}' docker compose -f '${compose_file}' ${profile_arg} ps -q) && \
[ -n \"\$ids\" ] || exit 17; \
for id in \$ids; do \
  status=\$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \"\$id\" 2>/dev/null || true); \
  [ \"\$status\" = \"healthy\" ] || [ \"\$status\" = \"running\" ] || exit 18; \
done
"
    while (( elapsed < hc_timeout )); do
      if ssh_run_once "$host" "$health_cmd"; then
        log "${host}: post-deploy health probe passed"
        break
      fi
      sleep "$hc_interval"
      elapsed=$((elapsed + hc_interval))
    done
    if (( elapsed >= hc_timeout )); then
      warn "${host}: post-deploy health probe timed out after ${hc_timeout}s"
      return 19
    fi
  fi

  log "bootstrap complete on ${host}"
  return 0
}

reason_for_code() {
  local code="$1"
  case "$code" in
    0) echo "ok" ;;
    10) echo "mkdir_failed" ;;
    11) echo "setup_script_copy_failed" ;;
    12) echo "remote_setup_failed" ;;
    13) echo "compose_copy_failed" ;;
    14) echo "compose_missing" ;;
    15) echo "registry_login_failed" ;;
    16) echo "compose_deploy_failed" ;;
    19) echo "post_deploy_health_timeout" ;;
    *) echo "unknown_failure" ;;
  esac
}

main() {
  require_local_cmd ssh
  require_local_cmd scp
  require_local_cmd docker
  load_env
  validate_env_and_nodes
  ensure_nuc_is_lightweight

  IFS=',' read -r -a dgx_nodes <<< "${DGX_NODES:?DGX_NODES not set}"
  local total=0
  local ok=0
  local failed=0
  local -a node_results=()

  for raw in "${dgx_nodes[@]}"; do
    local host
    host="$(trim "$raw")"
    [[ -n "$host" ]] || continue
    total=$((total + 1))
    local rc=0
    if bootstrap_dgx_node "$host"; then
      ok=$((ok + 1))
      node_results+=("${host}|ok|0")
    else
      rc=$?
      failed=$((failed + 1))
      node_results+=("${host}|$(reason_for_code "$rc")|${rc}")
    fi
  done

  log "cluster orchestration complete: total=${total}, ok=${ok}, failed=${failed}"
  log "node result summary (host|reason|code):"
  local item
  for item in "${node_results[@]}"; do
    log "  ${item}"
  done
  if (( failed > 0 )); then
    exit 2
  fi
}

main "$@"

