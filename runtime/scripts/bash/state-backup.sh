#!/usr/bin/env bash
# state-backup.sh — Create checkpoint backup of state.json before phase transitions
# Usage: state-backup.sh [--state PATH] [--max-backups N]
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"

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
STATE_FILE="${1:-$SQUAD_DIR/state.json}"
MAX_BACKUPS="${2:-5}"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "No state file to backup: $STATE_FILE" >&2
  exit 0
fi

BACKUP_DIR="$(dirname "$STATE_FILE")/backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
PHASE=$(grep -o '"phase"' "$STATE_FILE" >/dev/null 2>&1 && \
  sed -n 's/.*"phase"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -1 || echo "")
BACKUP_FILE="$BACKUP_DIR/state-${PHASE:-unknown}-${TIMESTAMP}.json"

cp "$STATE_FILE" "$BACKUP_FILE"

# Rotate: keep only MAX_BACKUPS most recent
ls -t "$BACKUP_DIR"/state-*.json 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs rm -f 2>/dev/null || true

echo "$BACKUP_FILE"
