#!/usr/bin/env bash
set -euo pipefail
. "$(CDPATH='' cd "$(dirname "$0")" && pwd)/python-detect.sh"

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"
PENDING_DIR="$REPO_ROOT/knowledge-base/.pending"
PROCESSED_DIR="$PENDING_DIR/processed"
FAILED_DIR="$PENDING_DIR/failed"
ERROR_LOG="$REPO_ROOT/.specify/squad/error.log"
KB_DEDUPE_WINDOW="${KB_DEDUPE_WINDOW:-200}"

usage() {
  cat >&2 <<'USAGE'
usage:
  kb-pending-merge.sh --run-id <id> [--agent <name>]
USAGE
}

log_error() {
  local message="$1"
  mkdir -p "$(dirname "$ERROR_LOG")"
  printf '%s\n' "$message" >> "$ERROR_LOG"
  printf '%s\n' "$message" >&2
}

extract_yaml_field() {
  local file_path="$1"
  local key="$2"
  awk -F': ' -v key="$key" '$1==key {print $2; exit}' "$file_path"
}

extract_payload() {
  local file_path="$1"
  awk 'BEGIN{in_payload=0}
       /^payload: \|/{in_payload=1; next}
       in_payload==1 {
         if ($0 ~ /^[^[:space:]]/) {exit}
         sub(/^  /, "", $0)
         print
       }' "$file_path"
}

checksum_for() {
  local target_file="$1"
  local operation="$2"
  local payload="$3"

  $PYTHON - "$target_file" "$operation" "$payload" <<'PY'
import hashlib
import sys
raw = "|".join([sys.argv[1], sys.argv[2], sys.argv[3]])
print("sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest())
PY
}

is_operation_merged() {
  local target_file="$1"
  local operation_id="$2"

  if [[ ! -f "$target_file" ]]; then
    return 1
  fi

  tail -n "$KB_DEDUPE_WINDOW" "$target_file" | grep -Fq "operation_id: $operation_id"
}

move_to_processed() {
  local file_path="$1"
  mkdir -p "$PROCESSED_DIR"
  mv -f "$file_path" "$PROCESSED_DIR/$(basename "$file_path")"
}

move_to_failed() {
  local file_path="$1"
  mkdir -p "$FAILED_DIR"
  mv -f "$file_path" "$FAILED_DIR/$(basename "$file_path")"
}

main() {
  local run_id=""
  local agent="AUDITOR"

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

  if [[ -z "$run_id" ]]; then
    usage
    exit 64
  fi

  mkdir -p "$PENDING_DIR" "$PROCESSED_DIR" "$FAILED_DIR"

  local pending_files
  pending_files="$(find "$PENDING_DIR" -maxdepth 1 -type f -name '*.pending.yaml' -print | LC_ALL=C sort || true)"
  if [[ -z "$pending_files" ]]; then
    exit 0
  fi

  local seen_operation_ids="\n"

  has_seen_operation_id() {
    local op_id="$1"
    printf '%s' "$seen_operation_ids" | grep -Fqx "$op_id"
  }

  mark_seen_operation_id() {
    local op_id="$1"
    seen_operation_ids="${seen_operation_ids}${op_id}\n"
  }

  while IFS= read -r pending_file; do
    [[ -z "$pending_file" ]] && continue

    local schema_version operation_id target_file operation checksum payload expected_checksum
    schema_version="$(extract_yaml_field "$pending_file" "schema_version" || true)"
    operation_id="$(extract_yaml_field "$pending_file" "operation_id" || true)"
    target_file="$(extract_yaml_field "$pending_file" "target_file" || true)"
    operation="$(extract_yaml_field "$pending_file" "operation" || true)"
    expected_checksum="$(extract_yaml_field "$pending_file" "checksum" || true)"
    payload="$(extract_payload "$pending_file")"

    if [[ "$schema_version" != "1" || -z "$operation_id" || -z "$target_file" || -z "$operation" || -z "$expected_checksum" ]]; then
      log_error "KB_PENDING_PARSE_ERROR:$pending_file"
      move_to_failed "$pending_file"
      continue
    fi

    checksum="$(checksum_for "$target_file" "$operation" "$payload")"
    if [[ "$checksum" != "$expected_checksum" ]]; then
      log_error "KB_PENDING_CHECKSUM_MISMATCH:$pending_file"
      move_to_failed "$pending_file"
      continue
    fi

    if has_seen_operation_id "$operation_id"; then
      move_to_processed "$pending_file"
      continue
    fi

    if is_operation_merged "$target_file" "$operation_id"; then
      mark_seen_operation_id "$operation_id"
      move_to_processed "$pending_file"
      continue
    fi

    if ! bash "$SCRIPT_DIR/kb-lock.sh" acquire --run-id "$run_id" --agent "$agent"; then
      rc=$?
      if [[ "$rc" -eq 2 ]]; then
        # Leave this and remaining files for next run.
        exit 0
      fi
      log_error "KB_PENDING_LOCK_ERROR:$pending_file"
      move_to_failed "$pending_file"
      continue
    fi

    if ! bash "$SCRIPT_DIR/kb-write.sh" append_entry --file "$target_file" --payload "$payload" --run-id "$run_id" --operation-id "$operation_id" --source "$agent"; then
      bash "$SCRIPT_DIR/kb-lock.sh" release --run-id "$run_id" >/dev/null 2>&1 || true
      log_error "KB_PENDING_WRITE_ERROR:$pending_file"
      move_to_failed "$pending_file"
      continue
    fi

    bash "$SCRIPT_DIR/kb-lock.sh" release --run-id "$run_id" >/dev/null 2>&1 || true
    mark_seen_operation_id "$operation_id"
    move_to_processed "$pending_file"
  done <<< "$pending_files"

  exit 0
}

main "$@"
