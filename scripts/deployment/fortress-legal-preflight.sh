#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_ROOT="${PACKAGE_ROOT:-$REPO_ROOT/fortress-guest-platform}"
APP_ROOT="${APP_ROOT:-$PACKAGE_ROOT/apps/command-center}"
RELEASE_ROOT="${RELEASE_ROOT:-/home/admin/releases/fortress-legal}"
MUTATION_FLAG=0

usage() {
  cat <<USAGE
Usage: $SCRIPT_NAME [--dry-run] [--candidate-release <id>]

Runs read-only Fortress Legal release preflight checks. This scaffold does not
install dependencies, build artifacts, deploy, restart services, change systemd,
change symlinks, or read .auth.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

refuse_auth_path() {
  case "$1" in
    *".auth"* ) die "refusing to read or reference .auth path: $1" ;;
  esac
}

candidate_release=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      shift
      ;;
    --candidate-release)
      [[ $# -ge 2 ]] || die "--candidate-release requires a value"
      candidate_release="$2"
      refuse_auth_path "$candidate_release"
      shift 2
      ;;
    --i-understand-this-mutates-runtime)
      MUTATION_FLAG=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      refuse_auth_path "$1"
      die "unknown argument: $1"
      ;;
  esac
done

if [[ "$MUTATION_FLAG" -eq 1 ]]; then
  die "--i-understand-this-mutates-runtime is not supported by this dry-run scaffold"
fi

[[ -d "$REPO_ROOT" ]] || die "repo root not found: $REPO_ROOT"
[[ -d "$PACKAGE_ROOT" ]] || die "package root not found: $PACKAGE_ROOT"
[[ -d "$APP_ROOT" ]] || die "app root not found: $APP_ROOT"

branch="$(git -C "$REPO_ROOT" branch --show-current)"
commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"
status_porcelain="$(git -C "$REPO_ROOT" status --porcelain)"
worktree_clean=false
if [[ -z "$status_porcelain" ]]; then
  worktree_clean=true
fi

package_json_status="missing"
[[ -f "$APP_ROOT/package.json" ]] && package_json_status="present"

lockfile_status="missing"
[[ -f "$PACKAGE_ROOT/package-lock.json" ]] && lockfile_status="package-lock.json"

candidate_path="not-provided"
candidate_exists=false
if [[ -n "$candidate_release" ]]; then
  candidate_path="$RELEASE_ROOT/releases/$candidate_release"
  [[ -d "$candidate_path" ]] && candidate_exists=true
fi

cat <<REPORT
mode=dry-run
enterprise=Fortress Legal
branch=$branch
commit=$commit
worktree_clean=$worktree_clean
package_root=$PACKAGE_ROOT
app_root=$APP_ROOT
package_json=$package_json_status
lockfile=$lockfile_status
release_root=$RELEASE_ROOT
candidate_release=$candidate_release
candidate_path=$candidate_path
candidate_exists=$candidate_exists
recommended_local_gates=npm ci && npm test --workspace @fortress/command-center && npm run build --workspace @fortress/command-center
recommended_next_action=Resolve preflight findings and capture release evidence before requesting HITL approval.
mutation_statement=No deploy, restart, symlink switch, artifact replacement, auth read, DB/Supabase mutation, Cloudflare/DNS mutation, or .auth read was performed.
REPORT
