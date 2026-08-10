#!/usr/bin/env bash
# state-lock.sh — File-level locking for state.json writes
# Modeled on kb-lock.sh but simpler (no lease/recovery — state writes are fast)
#
# Usage:
#   state-lock.sh acquire --run-id <id> [--agent <name>]
#   state-lock.sh release --run-id <id>
#   state-lock.sh status
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"

_resolve_run_dir() {
  local base current_file run_id
  if [[ -n "${ECHELON_RUN_DIR:-}" ]]; then
    echo "$ECHELON_RUN_DIR"
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

RUN_DIR="$(_resolve_run_dir)"
LOCK_FILE="$RUN_DIR/.state.lock"
LOCK_META="$RUN_DIR/.state.lock.meta"

DEFAULT_TIMEOUT=10  # seconds to wait for lock

usage() {
  cat >&2 <<'USAGE'
usage:
  state-lock.sh acquire --run-id <id> [--agent <name>]
  state-lock.sh release --run-id <id>
  state-lock.sh status
USAGE
}

do_acquire() {
  local run_id="" agent="COMMANDER" timeout=$DEFAULT_TIMEOUT
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-id) run_id="$2"; shift 2 ;;
      --agent)  agent="$2"; shift 2 ;;
      --timeout) timeout="$2"; shift 2 ;;
      *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
  done

  if [ -z "$run_id" ]; then
    echo "ERROR: --run-id required" >&2; exit 1
  fi

  mkdir -p "$RUN_DIR"

  # Try to acquire lock with timeout
  local start=$(date +%s)
  while true; do
    if (set -o noclobber; echo "$$" > "$LOCK_FILE") 2>/dev/null; then
      # Lock acquired — write metadata
      cat > "$LOCK_META" <<EOF
run_id: $run_id
agent: $agent
pid: $$
acquired_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
      echo "ACQUIRED"
      return 0
    fi

    # Check timeout
    local now=$(date +%s)
    if [ $((now - start)) -ge $timeout ]; then
      echo "TIMEOUT — lock held by PID $(cat "$LOCK_FILE" 2>/dev/null || echo unknown)" >&2
      # Check if holding process is dead (stale lock)
      local holder=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
      if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
        echo "Stale lock detected (PID $holder dead) — breaking" >&2
        rm -f "$LOCK_FILE" "$LOCK_META"
        continue
      fi
      return 1
    fi

    sleep 0.1
  done
}

do_release() {
  local run_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-id) run_id="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  if [ -f "$LOCK_FILE" ]; then
    rm -f "$LOCK_FILE" "$LOCK_META"
    echo "RELEASED"
  else
    echo "NO_LOCK"
  fi
}

do_status() {
  if [ -f "$LOCK_FILE" ]; then
    local holder=$(cat "$LOCK_FILE" 2>/dev/null || echo "unknown")
    echo "LOCKED by PID $holder"
    if [ -f "$LOCK_META" ]; then
      cat "$LOCK_META"
    fi
    # Check if holder is alive
    if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
      echo "WARNING: holding process is dead — lock is stale"
    fi
  else
    echo "UNLOCKED"
  fi
}

# Main dispatch
cmd="${1:-}"
shift || true

case "$cmd" in
  acquire) do_acquire "$@" ;;
  release) do_release "$@" ;;
  status)  do_status ;;
  *)       usage; exit 1 ;;
esac
