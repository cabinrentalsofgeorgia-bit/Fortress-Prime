#!/bin/bash

OUTPUT_FILE="$HOME/Fortress-Prime/cluster_specs.txt"
echo "==========================================" > $OUTPUT_FILE
echo "🚀 FORTRESS CLUSTER HARDWARE AUDIT" >> $OUTPUT_FILE
echo "==========================================" >> $OUTPUT_FILE

# --- 1. AUDIT SPARK 2 (Controller) ---
echo "" >> $OUTPUT_FILE
echo "--- NODE: SPARK 2 (Local) ---" >> $OUTPUT_FILE
echo "CPU: $(lscpu | grep 'Model name' | cut -d: -f2 | xargs)" >> $OUTPUT_FILE
echo "RAM: $(free -h | grep Mem | awk '{print $2}')" >> $OUTPUT_FILE

# Check NVIDIA GPUs on Spark 2
if command -v nvidia-smi &> /dev/null; then
    echo "GPU Check:" >> $OUTPUT_FILE
    nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader >> $OUTPUT_FILE
else
    echo "❌ No NVIDIA GPU found or driver missing." >> $OUTPUT_FILE
fi

# --- 2. AUDIT SPARK 1 (Agent) ---
# We assume 'admin@192.168.0.104' based on previous context. Update IP if needed.
AGENT_IP="192.168.0.104" 
echo "" >> $OUTPUT_FILE
echo "--- NODE: SPARK 1 (Remote: $AGENT_IP) ---" >> $OUTPUT_FILE

# Run SSH command to get remote specs
ssh -o BatchMode=yes -o ConnectTimeout=5 admin@$AGENT_IP "
    echo 'CPU: \$(lscpu | grep 'Model name' | cut -d: -f2 | xargs)';
    echo 'RAM: \$(free -h | grep Mem | awk '{print \$2}')';
    if command -v nvidia-smi &> /dev/null; then
        echo 'GPU Check:';
        nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader;
    else
        echo '❌ No NVIDIA GPU found.';
    fi
" >> $OUTPUT_FILE 2>&1

echo "==========================================" >> $OUTPUT_FILE
echo "✅ Audit Complete. File generated at: $OUTPUT_FILE"
