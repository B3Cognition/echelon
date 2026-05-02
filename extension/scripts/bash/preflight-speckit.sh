#!/usr/bin/env bash
# preflight-speckit.sh — check if spec-kit is available, compatible, and reachable.
# Exit codes:
#   0 — available and compatible (stdout: DEPENDENCY_SPECKIT_AVAILABLE:<version>)
#   1 — unavailable (command not found or non-zero exit)
#   2 — timeout
#   3 — incompatible version (major < 1)
set -uo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/python-detect.sh"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"
ERROR_LOG="${SPEC_KIT_ERROR_LOG:-$REPO_ROOT/.specify/squad/error.log}"
TIMEOUT_SECONDS="${SPEC_KIT_TIMEOUT:-3}"
MIN_MAJOR=1

# Parse arguments
cmd=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cmd) cmd="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$cmd" ]]; then
  echo "Usage: preflight-speckit.sh --cmd <command>" >&2
  exit 1
fi

mkdir -p "$(dirname "$ERROR_LOG")"

# Resolve full path of cmd via PATH (needed so python3 subprocess can find it)
cmd_path="$(command -v "$cmd" 2>/dev/null || true)"
if [[ -z "$cmd_path" ]]; then
  # Absolute path that doesn't exist, or not on PATH
  cmd_path="$cmd"
fi

# Use python3 to run the command with a timeout (portable: works on macOS + Linux)
version_output="$($PYTHON - "$cmd_path" "$TIMEOUT_SECONDS" 2>/dev/null <<'PY'
import subprocess, sys

cmd_path = sys.argv[1]
timeout = float(sys.argv[2])
try:
    result = subprocess.run(
        [cmd_path, "--version"],
        timeout=timeout,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        sys.stdout.write(result.stdout.strip())
        sys.exit(0)
    else:
        sys.exit(1)
except subprocess.TimeoutExpired:
    sys.exit(124)
except (FileNotFoundError, PermissionError):
    sys.exit(127)
PY
)"
py_rc=$?

if [[ $py_rc -eq 124 ]]; then
  printf 'DEPENDENCY_SPECKIT_TIMEOUT\n' >> "$ERROR_LOG"
  exit 2
fi

if [[ $py_rc -ne 0 ]]; then
  printf 'DEPENDENCY_SPECKIT_UNAVAILABLE\n' >> "$ERROR_LOG"
  exit 1
fi

# Parse major version from "spec-kit version X.Y.Z"
version_number="$(printf '%s' "$version_output" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
major="$(printf '%s' "$version_number" | cut -d. -f1)"

if [[ -z "$major" ]] || [[ "$major" -lt "$MIN_MAJOR" ]]; then
  printf 'DEPENDENCY_SPECKIT_INCOMPATIBLE\n' >> "$ERROR_LOG"
  exit 3
fi

printf 'DEPENDENCY_SPECKIT_AVAILABLE:%s\n' "$version_output"
exit 0
