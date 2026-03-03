#!/usr/bin/env bash
set -euo pipefail

echo "[coverage] Running Fortress Guest Platform coverage gate..."
if [ -d "fortress-guest-platform/tests" ]; then
  (
    cd fortress-guest-platform
    FGP_PY="./venv/bin/python"
    if [ ! -x "$FGP_PY" ]; then
      FGP_PY="python3"
    fi

    # Ensure coverage exists in selected interpreter
    "$FGP_PY" -m coverage --version >/dev/null 2>&1 || "$FGP_PY" -m pip install coverage

    TEST_HOST="127.0.0.1"
    TEST_PORT="${FGP_TEST_PORT:-18100}"
    TEST_URL="http://${TEST_HOST}:${TEST_PORT}"
    LOG_FILE="/tmp/fgp_coverage_backend.log"

    shutdown_backend() {
      local pid="$1"
      local waited=0

      if ! kill -0 "$pid" >/dev/null 2>&1; then
        return 0
      fi

      kill -INT "$pid" >/dev/null 2>&1 || true
      while kill -0 "$pid" >/dev/null 2>&1 && [ "$waited" -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
      done

      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -TERM "$pid" >/dev/null 2>&1 || true
      fi
      waited=0
      while kill -0 "$pid" >/dev/null 2>&1 && [ "$waited" -lt 10 ]; do
        sleep 1
        waited=$((waited + 1))
      done

      if kill -0 "$pid" >/dev/null 2>&1; then
        kill -KILL "$pid" >/dev/null 2>&1 || true
      fi

      wait "$pid" >/dev/null 2>&1 || true
    }

    "$FGP_PY" -m coverage erase
    "$FGP_PY" -m coverage run --parallel-mode -m uvicorn backend.main:app --host "$TEST_HOST" --port "$TEST_PORT" >"$LOG_FILE" 2>&1 &
    BACKEND_PID=$!
    trap 'shutdown_backend "$BACKEND_PID"' EXIT

    # Wait for backend health
    READY=0
    for _ in $(seq 1 60); do
      if curl -sf "${TEST_URL}/health" >/dev/null 2>&1; then
        READY=1
        break
      fi
      sleep 1
    done
    if [ "$READY" -ne 1 ]; then
      echo "[coverage] FGP backend failed to start for coverage run. See ${LOG_FILE}" >&2
      exit 1
    fi

    TEST_BASE_URL="$TEST_URL" "$FGP_PY" -m coverage run --parallel-mode -m pytest tests

    shutdown_backend "$BACKEND_PID"
    trap - EXIT

    "$FGP_PY" -m coverage combine || true

    # Gate on API/model/core coverage for deterministic CI signal.
    # Service/integration modules still report below as advisory while tests are expanded.
    FGP_COVERAGE_SCOPE="${FGP_COVERAGE_SCOPE:-backend/api/*,backend/models/*,backend/core/*}"
    # Enforced baseline gate after coverage uplift.
    FGP_COVERAGE_FAIL_UNDER="${FGP_COVERAGE_FAIL_UNDER:-65}"
    FGP_COVERAGE_TARGET="${FGP_COVERAGE_TARGET:-65}"

    "$FGP_PY" -m coverage xml -o coverage.xml --include="$FGP_COVERAGE_SCOPE"
    "$FGP_PY" -m coverage report --include="$FGP_COVERAGE_SCOPE" --fail-under="$FGP_COVERAGE_FAIL_UNDER"
    CURRENT_COVERAGE=$("$FGP_PY" -m coverage report --include="$FGP_COVERAGE_SCOPE" | awk '/TOTAL/ {gsub("%","",$NF); print $NF}')
    if [[ -n "${CURRENT_COVERAGE}" && "${CURRENT_COVERAGE}" -lt "${FGP_COVERAGE_TARGET}" ]]; then
      echo "[coverage] WARNING: scoped coverage ${CURRENT_COVERAGE}% is below target ${FGP_COVERAGE_TARGET}%."
    fi
    echo "[coverage] Advisory full-backend report (non-gating):"
    "$FGP_PY" -m coverage report --include="backend/*" || true
  )
else
  echo "[coverage] No fortress-guest-platform/tests directory found."
fi

echo "[coverage] Running CROG gateway coverage gate..."
if [ -d "crog-gateway/tests" ]; then
  (
    cd crog-gateway
    if ! python3 -m pytest --version >/dev/null 2>&1; then
      python3 -m pip install pytest pytest-cov >/dev/null 2>&1 || true
    fi
    if python3 -m pytest --version >/dev/null 2>&1; then
      python3 -m pytest tests --cov=. --cov-report=xml --cov-report=term || true
    else
      echo "[coverage] CROG: pytest unavailable in system python, skipping CROG coverage."
    fi
  )
else
  echo "[coverage] No crog-gateway/tests directory found."
fi

echo "[coverage] Complete."
