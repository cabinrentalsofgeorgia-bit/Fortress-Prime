#!/usr/bin/env bash
# =============================================================================
# FORTRESS PRIME — DEFCON MODE SWITCH (Teacher-Student Agentic Mesh)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------

# Pretty print header
hdr() { echo "$1"; }
# ENTERPRISE TOPOLOGY (128GB GB10 Architecture)
# ---------------------------------------------------------------------------
CAPTAIN_IP="127.0.0.1"       # Spark 2: Control Plane + Agentic Router
MUSCLE_IP="192.168.0.104"    # Spark 1: Apex Student Model (DeepSeek)
OCULAR_IP="192.168.0.105"    # Spark 3: Multimodal Vision (Docling)
SOVEREIGN_IP="192.168.0.106" # Spark 4: Audio/Speech (SenseVoice)

OLLAMA_PORT=11434
AGENT_MODEL="qwen2.5:32b"       # Runs on Spark 2 (The Fast Router)
STUDENT_MODEL="deepseek-r1:70b" # Runs on Spark 1 (The Local Heavy)

DEFCON_STATE="${SCRIPT_DIR}/.defcon_state"

# ---------------------------------------------------------------------------
# COLORS & LOGGING
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

remote() {
    local host="$1"; shift
    ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "admin@${host}" "$@" 2>/dev/null
}

on_node() {
    local ip="$1"; shift
    if [[ "$ip" == "127.0.0.1" ]]; then eval "$@"; else remote "$ip" "$@"; fi
}

get_current_mode() { [[ -f "$DEFCON_STATE" ]] && cat "$DEFCON_STATE" || echo "UNKNOWN"; }
set_mode() { echo "$1" > "$DEFCON_STATE"; log "DEFCON state: ${BOLD}$1${NC}"; }

ensure_ollama() {
    local ip="$1"; local name="$2"
    if curl -sf "http://${ip}:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1; then
        log "  ${name}: Ollama engine active"
    else
        on_node "$ip" "sudo systemctl start ollama 2>/dev/null || nohup ollama serve &>/dev/null &"
        sleep 3
        log "  ${name}: Ollama engine jumpstarted"
    fi
}

activate_mesh() {
    hdr "╔═══════════════════════════════════════════════════╗"
    hdr "║  ACTIVATING DEFCON 1 — AGENTIC MESH (Teacher/Student) ║"
    hdr "╚═══════════════════════════════════════════════════╝"
    
    ensure_ollama "$CAPTAIN_IP" "Spark-2 (Router)"
    ensure_ollama "$MUSCLE_IP" "Spark-1 (Student)"
    
    log "Loading Routing Agent (${AGENT_MODEL}) into Spark 2 VRAM..."
    curl -sf "http://${CAPTAIN_IP}:${OLLAMA_PORT}/api/generate" -d "{\"model\": \"${AGENT_MODEL}\", \"prompt\": \"Initialize routing protocol.\", \"stream\": false, \"options\": {\"num_predict\": 1}, \"keep_alive\": -1}" > /dev/null 2>&1 &

    log "Loading Heavy Student (${STUDENT_MODEL}) into Spark 1 VRAM..."
    curl -sf "http://${MUSCLE_IP}:${OLLAMA_PORT}/api/generate" -d "{\"model\": \"${STUDENT_MODEL}\", \"prompt\": \"Initialize reasoning matrix.\", \"stream\": false, \"options\": {\"num_predict\": 1}, \"keep_alive\": -1}" > /dev/null 2>&1 &

    sleep 3
    set_mode "AGENTIC-MESH"
    log "${BOLD}MESH ACTIVE${NC} — Spark 2 is routing. Spark 1 is reasoning. Frontier APIs on standby."
}

show_status() {
    echo -e "\n  Mode: ${BOLD}${GREEN}$(get_current_mode)${NC}\n"
    echo -e "  ${BOLD}INFERENCE MATRIX:${NC}"
    
    local s2_status="${RED}OFFLINE${NC}"; local s1_status="${RED}OFFLINE${NC}"
    curl -sf "http://${CAPTAIN_IP}:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1 && s2_status="${GREEN}Active${NC} (${AGENT_MODEL})"
    curl -sf "http://${MUSCLE_IP}:${OLLAMA_PORT}/api/tags" > /dev/null 2>&1 && s1_status="${GREEN}Active${NC} (${STUDENT_MODEL})"
    
    printf "    %-18s (%s): %b\n" "Spark-2 (Router)" "$CAPTAIN_IP" "$s2_status"
    printf "    %-18s (%s): %b\n" "Spark-1 (Student)" "$MUSCLE_IP" "$s1_status"
}

case "${1:-status}" in
    mesh|MESH|1) activate_mesh ;;
    status|STATUS|st) show_status ;;
    *) echo "Usage: $0 {mesh|status}"; exit 1 ;;
esac
