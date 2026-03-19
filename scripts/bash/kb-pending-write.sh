#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"
PENDING_DIR="$REPO_ROOT/knowledge-base/.pending"
PROCESSED_DIR="$PENDING_DIR/processed"
FAILED_DIR="$PENDING_DIR/failed"

usage() {
  cat >&2 <<'USAGE'
usage:
  kb-pending-write.sh --target-file <path> --operation <append_entry> --payload <yaml_fragment> --run-id <id> --agent <name> --operation-id <id>
USAGE
}

now_iso_utc() {
  python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
}

now_compact_utc() {
  python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
PY
}

main() {
  local target_file=""
  local operation=""
  local payload=""
  local run_id=""
  local agent=""
  local operation_id=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target-file)
        shift
        target_file="${1:-}"
        ;;
      --operation)
        shift
        operation="${1:-}"
        ;;
      --payload)
        shift
        payload="${1:-}"
        ;;
      --run-id)
        shift
        run_id="${1:-}"
        ;;
      --agent)
        shift
        agent="${1:-}"
        ;;
      --operation-id)
        shift
        operation_id="${1:-}"
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

  if [[ -z "$target_file" || -z "$operation" || -z "$run_id" || -z "$agent" || -z "$operation_id" ]]; then
    usage
    exit 64
  fi

  mkdir -p "$PENDING_DIR" "$PROCESSED_DIR" "$FAILED_DIR"

  local existing_file
  existing_file="$(find "$PENDING_DIR" -maxdepth 1 -type f -name "*.pending.yaml" -exec grep -l "^operation_id: ${operation_id}$" {} + 2>/dev/null | head -n 1 || true)"
  if [[ -n "$existing_file" ]]; then
    printf '%s\n' "$existing_file"
    exit 0
  fi

  local ts_compact created_at filename pending_path checksum
  ts_compact="$(now_compact_utc)"
  created_at="$(now_iso_utc)"
  filename="${ts_compact}-${run_id}-${operation_id}.pending.yaml"
  pending_path="$PENDING_DIR/$filename"

  checksum="$(python3 - "$target_file" "$operation" "$payload" <<'PY'
import hashlib
import sys

raw = "|".join([sys.argv[1], sys.argv[2], sys.argv[3]])
print("sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest())
PY
)"

  {
    printf 'schema_version: 1\n'
    printf 'operation_id: %s\n' "$operation_id"
    printf 'created_at: %s\n' "$created_at"
    printf 'source:\n'
    printf '  run_id: %s\n' "$run_id"
    printf '  agent: %s\n' "$agent"
    printf 'target_file: %s\n' "$target_file"
    printf 'operation: %s\n' "$operation"
    printf 'payload: |\n'
    if [[ -n "$payload" ]]; then
      while IFS= read -r line; do
        printf '  %s\n' "$line"
      done <<< "$payload"
    fi
    printf 'checksum: %s\n' "$checksum"
  } > "$pending_path"

  printf '%s\n' "$pending_path"
}

main "$@"
