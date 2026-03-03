#!/bin/bash
# =============================================================================
# FORTRESS PRIME — Night Watchman Protocol
# =============================================================================
# Monitors the Grand Router's progress. When sorting is complete (<100 unsorted),
# automatically kills the Captain's local Router and redeploys the Wolfpack in
# Trader Mode to hunt HEDGE_FUND signals.
#
# Usage:
#   chmod +x night_watchman.sh
#   nohup ./night_watchman.sh > watchman.log 2>&1 &
# =============================================================================

DB_HOST="localhost"
DB_USER="miner_bot"
DB_NAME="fortress_db"
THRESHOLD=100        # Switch when fewer than this many unsorted
CHECK_INTERVAL=600   # Check every 10 minutes (in seconds)
PROJECT_DIR="/home/admin/Fortress-Prime"

echo "🦉 ============================================"
echo "🦉  NIGHT WATCHMAN — ON DUTY"
echo "🦉 ============================================"
echo "   Started:    $(date)"
echo "   Monitoring: UNROUTED count in email_archive"
echo "   Threshold:  < $THRESHOLD unsorted → switch to Trader"
echo "   Interval:   Every $((CHECK_INTERVAL / 60)) minutes"
echo ""

while true; do
    NOW=$(date "+%Y-%m-%d %H:%M:%S")

    # Get current counts
    UNROUTED=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
        "SELECT COUNT(*) FROM email_archive WHERE division IS NULL;" 2>/dev/null | xargs)
    ROUTING=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
        "SELECT COUNT(*) FROM email_archive WHERE division = 'ROUTING';" 2>/dev/null | xargs)
    HEDGE=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
        "SELECT COUNT(*) FROM email_archive WHERE division = 'HEDGE_FUND';" 2>/dev/null | xargs)
    TOTAL=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
        "SELECT COUNT(*) FROM email_archive;" 2>/dev/null | xargs)

    REMAINING=$((UNROUTED + ROUTING))

    if [ "$REMAINING" -lt "$THRESHOLD" ]; then
        echo ""
        echo "[$NOW] ============================================"
        echo "[$NOW] ✅ SORTING COMPLETE!"
        echo "[$NOW]    Unsorted: $UNROUTED | In-flight: $ROUTING"
        echo "[$NOW]    HEDGE_FUND emails ready: $HEDGE"
        echo "[$NOW]    Total archive: $TOTAL"
        echo "[$NOW] ============================================"
        echo ""

        # -------------------------------------------------------
        # Phase Transition: Librarian → Hunter
        # -------------------------------------------------------

        # 1. Kill the Captain's local router
        echo "[$NOW] 🔄 Phase 1: Standing down the Librarian..."
        pkill -f "mining_rig_router" 2>/dev/null || true
        sleep 3

        # 2. Reset any stuck ROUTING rows
        STUCK=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
            "UPDATE email_archive SET division = NULL WHERE division = 'ROUTING' RETURNING id;" 2>/dev/null | wc -l)
        echo "[$NOW]    Reset $STUCK stuck ROUTING rows."

        # 3. Reset is_mined for HEDGE_FUND emails (Trader needs unmined rows)
        RESET=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
            "UPDATE email_archive SET is_mined = FALSE WHERE division = 'HEDGE_FUND' AND is_mined = TRUE RETURNING id;" 2>/dev/null | wc -l)
        echo "[$NOW]    Reset is_mined on $RESET HEDGE_FUND emails for fresh hunting."

        # 4. Deploy the Wolfpack in Trader Mode
        echo "[$NOW] 🔄 Phase 2: Launching the Hunter..."
        cd "$PROJECT_DIR"
        ./deploy_wolfpack.sh --mode trader 2>&1 | while read -r line; do
            echo "[$NOW]    $line"
        done

        # 5. Start the Captain's own Trader rig
        echo "[$NOW] 🔄 Phase 3: Starting Captain Trader..."
        DB_HOST=localhost \
        NIM_ENDPOINT=http://localhost:11434/v1/chat/completions \
        NIM_MODEL=qwen2.5:7b \
        PYTHONUNBUFFERED=1 \
        nohup /usr/bin/python3 -m src.mining_rig_trader \
            --batch 100 --workers 3 --worker-id "captain" \
            > "$PROJECT_DIR/captain_trader.log" 2>&1 &

        echo ""
        echo "[$NOW] 🚀 ============================================"
        echo "[$NOW] 🚀  TRANSITION COMPLETE"
        echo "[$NOW] 🚀  The Hunt has begun."
        echo "[$NOW] 🚀  Target: $HEDGE HEDGE_FUND emails"
        echo "[$NOW] 🚀  Monitor: tail -f captain_trader.log"
        echo "[$NOW] 🚀 ============================================"
        echo ""
        echo "🦉 Night Watchman signing off. $(date)"
        break
    else
        # Division breakdown for the log
        DIVISIONS=$(psql -h $DB_HOST -U $DB_USER -d $DB_NAME -t -c \
            "SELECT COALESCE(division,'UNROUTED') || ': ' || COUNT(*) FROM email_archive GROUP BY division ORDER BY COUNT(*) DESC;" 2>/dev/null | xargs -I{} echo "     {}")

        echo "[$NOW] ⏳ Sorting: $REMAINING remaining ($UNROUTED unsorted + $ROUTING in-flight)"
        echo "$DIVISIONS"
        echo ""
        sleep $CHECK_INTERVAL
    fi
done
