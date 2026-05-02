#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"
ERROR_LOG="$REPO_ROOT/.specify/squad/error.log"
RECOVERY_DIR="$REPO_ROOT/.specify/squad/recovery"
STATE_FILE="$REPO_ROOT/.specify/squad/state.json"
SEED_DIR="$REPO_ROOT/tests/fixtures/kb/valid-seeds"

usage() {
  cat >&2 <<'USAGE'
usage:
  kb-recover.sh detect --file <path>
  kb-recover.sh backup --file <path>
  kb-recover.sh restore --file <path>
USAGE
}

log_error() {
  local message="$1"
  mkdir -p "$(dirname "$ERROR_LOG")"
  printf '%s\n' "$message" >> "$ERROR_LOG"
  printf '%s\n' "$message" >&2
}

validate_file() {
  local file_path="$1"

  python3 - "$file_path" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print("missing_file", end="")
    sys.exit(1)

text = path.read_text(encoding="utf-8")
name = path.name

required = {
    "calibration-profile.yaml": ["schema_version:", "last_updated:", "confidence_policy:", "domains:"],
    "estimates-log.yaml": ["schema_version:", "append_only:", "entries:"],
    "patterns.yaml": ["schema_version:", "entries:"],
    "pitfalls.yaml": ["schema_version:", "entries:"],
    "agent-scores.yaml": ["schema_version:"],
}

for key in required.get(name, ["schema_version:"]):
    if key not in text:
        print(key.rstrip(":"), end="")
        sys.exit(1)

for line in text.splitlines():
    if line.count('"') % 2 != 0:
        print("malformed_yaml_quote", end="")
        sys.exit(1)

sys.exit(0)
PY
}

iso_utc() {
  python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
}

set_recovery_mode() {
  local state_file="$STATE_FILE"
  mkdir -p "$(dirname "$state_file")"
  if [[ ! -f "$state_file" ]]; then
    printf '{"recovery_mode": true}\n' > "$state_file"
    return 0
  fi

  python3 - "$state_file" <<'PY'
import json
import os
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
try:
    data = json.loads(state_path.read_text(encoding="utf-8"))
except Exception:
    data = {}

data["recovery_mode"] = True

tmp = state_path.with_name(state_path.name + f".tmp.{os.getpid()}")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(tmp, state_path)
PY
}

do_detect() {
  local file_path="$1"
  local violated_key
  if ! violated_key="$(validate_file "$file_path")"; then
    log_error "KB_SCHEMA_INVALID:$file_path:${violated_key:-unknown_field}"
    exit 1
  fi
  exit 0
}

do_backup() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    log_error "KB_BACKUP_SOURCE_MISSING:$file_path"
    exit 1
  fi
  mkdir -p "$RECOVERY_DIR"
  local filename ts backup_path
  filename="$(basename "$file_path")"
  ts="$(iso_utc | tr ':' '-')"
  backup_path="$RECOVERY_DIR/${filename}-${ts}.bak"
  cp "$file_path" "$backup_path"
  printf '%s\n' "$backup_path"
}

is_valid_backup_for_file() {
  local backup_file="$1"
  local original_name="$2"
  local tmp_path
  tmp_path="$(mktemp)"
  cp "$backup_file" "$tmp_path"
  mv "$tmp_path" "${tmp_path}-${original_name}"
  tmp_path="${tmp_path}-${original_name}"

  if validate_file "$tmp_path" >/dev/null 2>&1; then
    rm -f "$tmp_path"
    return 0
  fi

  rm -f "$tmp_path"
  return 1
}

do_restore() {
  local file_path="$1"
  mkdir -p "$RECOVERY_DIR"

  local filename
  filename="$(basename "$file_path")"

  local candidate
  candidate=""
  while IFS= read -r backup_file; do
    [[ -z "$backup_file" ]] && continue
    if is_valid_backup_for_file "$backup_file" "$filename"; then
      candidate="$backup_file"
      break
    fi
  done < <(find "$RECOVERY_DIR" -type f -name "${filename}-*.bak" -print | LC_ALL=C sort -r)

  if [[ -n "$candidate" ]]; then
    cp "$candidate" "$file_path"
  else
    local seed_file="$SEED_DIR/$filename"
    if [[ ! -f "$seed_file" ]]; then
      log_error "KB_RESTORE_SEED_MISSING:$seed_file"
      exit 1
    fi
    cp "$seed_file" "$file_path"
  fi

  set_recovery_mode
  printf 'KB_RECOVERY_WARNING:%s restored and recovery_mode=true\n' "$file_path" >&2
  exit 0
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 64
  fi

  local command="$1"
  shift
  local file_path=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --file)
        shift
        file_path="${1:-}"
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

  if [[ -z "$file_path" ]]; then
    usage
    exit 64
  fi

  case "$command" in
    detect)
      do_detect "$file_path"
      ;;
    backup)
      do_backup "$file_path"
      ;;
    restore)
      do_restore "$file_path"
      ;;
    *)
      usage
      exit 64
      ;;
  esac
}

main "$@"
