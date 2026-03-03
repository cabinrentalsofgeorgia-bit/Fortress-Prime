#!/usr/bin/env bash
# =============================================================================
# FORTRESS PRIME — DEFCON MODE SWITCH (Constitution Amendment IV-B)
# =============================================================================
# Single entry point for toggling between operational modes.
#
# MODES:
#   SWARM  (DEFCON 5) — Production. Ollama (qwen2.5:7b) x4 via Nginx LB.
#   HYDRA  (DEFCON 3) — Assault. Ollama (R1-70B) x4 parallel, preloaded.
#   TITAN  (DEFCON 1) — Strategic. R1-671B across 4 nodes via RPC.
#
# PLATFORM: DGX Spark (GB10 Grace Blackwell) = ARM64/aarch64
#   NVIDIA NIM containers are x86-only (as of 2026-02). Ollama provides
#   ARM64-native llama.cpp inference. HYDRA uses Ollama to serve R1-70B.
#   When ARM64 NIM ships, this script will be updated.
#
# USAGE:
#   ./switch_defcon.sh swarm       # Production mode
#   ./switch_defcon.sh hydra       # 4x R1-70B parallel (deep + fast)
#   ./switch_defcon.sh titan       # 671B pooled (deepest reasoning)
#   ./switch_defcon.sh status      # Show current mode and health
#
# Author: Fortress Prime Architect
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# CLUSTER TOPOLOGY (Ground Truth — matches config.py)
# ---------------------------------------------------------------------------
CAPTAIN_IP="192.168.0.100"
MUSCLE_IP="192.168.0.104"
OCULAR_IP="192.168.0.105"
SOVEREIGN_IP="192.168.0.106"

ALL_IPS=("$CAPTAIN_IP" "$MUSCLE_IP" "$OCULAR_IP" "$SOVEREIGN_IP")
NODE_NAMES=("Captain" "Muscle" "Ocular" "Sovereign")

# Fabric IPs (200G RoCEv2 NDR — compute path only)
FABRIC_CAPTAIN="10.10.10.2"
FABRIC_MUSCLE="10.10.10.1"
FABRIC_OCULAR="10.10.10.3"
FABRIC_SOVEREIGN="10.10.10.4"
FABRIC_IPS=("$FABRIC_CAPTAIN" "$FABRIC_MUSCLE" "$FABRIC_OCULAR" "$FABRIC_SOVEREIGN")

# Inference config
OLLAMA_PORT=11434
SWARM_MODEL="qwen2.5:7b"
HYDRA_MODEL="deepseek-r1:70b"

# TITAN Configuration (llama.cpp RPC — until ARM64 NIM ships for 671B)
LLAMA_SERVER="$HOME/Fortress-Prime/titan_engine/build/bin/llama-server"
RPC_SERVER="$HOME/Fortress-Prime/titan_engine/build/bin/rpc-server"
TITAN_MODEL="/mnt/fortress_nas/models/DeepSeek-R1-Q4_K_M/DeepSeek-R1-Q4_K_M/DeepSeek-R1-Q4_K_M-00001-of-00009.gguf"
TITAN_PORT=8080
RPC_PORT=50052

# Nginx configs
NGINX_SWARM_CONF="${SCRIPT_DIR}/nginx/wolfpack_swarm.conf"

# State file
DEFCON_STATE="${SCRIPT_DIR}/.defcon_state"

# ---------------------------------------------------------------------------
# COLORS
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

