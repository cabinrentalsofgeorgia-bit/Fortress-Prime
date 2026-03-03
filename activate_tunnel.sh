#!/bin/bash
# =============================================================================
# FORTRESS PRIME — Activate Cloudflare Tunnel for crog-ai.com
# =============================================================================
# Run this script with sudo to:
#   1. Copy the updated tunnel config to /etc/cloudflared/
#   2. Restart the cloudflared service
#
# Usage: sudo bash activate_tunnel.sh
# =============================================================================

set -e

echo "=========================================="
echo "  Fortress Prime — Tunnel Activation"
echo "=========================================="
echo ""

# 1. Copy updated config
echo "[1/3] Copying tunnel config..."
cp /home/admin/.cloudflared/config.yml /etc/cloudflared/config.yml
echo "      Done. Config now includes crog-ai.com root domain."
echo ""

# 2. Validate
echo "[2/3] Validating ingress rules..."
cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
echo ""

# 3. Restart service
echo "[3/3] Restarting cloudflared service..."
systemctl restart cloudflared
sleep 3
systemctl status cloudflared --no-pager | head -8
echo ""

echo "=========================================="
echo "  Tunnel activated!"
echo ""
echo "  crog-ai.com     -> Master Console"
echo "  www.crog-ai.com -> Master Console"
echo ""
echo "  NOTE: You must update the DNS record for"
echo "  crog-ai.com in Cloudflare Dashboard:"
echo ""
echo "  1. Go to DNS settings for crog-ai.com"
echo "  2. Delete existing A/AAAA records for @"
echo "  3. Add CNAME record:"
echo "     Name: @"
echo "     Target: aa7222a3-c1c9-4ee3-97c8-fb46b41a654e.cfargotunnel.com"
echo "     Proxy: ON (orange cloud)"
echo "=========================================="
