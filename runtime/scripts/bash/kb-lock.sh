#!/usr/bin/env bash
set -euo pipefail
. "$(CDPATH='' cd "$(dirname "$0")" && pwd)/python-detect.sh"

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-base"
LOCKS_DIR="$KB_DIR/.locks"
LOCK_DIR="$LOCKS_DIR/kb-write.lock"
METADATA_FILE="$LOCK_DIR/metadata.yaml"

_resolve_squad_dir() {
  local base current_file run_id
  if [[ -n "${ECHELON_SQUAD_DIR:-}" ]]; then
    echo "$ECHELON_SQUAD_DIR"
    return 0
  fi

  for base in runs; do
    current_file="$REPO_ROOT/$base/.current"
    if [[ -f "$current_file" ]]; then
      run_id=$(tr -d '[:space:]' < "$current_file")
      if [[ -n "$run_id" && -d "$REPO_ROOT/$base/$run_id" ]]; then
        echo "$REPO_ROOT/$base/$run_id"
        return 0
      fi
    fi
  done

  echo "$REPO_ROOT/runs"
}

SQUAD_DIR="$(_resolve_squad_dir)"
RECOVERY_DIR="${ECHELON_KB_RECOVERY_DIR:-$SQUAD_DIR/recovery}"

DEFAULT_LEASE_SECONDS=30
DEFAULT_GRACE_SECONDS=5
DEFAULT_POLL_SECONDS=1
DEFAULT_WAIT_SECONDS=30

usage() {
  cat >&2 <<'USAGE'
usage:
  kb-lock.sh acquire --run-id <id> [--agent <name>]
  kb-lock.sh release --run-id <id>
  kb-lock.sh status
USAGE
}

now_iso_utc() {
  $PYTHON - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
}

now_compact_utc() {
  $PYTHON - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
PY
}

iso_to_epoch() {
  local ts="$1"
  $PYTHON - "$ts" <<'PY'
import sys
from datetime import datetime, timezone

raw = sys.argv[1].strip()
if raw.endswith("Z"):
    raw = raw[:-1] + "+00:00"
try:
    dt = datetime.fromisoformat(raw)
except Exception:
    sys.exit(1)
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
print(int(dt.timestamp()))
PY
}

filesystem_type() {
  local path="$1"
  if stat -f %T "$path" >/dev/null 2>&1; then
    stat -f %T "$path"
    return 0
  fi
  if stat -f -c %T "$path" >/dev/null 2>&1; then
    stat -f -c %T "$path"
    return 0
  fi
  echo "unknown"
}

ensure_supported_filesystem() {
  local fs_type
  fs_type="$(filesystem_type "$REPO_ROOT")"

  # On some macOS variants, `stat -f %T` can return placeholder values such as '/'.
  # Treat unknown values as local unless they explicitly match unsupported network/distributed fs names.
  local fs_type_lc
  fs_type_lc="$(printf '%s' "$fs_type" | tr '[:upper:]' '[:lower:]')"

  case "$fs_type_lc" in
    *nfs*|*smb*|*cifs*|*fuse*|*sshfs*)
      printf 'KB_LOCK_UNSUPPORTED_FILESYSTEM:%s\n' "$fs_type" >&2
      exit 3
      ;;
    *)
      return 0
      ;;
  esac
}

read_meta_field() {
  local key="$1"
  local file="$2"
  if [[ ! -f "$file" ]]; then
    return 1
  fi
  awk -F': ' -v key="$key" '$1==key {print $2; exit}' "$file"
}

is_stale_lock() {
  local acquired_at="$1"
  local lease_seconds="$2"
  local grace_seconds="$3"

  local now_epoch acquired_epoch age max_age
  now_epoch="$($PYTHON - <<'PY'
import time
print(int(time.time()))
PY
)"
  if ! acquired_epoch="$(iso_to_epoch "$acquired_at")"; then
    return 0
  fi

  age=$((now_epoch - acquired_epoch))
  max_age=$((lease_seconds + grace_seconds))
  (( age > max_age ))
}

