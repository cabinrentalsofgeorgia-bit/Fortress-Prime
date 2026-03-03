#!/usr/bin/env bash
# =============================================================================
# FORTRESS PRIME — Master Sovereign Audit Script
# =============================================================================
# Probes every node, database, daemon, and AI agent across the entire sovereign
# footprint. Compiles results into a single timestamped audit report suitable
# for legal counsel review.
#
# Run locally on Captain (Spark-01, 192.168.0.100):
#   bash fortress_audit.sh
#
# Run remotely from Mac Mini (Florida):
#   bash fortress_audit.sh --remote
#   # or: ssh admin@192.168.0.100 "cd ~/Fortress-Prime && bash fortress_audit.sh"
#
# Flags:
#   --remote    SSH to Captain and execute the audit there
#   --quick     Skip slow operations (full NAS tree, index dump)
# =============================================================================

set -o pipefail

# ── Remote mode: bounce to Captain and exit ──────────────────────────────────
if [[ "$1" == "--remote" ]]; then
    CAPTAIN="192.168.0.100"
    echo "Connecting to Captain ($CAPTAIN) ..."
    ssh -o ConnectTimeout=10 admin@"$CAPTAIN" \
        "cd ~/Fortress-Prime && bash fortress_audit.sh ${*:2}"
    exit $?
fi

QUICK=false
[[ "$*" == *"--quick"* ]] && QUICK=true

# ── Constants ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="$SCRIPT_DIR/audit_report_${TIMESTAMP}.txt"

SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no"

declare -A NODES=(
    [captain]="192.168.0.100"
    [muscle]="192.168.0.104"
    [ocular]="192.168.0.105"
    [sovereign]="192.168.0.106"
)
declare -A FABRIC=(
    [captain]="10.10.10.2"
    [muscle]="10.10.10.1"
    [ocular]="10.10.10.3"
    [sovereign]="10.10.10.4"
)
NODE_ORDER=(captain muscle ocular sovereign)

NAS_MOUNT="/mnt/fortress_nas"
MQTT_BROKER="192.168.0.50"
MQTT_PORT=1883

DB_MAIN="fortress_db"
DB_FGP="fortress_guest"

FAILED_SECTIONS=()
SECTION_NUM=0

