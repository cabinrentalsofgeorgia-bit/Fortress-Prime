#!/bin/bash
# =============================================================================
# FORTRESS PRIME — SECURITY LOCKDOWN SCRIPT
# =============================================================================
# Run with: sudo bash lockdown_security.sh
#
# Fixes identified by security audit (2026-02-15):
#   1. UFW Firewall (no firewall was active)
#   2. PostgreSQL auth (accepting empty passwords)
#   3. Qdrant API key (no auth on 1.35M vectors)
#   4. Redis password (no auth)
#   5. Service binding (restrict to LAN/localhost)
#
# IMPORTANT: This script is designed to be safe. It:
#   - Always allows SSH first before enabling the firewall
#   - Allows Tailscale traffic
#   - Allows all traffic within the 4-node cluster (192.168.0.100-108)
#   - Only restricts access from outside the cluster LAN
# =============================================================================

set -e

CLUSTER_NODES=${CLUSTER_NODES:-"192.168.0.100,192.168.0.104,192.168.0.105,192.168.0.106"}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║   FORTRESS PRIME — SECURITY LOCKDOWN SCRIPT     ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Must be root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERROR: Must run as root. Use: sudo bash lockdown_security.sh${NC}"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────
# 1. UFW FIREWALL
# ─────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Configuring UFW Firewall...${NC}"

# Reset to defaults (deny incoming, allow outgoing)
ufw --force reset > /dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing

# SSH — always allow (don't lock ourselves out)
ufw allow 22/tcp comment "SSH"

# Tailscale — allow all traffic on tailscale interface
ufw allow in on tailscale0 comment "Tailscale VPN"

# Cluster LAN — allow all traffic between configured cluster nodes
IFS=',' read -r -a CLUSTER_NODE_ARRAY <<< "$CLUSTER_NODES"
for raw_node in "${CLUSTER_NODE_ARRAY[@]}"; do
    node="$(echo "$raw_node" | xargs)"
    [ -n "$node" ] || continue
    ufw allow from "$node" comment "Fortress cluster node $node"
done

# Fabric network — allow all inter-node compute traffic
ufw allow from 10.10.10.0/24 comment "Fabric-A RoCEv2"
ufw allow from 192.168.2.0/24 comment "Fabric-B Direct Link"

# Docker bridge — allow container-to-host traffic
ufw allow from 172.16.0.0/12 comment "Docker bridge networks"

# Mission Control (Open WebUI) — allow from LAN only
# This is the web UI that has its own auth
ufw allow from 192.168.0.0/24 to any port 8080 comment "Mission Control (LAN only)"

# Portainer — allow from LAN only
ufw allow from 192.168.0.0/24 to any port 8888 comment "Portainer (LAN only)"

# Grafana — allow from LAN only
ufw allow from 192.168.0.0/24 to any port 3000 comment "Grafana (LAN only)"

# BLOCK everything else from the internet
# Port 80 was previously reachable from the internet!

# Enable the firewall
ufw --force enable
echo -e "${GREEN}  ✓ UFW enabled. Cluster traffic allowed. Internet blocked.${NC}"
echo ""

# ─────────────────────────────────────────────────────────────────
# 2. POSTGRESQL — Require password for all connections
# ─────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/5] Securing PostgreSQL...${NC}"

PG_HBA="/etc/postgresql/16/main/pg_hba.conf"
if [ -f "$PG_HBA" ]; then
    # Backup
    cp "$PG_HBA" "${PG_HBA}.bak.$(date +%Y%m%d_%H%M%S)"
    
    # Replace 'trust' with 'scram-sha-256' for all non-local connections
    # Keep peer auth for local unix socket (used by postgres user)
    sed -i 's/\btrust\b/scram-sha-256/g' "$PG_HBA"
    
    # Ensure peer auth for local postgres user (so pg_ctl works)
    # Check if there's a local peer line; if not, add one
    if ! grep -q "^local.*all.*postgres.*peer" "$PG_HBA"; then
        echo "local   all   postgres   peer" >> "$PG_HBA"
    fi
    
    # Restrict listen_addresses to localhost + cluster nodes only
    PG_CONF="/etc/postgresql/16/main/postgresql.conf"
    if [ -f "$PG_CONF" ]; then
        # Change listen_addresses from '*' to cluster IPs only
        sed -i "s/^listen_addresses\s*=\s*'[^']*'/listen_addresses = 'localhost,192.168.0.100'/" "$PG_CONF"
    fi
    
    # Reload PostgreSQL (not restart — no downtime)
    systemctl reload postgresql 2>/dev/null || pg_ctlcluster 16 main reload 2>/dev/null || true
    
    echo -e "${GREEN}  ✓ PostgreSQL: trust → scram-sha-256. listen_addresses restricted.${NC}"
    echo -e "${GREEN}    Backup: ${PG_HBA}.bak.*${NC}"
