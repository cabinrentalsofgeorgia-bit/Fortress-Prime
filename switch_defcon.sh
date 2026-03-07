#!/usr/bin/env bash
# ============================================================================
# FORTRESS PRIME — DEFCON Mode Switch (The Kill Switch)
# ============================================================================
# Governing Documents:
#   CONSTITUTION.md   — Article VI (Kill Switch Protocol)
#   REQUIREMENTS.md   — Section 1.4 (VRAM), Section 2.3 (Service Mesh)
#   config.py         — Cluster topology, DEFCON env var
#
# DEFCON Tiers:
#   SWARM  (5)         — Ollama via Nginx LB        ./switch_defcon.sh swarm
#   FORTRESS_LEGAL     — Multi-model per-node       ./switch_defcon.sh fortress_legal
#                       (chat :8081, embed :8082, gateway :8090; no RPC)
#
# Other:
#   ./switch_defcon.sh status   — Current mode, processes, GPU temps
#   ./switch_defcon.sh build    — Build llama.cpp (CUDA only, Blackwell-native)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Cluster Topology — mirrors config.py (REQUIREMENTS.md Section 1.1)
# All compute traffic on the 200 Gb/s RoCEv2 fabric; SSH on management LAN.
# ---------------------------------------------------------------------------
CAPTAIN_FABRIC="${FABRIC_CAPTAIN:-10.10.10.1}"
MUSCLE_FABRIC="${FABRIC_MUSCLE:-10.10.10.2}"
OCULAR_FABRIC="${FABRIC_OCULAR:-10.10.10.3}"
SOVEREIGN_FABRIC="${FABRIC_SOVEREIGN:-10.10.10.4}"

CAPTAIN_MGMT="${SPARK_01_IP:-192.168.0.100}"
MUSCLE_MGMT="${SPARK_02_IP:-192.168.0.104}"
OCULAR_MGMT="${SPARK_03_IP:-192.168.0.105}"
SOVEREIGN_MGMT="${SPARK_04_IP:-192.168.0.106}"

WORKER_FABRIC=("$MUSCLE_FABRIC" "$OCULAR_FABRIC" "$SOVEREIGN_FABRIC")
WORKER_MGMT=("$MUSCLE_MGMT" "$OCULAR_MGMT" "$SOVEREIGN_MGMT")
WORKER_NAMES=("Muscle" "Ocular" "Sovereign")
ALL_FABRIC=("$CAPTAIN_FABRIC" "${WORKER_FABRIC[@]}")
ALL_MGMT=("$CAPTAIN_MGMT" "${WORKER_MGMT[@]}")

# Fortress Legal — multi-model per-node ports
CHAT_PORT="${CHAT_PORT:-8081}"
EMBED_PORT="${EMBED_PORT:-8082}"
GATEWAY_PORT="${GATEWAY_PORT:-8090}"

# Paths
LLAMA_SRC="${LLAMA_SRC:-$HOME/llama.cpp}"
LLAMA_BUILD="${LLAMA_SRC}/build"
LLAMA_BIN="${LLAMA_BUILD}/bin"
NGINX_CONF="${NGINX_CONF:-${SCRIPT_DIR}/nginx/fortress_legal_gateway.conf}"

# Fortress Legal models (NAS; all nodes mount /mnt/fortress_nas)
CHAT_MODEL_PATH="${CHAT_MODEL_PATH:-/mnt/fortress_nas/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf}"
EMBED_MODEL_PATH="${EMBED_MODEL_PATH:-/mnt/fortress_nas/models/nomic-embed-text-v1.5.f16.gguf}"

# Chat server — document-optimized (high throughput, RAG)
CHAT_CTX="${CHAT_CTX:-32768}"
CHAT_PARALLEL="${CHAT_PARALLEL:-8}"
CHAT_GPU_LAYERS="${CHAT_GPU_LAYERS:-999}"

# Embed server — tuned for embedding workload
EMBED_PARALLEL="${EMBED_PARALLEL:-4}"
EMBED_GPU_LAYERS="${EMBED_GPU_LAYERS:-999}"