# ── Helpers ──────────────────────────────────────────────────────────────────
banner() {
    SECTION_NUM=$((SECTION_NUM + 1))
    local label="SECTION ${SECTION_NUM}: $1"
    local line
    line=$(printf '=%.0s' $(seq 1 ${#label}))
    {
        echo ""
        echo "============================================================================"
        echo "  ${label}"
        echo "============================================================================"
    } >> "$REPORT"
}

fail_section() {
    echo "  [FAILED] $1" >> "$REPORT"
    FAILED_SECTIONS+=("Section ${SECTION_NUM}: $1")
}

remote_cmd() {
    local ip="$1"; shift
    ssh $SSH_OPTS admin@"$ip" "$@" 2>&1
}

safe_curl() {
    curl -sf --connect-timeout 5 --max-time 15 "$@" 2>&1
}

safe_psql() {
    local db="$1"; shift
    psql -d "$db" -t -A "$@" 2>&1
}

safe_psql_pretty() {
    local db="$1"; shift
    psql -d "$db" "$@" 2>&1
}

# ── Begin Report ─────────────────────────────────────────────────────────────
echo "FORTRESS PRIME — Sovereign Audit starting at $(date -u +%Y-%m-%dT%H:%M:%SZ) ..."
echo "Report: $REPORT"

cat > "$REPORT" <<HEADER
################################################################################
#                                                                              #
#            FORTRESS PRIME — SOVEREIGN INFRASTRUCTURE AUDIT REPORT            #
#                                                                              #
################################################################################
#
#  Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC
#  Host:      $(hostname)
#  Operator:  $(whoami)
#
################################################################################
HEADER

# =============================================================================
# SECTION 1: HEADER AND ENVIRONMENT
# =============================================================================
banner "HEADER AND ENVIRONMENT"
{
    echo ""
    echo "  Timestamp (UTC) : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "  Timestamp (Local): $(date)"
    echo "  Hostname         : $(hostname)"
    echo "  Kernel           : $(uname -r)"
    echo "  Architecture     : $(uname -m)"
    echo "  OS               : $(lsb_release -ds 2>/dev/null || cat /etc/os-release 2>/dev/null | head -1 || echo 'unknown')"
    echo ""

    echo "  --- DEFCON State ---"
    if [[ -f "$SCRIPT_DIR/.defcon_state" ]]; then
        echo "  $(cat "$SCRIPT_DIR/.defcon_state")"
    else
        echo "  .defcon_state file not found (defaulting to SWARM)"
    fi
    echo ""

    echo "  --- Git Status ---"
    cd "$SCRIPT_DIR" 2>/dev/null
    echo "  Branch     : $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'N/A')"
    echo "  Last Commit: $(git log -1 --format='%h %s (%ci)' 2>/dev/null || echo 'N/A')"
    echo "  Repo State : $(git status --porcelain 2>/dev/null | wc -l) uncommitted changes"
} >> "$REPORT"

# =============================================================================
# SECTION 2: CLUSTER HARDWARE (ALL 4 DGX NODES)
# =============================================================================
banner "CLUSTER HARDWARE (ALL 4 DGX SPARK NODES)"

for node in "${NODE_ORDER[@]}"; do
    ip="${NODES[$node]}"
    fabric_ip="${FABRIC[$node]}"
    {
        echo ""
        echo "  --- Node: ${node^^} ($ip) | Fabric: $fabric_ip ---"
    } >> "$REPORT"

    if [[ "$ip" == "${NODES[captain]}" ]]; then
        # Local node
        {
            echo "  CPU      : $(lscpu 2>/dev/null | grep 'Model name' | cut -d: -f2 | xargs || echo 'N/A')"
            echo "  Cores    : $(nproc 2>/dev/null || echo 'N/A')"
            echo "  RAM Total: $(free -h 2>/dev/null | awk '/Mem:/{print $2}' || echo 'N/A')"
            echo "  RAM Avail: $(free -h 2>/dev/null | awk '/Mem:/{print $7}' || echo 'N/A')"
            echo "  Disk:"
            df -h / /home 2>/dev/null | sed 's/^/    /'
            echo "  GPU:"
            if command -v nvidia-smi &>/dev/null; then
                nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu --format=csv,noheader 2>/dev/null | sed 's/^/    /'
            else
                echo "    nvidia-smi not available"
            fi
        } >> "$REPORT" 2>&1
    else
        # Remote node via SSH
        result=$(remote_cmd "$ip" "
            echo \"CPU      : \$(lscpu 2>/dev/null | grep 'Model name' | cut -d: -f2 | xargs || echo N/A)\";
            echo \"Cores    : \$(nproc 2>/dev/null || echo N/A)\";
            echo \"RAM Total: \$(free -h 2>/dev/null | awk '/Mem:/{print \$2}' || echo N/A)\";
            echo \"RAM Avail: \$(free -h 2>/dev/null | awk '/Mem:/{print \$7}' || echo N/A)\";
            echo \"Disk:\";
            df -h / /home 2>/dev/null | sed 's/^/  /';
            echo \"GPU:\";
            if command -v nvidia-smi &>/dev/null; then
                nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu --format=csv,noheader 2>/dev/null | sed 's/^/  /';
            else
                echo '  nvidia-smi not available';
            fi
        " 2>&1)
        if [[ $? -eq 0 ]]; then
            echo "$result" | sed 's/^/  /' >> "$REPORT"
        else
            fail_section "SSH to ${node^^} ($ip)"
            echo "  [UNREACHABLE] Could not SSH to $ip" >> "$REPORT"
        fi
    fi
done

# Fabric LAN ping test
{
    echo ""
    echo "  --- Fabric LAN Connectivity (200G RoCEv2) ---"
} >> "$REPORT"
for node in "${NODE_ORDER[@]}"; do
    fip="${FABRIC[$node]}"
    if ping -c1 -W2 "$fip" &>/dev/null; then
        echo "  ${node^^} ($fip): REACHABLE" >> "$REPORT"
    else
        echo "  ${node^^} ($fip): UNREACHABLE" >> "$REPORT"
    fi
done

# =============================================================================
# SECTION 3: NAS / SYNOLOGY VAULT
# =============================================================================
banner "NAS / SYNOLOGY VAULT"
{
    echo ""
    echo "  --- NFS Mount Verification ---"
    if findmnt -T "$NAS_MOUNT" &>/dev/null; then
        echo "  Status: MOUNTED"
        findmnt -T "$NAS_MOUNT" --output TARGET,SOURCE,FSTYPE,OPTIONS -n 2>/dev/null | sed 's/^/  /'
    else
        fail_section "NAS mount at $NAS_MOUNT"
        echo "  Status: NOT MOUNTED"
    fi
    echo ""

    echo "  --- NAS Disk Usage ---"
    df -hT 2>/dev/null | grep -E 'nfs|fortress_nas' | sed 's/^/  /' || echo "  No NFS mount found in df"
    echo ""

    if [[ -d "$NAS_MOUNT" ]]; then
        echo "  --- Key NAS Directories (depth 2) ---"
        for sector in sectors/legal backups nim_cache fortress_data; do
            target="$NAS_MOUNT/$sector"
            if [[ -d "$target" ]]; then
                echo "  [$sector]"
                if [[ "$QUICK" == "false" ]]; then
                    find "$target" -maxdepth 2 -type d 2>/dev/null | head -40 | sed 's/^/    /'
                else
                    ls -1 "$target" 2>/dev/null | head -20 | sed 's/^/    /'
                fi
                echo "    Files: $(find "$target" -type f 2>/dev/null | wc -l)"
            else
                echo "  [$sector] — directory not found"
            fi
            echo ""
        done

        echo "  --- Critical File Counts ---"
        for path in \
            "sectors/legal/owner-contracts" \
            "sectors/legal/prime-trust-23-11161" \
            "sectors/legal/fish-trap-suv2026000013"; do
            full="$NAS_MOUNT/$path"
            if [[ -d "$full" ]]; then
                echo "  $path: $(find "$full" -type f 2>/dev/null | wc -l) files"
            else
                echo "  $path: (not found)"
            fi
        done
    fi
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 4: DOCKER FLEET (ALL 4 NODES)
# =============================================================================
banner "DOCKER FLEET (ALL 4 NODES)"

TOTAL_CONTAINERS=0
for node in "${NODE_ORDER[@]}"; do
    ip="${NODES[$node]}"
    {
        echo ""
        echo "  --- ${node^^} ($ip) Docker Containers ---"
    } >> "$REPORT"

    if [[ "$ip" == "${NODES[captain]}" ]]; then
        docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}' 2>/dev/null | sed 's/^/  /' >> "$REPORT"
        count=$(docker ps -q 2>/dev/null | wc -l | xargs)
    else
        result=$(remote_cmd "$ip" "docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'" 2>&1)
        if [[ $? -eq 0 ]]; then
            echo "$result" | sed 's/^/  /' >> "$REPORT"
            count=$(echo "$result" | grep -c "Up" || true)
        else
            echo "  [UNREACHABLE]" >> "$REPORT"
            count=0
        fi
    fi
    count=${count:-0}
    TOTAL_CONTAINERS=$((TOTAL_CONTAINERS + count))
done

{
    echo ""
    echo "  --- Captain: Docker Volumes ---"
    docker system df -v 2>/dev/null | head -30 | sed 's/^/  /'
    echo ""
    echo "  --- Captain: Docker Networks ---"
    docker network ls --format 'table {{.Name}}\t{{.Driver}}\t{{.Scope}}' 2>/dev/null | sed 's/^/  /'
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 5: POSTGRESQL — fortress_db SCHEMA
# =============================================================================
banner "POSTGRESQL — fortress_db SCHEMA"
{
    echo ""
    echo "  --- Database Size ---"
    safe_psql "$DB_MAIN" -c "SELECT pg_size_pretty(pg_database_size('$DB_MAIN'));" | sed 's/^/  /'
    echo ""

    echo "  --- Schemas ---"
    safe_psql_pretty "$DB_MAIN" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast') ORDER BY schema_name;" | sed 's/^/  /'
    echo ""

    echo "  --- Tables with Row Counts ---"
    safe_psql_pretty "$DB_MAIN" -c "
        SELECT schemaname || '.' || relname AS table_name,
               n_live_tup AS row_count
        FROM pg_stat_user_tables
        ORDER BY schemaname, relname;" | sed 's/^/  /'
    echo ""

    if [[ "$QUICK" == "false" ]]; then
        echo "  --- Foreign Keys ---"
        safe_psql_pretty "$DB_MAIN" -c "
            SELECT tc.table_schema || '.' || tc.table_name AS table_name,
                   kcu.column_name,
                   ccu.table_schema || '.' || ccu.table_name AS references_table,
                   ccu.column_name AS references_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.table_schema, tc.table_name
            LIMIT 100;" | sed 's/^/  /'
        echo ""

        echo "  --- Index Count per Table (top 30) ---"
        safe_psql_pretty "$DB_MAIN" -c "
            SELECT schemaname || '.' || tablename AS table_name,
                   count(*) AS index_count
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog','information_schema')
            GROUP BY schemaname, tablename
            ORDER BY index_count DESC
            LIMIT 30;" | sed 's/^/  /'
    fi
} >> "$REPORT" 2>&1 || fail_section "PostgreSQL fortress_db"

# =============================================================================
# SECTION 6: POSTGRESQL — fortress_guest SCHEMA
# =============================================================================
banner "POSTGRESQL — fortress_guest SCHEMA"
{
    echo ""
    echo "  --- Database Size ---"
    safe_psql "$DB_FGP" -c "SELECT pg_size_pretty(pg_database_size('$DB_FGP'));" | sed 's/^/  /' 2>&1
    echo ""

    echo "  --- Tables with Row Counts ---"
    safe_psql_pretty "$DB_FGP" -c "
        SELECT schemaname || '.' || relname AS table_name,
               n_live_tup AS row_count
        FROM pg_stat_user_tables
        ORDER BY schemaname, relname;" | sed 's/^/  /'
    echo ""

    echo "  --- Financial Table Integrity ---"
    echo "  [trust_balance]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM trust_balance;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [reservations]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM reservations;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [owner_statements]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM owner_statements;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [properties]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM properties;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [guests]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM guests;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [damage_claims]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM damage_claims;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [rental_agreements]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM rental_agreements;" 2>/dev/null | sed 's/^/    rows: /'
    echo "  [messages]"
    safe_psql "$DB_FGP" -c "SELECT count(*) FROM messages;" 2>/dev/null | sed 's/^/    rows: /'
} >> "$REPORT" 2>&1 || fail_section "PostgreSQL fortress_guest"

# =============================================================================
# SECTION 7: QDRANT VECTOR DATABASE
# =============================================================================
banner "QDRANT VECTOR DATABASE"
{
    echo ""
    echo "  --- Collections Overview ---"
    collections_json=$(safe_curl "http://127.0.0.1:6333/collections")
    if [[ -n "$collections_json" ]]; then
        echo "$collections_json" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "$collections_json" | sed 's/^/  /'
    else
        fail_section "Qdrant (port 6333)"
        echo "  [UNREACHABLE] Qdrant not responding on port 6333"
    fi
    echo ""

    for coll in fortress_knowledge email_embeddings legal_library; do
        echo "  --- Collection Detail: $coll ---"
        detail=$(safe_curl "http://127.0.0.1:6333/collections/$coll")
        if [[ -n "$detail" ]]; then
            echo "$detail" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    r=d.get('result',{})
    print(f'  Vectors : {r.get(\"vectors_count\",\"?\"):>12}')
    print(f'  Points  : {r.get(\"points_count\",\"?\"):>12}')
    print(f'  Segments: {len(r.get(\"segments\",[])):>12}')
    print(f'  Status  : {r.get(\"status\",\"?\")}')
    cfg=r.get('config',{}).get('params',{}).get('vectors',{})
    if isinstance(cfg,dict) and 'size' in cfg:
        print(f'  Dim     : {cfg[\"size\"]}')
except: print('  (parse error)')
" 2>/dev/null
        else
            echo "  (not found or unreachable)"
        fi
        echo ""
    done
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 8: REDPANDA / KAFKA EVENT BUS
# =============================================================================
banner "REDPANDA / KAFKA EVENT BUS"
{
    echo ""
    RPANDA_CONTAINER=$(docker ps --filter "name=fortress-event-broker" --format '{{.Names}}' 2>/dev/null | head -1)
    if [[ -n "$RPANDA_CONTAINER" ]]; then
        echo "  Container: $RPANDA_CONTAINER (running)"
        echo ""

        echo "  --- Cluster Health ---"
        docker exec "$RPANDA_CONTAINER" rpk cluster health 2>/dev/null | sed 's/^/  /' || echo "  rpk health check failed"
        echo ""

        echo "  --- Topics ---"
        docker exec "$RPANDA_CONTAINER" rpk topic list 2>/dev/null | sed 's/^/  /' || echo "  rpk topic list failed"
        echo ""

        echo "  --- Consumer Groups ---"
        docker exec "$RPANDA_CONTAINER" rpk group list 2>/dev/null | sed 's/^/  /' || echo "  rpk group list failed"
    else
        fail_section "Redpanda event broker"
        echo "  [NOT RUNNING] Redpanda container not found"
    fi
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 9: ACTIVE DAEMONS AND SERVICES
# =============================================================================
banner "ACTIVE DAEMONS AND SERVICES"
{
    echo ""
    echo "  --- Key Processes ---"
    DAEMONS=(
        "master_console"
        "bare_metal_dashboard"
        "batch_classifier"
        "legal_case_manager"
        "fortress_sentinel"
        "claude_proxy"
        "uvicorn.*8100"
        "next.*3001"
        "payout_consumer"
        "iot_consumer"
        "revenue_consumer"
        "mining_rig"
    )
    for d in "${DAEMONS[@]}"; do
        pid=$(pgrep -f "$d" 2>/dev/null | head -1)
        if [[ -n "$pid" ]]; then
            echo "  [RUNNING] $d (PID: $pid)"
        else
            echo "  [  OFF  ] $d"
        fi
    done
    echo ""

    echo "  --- Port Listeners ---"
    PORTS=(3000 3001 3100 5100 6333 8001 8080 8085 8100 9090 9644 9800 9876 9877 9878)
    printf "  %-8s %-10s %s\n" "PORT" "STATUS" "PROCESS"
    printf "  %-8s %-10s %s\n" "--------" "----------" "-----------------------------"
    for port in "${PORTS[@]}"; do
        listener=$(ss -tlnp "sport = :$port" 2>/dev/null | tail -n +2 | head -1)
        if [[ -n "$listener" ]]; then
            proc=$(echo "$listener" | grep -oP 'users:\(\("\K[^"]+' || echo "unknown")
            printf "  %-8s %-10s %s\n" "$port" "LISTENING" "$proc"
        else
            printf "  %-8s %-10s %s\n" "$port" "CLOSED" "-"
        fi
    done
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 10: NGINX LOAD BALANCER
# =============================================================================
banner "NGINX LOAD BALANCER"
{
    echo ""
    NGINX_CONTAINER=$(docker ps --filter "name=wolfpack" --format '{{.Names}}' 2>/dev/null | head -1)
    if [[ -n "$NGINX_CONTAINER" ]]; then
        echo "  Container: $NGINX_CONTAINER (running)"
    else
        echo "  Container: (not found via 'wolfpack' filter)"
        NGINX_CONTAINER=$(docker ps --filter "name=nginx" --format '{{.Names}}' 2>/dev/null | head -1)
        if [[ -n "$NGINX_CONTAINER" ]]; then
            echo "  Fallback:  $NGINX_CONTAINER (running)"
        else
            echo "  [NOT RUNNING] No Nginx container found"
        fi
    fi
    echo ""

    echo "  --- Upstream Definitions (from wolfpack_ai.conf) ---"
    CONF="$SCRIPT_DIR/nginx/wolfpack_ai.conf"
    if [[ -f "$CONF" ]]; then
        grep -E '^\s*upstream |^\s*server ' "$CONF" 2>/dev/null | sed 's/^/  /'
    else
        echo "  (config file not found at $CONF)"
    fi
    echo ""

    echo "  --- Nginx Health Check ---"
    health=$(safe_curl "http://127.0.0.1/health")
    if [[ -n "$health" ]]; then
        echo "  /health: $health"
    else
        echo "  /health: UNREACHABLE"
    fi
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 11: CRONTAB / SCHEDULED OPERATIONS
# =============================================================================
banner "CRONTAB / SCHEDULED OPERATIONS"
{
    echo ""
    echo "  --- Container Cron (scheduler/crontab) ---"
    CRON_FILE="$SCRIPT_DIR/scheduler/crontab"
    if [[ -f "$CRON_FILE" ]]; then
        grep -v '^#' "$CRON_FILE" | grep -v '^$' | sed 's/^/  /'
    else
        echo "  (file not found)"
    fi
    echo ""

    echo "  --- Host Crontab (Captain) ---"
    crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$' | sed 's/^/  /' || echo "  (empty or not accessible)"
    echo ""

    for node in muscle ocular sovereign; do
        ip="${NODES[$node]}"
        echo "  --- Host Crontab (${node^^}, $ip) ---"
        result=$(remote_cmd "$ip" "crontab -l 2>/dev/null | grep -v '^#' | grep -v '^\$'" 2>&1)
        if [[ $? -eq 0 && -n "$result" ]]; then
            echo "$result" | sed 's/^/  /'
        else
            echo "  (empty or unreachable)"
        fi
        echo ""
    done
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 12: NVIDIA NIM / INFERENCE STATUS
# =============================================================================
banner "NVIDIA NIM / INFERENCE STATUS"
{
    echo ""
    echo "  --- NIM Containers (all nodes) ---"
    for node in "${NODE_ORDER[@]}"; do
        ip="${NODES[$node]}"
        echo "  [${node^^}]"
        if [[ "$ip" == "${NODES[captain]}" ]]; then
            docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -iE 'nim|ollama|deepseek|qwen' | sed 's/^/    /' || echo "    (none found)"
        else
            result=$(remote_cmd "$ip" "docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -iE 'nim|ollama|deepseek|qwen'" 2>&1)
            if [[ -n "$result" ]]; then
                echo "$result" | sed 's/^/    /'
            else
                echo "    (none found or unreachable)"
            fi
        fi
    done
    echo ""

    echo "  --- SWARM Endpoint (http://192.168.0.100/v1/models) ---"
    swarm=$(safe_curl "http://192.168.0.100/v1/models")
    if [[ -n "$swarm" ]]; then
        echo "$swarm" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for m in d.get('data',d.get('models',[])):
        name=m.get('id',m.get('model','?'))
        print(f'  Model: {name}')
except: print('  (parse error)')
" 2>/dev/null || echo "  $swarm" | head -5 | sed 's/^/  /'
    else
        echo "  [UNREACHABLE]"
    fi
    echo ""

    echo "  --- HYDRA Endpoint (http://192.168.0.100/hydra/v1/models) ---"
    hydra=$(safe_curl "http://192.168.0.100/hydra/v1/models")
    if [[ -n "$hydra" ]]; then
        echo "$hydra" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for m in d.get('data',d.get('models',[])):
        name=m.get('id',m.get('model','?'))
        print(f'  Model: {name}')
except: print('  (parse error)')
" 2>/dev/null || echo "  $hydra" | head -5 | sed 's/^/  /'
    else
        echo "  [UNREACHABLE or HYDRA not active]"
    fi
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 13: OPEN WEBUI / MISSION CONTROL
# =============================================================================
banner "OPEN WEBUI / MISSION CONTROL"
{
    echo ""
    MC_CONTAINER=$(docker ps --filter "name=mission_control" --format '{{.Names}} | {{.Status}}' 2>/dev/null | head -1)
    if [[ -n "$MC_CONTAINER" ]]; then
        echo "  Container: $MC_CONTAINER"
    else
        MC_CONTAINER=$(docker ps --filter "name=open-webui" --format '{{.Names}} | {{.Status}}' 2>/dev/null | head -1)
        if [[ -n "$MC_CONTAINER" ]]; then
            echo "  Container: $MC_CONTAINER"
        else
            echo "  [NOT RUNNING] Mission Control container not found"
        fi
    fi
    echo ""

    echo "  --- Health Check (port 8080) ---"
    mc_health=$(safe_curl "http://127.0.0.1:8080/health")
    if [[ -n "$mc_health" ]]; then
        echo "  Status: $mc_health"
    else
        http_code=$(curl -sf -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "http://127.0.0.1:8080/" 2>/dev/null)
        if [[ "$http_code" =~ ^[23] ]]; then
            echo "  Status: Responding (HTTP $http_code)"
        else
            echo "  Status: UNREACHABLE (HTTP $http_code)"
        fi
    fi
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 14: FGP BACKEND HEALTH
# =============================================================================
banner "FGP BACKEND HEALTH (PORT 8100)"
{
    echo ""
    echo "  --- Health Endpoint ---"
    fgp_health=$(safe_curl "http://127.0.0.1:8100/health")
    if [[ -n "$fgp_health" ]]; then
        echo "  $fgp_health" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "  $fgp_health"
    else
        fail_section "FGP Backend (port 8100)"
        echo "  [UNREACHABLE] FGP backend not responding"
    fi
    echo ""

    echo "  --- Streamline VRS Connection ---"
    sl_status=$(safe_curl "http://127.0.0.1:8100/api/integrations/streamline/status")
    if [[ -n "$sl_status" ]]; then
        echo "$sl_status" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || echo "  $sl_status"
    else
        echo "  [UNREACHABLE] Streamline status endpoint not responding"
    fi
    echo ""

    echo "  --- FGP Entity Counts (from fortress_guest DB) ---"
    for tbl in properties reservations guests damage_claims rental_agreements work_orders messages housekeeping_tasks guest_reviews; do
        cnt=$(safe_psql "$DB_FGP" -c "SELECT count(*) FROM $tbl;" 2>/dev/null | xargs)
        printf "  %-25s %s\n" "$tbl:" "${cnt:-error}"
    done
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 15: FGP FRONTEND HEALTH
# =============================================================================
banner "FGP FRONTEND HEALTH (PORT 3001)"
{
    echo ""
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "http://127.0.0.1:3001" 2>/dev/null)
    echo "  HTTP Status: $http_code"
    if [[ "$http_code" =~ ^[23] ]]; then
        echo "  Status: HEALTHY"
    else
        fail_section "FGP Frontend (port 3001)"
        echo "  Status: UNHEALTHY or UNREACHABLE"
    fi
    echo ""

    echo "  --- Next.js Build Info ---"
    BUILD_DIR="$SCRIPT_DIR/fortress-guest-platform/frontend-next/.next"
    if [[ -d "$BUILD_DIR" ]]; then
        echo "  .next directory: EXISTS"
        echo "  Last modified:   $(stat -c '%y' "$BUILD_DIR" 2>/dev/null || stat -f '%Sm' "$BUILD_DIR" 2>/dev/null || echo 'unknown')"
        BUILD_ID_FILE="$BUILD_DIR/BUILD_ID"
        if [[ -f "$BUILD_ID_FILE" ]]; then
            echo "  Build ID:        $(cat "$BUILD_ID_FILE")"
        fi
    else
        echo "  .next directory: NOT FOUND (build may be required)"
    fi
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 16: IOT SUBSYSTEM
# =============================================================================
banner "IOT SUBSYSTEM"
{
    echo ""
    echo "  --- MQTT Broker ($MQTT_BROKER:$MQTT_PORT) ---"
    if timeout 3 bash -c "echo >/dev/tcp/$MQTT_BROKER/$MQTT_PORT" 2>/dev/null; then
        echo "  Status: REACHABLE"
    else
        echo "  Status: UNREACHABLE"
    fi
    echo ""

    echo "  --- IoT Consumer Daemon ---"
    iot_pid=$(pgrep -f "iot_consumer_daemon" 2>/dev/null | head -1)
    if [[ -n "$iot_pid" ]]; then
        echo "  Status: RUNNING (PID: $iot_pid)"
    else
        iot_docker=$(docker ps --filter "name=iot-consumer" --format '{{.Names}} {{.Status}}' 2>/dev/null | head -1)
        if [[ -n "$iot_docker" ]]; then
            echo "  Status: RUNNING in Docker ($iot_docker)"
        else
            echo "  Status: NOT RUNNING"
        fi
    fi
    echo ""

    echo "  --- IoT Database Tables (fortress_guest) ---"
    for tbl in iot_schema.device_events iot_schema.digital_twins; do
        cnt=$(safe_psql "$DB_FGP" -c "SELECT count(*) FROM $tbl;" 2>/dev/null | xargs)
        if [[ -n "$cnt" && "$cnt" != *"ERROR"* ]]; then
            printf "  %-30s %s rows\n" "$tbl:" "$cnt"
        else
            printf "  %-30s %s\n" "$tbl:" "(table not found)"
        fi
    done
} >> "$REPORT" 2>&1

# =============================================================================
# SECTION 17: LEGAL COMMAND CENTER
# =============================================================================
banner "LEGAL COMMAND CENTER"
{
    echo ""
    echo "  --- Legal Case Manager (port 9878) ---"
    legal_health=$(safe_curl "http://127.0.0.1:9878/api/cases")
    if [[ -n "$legal_health" ]]; then
        echo "  Status: RESPONDING"
        echo "$legal_health" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    cases=d if isinstance(d,list) else d.get('cases',d.get('data',[]))
    if isinstance(cases,list):
        print(f'  Active Cases: {len(cases)}')
        for c in cases:
            slug=c.get('case_slug','?')
            status=c.get('status','?')
            print(f'    - {slug} [{status}]')
except: print('  (parse error)')
" 2>/dev/null
    else
        echo "  Status: UNREACHABLE (port 9878)"
    fi
    echo ""

    echo "  --- Legal Schema (fortress_db) ---"
    for tbl in legal.cases legal.case_actions legal.case_watchdog legal.case_evidence legal.correspondence legal.deadlines; do
        cnt=$(safe_psql "$DB_MAIN" -c "SELECT count(*) FROM $tbl;" 2>/dev/null | xargs)
        if [[ -n "$cnt" && "$cnt" != *"ERROR"* ]]; then
            printf "  %-30s %s rows\n" "$tbl:" "$cnt"
        else
            printf "  %-30s %s\n" "$tbl:" "(not found)"
        fi
    done
    echo ""

    echo "  --- Upcoming Deadlines ---"
    safe_psql_pretty "$DB_MAIN" -c "
        SELECT c.case_slug, d.deadline_type, d.due_date, d.status,
               CASE
                 WHEN d.due_date < CURRENT_DATE THEN 'OVERDUE'
                 WHEN d.due_date <= CURRENT_DATE + 3 THEN 'CRITICAL'
                 WHEN d.due_date <= CURRENT_DATE + 7 THEN 'URGENT'
                 ELSE 'NORMAL'
               END AS urgency
        FROM legal.deadlines d
        LEFT JOIN legal.cases c ON c.id = d.case_id
        WHERE d.status != 'completed'
        ORDER BY d.due_date
        LIMIT 20;" 2>/dev/null | sed 's/^/  /' || echo "  (no deadlines table or empty)"
} >> "$REPORT" 2>&1

# =============================================================================
# CLOSING: SUMMARY BLOCK
# =============================================================================
{
    echo ""
    echo "============================================================================"
    echo "  AUDIT SUMMARY"
    echo "============================================================================"
    echo ""

    TOTAL_TABLES_MAIN=$(safe_psql "$DB_MAIN" -c "SELECT count(*) FROM pg_stat_user_tables;" 2>/dev/null | xargs)
    TOTAL_TABLES_FGP=$(safe_psql "$DB_FGP" -c "SELECT count(*) FROM pg_stat_user_tables;" 2>/dev/null | xargs)

    TOTAL_VECTORS="unknown"
    coll_names=$(safe_curl "http://127.0.0.1:6333/collections" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for c in d.get('result',{}).get('collections',[]):
        print(c['name'])
except: pass
" 2>/dev/null)
    if [[ -n "$coll_names" ]]; then
        total_v=0
        while IFS= read -r cname; do
            pc=$(safe_curl "http://127.0.0.1:6333/collections/$cname" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('result',{}).get('points_count',0))
except: print(0)
" 2>/dev/null)
            total_v=$((total_v + ${pc:-0}))
        done <<< "$coll_names"
        TOTAL_VECTORS="$total_v"
    fi

    NAS_USAGE=$(df -h "$NAS_MOUNT" 2>/dev/null | tail -1 | awk '{print $3 " used / " $2 " total (" $5 ")"}')

    printf "  %-35s %s\n" "Total Docker Containers (running):" "$TOTAL_CONTAINERS"
    printf "  %-35s %s\n" "Total Tables (fortress_db):" "${TOTAL_TABLES_MAIN:-error}"
    printf "  %-35s %s\n" "Total Tables (fortress_guest):" "${TOTAL_TABLES_FGP:-error}"
    printf "  %-35s %s\n" "Total Vectors (Qdrant):" "$TOTAL_VECTORS"
    printf "  %-35s %s\n" "NAS Storage:" "${NAS_USAGE:-unknown}"
    echo ""

    if [[ ${#FAILED_SECTIONS[@]} -gt 0 ]]; then
        echo "  *** SECTIONS WITH FAILURES ***"
        for f in "${FAILED_SECTIONS[@]}"; do
            echo "    - $f"
        done
    else
        echo "  All sections completed successfully. No failures detected."
    fi
    echo ""

    echo "============================================================================"
    echo "  Report generated in $((SECONDS)) seconds"
    echo "  Output: $REPORT"
    echo "============================================================================"
} >> "$REPORT" 2>&1

echo ""
echo "Audit complete in ${SECONDS}s. Report saved to:"
echo "  $REPORT"
echo ""
if [[ ${#FAILED_SECTIONS[@]} -gt 0 ]]; then
    echo "WARNING: ${#FAILED_SECTIONS[@]} section(s) had failures:"
    for f in "${FAILED_SECTIONS[@]}"; do
        echo "  - $f"
    done
fi