quarantine_stale_lock() {
  mkdir -p "$RECOVERY_DIR"
  if [[ -f "$METADATA_FILE" ]]; then
    local ts
    ts="$(now_compact_utc)"
    cp "$METADATA_FILE" "$RECOVERY_DIR/stale-lock-${ts}.yaml"
  fi
  rm -rf "$LOCK_DIR"
}

write_metadata() {
  local run_id="$1"
  local agent="$2"
  local acquired_at
  acquired_at="$(now_iso_utc)"

  cat > "$METADATA_FILE" <<EOF
owner_run_id: $run_id
owner_agent: $agent
acquired_at: $acquired_at
lease_seconds: $DEFAULT_LEASE_SECONDS
pid: $$
EOF
}

acquire_lock() {
  local run_id="$1"
  local agent="$2"

  mkdir -p "$LOCKS_DIR"

  local start_epoch now_epoch elapsed
  start_epoch="$($PYTHON - <<'PY'
import time
print(int(time.time()))
PY
)"

  while true; do
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      write_metadata "$run_id" "$agent"
      exit 0
    fi

    if [[ -f "$METADATA_FILE" ]]; then
      local acquired_at lease_seconds
      acquired_at="$(read_meta_field acquired_at "$METADATA_FILE" || true)"
      lease_seconds="$(read_meta_field lease_seconds "$METADATA_FILE" || true)"
      lease_seconds="${lease_seconds:-$DEFAULT_LEASE_SECONDS}"
      if [[ -n "$acquired_at" ]] && is_stale_lock "$acquired_at" "$lease_seconds" "$DEFAULT_GRACE_SECONDS"; then
        quarantine_stale_lock
        continue
      fi
    fi

    now_epoch="$($PYTHON - <<'PY'
import time
print(int(time.time()))
PY
)"
    elapsed=$((now_epoch - start_epoch))
    if (( elapsed >= DEFAULT_WAIT_SECONDS )); then
      printf 'KB_LOCK_TIMEOUT\n' >&2
      exit 2
    fi

    sleep "$DEFAULT_POLL_SECONDS"
  done
}

release_lock() {
  local run_id="$1"

  if [[ ! -d "$LOCK_DIR" ]]; then
    printf 'KB_LOCK_RELEASE_NOOP: lock is not held\n' >&2
    exit 0
  fi

  if [[ -f "$METADATA_FILE" ]]; then
    local owner_run_id
    owner_run_id="$(read_meta_field owner_run_id "$METADATA_FILE" || true)"
    if [[ -n "$owner_run_id" && "$owner_run_id" != "$run_id" ]]; then
      printf 'KB_LOCK_RELEASE_DENIED:owner=%s current=%s\n' "$owner_run_id" "$run_id" >&2
      exit 1
    fi
  fi

  rm -rf "$LOCK_DIR"
  exit 0
}

status_lock() {
  if [[ -d "$LOCK_DIR" ]]; then
    local owner_run_id
    owner_run_id="$(read_meta_field owner_run_id "$METADATA_FILE" || true)"
    owner_run_id="${owner_run_id:-unknown}"
    printf 'LOCKED:%s\n' "$owner_run_id"
  else
    printf 'UNLOCKED\n'
  fi
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 64
  fi

  ensure_supported_filesystem

  local subcommand="$1"
  shift

  local run_id=""
  local agent="unknown"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-id)
        shift
        run_id="${1:-}"
        ;;
      --agent)
        shift
        agent="${1:-}"
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

  case "$subcommand" in
    acquire)
      if [[ -z "$run_id" ]]; then
        usage
        exit 64
      fi
      acquire_lock "$run_id" "$agent"
      ;;
    release)
      if [[ -z "$run_id" ]]; then
        usage
        exit 64
      fi
      release_lock "$run_id"
      ;;
    status)
      status_lock
      ;;
    *)
      usage
      exit 64
      ;;
  esac
}

main "$@"
