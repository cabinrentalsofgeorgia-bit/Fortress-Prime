#!/usr/bin/env bash
set -euo pipefail

resolve_ray_bin() {
  local candidate

  if [[ -n "${RAY_BIN:-}" && -x "${RAY_BIN}" ]]; then
    printf '%s\n' "${RAY_BIN}"
    return 0
  fi

  for candidate in \
    "/home/admin/.local/bin/ray" \
    "${HOME:-/home/admin}/.local/bin/ray"
  do
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  if command -v ray >/dev/null 2>&1; then
    command -v ray
    return 0
  fi

  echo "ERROR: Ray CLI not found. Set RAY_BIN or install the launcher into /home/admin/.local/bin/ray." >&2
  return 1
}