SSH_USER="${SSH_USER:-admin}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"
LOG_DIR="${LOG_DIR:-/tmp}"
mkdir -p "$LOG_DIR" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
err()  { log "ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

ssh_node() {
    local host="$1"; shift
    ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no \
        "${SSH_USER}@${host}" "$@"
}

gpu_temp_local() {
    nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null || echo "N/A"
}

gpu_temp_remote() {
    ssh_node "$1" \
        "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null" \
        || echo "N/A"
}

check_gpu_safe() {
    local temp
    temp=$(gpu_temp_local)
    if [[ "$temp" != "N/A" ]] && (( temp > 85 )); then
        die "GPU temperature ${temp}°C exceeds 85°C safety threshold (CONSTITUTION Article VI). Aborting."
    fi
}

persist_defcon() {
    local mode="$1"
    if [[ -f "$ENV_FILE" ]] && grep -q '^FORTRESS_DEFCON=' "$ENV_FILE" 2>/dev/null; then
        sed -i "s/^FORTRESS_DEFCON=.*/FORTRESS_DEFCON=${mode}/" "$ENV_FILE"
    else
        echo "FORTRESS_DEFCON=${mode}" >> "$ENV_FILE"
    fi
    export FORTRESS_DEFCON="$mode"
}

# ---------------------------------------------------------------------------
# build_llama — Clean-build llama.cpp with CUDA only (no RPC)
# Blackwell-safe: CMAKE_CUDA_ARCHITECTURES=native
# ---------------------------------------------------------------------------
build_llama() {
    log "=========================================="
    log " FORTRESS PRIME: BUILDING llama.cpp"
    log " Flags: GGML_CUDA=ON (no RPC)"
    log "=========================================="

    if [[ ! -d "$LLAMA_SRC" ]]; then
        log "Cloning llama.cpp into ${LLAMA_SRC}..."
        git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_SRC"
    else
        log "Updating llama.cpp (fast-forward only)..."
        git -C "$LLAMA_SRC" fetch --all
        git -C "$LLAMA_SRC" pull --ff-only || log "WARN: pull failed — building from current HEAD"
    fi

    log "Cleaning previous build directory..."
    rm -rf "$LLAMA_BUILD"
    mkdir -p "$LLAMA_BUILD"

    log "Running CMake configure (CUDA, native arch)..."
    cmake -B "$LLAMA_BUILD" -S "$LLAMA_SRC" \
        -DGGML_CUDA=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES="native"

    local nproc
    nproc=$(nproc 2>/dev/null || echo 4)
    log "Building with ${nproc} parallel jobs..."
    cmake --build "$LLAMA_BUILD" --config Release -j"${nproc}"

    local server_bin="${LLAMA_BIN}/llama-server"
    [[ -f "$server_bin" ]] || die "Build failed: llama-server not found at ${server_bin}"

    log "Binary: llama-server $(du -h "$server_bin" | cut -f1)"

    log "Distributing llama-server to worker nodes..."
    for i in "${!WORKER_MGMT[@]}"; do
        local host="${WORKER_MGMT[$i]}"
        local name="${WORKER_NAMES[$i]}"
        log "  -> ${name} (${host})..."
        ssh_node "$host" "mkdir -p '${LLAMA_BIN}'" 2>/dev/null || true
        scp -o ConnectTimeout=5 "$server_bin" "${SSH_USER}@${host}:${server_bin}"
        log "     ${name}: OK"
    done

    log "=========================================="
    log " BUILD + DISTRIBUTE COMPLETE"
    log "=========================================="
}

# ---------------------------------------------------------------------------
# ensure_llama_binaries — Build if llama-server missing
# ---------------------------------------------------------------------------
ensure_llama_binaries() {
    local server_bin="${LLAMA_BIN}/llama-server"
    if [[ ! -f "$server_bin" ]]; then
        log "llama-server not found — triggering build..."
        build_llama
        return
    fi
    log "llama-server already present at ${server_bin}"
}

# ---------------------------------------------------------------------------
# stop_all_inference — Kill llama-server (chat/embed), gateway Nginx, Ollama
# ---------------------------------------------------------------------------
stop_all_inference() {
    log "Stopping all inference processes and gateway..."

    # Gateway (Captain only)
    fuser -k -9 "${GATEWAY_PORT}/tcp" 2>/dev/null || true
    pkill -f "nginx.*fortress_legal_gateway" 2>/dev/null || true

    # Captain: chat + embed by port
    fuser -k -9 "${CHAT_PORT}/tcp" 2>/dev/null || true
    fuser -k -9 "${EMBED_PORT}/tcp" 2>/dev/null || true
    pkill -f "llama-server" 2>/dev/null || true

    for host in "${ALL_MGMT[@]}"; do
        ssh_node "$host" "
            fuser -k -9 ${CHAT_PORT}/tcp 2>/dev/null || true
            fuser -k -9 ${EMBED_PORT}/tcp 2>/dev/null || true
            pkill -f llama-server 2>/dev/null || true
            systemctl stop ollama 2>/dev/null || true
            pkill -f ollama 2>/dev/null || true
            true
        " || log "WARN: Could not reach ${host} for cleanup (continuing)"
    done
    sleep 2
    log "  All inference processes and gateway stopped."
}

# ---------------------------------------------------------------------------
# start_gateway — Start Nginx with fortress_legal_gateway.conf on Captain
# ---------------------------------------------------------------------------
start_gateway() {
    [[ -f "$NGINX_CONF" ]] || die "Gateway config not found: ${NGINX_CONF}"
    fuser -k -9 "${GATEWAY_PORT}/tcp" 2>/dev/null || true
    sleep 1
    if nginx -c "$NGINX_CONF" 2>/dev/null; then
        log "Gateway Nginx started (listen ${GATEWAY_PORT})"
    else
        # May already be running or need different invocation
        if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GATEWAY_PORT}/health" 2>/dev/null | grep -q 200; then
            log "Gateway already responding on :${GATEWAY_PORT}"
        else
            err "Failed to start gateway. Try: nginx -c ${NGINX_CONF}"
        fi
    fi
}

