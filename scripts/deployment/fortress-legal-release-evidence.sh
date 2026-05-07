#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_ROOT="${PACKAGE_ROOT:-$REPO_ROOT/fortress-guest-platform}"
APP_ROOT="${APP_ROOT:-$PACKAGE_ROOT/apps/command-center}"
RELEASE_ROOT="${RELEASE_ROOT:-/home/admin/releases/fortress-legal}"
DRY_RUN=1
MUTATION_FLAG=0

usage() {
  cat <<USAGE
Usage: $SCRIPT_NAME [--dry-run] [--release-id <id>] [--operator-approval <ref>]

Collects non-secret Fortress Legal release evidence facts and prints the
recommended evidence path. This scaffold is read-only by default and does not
write evidence files, build artifacts, switch symlinks, deploy, or restart
services.

Environment overrides:
  PACKAGE_ROOT   default: $PACKAGE_ROOT
  APP_ROOT       default: $APP_ROOT
  RELEASE_ROOT   default: $RELEASE_ROOT
USAGE
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

redact() {
  sed -E 's#([A-Za-z0-9_]*(SECRET|TOKEN|COOKIE|PASSWORD|PASS|KEY|AUTH|DATABASE_URL|DB_URL|SUPABASE)[A-Za-z0-9_]*=)[^[:space:]]+#\1[REDACTED]#Ig'
}

refuse_auth_path() {
  case "$1" in
    *".auth"* ) die "refusing to read or reference .auth path: $1" ;;
  esac
}

require_readonly_mode() {
  if [[ "$MUTATION_FLAG" -eq 1 ]]; then
    die "--i-understand-this-mutates-runtime is not supported by this dry-run scaffold"
  fi
}

release_id=""
operator_approval="not-provided"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --release-id)
      [[ $# -ge 2 ]] || die "--release-id requires a value"
      release_id="$2"
      refuse_auth_path "$release_id"
      shift 2
      ;;
    --operator-approval)
      [[ $# -ge 2 ]] || die "--operator-approval requires a value"
      operator_approval="$2"
      refuse_auth_path "$operator_approval"
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

require_readonly_mode

[[ -d "$PACKAGE_ROOT" ]] || die "package root not found: $PACKAGE_ROOT"
[[ -d "$APP_ROOT" ]] || die "app root not found: $APP_ROOT"

source_branch="$(git -C "$REPO_ROOT" branch --show-current)"
source_commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"
short_commit="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"
status_porcelain="$(git -C "$REPO_ROOT" status --porcelain)"
worktree_clean=false
if [[ -z "$status_porcelain" ]]; then
  worktree_clean=true
fi

node_version="$(node -v 2>/dev/null || printf 'unavailable')"
npm_version="$(npm -v 2>/dev/null || printf 'unavailable')"
package_lock="$PACKAGE_ROOT/package-lock.json"
package_lock_sha256="missing"
if [[ -f "$package_lock" ]]; then
  package_lock_sha256="$(sha256sum "$package_lock" | awk '{print $1}')"
fi

build_id_path="$APP_ROOT/.next/BUILD_ID"
build_id="not-built-in-worktree"
if [[ -f "$build_id_path" ]]; then
  build_id="$(tr -d '\n' < "$build_id_path")"
fi

timestamp="$(date -u +%Y%m%d-%H%M%S)"
if [[ -z "$release_id" ]]; then
  release_id="$timestamp-$short_commit-$build_id"
fi

release_path="$RELEASE_ROOT/releases/$release_id"
evidence_path="$RELEASE_ROOT/evidence/$release_id/evidence.json"
rollback_target="$RELEASE_ROOT/previous"

cat <<REPORT | redact
mode=dry-run
enterprise=Fortress Legal
source_branch=$source_branch
source_commit=$source_commit
worktree_clean=$worktree_clean
node_version=$node_version
npm_version=$npm_version
package_lock_sha256=$package_lock_sha256
package_manager_root=$PACKAGE_ROOT
app_root=$APP_ROOT
build_command=npm run build --workspace @fortress/command-center
build_id=$build_id
release_id=$release_id
artifact_path=$release_path
evidence_path=$evidence_path
rollback_target=$rollback_target
operator_approval=$operator_approval
timestamp_utc=$timestamp
dry_run=$DRY_RUN
REPORT

cat <<'NEXT'
recommended_next_action=Review this evidence output, run preflight, and request explicit HITL approval before any production mutation.
mutation_statement=No deploy, restart, symlink switch, artifact replacement, auth read, DB/Supabase mutation, Cloudflare/DNS mutation, or .auth read was performed.
NEXT
