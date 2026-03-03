#!/bin/bash

# --- CONFIGURATION ---
REMOTE_IP="192.168.0.104"
REMOTE_USER="admin"

echo "=========================================="
echo "⚡ FORTRESS CLUSTER DIAGNOSTIC"
echo "=========================================="

# 1. INSTALL TOOLS (Both Nodes)
echo "[1] Installing Network Tools..."
sudo apt-get install -y iperf3 > /dev/null 2>&1
ssh -o BatchMode=yes -o StrictHostKeyChecking=no $REMOTE_USER@$REMOTE_IP "sudo apt-get install -y iperf3 > /dev/null 2>&1"

# 2. RUN SPEED TEST
echo ""
echo "[2] Testing Inter-Node Speed (The Cable)..."
# Start Server on Spark 1 (Background)
ssh -f $REMOTE_USER@$REMOTE_IP "nohup iperf3 -s > /dev/null 2>&1 &"
sleep 2
# Run Client on Spark 2
SPEED_RESULT=$(iperf3 -c $REMOTE_IP -t 5 -P 4 | grep "receiver" | tail -n 1)
# Kill Remote Server
ssh $REMOTE_USER@$REMOTE_IP "pkill iperf3"

if echo "$SPEED_RESULT" | grep -q "Gbits/sec"; then
    SPEED_VAL=$(echo "$SPEED_RESULT" | awk '{print $7}')
    echo "   -> Bandwidth Result: $SPEED_VAL Gbps"
else
    echo "   -> Bandwidth Result: FAILED (Check network/firewall)"
    SPEED_VAL=0
fi

# 3. AUDIT TOTAL CLUSTER MEMORY
echo ""
echo "[3] Auditing Total Cluster Power..."
LOCAL_RAM=$(free -g | grep Mem | awk '{print $2}')
REMOTE_RAM=$(ssh $REMOTE_USER@$REMOTE_IP "free -g | grep Mem | awk '{print \$2}'")

# Simple GPU VRAM Check
LOCAL_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | awk '{s+=$1} END {print s/1024}')
REMOTE_VRAM=$(ssh $REMOTE_USER@$REMOTE_IP "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | awk '{s+=\$1} END {print s/1024}'")

# Fallback for prototype hardware if nvidia-smi fails
if [ -z "$LOCAL_VRAM" ]; then LOCAL_VRAM="128 (Estimated)"; fi
if [ -z "$REMOTE_VRAM" ]; then REMOTE_VRAM="128 (Estimated)"; fi

echo "   Node 1 (Spark 2): ${LOCAL_RAM}GB RAM | ${LOCAL_VRAM}GB VRAM"
echo "   Node 2 (Spark 1): ${REMOTE_RAM}GB RAM | ${REMOTE_VRAM}GB VRAM"
echo "=========================================="
echo "STRATEGY RECOMMENDATION:"

# Compare floating point numbers for speed
if (( $(echo "$SPEED_VAL > 20" | bc -l 2>/dev/null || echo 0) )); then
    echo "   ✅ CABLE SPEED: HIGH ($SPEED_VAL Gbps)"
    echo "      -> YOU CAN RUN: Llama-3.1-405B (Split Cluster)"
else
    echo "   ⚠️ CABLE SPEED: MODERATE ($SPEED_VAL Gbps)"
    echo "      -> RECOMMENDATION: DeepSeek-R1-70B (Single Node)"
    echo "         (405B will be too slow over this cable)"
fi
echo "=========================================="