# ---------------------------------------------------------------------------
# launch_fortress_legal — Start chat + embed on each node, then gateway
# ---------------------------------------------------------------------------
launch_fortress_legal() {
    log "Starting Fortress Legal: chat (${CHAT_PORT}) + embed (${EMBED_PORT}) on all nodes..."

    # ---- Captain (local) ----
    log "Captain (${CAPTAIN_FABRIC}): starting chat server..."
    fuser -k -9 "${CHAT_PORT}/tcp" 2>/dev/null || true
    sleep 1
    nohup "${LLAMA_BIN}/llama-server" \
        --model "$CHAT_MODEL_PATH" \
        --host "$CAPTAIN_FABRIC" \
        --port "$CHAT_PORT" \
        --n-gpu-layers "$CHAT_GPU_LAYERS" \
        --ctx-size "$CHAT_CTX" \
        --parallel "$CHAT_PARALLEL" \
        --cont-batching \
        > "${LOG_DIR}/llama-chat-captain.log" 2>&1 &

    log "Captain: starting embed server..."
    fuser -k -9 "${EMBED_PORT}/tcp" 2>/dev/null || true
    sleep 1
    nohup "${LLAMA_BIN}/llama-server" \
        --model "$EMBED_MODEL_PATH" \
        --host "$CAPTAIN_FABRIC" \
        --port "$EMBED_PORT" \
        --n-gpu-layers "$EMBED_GPU_LAYERS" \
        --parallel "$EMBED_PARALLEL" \
        --cont-batching \
        > "${LOG_DIR}/llama-embed-captain.log" 2>&1 &

    # ---- Workers (SSH) ----
    for i in "${!WORKER_MGMT[@]}"; do
        local mgmt="${WORKER_MGMT[$i]}"
        local fabric="${WORKER_FABRIC[$i]}"
        local name="${WORKER_NAMES[$i]}"

        log "${name} (${fabric}): starting chat + embed..."
        ssh_node "$mgmt" "
            fuser -k -9 ${CHAT_PORT}/tcp 2>/dev/null || true
            fuser -k -9 ${EMBED_PORT}/tcp 2>/dev/null || true
            sleep 1
            nohup '${LLAMA_BIN}/llama-server' --model '${CHAT_MODEL_PATH}' --host '${fabric}' --port ${CHAT_PORT} \
                --n-gpu-layers ${CHAT_GPU_LAYERS} --ctx-size ${CHAT_CTX} --parallel ${CHAT_PARALLEL} --cont-batching \
                > '${LOG_DIR}/llama-chat-${name,,}.log' 2>&1 &
            sleep 2
            nohup '${LLAMA_BIN}/llama-server' --model '${EMBED_MODEL_PATH}' --host '${fabric}' --port ${EMBED_PORT} \
                --n-gpu-layers ${EMBED_GPU_LAYERS} --parallel ${EMBED_PARALLEL} --cont-batching \
                > '${LOG_DIR}/llama-embed-${name,,}.log' 2>&1 &
        " || err "  ${name}: failed to start"
    done

    log "Waiting for backends to accept connections..."
    local checks=0 max_checks=120
    while (( checks < max_checks )); do
        local c1 c2
        c1=$(curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${CHAT_PORT}/health" 2>/dev/null || echo "000")
        c2=$(curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${EMBED_PORT}/health" 2>/dev/null || echo "000")
        if [[ "$c1" == "200" || "$c1" == "503" ]] && [[ "$c2" == "200" || "$c2" == "503" ]]; then
            break
        fi
        sleep 5
        checks=$((checks + 1))
        if (( checks % 6 == 0 )); then
            log "  Still loading... (${checks}/${max_checks}, chat=${c1} embed=${c2})"
        fi
    done

    c1=$(curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${CHAT_PORT}/health" 2>/dev/null || echo "000")
    c2=$(curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${EMBED_PORT}/health" 2>/dev/null || echo "000")
    if [[ "$c1" != "200" && "$c1" != "503" ]] || [[ "$c2" != "200" && "$c2" != "503" ]]; then
        err "Captain backends not ready (chat=${c1} embed=${c2}). Check ${LOG_DIR}/llama-*.log"
    fi

    start_gateway

    # Gateway health
    sleep 2
    if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GATEWAY_PORT}/health" 2>/dev/null | grep -q 200; then
        log "Gateway HEALTHY at http://${CAPTAIN_FABRIC}:${GATEWAY_PORT}"
    else
        err "Gateway not responding on :${GATEWAY_PORT}"
    fi

    log "=========================================="
    log " FORTRESS LEGAL ACTIVE"
    log "  Gateway : http://${CAPTAIN_FABRIC}:${GATEWAY_PORT}/v1"
    log "  Chat    : ${CHAT_MODEL_PATH}"
    log "  Embed   : ${EMBED_MODEL_PATH}"
    log "  Context : ${CHAT_CTX}  Parallel : ${CHAT_PARALLEL}"
    log "=========================================="
}

# ---------------------------------------------------------------------------
# fortress_legal — DEFCON Fortress Legal: multi-model per-node + gateway
# ---------------------------------------------------------------------------
fortress_legal() {
    log "=========================================="
    log " FORTRESS PRIME: FORTRESS LEGAL MODE"
    log " Multi-model per-node (chat + embed), Nginx gateway"
    log "=========================================="

    check_gpu_safe
    ensure_llama_binaries

    [[ -f "$CHAT_MODEL_PATH" ]] || die "Chat model not found: ${CHAT_MODEL_PATH} — check NAS mount."
    [[ -f "$EMBED_MODEL_PATH" ]] || die "Embed model not found: ${EMBED_MODEL_PATH} — check NAS mount."

    stop_all_inference
    launch_fortress_legal
    persist_defcon "FORTRESS_LEGAL"
}

# ---------------------------------------------------------------------------
# swarm — DEFCON 5: Tear down Fortress Legal, restart Ollama
# ---------------------------------------------------------------------------
swarm() {
    log "=========================================="
    log " FORTRESS PRIME: SWARM MODE (DEFCON 5)"
    log "=========================================="

    stop_all_inference

    log "Starting Ollama on all nodes..."
    for host in "${ALL_MGMT[@]}"; do
        ssh_node "$host" \
            "systemctl start ollama 2>/dev/null || nohup ollama serve > '${LOG_DIR}/ollama.log' 2>&1 &" \
            || true
    done
    sleep 3

    persist_defcon "SWARM"

    log "=========================================="
    log " SWARM MODE ACTIVE (DEFCON 5)"
    log "  Nginx LB: http://${CAPTAIN_MGMT}/v1"
    log "=========================================="
}

# ---------------------------------------------------------------------------
# status — Print cluster health
# ---------------------------------------------------------------------------
status() {
    echo "============================================================"
    echo "  FORTRESS PRIME — DEFCON STATUS"
    echo "============================================================"

    local defcon="${FORTRESS_DEFCON:-UNKNOWN}"
    if [[ -f "$ENV_FILE" ]]; then
        defcon=$(grep -oP '^FORTRESS_DEFCON=\K.*' "$ENV_FILE" 2>/dev/null || echo "$defcon")
    fi

    echo ""
    echo "  DEFCON Level : ${defcon}"
    echo ""

    echo "  --- Captain (${CAPTAIN_FABRIC}) ---"
    echo "    GPU Temp   : $(gpu_temp_local)°C"
    echo -n "    Chat :${CHAT_PORT}  : "
    curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${CHAT_PORT}/health" 2>/dev/null | grep -q 200 && echo "UP" || echo "down"
    echo -n "    Embed :${EMBED_PORT} : "
    curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${EMBED_PORT}/health" 2>/dev/null | grep -q 200 && echo "UP" || echo "down"
    echo -n "    Gateway :${GATEWAY_PORT} : "
    curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${GATEWAY_PORT}/health" 2>/dev/null | grep -q 200 && echo "UP" || echo "down"
    if pgrep -f "ollama" >/dev/null 2>&1; then
        echo "    Ollama   : RUNNING"
    else
        echo "    Ollama   : stopped"
    fi

    for i in "${!WORKER_MGMT[@]}"; do
        local mgmt="${WORKER_MGMT[$i]}"
        local fabric="${WORKER_FABRIC[$i]}"
        local name="${WORKER_NAMES[$i]}"
        echo ""
        echo "  --- ${name} (${fabric}) ---"
        echo "    GPU Temp : $(gpu_temp_remote "$mgmt")°C"
        echo -n "    Chat :${CHAT_PORT}  : "
        curl -s -o /dev/null -w "%{http_code}" "http://${fabric}:${CHAT_PORT}/health" 2>/dev/null | grep -q 200 && echo "UP" || echo "down"
        echo -n "    Embed :${EMBED_PORT} : "
        curl -s -o /dev/null -w "%{http_code}" "http://${fabric}:${EMBED_PORT}/health" 2>/dev/null | grep -q 200 && echo "UP" || echo "down"
        if ssh_node "$mgmt" "pgrep -f ollama" >/dev/null 2>&1; then
            echo "    Ollama   : RUNNING"
        else
            echo "    Ollama   : stopped"
        fi
    done

    if [[ "$defcon" == "FORTRESS_LEGAL" ]]; then
        echo ""
        echo "  Fortress Legal Gateway : http://${CAPTAIN_FABRIC}:${GATEWAY_PORT}/v1"
    fi

    echo ""
    echo "============================================================"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "${1:-}" in
    swarm)            swarm ;;
    fortress_legal)   fortress_legal ;;
    status)           status ;;
    build)            check_gpu_safe; build_llama ;;
    *)
        echo "Usage: $0 {swarm|fortress_legal|status|build}"
        echo ""
        echo "  swarm          DEFCON 5 — Ollama via Nginx LB (production)"
        echo "  fortress_legal Multi-model per-node: chat :${CHAT_PORT}, embed :${EMBED_PORT}, gateway :${GATEWAY_PORT}"
        echo "  status         Show DEFCON level, processes, GPU temps"
        echo "  build          Build llama.cpp (CUDA, Blackwell-native); optionally distribute to workers"
        exit 1
        ;;
esac
