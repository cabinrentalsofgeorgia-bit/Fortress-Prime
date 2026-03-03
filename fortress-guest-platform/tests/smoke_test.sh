#!/usr/bin/env bash
# ============================================================================
# Fortress Guest Platform — Smoke Test Suite
# Run: bash tests/smoke_test.sh [BASE_URL]
# Curls every critical endpoint, reports PASS/FAIL with color + timing.
# ============================================================================
set -euo pipefail

BASE="${1:-http://localhost:8100}"
PASS=0
FAIL=0
WARN=0
RESULTS=()

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_header() { echo -e "\n${BOLD}${CYAN}=== $1 ===${NC}"; }

AUTH_TOKEN=""
do_login() {
    AUTH_TOKEN=$(curl -s -X POST "${BASE}/api/auth/login" \
        -H "Content-Type: application/json" \
        -d '{"email":"gary@cabin-rentals-of-georgia.com","password":"Fortress2026!"}' \
        2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
    if [ -n "$AUTH_TOKEN" ]; then
        echo -e "  ${GREEN}PASS${NC}  Login (got JWT)"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}FAIL${NC}  Login — could not authenticate"
        FAIL=$((FAIL + 1))
    fi
}

check() {
    local label="$1"
    local method="$2"
    local path="$3"
    local body="${4:-}"
    local expect_status="${5:-200}"

    local start_ms
    start_ms=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")

    local args=(-s -o /dev/null -w "%{http_code}" --max-time 15)
    [ -n "$AUTH_TOKEN" ] && args+=(-H "Authorization: Bearer $AUTH_TOKEN")
    if [ "$method" = "POST" ]; then
        args+=(-X POST -H "Content-Type: application/json")
        [ -n "$body" ] && args+=(-d "$body")
    fi

    local status
    status=$(curl "${args[@]}" "${BASE}${path}" 2>/dev/null || echo "000")

    local end_ms
    end_ms=$(date +%s%3N 2>/dev/null || python3 -c "import time; print(int(time.time()*1000))")
    local duration=$(( end_ms - start_ms ))

    if [ "$status" = "$expect_status" ]; then
        echo -e "  ${GREEN}PASS${NC}  ${label}  ${CYAN}${status}${NC}  ${duration}ms"
        PASS=$((PASS + 1))
        RESULTS+=("PASS|${label}|${status}|${duration}ms")
    elif [ "$status" = "000" ]; then
        echo -e "  ${RED}FAIL${NC}  ${label}  ${RED}CONNECTION REFUSED${NC}"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL|${label}|connection_refused|${duration}ms")
    else
        echo -e "  ${RED}FAIL${NC}  ${label}  expected=${expect_status} got=${RED}${status}${NC}  ${duration}ms"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL|${label}|${status}|${duration}ms")
    fi
}

check_ws() {
    local label="WebSocket /ws"
    local ws_url="${BASE/http/ws}/ws"
    if command -v websocat &>/dev/null; then
        timeout 3 websocat -1 "$ws_url" </dev/null &>/dev/null && {
            echo -e "  ${GREEN}PASS${NC}  ${label}  ${CYAN}connected${NC}"
            PASS=$((PASS + 1))
        } || {
            echo -e "  ${YELLOW}WARN${NC}  ${label}  ${YELLOW}could not connect (non-critical)${NC}"
            WARN=$((WARN + 1))
        }
    else
        echo -e "  ${YELLOW}SKIP${NC}  ${label}  ${YELLOW}websocat not installed${NC}"
        WARN=$((WARN + 1))
    fi
}

echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║     Fortress Guest Platform — Smoke Test Suite          ║"
echo "  ║     $(date '+%Y-%m-%d %H:%M:%S %Z')                            ║"
echo "  ║     Target: ${BASE}                      ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# --- Auth ---
log_header "Authentication"
do_login

# --- Health ---
log_header "Health Endpoints"
check "Basic health"               GET  "/health"
check "Deep health (DB+Redis)"     GET  "/health/deep"
check "Readiness probe"            GET  "/health/ready"

# --- Core Data ---
log_header "Core Data APIs"
check "List properties"            GET  "/api/properties/"
check "List reservations"          GET  "/api/reservations/"
check "List guests"                GET  "/api/guests/"
check "Arriving today"             GET  "/api/guests/arriving/today"
check "Departing today"            GET  "/api/guests/departing/today"
check "Dashboard stats"            GET  "/api/analytics/dashboard"

# --- Operations ---
log_header "Operations APIs"
check "Message threads"            GET  "/api/messages/threads"
check "Work orders"                GET  "/api/workorders/"
check "Housekeeping today"         GET  "/api/housekeeping/today"
check "Housekeeping week"          GET  "/api/housekeeping/week"

# --- Damage & Inspections ---
log_header "Damage Claims & Inspections"
check "Damage claims list"         GET  "/api/damage-claims/"
check "Damage claim stats"         GET  "/api/damage-claims/stats"
check "Inspection summary"         GET  "/api/inspections/summary"
check "Inspection history"         GET  "/api/inspections/history"

# --- Guest Experience ---
log_header "Guest Experience"
check "Guestbook guides"           GET  "/api/guestbook/"
check "Guestbook extras"           GET  "/api/guestbook/extras"
check "Review queue"               GET  "/api/review/queue"

# --- Utilities ---
log_header "Utilities & Services"
check "Utility service types"       GET  "/api/utilities/types"

# --- Integrations ---
log_header "Integrations & Channels"
check "Streamline status"          GET  "/api/integrations/streamline/status"
check "Channel manager status"     GET  "/api/channel-manager/status"

# --- AI ---
log_header "AI Endpoints"
check "AI ask"                     POST "/api/ai/ask" '{"question":"What is the occupancy rate?"}'

# --- Search ---
log_header "Search"
check "Global search"              GET  "/api/search/?q=cabin"

# --- WebSocket ---
log_header "WebSocket"
check_ws

# --- Summary ---
TOTAL=$((PASS + FAIL + WARN))
echo ""
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}PASS: ${PASS}${NC}  ${RED}FAIL: ${FAIL}${NC}  ${YELLOW}WARN: ${WARN}${NC}  TOTAL: ${TOTAL}"

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}ALL CRITICAL CHECKS PASSED${NC}"
else
    echo -e "  ${RED}${BOLD}${FAIL} CHECK(S) FAILED — REVIEW ABOVE${NC}"
fi
echo -e "${BOLD}════════════════════════════════════════════════════════════${NC}"
echo ""

exit "$FAIL"
