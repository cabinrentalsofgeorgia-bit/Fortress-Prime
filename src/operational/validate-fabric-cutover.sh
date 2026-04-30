#!/usr/bin/env bash
# validate-fabric-cutover.sh — read-only post-cutover validation for spark-5/6 fabric.
#
# Cluster-network-audit drove this script. Run from any host with cluster
# network access (e.g. spark-2). Outputs pass/fail table to stdout.
#
# Usage:
#   bash src/operational/validate-fabric-cutover.sh
#
# Exit code:
#   0 if all checks pass
#   1 if any check fails (so the script can drive CI/cron)
#
# This script is READ-ONLY. It does not modify any host config.

set -u

CANONICAL_KERNEL="6.17.0-1014-nvidia"
CANONICAL_FW="28.45.4028"
CANONICAL_MTU=9000
RC=0

pass() { printf "  ✓ %-60s PASS\n" "$1"; }
fail() { printf "  ✗ %-60s FAIL — %s\n" "$1" "$2"; RC=1; }

ssh_run() {
  local ip=$1; shift
  timeout 10 ssh -o BatchMode=yes -o ConnectTimeout=5 admin@"$ip" "$@" 2>/dev/null
}

echo "=========================================================="
echo "  Fortress Cluster Fabric Validation — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "=========================================================="

echo
echo "[1/8] SSH reachability on mgmt LAN"
for ip in 192.168.0.104 192.168.0.100 192.168.0.105 192.168.0.106 192.168.0.109 192.168.0.115; do
  out=$(ssh_run "$ip" 'hostname' 2>&1)
  if [ -n "$out" ] && ! echo "$out" | grep -qi "denied\|refused\|timeout"; then
    pass "ssh admin@$ip ($out)"
  else
    fail "ssh admin@$ip" "$out"
  fi
done

echo
echo "[2/8] Fabric A pings (10.10.10.X) from $(hostname)"
for x in 1 2 3 4 5 6; do
  ip="10.10.10.$x"
  if timeout 3 ping -c 2 -W 1 "$ip" >/dev/null 2>&1; then
    pass "ping $ip (spark-$x fabric A)"
  else
    fail "ping $ip (spark-$x fabric A)" "no response"
  fi
done

echo
echo "[3/8] Fabric B pings (10.10.11.X) from $(hostname)"
for x in 1 2 3 4 5 6; do
  ip="10.10.11.$x"
  if timeout 3 ping -c 2 -W 1 "$ip" >/dev/null 2>&1; then
    pass "ping $ip (spark-$x fabric B)"
  else
    fail "ping $ip (spark-$x fabric B)" "no response"
  fi
done

echo
echo "[4/8] Kernel version match (canonical: $CANONICAL_KERNEL)"
for ip in 192.168.0.104 192.168.0.100 192.168.0.105 192.168.0.106 192.168.0.109 192.168.0.115; do
  k=$(ssh_run "$ip" 'uname -r' 2>&1)
  if [ "$k" = "$CANONICAL_KERNEL" ]; then
    pass "spark-${ip##*.} kernel ($k)"
  else
    fail "spark-${ip##*.} kernel" "got '$k' want '$CANONICAL_KERNEL'"
  fi
done

echo
echo "[5/8] mlx5_core driver loaded"
for ip in 192.168.0.104 192.168.0.100 192.168.0.105 192.168.0.106 192.168.0.109 192.168.0.115; do
  if ssh_run "$ip" 'lsmod | grep -q "^mlx5_core"' >/dev/null 2>&1; then
    pass "spark-${ip##*.} mlx5_core loaded"
  else
    fail "spark-${ip##*.} mlx5_core loaded" "module not in lsmod"
  fi
done

echo
echo "[6/8] ConnectX firmware match (canonical: $CANONICAL_FW)"
for ip in 192.168.0.104 192.168.0.100 192.168.0.105 192.168.0.106 192.168.0.109 192.168.0.115; do
  fw=$(ssh_run "$ip" 'sudo -n ethtool -i enp1s0f0np0 2>/dev/null | grep firmware-version | awk "{print \$2}"' 2>&1)
  if [ -z "$fw" ]; then
    fail "spark-${ip##*.} firmware" "could not read (no NIC, no sudo NOPASSWD, or port absent)"
  elif [ "$fw" = "$CANONICAL_FW" ]; then
    pass "spark-${ip##*.} firmware ($fw)"
  else
    fail "spark-${ip##*.} firmware" "got '$fw' want '$CANONICAL_FW'"
  fi
done

echo
echo "[7/8] Fabric port MTU = $CANONICAL_MTU"
for ip in 192.168.0.104 192.168.0.100 192.168.0.105 192.168.0.106 192.168.0.109 192.168.0.115; do
  for iface in enp1s0f0np0 enP2p1s0f1np1; do
    mtu=$(ssh_run "$ip" "cat /sys/class/net/$iface/mtu 2>/dev/null" 2>&1)
    if [ -z "$mtu" ]; then
      fail "spark-${ip##*.} $iface mtu" "interface absent"
    elif [ "$mtu" = "$CANONICAL_MTU" ]; then
      pass "spark-${ip##*.} $iface mtu ($mtu)"
    else
      fail "spark-${ip##*.} $iface mtu" "got $mtu want $CANONICAL_MTU"
    fi
  done
done

echo
echo "[8/8] Critical service health"
brain=$(curl -sS --max-time 5 http://192.168.0.109:8100/v1/health/ready 2>/dev/null)
echo "$brain" | grep -q "ready" && pass "BRAIN spark-5:8100" || fail "BRAIN spark-5:8100" "$brain"

vision=$(curl -sS --max-time 5 http://192.168.0.105:8101/v1/health/ready 2>/dev/null)
echo "$vision" | grep -q "ready" && pass "vision-NIM spark-3:8101" || fail "vision-NIM spark-3:8101" "$vision"

embed=$(curl -sS --max-time 5 http://192.168.0.105:8102/v1/health/ready 2>/dev/null)
echo "$embed" | grep -q "ready" && pass "embed-NIM spark-3:8102" || fail "embed-NIM spark-3:8102" "$embed"

litellm=$(curl -sS --max-time 5 http://192.168.0.100:8002/health 2>/dev/null)
echo "$litellm" | grep -qE "(error|message|status|model_info)" && pass "LiteLLM spark-2:8002 (responding)" || fail "LiteLLM spark-2:8002" "$litellm"

qdrant=$(curl -sS --max-time 5 http://192.168.0.100:6333 2>/dev/null)
echo "$qdrant" | grep -q "qdrant" && pass "Qdrant spark-2:6333" || fail "Qdrant spark-2:6333" "$qdrant"

qvrs=$(curl -sS --max-time 5 http://192.168.0.106:6333 2>/dev/null)
echo "$qvrs" | grep -q "qdrant" && pass "Qdrant-VRS spark-4:6333" || fail "Qdrant-VRS spark-4:6333" "$qvrs"

echo
echo "=========================================================="
[ $RC -eq 0 ] && echo "  RESULT: ALL CHECKS PASSED" || echo "  RESULT: $RC OR MORE FAILURES — review above"
echo "=========================================================="

exit $RC
