#!/bin/bash
OUTPUT_FILE="cluster_state_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$OUTPUT_FILE") 2>&1

echo "================================================="
echo "  CROG-FORTRESS-AI CAPTAIN DIAGNOSTIC REPORT"
echo "================================================="

echo -e "\n[1] CAPTAIN NODE (.100) LOCAL STATE"
echo "-------------------------------------------------"
echo "[Architecture]" && uname -m
echo -e "\n[Docker Containers]" && docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo -e "\n[Port Listeners (8000/Web)]" && sudo lsof -i -P -n | grep -E "LISTEN.*(8000|80|443)"
echo -e "\n[NFS Mounts]" && df -hT | grep -E 'nfs|nvme' && findmnt -T /mnt/fortress_nas || echo 'NAS check failed'

for ip in 192.168.0.104 192.168.0.105 192.168.0.106; do
  echo -e "\n================================================="
  echo "  AUDITING WORKER NODE: $ip"
  echo "================================================="
  ssh -o BatchMode=yes -o ConnectTimeout=5 admin@$ip "
    echo '[Architecture]' && uname -m &&
    echo -e '\n[Docker Containers]' && docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' &&
    echo -e '\n[GPU Status]' && nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader || echo 'nvidia-smi failed' &&
    echo -e '\n[NFS Mounts]' && df -hT | grep -E 'nfs|nvme' && findmnt -T /mnt/fortress_nas || echo 'NAS check failed'
  "
done

echo "Audit complete. Saved to $OUTPUT_FILE"
