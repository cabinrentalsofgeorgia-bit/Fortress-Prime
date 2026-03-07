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
#   SWARM  (5) — Ollama via Nginx LB        ./switch_defcon.sh swarm
#   HYDRA  (3) — 70B model via RPC bridge   ./switch_defcon.sh hydra
#   TITAN  (1) — 671B model via RPC bridge  ./switch_defcon.sh titan
#
# Other:
#   ./switch_defcon.sh status   — Current mode, processes, GPU temps
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
ALL_MGMT=("$CAPTAIN_MGMT" "${WORKER_MGMT[@]}")

# Ports (REQUIREMENTS.md Section 2.3)
RPC_PORT="${RPC_PORT:-50052}"
API_PORT="${API_PORT:-8081}"

# Paths
LLAMA_SRC="${LLAMA_SRC:-$HOME/llama.cpp}"
LLAMA_BUILD="${LLAMA_SRC}/build"
LLAMA_BIN="${LLAMA_BUILD}/bin"

# HYDRA model (DEFCON 3 — 70B via RPC bridge, ~140 GB on NAS)
HYDRA_MODEL_PATH="${HYDRA_MODEL_PATH:-/mnt/fortress_nas/models/DeepSeek-R1-Distill-Qwen-70B.gguf}"
HYDRA_CTX="${HYDRA_CTX:-8192}"
HYDRA_PARALLEL="${HYDRA_PARALLEL:-2}"
HYDRA_GPU_LAYERS="${HYDRA_GPU_LAYERS:-999}"

# TITAN model (DEFCON 1 — 671B via RPC bridge, ~377 GB on NAS)
TITAN_MODEL_PATH="${TITAN_MODEL_PATH:-/mnt/fortress_nas/models/DeepSeek-R1-671B-Q4_K_M.gguf}"
TITAN_CTX="${TITAN_CTX:-8192}"
TITAN_PARALLEL="${TITAN_PARALLEL:-1}"
TITAN_GPU_LAYERS="${TITAN_GPU_LAYERS:-999}"

SSH_USER="${SSH_USER:-admin}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"
LOG_DIR="${LOG_DIR:-/tmp}"
mkdir -p "$LOG_DIR" 2>/dev/null || true