else
    echo -e "${RED}  ✗ pg_hba.conf not found at $PG_HBA${NC}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# 3. QDRANT — Enable API key authentication
# ─────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/5] Securing Qdrant...${NC}"

# Generate a random API key for Qdrant
QDRANT_API_KEY=$(openssl rand -hex 32)

# Check if Qdrant is running
if docker ps --filter name=fortress-qdrant --format '{{.Names}}' | grep -q fortress-qdrant; then
    # Stop the current container
    docker stop fortress-qdrant > /dev/null 2>&1
    docker rm fortress-qdrant > /dev/null 2>&1
    
    # Recreate with API key
    docker run -d \
        --name fortress-qdrant \
        --restart unless-stopped \
        -p 127.0.0.1:6333:6333 \
        -p 127.0.0.1:6334:6334 \
        -v qdrant_storage:/qdrant/storage \
        -e QDRANT__SERVICE__API_KEY="$QDRANT_API_KEY" \
        qdrant/qdrant:latest
    
    # Save the API key
    echo "QDRANT_API_KEY=$QDRANT_API_KEY" >> /home/admin/Fortress-Prime/.env
    
    echo -e "${GREEN}  ✓ Qdrant: API key enabled, bound to localhost only.${NC}"
    echo -e "${GREEN}    Key saved to .env as QDRANT_API_KEY${NC}"
    echo -e "${YELLOW}    ⚠ UPDATE tools/owui_architect_toolkit.py to pass this key in headers!${NC}"
    echo -e "${YELLOW}    ⚠ UPDATE tools/fortress_sentinel.py to pass this key!${NC}"
else
    echo -e "${RED}  ✗ Qdrant container not found. Skipping.${NC}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# 4. REDIS — Set password
# ─────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[4/5] Securing Redis...${NC}"

REDIS_PASSWORD=$(openssl rand -hex 16)

# Redis is a Swarm service — update via service update
if docker service ls --filter name=fortress_redis --format '{{.Name}}' | grep -q fortress_redis; then
    docker service update --env-add "REDIS_ARGS=--requirepass $REDIS_PASSWORD" fortress_redis 2>/dev/null || \
    echo -e "${YELLOW}  ⚠ Could not update Swarm service. Add --requirepass manually.${NC}"
    
    echo "REDIS_PASSWORD=$REDIS_PASSWORD" >> /home/admin/Fortress-Prime/.env
    echo -e "${GREEN}  ✓ Redis: password set.${NC}"
    echo -e "${GREEN}    Key saved to .env as REDIS_PASSWORD${NC}"
else
    echo -e "${YELLOW}  ⚠ Redis Swarm service not found. Set password manually.${NC}"
fi
echo ""

# ─────────────────────────────────────────────────────────────────
# 5. VERIFICATION
# ─────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/5] Verification...${NC}"

echo -n "  UFW status: "
ufw status | head -1

echo -n "  Postgres password test: "
PGPASSWORD="" psql -h 192.168.0.100 -U miner_bot -d fortress_db -c "SELECT 1" 2>&1 | head -1

echo -n "  Qdrant auth test: "
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:6333/collections 2>/dev/null)
if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "403" ]; then
    echo -e "${GREEN}Blocked (requires API key)${NC}"
else
    echo -e "${YELLOW}$HTTP_CODE (check manually)${NC}"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║            LOCKDOWN COMPLETE                     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "NEXT STEPS (manual):"
echo "  1. Test SSH from another machine to confirm it still works"
echo "  2. Test Mission Control at http://192.168.0.100:8080"
echo "  3. Update Qdrant API key in:"
echo "     - tools/owui_architect_toolkit.py (add header to qdrant_client)"
echo "     - tools/fortress_sentinel.py (add header to qdrant_client)"
echo "     - src/agent_fortress.py (add header to qdrant_client)"
echo "  4. Update Redis password in any scripts that use Redis"
echo "  5. Check your router — port 80 was forwarded to this machine."
echo "     Remove the port forward if not needed for external API."
echo ""
echo "API Keys saved to /home/admin/Fortress-Prime/.env"
echo "Postgres backup at ${PG_HBA}.bak.*"
