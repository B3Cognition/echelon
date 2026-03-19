#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
ERROR_LOG="$REPO_ROOT/.specify/squad/error.log"
DEFAULT_CMD="speckit"
SUPPORTED_MIN_VERSION="1.0.0"

usage() {
  echo "usage: $0 [--cmd <command>]" >&2
}

log_error() {
  local message="$1"
  mkdir -p "$(dirname "$ERROR_LOG")"
  printf '%s\n' "$message" >> "$ERROR_LOG"
  printf '%s\n' "$message" >&2
}

parse_semver() {
  local version="$1"
  version="${version#v}"
  IFS='.' read -r major minor patch <<< "$version"
  major="${major:-0}"
  minor="${minor:-0}"
  patch="${patch:-0}"
  printf '%s %s %s\n' "$major" "$minor" "$patch"
}

version_gte() {
  local have="$1"
  local need="$2"
  local h_major h_minor h_patch n_major n_minor n_patch
  read -r h_major h_minor h_patch <<< "$(parse_semver "$have")"
  read -r n_major n_minor n_patch <<< "$(parse_semver "$need")"

  if (( h_major > n_major )); then return 0; fi
  if (( h_major < n_major )); then return 1; fi
  if (( h_minor > n_minor )); then return 0; fi
  if (( h_minor < n_minor )); then return 1; fi
  if (( h_patch >= n_patch )); then return 0; fi
  return 1
}

cmd_name="$DEFAULT_CMD"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cmd)
      shift
      if [[ $# -eq 0 ]]; then
        usage
        exit 64
      fi
      cmd_name="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 64
      ;;
  esac
  shift
done

if ! command -v "$cmd_name" >/dev/null 2>&1; then
  log_error "DEPENDENCY_SPECKIT_UNAVAILABLE"
  exit 1
fi

probe_output=""
if ! probe_output="$(python3 - "$cmd_name" <<'PY'
import subprocess
import sys

cmd = [sys.argv[1], "--version"]
try:
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=2)
except subprocess.TimeoutExpired:
    print("__TIMEOUT__")
    sys.exit(124)

print(result.stdout.strip())
sys.exit(result.returncode)
PY
)"; then
  rc=$?
  if [[ "$rc" -eq 124 ]] || [[ "$probe_output" == "__TIMEOUT__" ]]; then
    log_error "DEPENDENCY_SPECKIT_TIMEOUT"
    exit 2
  fi
  # Command exists but failed to answer version in expected way.
  log_error "DEPENDENCY_SPECKIT_INCOMPATIBLE"
  exit 3
fi

version="$(printf '%s' "$probe_output" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
if [[ -z "$version" ]]; then
  log_error "DEPENDENCY_SPECKIT_INCOMPATIBLE"
  exit 3
fi

if ! version_gte "$version" "$SUPPORTED_MIN_VERSION"; then
  log_error "DEPENDENCY_SPECKIT_INCOMPATIBLE"
  exit 3
fi

printf 'DEPENDENCY_SPECKIT_AVAILABLE:%s\n' "$version"
exit 0
