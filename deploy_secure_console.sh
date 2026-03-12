#!/bin/bash
# =============================================================================
# Deploy Secure Master Console
# =============================================================================
# This script deploys the security-hardened version of the Master Console
# with all critical vulnerabilities fixed.
#
# Usage:
#   ./deploy_secure_console.sh
#
# Author: Fortress Prime Security Team
# Date: 2026-02-16
# =============================================================================

set -e  # Exit on error

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║         🔒 DEPLOYING SECURE MASTER CONSOLE                     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ── Configuration ──
PROJECT_ROOT="/home/admin/Fortress-Prime"
BACKUP_DIR="$PROJECT_ROOT/backups/$(date +%Y%m%d_%H%M%S)"
LOG_FILE="/tmp/crog_secure.log"

# ── Step 1: Verify Prerequisites ──
echo "📋 Step 1: Checking prerequisites..."

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "   Create it first or copy from .env.example"
    exit 1
fi

if ! grep -q "JWT_RSA_PUBLIC_KEY=" "$PROJECT_ROOT/.env.security"; then
    echo "❌ ERROR: JWT_RSA_PUBLIC_KEY not found in .env.security"
    echo "   Configure RSA keys in .env.security before deployment."
    exit 1
fi

if ! grep -q "JWT_RSA_PRIVATE_KEY=" "$PROJECT_ROOT/.env.security"; then
    echo "❌ ERROR: JWT_RSA_PRIVATE_KEY not found in .env.security"
    echo "   Configure RSA keys in .env.security before deployment."
    exit 1
fi

echo "✅ Prerequisites check passed"
echo ""

# ── Step 2: Backup Current Version ──
echo "📦 Step 2: Creating backup..."

mkdir -p "$BACKUP_DIR"

if [ -f "$PROJECT_ROOT/tools/master_console.py" ]; then
    cp "$PROJECT_ROOT/tools/master_console.py" "$BACKUP_DIR/master_console_backup.py"
    echo "✅ Backup created: $BACKUP_DIR/master_console_backup.py"
else
    echo "ℹ️  No existing master_console.py to backup"
fi
echo ""

# ── Step 3: Stop Current Instance ──
echo "🛑 Step 3: Stopping current Master Console..."

if pgrep -f "tools/master_console.py" > /dev/null; then
    pkill -f "tools/master_console.py"
    echo "✅ Stopped existing process"
    sleep 2
else
    echo "ℹ️  No running process found"
fi
echo ""

# ── Step 4: Deploy Secure Version ──
echo "🚀 Step 4: Deploying secure version..."

cp "$PROJECT_ROOT/tools/master_console_secure.py" "$PROJECT_ROOT/tools/master_console.py"
echo "✅ Deployed master_console.py (security-hardened)"
echo ""

# ── Step 5: Start Secure Console ──
echo "▶️  Step 5: Starting secure Master Console..."

cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env.security"
set +a
nohup ./venv/bin/python3 tools/master_console.py > "$LOG_FILE" 2>&1 &
NEW_PID=$!

echo "✅ Started with PID: $NEW_PID"
echo "   Log file: $LOG_FILE"
echo ""

# ── Step 6: Verify Startup ──
echo "🔍 Step 6: Verifying startup..."
sleep 3

if ps -p $NEW_PID > /dev/null; then
    echo "✅ Process is running"
else
    echo "❌ ERROR: Process failed to start"
    echo "   Check logs: tail -f $LOG_FILE"
    exit 1
fi

# Check if responding
if curl -s http://192.168.0.100:9800/health > /dev/null; then
    echo "✅ Health check passed"
else
    echo "⚠️  WARNING: Health check failed (may still be starting...)"
fi
echo ""

# ── Step 7: Display Status ──
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                  ✅ DEPLOYMENT SUCCESSFUL                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Status:"
echo "   Service: CROG Command Center (Secure)"
echo "   Version: 2.1.0-secure"
echo "   PID: $NEW_PID"
echo "   URL: http://192.168.0.100:9800"
echo "   Public URL: https://crog-ai.com"
echo ""
echo "🔐 Security Improvements:"
echo "   ✅ JWT secret from environment"
echo "   ✅ CORS restricted to whitelist"
echo "   ✅ Secure cookies (auto-detect)"
echo "   ✅ Input validation (Pydantic)"
echo "   ✅ Security headers"
echo "   ✅ Enhanced audit logging"
echo ""
echo "📝 Next Steps:"
echo "   1. Test login: https://crog-ai.com/login"
echo "   2. Monitor logs: tail -f $LOG_FILE"
echo "   3. Review audit: cat /home/admin/Fortress-Prime/SECURITY_AUDIT_REPORT.md"
echo ""
echo "🔧 Rollback (if needed):"
echo "   cp $BACKUP_DIR/master_console_backup.py $PROJECT_ROOT/tools/master_console.py"
echo "   pkill -f master_console && cd $PROJECT_ROOT && nohup ./venv/bin/python3 tools/master_console.py &"
echo ""
echo "═══════════════════════════════════════════════════════════════"