# Shared libraries live alongside binaries in LLAMA_BIN.
# RPC backend (libggml-rpc.so) is dynamically loaded at runtime;
# without this path the --rpc flag never registers.
LLAMA_LD="LD_LIBRARY_PATH=${LLAMA_BIN}:\${LD_LIBRARY_PATH:-}"

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
# build_llama — Clean-build llama.cpp with RPC + CUDA (CMake)
# Called automatically by hydra/titan if binaries are missing or stale.
# ---------------------------------------------------------------------------
build_llama() {
    log "=========================================="
    log " FORTRESS PRIME: BUILDING llama.cpp"
    log " Flags: GGML_RPC=ON  GGML_CUDA=ON"
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

    log "Running CMake configure..."
    cmake -B "$LLAMA_BUILD" -S "$LLAMA_SRC" \
        -DGGML_RPC=ON \
        -DGGML_CUDA=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES="native"

    local nproc
    nproc=$(nproc 2>/dev/null || echo 4)
    log "Building with ${nproc} parallel jobs..."
    cmake --build "$LLAMA_BUILD" --config Release -j"${nproc}"

    # CMake names the RPC server binary "rpc-server" (not "llama-rpc-server")
    local server_bin="${LLAMA_BIN}/llama-server"
    local rpc_bin="${LLAMA_BIN}/rpc-server"

    [[ -f "$server_bin" ]] || die "Build failed: llama-server not found at ${server_bin}"
    [[ -f "$rpc_bin"    ]] || die "Build failed: rpc-server not found at ${rpc_bin}"

    # RPC backend is a dynamic library — run with cwd=LLAMA_BIN so backend search finds libggml-rpc.so
    # Capture help output to avoid SIGPIPE when grep -q exits early (pipefail).
    local help_output
    help_output=$(cd "${LLAMA_BIN}" && LD_LIBRARY_PATH="${LLAMA_BIN}:${LD_LIBRARY_PATH:-}" "$server_bin" --help 2>&1 || true)
    if echo "$help_output" | grep -q -- '--rpc'; then
        log "CONFIRMED: --rpc flag recognized by llama-server (libggml-rpc.so loaded)"
    else
        die "llama-server built but --rpc flag NOT recognized. Check that libggml-rpc.so exists in ${LLAMA_BIN}"
    fi

    log "Binary sizes:"
    log "  llama-server: $(du -h "$server_bin" | cut -f1)"
    log "  rpc-server:   $(du -h "$rpc_bin"    | cut -f1)"

    # Collect shared libraries that worker nodes need alongside rpc-server
    local so_files=()
    for f in "${LLAMA_BIN}"/*.so; do
        [[ -f "$f" ]] && so_files+=("$f")
    done

    log "Distributing rpc-server + shared libraries to worker nodes..."
    for i in "${!WORKER_MGMT[@]}"; do
        local host="${WORKER_MGMT[$i]}"
        local name="${WORKER_NAMES[$i]}"
        log "  -> ${name} (${host})..."
        ssh_node "$host" "mkdir -p '${LLAMA_BIN}'" 2>/dev/null || true
        scp -o ConnectTimeout=5 "$rpc_bin" "${SSH_USER}@${host}:${rpc_bin}"
        for so in "${so_files[@]}"; do
            scp -o ConnectTimeout=5 "$so" "${SSH_USER}@${host}:${LLAMA_BIN}/$(basename "$so")"
        done
        log "     ${name}: OK"
    done

    log "=========================================="
    log " BUILD + DISTRIBUTE COMPLETE"
    log "=========================================="
}

# ---------------------------------------------------------------------------
# ensure_rpc_binaries — Build if binaries are missing or lack --rpc support
# ---------------------------------------------------------------------------
ensure_rpc_binaries() {
    local server_bin="${LLAMA_BIN}/llama-server"
    local rpc_bin="${LLAMA_BIN}/rpc-server"

    if [[ ! -f "$server_bin" ]] || [[ ! -f "$rpc_bin" ]]; then
        log "Binaries not found — triggering build..."
        build_llama
        return
    fi

    # Run with cwd=LLAMA_BIN so backend search finds libggml-rpc.so
    local help_output
    help_output=$(cd "${LLAMA_BIN}" && LD_LIBRARY_PATH="${LLAMA_BIN}:${LD_LIBRARY_PATH:-}" "$server_bin" --help 2>&1 || true)
    if ! echo "$help_output" | grep -q -- '--rpc'; then
        log "Existing llama-server lacks --rpc support — rebuilding..."
        build_llama
        return
    fi

    log "RPC-enabled binaries already present."
}

# ---------------------------------------------------------------------------
# stop_all_inference — Kill every inference process across the cluster
# ---------------------------------------------------------------------------
stop_all_inference() {
    log "Stopping all inference processes across cluster..."
    pkill -f "llama-server" 2>/dev/null || true
    for host in "${ALL_MGMT[@]}"; do
        ssh_node "$host" "pkill -f rpc-server 2>/dev/null; \
                          systemctl stop ollama 2>/dev/null; \
                          pkill -f ollama 2>/dev/null; true" \
            || log "WARN: Could not reach ${host} for cleanup (continuing)"
    done
    sleep 2
    log "  All inference processes stopped."
}

# ---------------------------------------------------------------------------
# launch_rpc_cluster — Start RPC servers on workers, llama-server on Captain
#   $1 = model path    $2 = ctx size    $3 = parallel    $4 = gpu layers
#   $5 = mode label (HYDRA / TITAN)
# ---------------------------------------------------------------------------
launch_rpc_cluster() {
    local model="$1" ctx="$2" par="$3" layers="$4" label="$5"

    # ---- RPC servers on workers ----
    log "Starting RPC servers on worker nodes (fabric :${RPC_PORT})..."
    for i in "${!WORKER_MGMT[@]}"; do
        local mgmt="${WORKER_MGMT[$i]}"
        local fabric="${WORKER_FABRIC[$i]}"
        local name="${WORKER_NAMES[$i]}"

        ssh_node "$mgmt" "pkill -f rpc-server 2>/dev/null; true" || true
        sleep 1

        log "  Starting rpc-server on ${name} (${fabric}:${RPC_PORT})..."
        ssh_node "$mgmt" "nohup env LD_LIBRARY_PATH='${LLAMA_BIN}' '${LLAMA_BIN}/rpc-server' \
            --host '${fabric}' \
            --port '${RPC_PORT}' \
            > '${LOG_DIR}/rpc-${name,,}.log' 2>&1 &"
        sleep 2

        if ssh_node "$mgmt" "pgrep -f rpc-server" >/dev/null 2>&1; then
            log "     ${name}: RUNNING"
        else
            err "     ${name}: FAILED — check ${LOG_DIR}/rpc-${name,,}.log on ${mgmt}"
        fi
    done

    # ---- llama-server on Captain ----
    log "Starting llama-server on Captain (${CAPTAIN_FABRIC}:${API_PORT})..."
    pkill -f llama-server 2>/dev/null || true
    sleep 1

    local rpc_targets="${MUSCLE_FABRIC}:${RPC_PORT},${OCULAR_FABRIC}:${RPC_PORT},${SOVEREIGN_FABRIC}:${RPC_PORT}"

    LD_LIBRARY_PATH="${LLAMA_BIN}:${LD_LIBRARY_PATH:-}" \
    GGML_BACKEND_PATH="${LLAMA_BIN}/libggml-rpc.so" \
    nohup "${LLAMA_BIN}/llama-server" \
        --model "$model" \
        --host "$CAPTAIN_FABRIC" \
        --port "$API_PORT" \
        --rpc "${rpc_targets}" \
        --n-gpu-layers "$layers" \
        --ctx-size "$ctx" \
        --parallel "$par" \
        > "${LOG_DIR}/llama-server.log" 2>&1 &

    local pid=$!
    log "  llama-server PID: ${pid}"
    log "  RPC targets: ${rpc_targets}"
    log "  Waiting for model load and health endpoint..."

    local checks=0 max_checks=180
    local code
    while (( checks < max_checks )); do
        code=$(curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${API_PORT}/health" 2>/dev/null || echo "000")
        if [[ "$code" == "200" || "$code" == "503" ]]; then
            break
        fi
        sleep 5
        checks=$((checks + 1))
        if (( checks % 12 == 0 )); then
            log "  Still loading model... (${checks}/${max_checks} checks, $((checks * 5))s elapsed)"
        fi
    done

    code=$(curl -s -o /dev/null -w "%{http_code}" "http://${CAPTAIN_FABRIC}:${API_PORT}/health" 2>/dev/null || echo "000")
    if [[ "$code" == "200" || "$code" == "503" ]]; then
        log "  llama-server HEALTHY at http://${CAPTAIN_FABRIC}:${API_PORT}"
    else
        err "  llama-server not responding after $((max_checks * 5))s"
        err "  Tail the log: tail -f ${LOG_DIR}/llama-server.log"
    fi

    log "=========================================="
    log " ${label} MODE ACTIVE"
    log "  Endpoint : http://${CAPTAIN_FABRIC}:${API_PORT}/v1"
    log "  Model    : ${model}"
    log "  RPC      : ${rpc_targets}"
    log "  Context  : ${ctx} tokens"
    log "  Parallel : ${par}"
    log "=========================================="
}

# ---------------------------------------------------------------------------
# hydra — DEFCON 3: Build (with RPC) + deploy 70B via RPC bridge
# ---------------------------------------------------------------------------
hydra() {
    log "=========================================="
    log " FORTRESS PRIME: HYDRA MODE (DEFCON 3)"
    log " 70B model via RPC bridge across 4 nodes"
    log "=========================================="

    check_gpu_safe

    ensure_rpc_binaries

    [[ -f "$HYDRA_MODEL_PATH" ]] || die "Model not found: ${HYDRA_MODEL_PATH} — check NAS mount (/mnt/fortress_nas)."

    stop_all_inference
    launch_rpc_cluster "$HYDRA_MODEL_PATH" "$HYDRA_CTX" "$HYDRA_PARALLEL" "$HYDRA_GPU_LAYERS" "HYDRA"
    persist_defcon "HYDRA"
}

# ---------------------------------------------------------------------------
# titan — DEFCON 1: Deploy 671B via RPC bridge (binaries must exist)
# ---------------------------------------------------------------------------
titan() {
    log "=========================================="
    log " FORTRESS PRIME: TITAN MODE (DEFCON 1)"
    log " DeepSeek-R1-671B across 4 nodes"
    log "=========================================="

    check_gpu_safe

    ensure_rpc_binaries

    [[ -f "$TITAN_MODEL_PATH" ]] || die "Model not found: ${TITAN_MODEL_PATH} — check NAS mount (/mnt/fortress_nas)."

    stop_all_inference
    launch_rpc_cluster "$TITAN_MODEL_PATH" "$TITAN_CTX" "$TITAN_PARALLEL" "$TITAN_GPU_LAYERS" "TITAN"
    persist_defcon "TITAN"
}

# ---------------------------------------------------------------------------
# swarm — DEFCON 5: Tear down RPC cluster, restart Ollama
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
    echo "    GPU Temp      : $(gpu_temp_local)°C"
    if pgrep -f "llama-server" >/dev/null 2>&1; then
        echo "    llama-server   : RUNNING (PID $(pgrep -of llama-server))"
    else
        echo "    llama-server   : stopped"
    fi
    if pgrep -f "ollama" >/dev/null 2>&1; then
        echo "    Ollama         : RUNNING"
    else
        echo "    Ollama         : stopped"
    fi

    for i in "${!WORKER_MGMT[@]}"; do
        local mgmt="${WORKER_MGMT[$i]}"
        local fabric="${WORKER_FABRIC[$i]}"
        local name="${WORKER_NAMES[$i]}"

        echo ""
        echo "  --- ${name} (${fabric}) ---"
        echo "    GPU Temp      : $(gpu_temp_remote "$mgmt")°C"
        if ssh_node "$mgmt" "pgrep -f rpc-server" >/dev/null 2>&1; then
            echo "    rpc-server     : RUNNING on :${RPC_PORT}"
        else
            echo "    rpc-server     : stopped"
        fi
        if ssh_node "$mgmt" "pgrep -f ollama" >/dev/null 2>&1; then
            echo "    Ollama         : RUNNING"
        else
            echo "    Ollama         : stopped"
        fi
    done

    if [[ "$defcon" == "HYDRA" ]] || [[ "$defcon" == "TITAN" ]]; then
        echo ""
        if curl -sf "http://${CAPTAIN_FABRIC}:${API_PORT}/health" >/dev/null 2>&1; then
            echo "  ${defcon} Health : ONLINE — http://${CAPTAIN_FABRIC}:${API_PORT}/v1"
        else
            echo "  ${defcon} Health : UNREACHABLE"
        fi
    fi

    echo ""
    echo "============================================================"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
case "${1:-}" in
    swarm)          swarm ;;
    hydra)          hydra ;;
    titan)          titan ;;
    status)         status ;;
    *)
        echo "Usage: $0 {swarm|hydra|titan|status}"
        echo ""
        echo "  swarm   DEFCON 5 — Ollama via Nginx LB (production)"
        echo "  hydra   DEFCON 3 — 70B model via RPC bridge (builds llama.cpp with RPC if needed)"
        echo "  titan   DEFCON 1 — 671B model via RPC bridge (strategic)"
        echo "  status  Show DEFCON level, processes, GPU temps"
        exit 1
        ;;
esac
