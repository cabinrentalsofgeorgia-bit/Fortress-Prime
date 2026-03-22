#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

LOG_ROOT="${APP_ROOT}/runtime-logs/seo-operator"
mkdir -p "${LOG_ROOT}"

log() {
    printf '[seo-operator-stack] %s\n' "$*"
}

port_is_open() {
    python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.25)
try:
    sock.connect(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
raise SystemExit(0)
PY
}

process_is_running() {
    local pattern="$1"
    pgrep -f "$pattern" >/dev/null 2>&1
}

pid_is_running() {
    local pid="$1"
    [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

pid_file_for() {
    local name="$1"
    printf '%s/%s.pid\n' "${LOG_ROOT}" "${name}"
}

start_background() {
    local name="$1"
    local script_path="$2"
    local log_file="${LOG_ROOT}/${name}.log"
    local pid_file
    pid_file="$(pid_file_for "${name}")"

    log "starting ${name}"
    nohup "${script_path}" >"${log_file}" 2>&1 &
    printf '%s\n' "$!" >"${pid_file}"
    disown || true
}

ensure_port_service() {
    local name="$1"
    local port="$2"
    local script_path="$3"

    if port_is_open "${port}"; then
        log "${name} already listening on ${port}"
        return 0
    fi

    start_background "${name}" "${script_path}"
    sleep 2
    if port_is_open "${port}"; then
        log "${name} started on ${port}"
        return 0
    fi

    log "${name} failed to start; inspect ${LOG_ROOT}/${name}.log"
    return 1
}

ensure_process_service() {
    local name="$1"
    local pattern="$2"
    local script_path="$3"
    local pid_file
    pid_file="$(pid_file_for "${name}")"
    if [[ -f "${pid_file}" ]]; then
        local existing_pid
        existing_pid="$(<"${pid_file}")"
        if pid_is_running "${existing_pid}"; then
            log "${name} already running (pid ${existing_pid})"
            return 0
        fi
        rm -f "${pid_file}"
    fi

    if process_is_running "${pattern}"; then
        log "${name} already running"
        return 0
    fi

    start_background "${name}" "${script_path}"
    sleep 2
    local started_pid
    started_pid="$(<"${pid_file}")"
    if pid_is_running "${started_pid}"; then
        log "${name} started (pid ${started_pid})"
        return 0
    fi

    rm -f "${pid_file}"
    log "${name} failed to start; inspect ${LOG_ROOT}/${name}.log"
    return 1
}

ensure_port_service "backend-8118" 8118 "${SCRIPT_DIR}/start_seo_backend_8118.sh"
ensure_port_service "storefront-3210" 3210 "${SCRIPT_DIR}/start_storefront_3210.sh"
ensure_process_service \
    "primary-arq-worker" \
    "fortress-seo-primary-arq-worker backend\\.core\\.worker\\.WorkerSettings" \
    "${SCRIPT_DIR}/start_primary_arq_worker.sh"
ensure_process_service \
    "seo-deploy-consumer" \
    "fortress-seo-deploy-consumer -" \
    "${SCRIPT_DIR}/start_seo_deploy_consumer.sh"
ensure_port_service "smoke-backend-8124" 8124 "${SCRIPT_DIR}/start_seo_smoke_backend_8124.sh"

log "stack ready"
