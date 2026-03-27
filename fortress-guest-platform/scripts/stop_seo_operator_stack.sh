#!/usr/bin/env bash
set -euo pipefail

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/seo_runtime_common.sh"

log() {
    printf '[seo-operator-stack-stop] %s\n' "$*"
}

LOG_ROOT="${APP_ROOT}/runtime-logs/seo-operator"

pid_is_running() {
    local pid="$1"
    kill -0 "${pid}" 2>/dev/null
}

pid_file_for() {
    local name="$1"
    printf '%s/%s.pid\n' "${LOG_ROOT}" "${name}"
}

find_port_pids() {
    python3 - "$1" <<'PY'
import re
import subprocess
import sys

port = sys.argv[1]
result = subprocess.run(
    ["ss", "-ltnp", f"( sport = :{port} )"],
    capture_output=True,
    text=True,
    check=False,
)
pids: set[str] = set()
for match in re.finditer(r"pid=(\d+)", result.stdout):
    pids.add(match.group(1))
for pid in sorted(pids):
    print(pid)
PY
}

wait_for_pids_to_exit() {
    local description="$1"
    shift
    local pids=("$@")
    local remaining=()
    local attempt
    for attempt in {1..20}; do
        remaining=()
        local pid
        for pid in "${pids[@]}"; do
            if pid_is_running "${pid}"; then
                remaining+=("${pid}")
            fi
        done
        if [[ "${#remaining[@]}" -eq 0 ]]; then
            log "${description} stopped"
            return 0
        fi
        sleep 0.25
    done

    log "warning: ${description} still running after SIGTERM: ${remaining[*]}"
    return 1
}

stop_port_service() {
    local name="$1"
    local port="$2"
    local pid_file
    pid_file="$(pid_file_for "${name}")"
    mapfile -t pids < <(find_port_pids "${port}")
    if [[ "${#pids[@]}" -eq 0 ]]; then
        rm -f "${pid_file}"
        log "${name} not running on ${port}"
        return 0
    fi

    log "stopping ${name} on ${port}: ${pids[*]}"
    kill "${pids[@]}" 2>/dev/null || true
    wait_for_pids_to_exit "${name}" "${pids[@]}" || true

    mapfile -t pids < <(find_port_pids "${port}")
    if [[ "${#pids[@]}" -gt 0 ]]; then
        log "warning: ${name} still owns ${port}: ${pids[*]}"
        return 1
    fi
    rm -f "${pid_file}"
}

stop_process_service() {
    local name="$1"
    local pattern="$2"
    local pid_file
    pid_file="$(pid_file_for "${name}")"
    local pids=()
    if [[ -f "${pid_file}" ]]; then
        local recorded_pid
        recorded_pid="$(<"${pid_file}")"
        if pid_is_running "${recorded_pid}"; then
            pids=("${recorded_pid}")
        else
            rm -f "${pid_file}"
        fi
    fi
    if [[ "${#pids[@]}" -eq 0 ]]; then
        mapfile -t pids < <(pgrep -f "${pattern}" || true)
    fi
    if [[ "${#pids[@]}" -eq 0 ]]; then
        log "${name} not running"
        return 0
    fi

    log "stopping ${name}: ${pids[*]}"
    kill "${pids[@]}" 2>/dev/null || true
    wait_for_pids_to_exit "${name}" "${pids[@]}" || true

    mapfile -t pids < <(pgrep -f "${pattern}" || true)
    if [[ "${#pids[@]}" -gt 0 ]]; then
        log "warning: ${name} still matches pattern: ${pids[*]}"
        return 1
    fi
    rm -f "${pid_file}"
}

stop_port_service "smoke-backend-8124" 8124
stop_process_service \
    "seo-deploy-consumer" \
    "fortress-seo-deploy-consumer -"
stop_process_service \
    "primary-arq-worker" \
    "fortress-seo-primary-arq-worker backend\\.core\\.worker\\.WorkerSettings"
stop_port_service "storefront-3210" 3210
stop_port_service "backend-8118" 8118

log "stop signals sent"
