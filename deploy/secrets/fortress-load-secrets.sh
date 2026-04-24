#!/usr/bin/env bash
# fortress-load-secrets — resolve env vars from `pass` per a manifest file.
#
# Manifest format (one entry per line):
#   ENV_VAR_NAME    pass/path
# Lines starting with '#' and blank lines are ignored. Whitespace
# between the var name and the pass path can be any amount (spaces
# and/or tabs).
#
# Modes:
#   fortress-load-secrets                # print "VAR=value" to stdout
#   fortress-load-secrets --output FILE  # atomically write FILE (mode 0600)
#   fortress-load-secrets --manifest M   # use M instead of /etc/fortress/secrets.manifest
#   fortress-load-secrets -h | --help    # usage
#
# Failure modes:
#   - manifest missing                       -> exit 2
#   - line malformed (not "NAME PATH")        -> exit 3
#   - `pass show <path>` fails OR returns ""  -> exit 1
#
# Errors are written to stderr and name the failing variable + pass
# path only. Secret values are never written to stderr or stdout
# unless they are the legitimate VAR=value output going to stdout
# (or to the --output file). When stdout is a terminal AND --output
# is not used, the script refuses to print to avoid leaking secrets
# into shell scrollback.

set -u
set -o pipefail

PROG="$(basename "$0")"
MANIFEST="/etc/fortress/secrets.manifest"
OUTPUT_FILE=""

usage() {
  cat <<EOF
Usage: ${PROG} [--manifest PATH] [--output FILE]

Resolves env vars from \`pass\` per the manifest. Each manifest line:
    ENV_VAR_NAME    pass/path

Without --output, prints "VAR=value" lines to stdout (refused if stdout
is a TTY). With --output, atomically writes the file with mode 0600
(suitable for systemd EnvironmentFile=).
EOF
}

err() {
  printf '%s: %s\n' "${PROG}" "$*" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      [[ $# -ge 2 ]] || { err "--manifest requires a path"; exit 64; }
      MANIFEST="$2"; shift 2;;
    --output)
      [[ $# -ge 2 ]] || { err "--output requires a path"; exit 64; }
      OUTPUT_FILE="$2"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      err "unknown argument: $1"; usage >&2; exit 64;;
  esac
done

if [[ ! -f "${MANIFEST}" ]]; then
  err "manifest not found: ${MANIFEST}"
  exit 2
fi

# Refuse to print secrets to a terminal — they would land in scrollback
# / journal capture / tmux logs.
if [[ -z "${OUTPUT_FILE}" && -t 1 ]]; then
  err "refusing to write secrets to a terminal; use --output FILE"
  exit 65
fi

# Build the env content into a string first so we can write it
# atomically. Never echo individual values to a logged stream.
ENV_CONTENT=""
LINE_NO=0

while IFS= read -r raw_line || [[ -n "${raw_line}" ]]; do
  LINE_NO=$((LINE_NO + 1))
  # Strip leading/trailing whitespace.
  trimmed="${raw_line#"${raw_line%%[![:space:]]*}"}"
  trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"
  # Skip blanks + comments.
  [[ -z "${trimmed}" || "${trimmed}" == \#* ]] && continue

  # Split into VAR + PATH on whitespace.
  var_name="${trimmed%%[[:space:]]*}"
  rest="${trimmed#"${var_name}"}"
  pass_path="${rest#"${rest%%[![:space:]]*}"}"

  if [[ -z "${var_name}" || -z "${pass_path}" || "${var_name}" == "${pass_path}" ]]; then
    err "manifest line ${LINE_NO} malformed (expected: ENV_VAR_NAME pass/path)"
    exit 3
  fi

  # Validate var name: must be ASCII identifier-shaped so we never end
  # up writing a malformed env file.
  if ! [[ "${var_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    err "manifest line ${LINE_NO}: invalid env var name (must match [A-Za-z_][A-Za-z0-9_]*)"
    exit 3
  fi

  # Resolve via pass. Capture stdout but not stderr — pass's own stderr
  # may include the path but never the value.
  if ! value="$(pass show "${pass_path}" 2>/dev/null)"; then
    err "${var_name}: pass show '${pass_path}' failed"
    exit 1
  fi
  if [[ -z "${value}" ]]; then
    err "${var_name}: pass show '${pass_path}' returned empty"
    exit 1
  fi
  # Use only the FIRST line of the pass entry — the rest of a pass
  # record is conventionally metadata, never the secret.
  value="${value%%$'\n'*}"
  if [[ -z "${value}" ]]; then
    err "${var_name}: pass show '${pass_path}' first line empty"
    exit 1
  fi

  # Single-quote-quote the value so newlines/spaces/special chars survive
  # an EnvironmentFile re-read. Single quotes inside the value are
  # escaped as: '\''
  escaped="${value//\'/\'\\\'\'}"
  ENV_CONTENT+="${var_name}='${escaped}'"$'\n'

done < "${MANIFEST}"

if [[ -z "${OUTPUT_FILE}" ]]; then
  printf '%s' "${ENV_CONTENT}"
  exit 0
fi

# Atomic write to OUTPUT_FILE with mode 0600. mktemp in same dir so
# rename() stays atomic on the target filesystem.
out_dir="$(dirname "${OUTPUT_FILE}")"
mkdir -p "${out_dir}"
tmp_file="$(mktemp "${out_dir}/.fortress-load-secrets.XXXXXX")"
chmod 0600 "${tmp_file}"
printf '%s' "${ENV_CONTENT}" > "${tmp_file}"
mv -f "${tmp_file}" "${OUTPUT_FILE}"
chmod 0600 "${OUTPUT_FILE}"
exit 0
