#!/usr/bin/env bash
set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
RELEASE_ROOT="${RELEASE_ROOT:-/home/admin/releases/fortress-legal}"
MUTATION_FLAG=0

usage() {
  cat <<USAGE
Usage: $SCRIPT_NAME [--dry-run] [--target-release <id>]

Prints a read-only Fortress Legal rollback plan. This scaffold does not switch
symlinks, restart services, replace artifacts, deploy, mutate systemd, or read
.auth.
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

target_release=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      shift
      ;;
    --target-release)
      [[ $# -ge 2 ]] || die "--target-release requires a value"
      target_release="$2"
      refuse_auth_path "$target_release"
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

current_link="$RELEASE_ROOT/current"
previous_link="$RELEASE_ROOT/previous"
target_path="not-selected"

if [[ -z "$target_release" ]]; then
  if [[ -L "$previous_link" ]]; then
    target_path="$(readlink -f "$previous_link")"
  else
    target_path="$previous_link"
  fi
else
  target_path="$RELEASE_ROOT/releases/$target_release"
fi

target_exists=false
[[ -e "$target_path" ]] && target_exists=true

evidence_path="$target_path/evidence.json"
hash_manifest="$target_path/hashes.sha256"
build_id_path="$target_path/.next/BUILD_ID"

cat <<REPORT
mode=dry-run
enterprise=Fortress Legal
release_root=$RELEASE_ROOT
current_link=$current_link
previous_link=$previous_link
target_release=$target_release
target_path=$target_path
target_exists=$target_exists
expected_evidence_path=$evidence_path
expected_hash_manifest=$hash_manifest
expected_build_id_path=$build_id_path
required_approval=Explicit HITL production-mutation approval tied to target release and rollback reason.
planned_mutating_steps_if_approved=1 switch current symlink; 2 restart approved frontend service only; 3 run smoke checks; 4 capture rollback evidence.
recommended_next_action=Verify target evidence and hashes, then request explicit HITL approval before any rollback mutation.
mutation_statement=No deploy, restart, symlink switch, artifact replacement, auth read, DB/Supabase mutation, Cloudflare/DNS mutation, or .auth read was performed.
REPORT