log()  { echo -e "${GREEN}[DEFCON]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; }
hdr()  { echo -e "${BOLD}${CYAN}$1${NC}"; }

# ---------------------------------------------------------------------------
# SSH HELPER
# ---------------------------------------------------------------------------
remote() {
    local host="$1"; shift
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes \
        "admin@${host}" "$@" 2>/dev/null
}

on_node() {
    local ip="$1"; shift
    if [[ "$ip" == "$CAPTAIN_IP" ]]; then
        eval "$@"
    else
        remote "$ip" "$@"
    fi
}

# ---------------------------------------------------------------------------
# STATE MANAGEMENT
# ---------------------------------------------------------------------------
get_current_mode() {
    [[ -f "$DEFCON_STATE" ]] && cat "$DEFCON_STATE" || echo "UNKNOWN"
}

set_mode() {
    echo "$1" > "$DEFCON_STATE"
    log "DEFCON state: ${BOLD}$1${NC}"
}

# ---------------------------------------------------------------------------
# CLEANUP: Stop TITAN bare-metal processes
# ---------------------------------------------------------------------------
stop_titan() {
    log "Stopping TITAN processes..."
    for i in "${!ALL_IPS[@]}"; do
        on_node "${ALL_IPS[$i]}" "pkill -f llama-server 2>/dev/null; pkill -f rpc-server 2>/dev/null" || true
    done
    sleep 1
}

# ---------------------------------------------------------------------------
# CLEANUP: Stop Ollama on all nodes
# ---------------------------------------------------------------------------
stop_ollama() {
    log "Stopping Ollama on all nodes..."
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local name="${NODE_NAMES[$i]}"
        on_node "$ip" "systemctl stop ollama 2>/dev/null || pkill -f 'ollama serve' 2>/dev/null" || true
        log "  ${name}: ${DIM}Ollama stopped${NC}"
    done
    sleep 2
}

# ---------------------------------------------------------------------------
# HELPER: Ensure Ollama is running on a node
# ---------------------------------------------------------------------------
ensure_ollama() {
    local ip="$1"
    local name="$2"
    if curl -sf "http://${ip}:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1; then
        log "  ${name}: Ollama running"
    else
        on_node "$ip" "systemctl start ollama 2>/dev/null || nohup ollama serve &>/dev/null &"
        sleep 3
        log "  ${name}: Ollama started"
    fi
}

# ---------------------------------------------------------------------------
# HELPER: Check if a model is loaded in Ollama VRAM on a node
# ---------------------------------------------------------------------------
is_model_loaded() {
    local ip="$1"
    local model="$2"
    curl -sf "http://${ip}:${OLLAMA_PORT}/api/ps" 2>/dev/null | \
        python3 -c "
import sys,json
try:
    models = [m['name'] for m in json.load(sys.stdin).get('models',[])]
    print('YES' if '${model}' in models else 'NO')
except:
    print('NO')
" 2>/dev/null || echo "NO"
}

# ---------------------------------------------------------------------------
# HELPER: Check if a model is pulled (downloaded) on a node
# ---------------------------------------------------------------------------
is_model_available() {
    local ip="$1"
    local model="$2"
    curl -sf "http://${ip}:${OLLAMA_PORT}/api/tags" 2>/dev/null | \
        python3 -c "
import sys,json
try:
    models = [m['name'] for m in json.load(sys.stdin).get('models',[])]
    print('YES' if '${model}' in models else 'NO')
except:
    print('NO')
" 2>/dev/null || echo "NO"
}

# ===========================================================================
# SWARM MODE (DEFCON 5) — Production
# ===========================================================================
activate_swarm() {
    hdr "╔═══════════════════════════════════════════════════╗"
    hdr "║  ACTIVATING DEFCON 5 — SWARM MODE (Production)   ║"
    hdr "║  Engine: Ollama (qwen2.5:7b) x4 via Nginx LB    ║"
    hdr "╚═══════════════════════════════════════════════════╝"

    stop_titan

    # Start Ollama on all nodes
    for i in "${!ALL_IPS[@]}"; do
        ensure_ollama "${ALL_IPS[$i]}" "${NODE_NAMES[$i]}"
    done

    # Swap Nginx to SWARM upstreams
    if [[ -f "$NGINX_SWARM_CONF" ]]; then
        docker cp "$NGINX_SWARM_CONF" wolfpack-lb:/etc/nginx/conf.d/default.conf 2>/dev/null || true
        docker exec wolfpack-lb nginx -s reload 2>/dev/null || true
        log "Nginx LB → SWARM upstreams (:${OLLAMA_PORT})"
    fi

    set_mode "SWARM"

    echo ""
    log "${BOLD}SWARM MODE ACTIVE${NC}"
    log "  Endpoint:   http://${CAPTAIN_IP}/v1/chat/completions"
    log "  Embeddings: http://${CAPTAIN_IP}/api/embeddings"
    log "  Model:      ${SWARM_MODEL} (load-balanced x4)"
    log "  Throughput:  ~5,000 tasks/min"
}

# ===========================================================================
# HYDRA MODE (DEFCON 3) — 4x R1-70B via Ollama (ARM64-native)
# ===========================================================================
# NOTE: NVIDIA NIM does not ship ARM64 images for LLMs (as of 2026-02).
# DGX Spark (GB10 Grace Blackwell) is aarch64. Ollama uses llama.cpp
# compiled natively on each node. When ARM64 NIM ships, this will update.
# ---------------------------------------------------------------------------
activate_hydra() {
    hdr "╔═══════════════════════════════════════════════════╗"
    hdr "║  ACTIVATING DEFCON 3 — HYDRA MODE (Assault)      ║"
    hdr "║  Engine: Ollama (DeepSeek-R1-70B) x4 nodes       ║"
    hdr "║  Runtime: ARM64-native llama.cpp (GB10 Blackwell) ║"
    hdr "╚═══════════════════════════════════════════════════╝"

    # Stop competing GPU workloads (TITAN)
    stop_titan

    # ── Ensure Ollama running on all nodes ──
    log ""
    for i in "${!ALL_IPS[@]}"; do
        ensure_ollama "${ALL_IPS[$i]}" "${NODE_NAMES[$i]}"
    done

    # ── Verify R1-70B is pulled on all nodes ──
    log ""
    log "Checking ${HYDRA_MODEL} availability..."
    local missing=0
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local name="${NODE_NAMES[$i]}"
        local available
        available=$(is_model_available "$ip" "$HYDRA_MODEL")

        if [[ "$available" == "YES" ]]; then
            log "  ${name}: ${GREEN}${HYDRA_MODEL} ready${NC}"
        else
            warn "  ${name}: ${HYDRA_MODEL} not found — initiating pull..."
            on_node "$ip" "nohup ollama pull ${HYDRA_MODEL} > /tmp/ollama-pull-hydra.log 2>&1 &"
            missing=$((missing + 1))
        fi
    done

    if [[ $missing -gt 0 ]]; then
        warn ""
        warn "  ${missing} node(s) pulling ${HYDRA_MODEL} (~42.5 GB each)."
        warn "  Monitor: ssh admin@<ip> tail -f /tmp/ollama-pull-hydra.log"
        warn "  Re-run './switch_defcon.sh hydra' after pulls complete."
        echo ""
        set_mode "HYDRA"
        return
    fi

    # ── Pre-load R1-70B into VRAM on every node ──
    log ""
    log "Loading ${HYDRA_MODEL} into GPU memory (42.5 GB per node)..."
    log "  128GB unified memory → ~85 GB headroom after model load"
    log ""

    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local name="${NODE_NAMES[$i]}"

        # Warm-up request to load model; keep_alive=-1 keeps it resident
        curl -sf "http://${ip}:${OLLAMA_PORT}/api/generate" \
            -d "{\"model\": \"${HYDRA_MODEL}\", \"prompt\": \"ping\", \"stream\": false, \"options\": {\"num_predict\": 1}, \"keep_alive\": -1}" \
            > /dev/null 2>&1 &

        log "  ${name}: Loading into VRAM..."
    done

    # ── Poll for all 4 heads loaded ──
    local max_wait=300   # 5 min (70B loads in ~30-60s per node)
    local interval=10
    local elapsed=0
    local healthy=0

    while [[ $elapsed -lt $max_wait ]]; do
        healthy=0
        for i in "${!ALL_IPS[@]}"; do
            local loaded
            loaded=$(is_model_loaded "${ALL_IPS[$i]}" "$HYDRA_MODEL")
            [[ "$loaded" == "YES" ]] && healthy=$((healthy + 1))
        done

        if [[ $healthy -ge 4 ]]; then
            log "  ${GREEN}ALL 4 HEADS LOADED${NC}"
            break
        fi

        log "  ${healthy}/4 heads in VRAM (${elapsed}s)..."
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    # ── Nginx stays on Ollama upstreams (same port, different model) ──
    if [[ -f "$NGINX_SWARM_CONF" ]]; then
        docker cp "$NGINX_SWARM_CONF" wolfpack-lb:/etc/nginx/conf.d/default.conf 2>/dev/null || true
        docker exec wolfpack-lb nginx -s reload 2>/dev/null || true
        log "Nginx LB → Ollama upstreams (:${OLLAMA_PORT})"
    fi

    set_mode "HYDRA"

    echo ""
    log "${BOLD}HYDRA MODE ACTIVE (${healthy}/4 heads loaded)${NC}"
    log ""
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local name="${NODE_NAMES[$i]}"
        local status="${RED}LOADING${NC}"
        local loaded
        loaded=$(is_model_loaded "$ip" "$HYDRA_MODEL")
        [[ "$loaded" == "YES" ]] && status="${GREEN}R1-70B LOADED${NC}"
        log "  ${name} (${ip}): [${status}]"
    done
    log ""
    log "  API:    http://${CAPTAIN_IP}/v1/chat/completions"
    log "  Model:  ${HYDRA_MODEL} (specify in request body)"
    log "  LB:    Nginx least_conn across 4 nodes"
    log ""
    log "  Test:"
    log "    curl http://${CAPTAIN_IP}/v1/chat/completions \\"
    log "      -d '{\"model\":\"${HYDRA_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
    log ""
    log "  NOTE: Embeddings still available at http://${CAPTAIN_IP}/api/embeddings"

    if [[ $healthy -lt 4 ]]; then
        warn "  ${healthy}/4 heads loaded. Others may still be loading."
        warn "  Check: ./switch_defcon.sh status"
    fi
}

# ===========================================================================
# TITAN MODE (DEFCON 1) — 671B via llama.cpp RPC
# ===========================================================================
activate_titan() {
    hdr "╔═══════════════════════════════════════════════════╗"
    hdr "║  ACTIVATING DEFCON 1 — TITAN MODE (Strategic)    ║"
    hdr "║  Engine: DeepSeek-R1-671B via llama.cpp RPC      ║"
    hdr "║  RAM: 460GB pooled across 4 nodes (fabric)       ║"
    hdr "╚═══════════════════════════════════════════════════╝"

    if [[ ! -f "$TITAN_MODEL" ]]; then
        err "671B model not found: $TITAN_MODEL"
        exit 1
    fi

    local snapshot_dir="/mnt/fortress_nas/backups"
    if [[ -d "$snapshot_dir" ]] && ls "$snapshot_dir"/GOLDEN_STATE_* &>/dev/null; then
        log "Golden Snapshot verified."
    else
        warn "Golden Snapshot not found. Proceeding without rollback point."
    fi

    # Stop everything — TITAN needs all 4 nodes' full RAM
    stop_titan
    stop_ollama
    sleep 3

    # Launch RPC servers on workers (over 200G fabric)
    log "Launching RPC servers on fabric network..."
    for i in 1 2 3; do
        local ip="${ALL_IPS[$i]}"
        local name="${NODE_NAMES[$i]}"
        local fabric="${FABRIC_IPS[$i]}"

        remote "$ip" "nohup ${RPC_SERVER} --host 0.0.0.0 --port ${RPC_PORT} > /tmp/rpc-${name,,}.log 2>&1 &"
        log "  ${name}: RPC on ${fabric}:${RPC_PORT}"
    done
    sleep 3

    local rpc_list="${FABRIC_MUSCLE}:${RPC_PORT},${FABRIC_OCULAR}:${RPC_PORT},${FABRIC_SOVEREIGN}:${RPC_PORT}"

    log "Launching TITAN server on Captain..."
    nohup ${LLAMA_SERVER} \
        --model "${TITAN_MODEL}" \
        --host 0.0.0.0 \
        --port ${TITAN_PORT} \
        --rpc "${rpc_list}" \
        --ctx-size 8192 \
        --n-gpu-layers 99 \
        --parallel 1 \
        --mlock \
        --flash-attn \
        > /tmp/titan-captain.log 2>&1 &

    set_mode "TITAN"

    echo ""
    log "${BOLD}TITAN MODE ACTIVATING${NC}"
    log "  Endpoint:  http://${FABRIC_CAPTAIN}:${TITAN_PORT}/v1/chat/completions"
    log "  Model:     DeepSeek-R1-671B (Q4_K_M, 377GB)"
    log "  Context:   8,192 tokens"
    log "  Parallel:  1 (single deep query)"
    log "  RPC:       ${rpc_list}"
    log ""
    warn "  Model load: 3-5 min (377GB across 200G fabric)."
    log "  Monitor: tail -f /tmp/titan-captain.log"
}

# ===========================================================================
# STATUS
# ===========================================================================
show_status() {
    local mode
    mode=$(get_current_mode)

    echo ""
    hdr "╔═══════════════════════════════════════════════════╗"
    hdr "║         FORTRESS PRIME — DEFCON STATUS            ║"
    hdr "╚═══════════════════════════════════════════════════╝"
    echo -e "  Mode: ${BOLD}${GREEN}${mode}${NC}"
    echo ""

    echo -e "  ${BOLD}FLEET:${NC}"
    for i in "${!ALL_IPS[@]}"; do
        local ip="${ALL_IPS[$i]}"
        local name="${NODE_NAMES[$i]}"
        local engines=""

        # Check Ollama
        if curl -sf "http://${ip}:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1; then
            # Check what model is loaded
            local loaded_model
            loaded_model=$(curl -sf "http://${ip}:${OLLAMA_PORT}/api/ps" 2>/dev/null | \
                python3 -c "
import sys,json
try:
    models = json.load(sys.stdin).get('models',[])
    if models:
        print(models[0]['name'])
    else:
        print('idle')
except:
    print('?')
" 2>/dev/null || echo "?")
            engines+="${GREEN}Ollama${NC}(${loaded_model}) "
        fi

        # Check llama-server (TITAN)
        if curl -sf "http://${ip}:${TITAN_PORT}/health" > /dev/null 2>&1; then
            engines+="${GREEN}TITAN:${TITAN_PORT}${NC} "
        fi

        [[ -z "$engines" ]] && engines="${RED}OFFLINE${NC}"
        printf "    %-12s (%s): %b\n" "$name" "$ip" "$engines"
    done

    echo ""
    echo -e "  ${BOLD}SERVICES:${NC}"

    # Qdrant
    if curl -sf "http://localhost:6333/collections" > /dev/null 2>&1; then
        local cols
        cols=$(curl -sf "http://localhost:6333/collections" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('result',{}).get('collections',[])))" 2>/dev/null || echo "?")
        echo -e "    Qdrant:    ${GREEN}UP (${cols} collections)${NC}"
    else
        echo -e "    Qdrant:    ${RED}DOWN${NC}"
    fi

    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q wolfpack-lb; then
        echo -e "    Nginx LB:  ${GREEN}UP${NC}"
    else
        echo -e "    Nginx LB:  ${RED}DOWN${NC}"
    fi

    if pg_isready -h "$CAPTAIN_IP" -p 5432 > /dev/null 2>&1; then
        echo -e "    Postgres:  ${GREEN}UP${NC}"
    else
        echo -e "    Postgres:  ${RED}DOWN${NC}"
    fi

    echo ""
    hdr "═══════════════════════════════════════════════════"
}

# ===========================================================================
# MAIN
# ===========================================================================
case "${1:-status}" in
    swarm|SWARM|5)
        activate_swarm ;;
    hydra|HYDRA|3)
        activate_hydra ;;
    titan|TITAN|1)
        activate_titan ;;
    status|STATUS|st)
        show_status ;;
    *)
        echo ""
        echo "FORTRESS PRIME — DEFCON Mode Switch"
        echo ""
        echo "Usage: $0 {swarm|hydra|titan|status}"
        echo ""
        echo "  swarm  (DEFCON 5) — Ollama qwen2.5:7b x4, Nginx LB"
        echo "  hydra  (DEFCON 3) — Ollama R1-70B x4, preloaded in VRAM"
        echo "  titan  (DEFCON 1) — R1-671B pooled via RPC (all 4 nodes)"
        echo "  status — Fleet health and active model per node"
        echo ""
        exit 1 ;;
esac
