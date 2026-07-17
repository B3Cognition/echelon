#!/usr/bin/env bash
# Context7 CLI wrapper for Echelon agents.
# Usage:
#   context7-docs.sh library "<library name>" [--json]
#   context7-docs.sh docs "<context7-library-id>" "<question>" [--json]
#
# In --json mode, stdout is an Echelon envelope:
#   {schema, ok, command, query, library_id, redirected_from, result}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTX7_NODE_DIR="$(dirname "$SCRIPT_DIR")/node/context7"
NODE_RUNTIME_RESOLVER="$SCRIPT_DIR/node-runtime-resolver.sh"

if [[ ! -f "$NODE_RUNTIME_RESOLVER" ]]; then
  echo "Context7 runtime resolver is missing at $NODE_RUNTIME_RESOLVER" >&2
  exit 127
fi
# shellcheck source=node-runtime-resolver.sh
source "$NODE_RUNTIME_RESOLVER"

if [[ -n "${ECHELON_CONTEXT7_BIN:-}" ]]; then
  CTX7_BIN="$ECHELON_CONTEXT7_BIN"
else
  if ! CTX7_RUNTIME_DIR="$(echelon_resolve_context7_runtime "$(dirname "$CTX7_NODE_DIR")")"; then
    exit 127
  fi
  CTX7_BIN="$CTX7_RUNTIME_DIR/node_modules/.bin/ctx7"
fi

if [[ ! -x "$CTX7_BIN" ]]; then
  echo "Context7 CLI is not installed at $CTX7_BIN" >&2
  echo "Run Echelon's installer: bash <echelon-checkout>/scripts/install.sh" >&2
  exit 127
fi

JSON_MODE=false
for arg in "$@"; do
  if [[ "$arg" == "--json" ]]; then
    JSON_MODE=true
    break
  fi
done

emit_json_envelope() {
  local status="$1" command_name="$2" query="$3" library_id="$4" redirected_from="$5" out_file="$6" err_file="$7"
  python3 - "$status" "$command_name" "$query" "$library_id" "$redirected_from" "$out_file" "$err_file" <<'PY'
import json
import sys
from pathlib import Path

status = int(sys.argv[1])
command_name = sys.argv[2]
query = sys.argv[3]
library_id = sys.argv[4] or None
redirected_from = sys.argv[5] or None
out_path = Path(sys.argv[6])
err_path = Path(sys.argv[7])
stdout_text = out_path.read_text(encoding="utf-8", errors="replace")
stderr_text = err_path.read_text(encoding="utf-8", errors="replace")

try:
    result = json.loads(stdout_text) if stdout_text.strip() else None
    parse_error = None
except json.JSONDecodeError as exc:
    result = stdout_text
    parse_error = str(exc)

payload = {
    "schema": "echelon.context7.v1",
    "ok": status == 0 and parse_error is None,
    "command": command_name,
    "query": query,
    "library_id": library_id,
    "redirected_from": redirected_from,
    "result": result,
}
if stderr_text:
    payload["stderr"] = stderr_text
if status != 0:
    payload["exit_code"] = status
if parse_error is not None:
    payload["parse_error"] = parse_error

print(json.dumps(payload, ensure_ascii=False))
PY
}

run_json_command() {
  local command_name="$1" query="$2" library_id="$3" redirected_from="$4"
  shift 4

  local out_file err_file status
  out_file="$(mktemp)"
  err_file="$(mktemp)"
  cleanup_json_command() {
    rm -f "$out_file" "$err_file"
  }
  trap cleanup_json_command RETURN

  set +e
  "$CTX7_BIN" "$@" >"$out_file" 2>"$err_file"
  status="$?"
  set -e

  emit_json_envelope "$status" "$command_name" "$query" "$library_id" "$redirected_from" "$out_file" "$err_file"
  return "$status"
}

if [[ "$JSON_MODE" == "true" && "${1:-}" == "library" ]]; then
  if [[ "$#" -lt 2 ]]; then
    run_json_command "library" "" "" "" "$@"
    exit "$?"
  fi
  QUERY="$2"
  run_json_command "library" "$QUERY" "" "" "$@"
  exit "$?"
fi

if [[ "${1:-}" == "docs" ]]; then
  if [[ "$#" -lt 3 ]]; then
    exec "$CTX7_BIN" "$@"
  fi
  shift
  LIBRARY_ID="$1"
  QUERY="$2"
  shift 2

  OUT_FILE="$(mktemp)"
  ERR_FILE="$(mktemp)"
  cleanup() {
    rm -f "$OUT_FILE" "$ERR_FILE"
  }
  trap cleanup EXIT

  if [[ "$JSON_MODE" == "true" ]]; then
    set +e
    "$CTX7_BIN" docs "$LIBRARY_ID" "$QUERY" "$@" >"$OUT_FILE" 2>"$ERR_FILE"
    STATUS="$?"
    set -e

    NEW_ID="$(sed -n 's/^New ID: //p' "$OUT_FILE" | head -1)"
    if [[ "$STATUS" -ne 0 && -n "$NEW_ID" ]]; then
      run_json_command "docs" "$QUERY" "$NEW_ID" "$LIBRARY_ID" docs "$NEW_ID" "$QUERY" "$@"
      exit "$?"
    fi

    emit_json_envelope "$STATUS" "docs" "$QUERY" "$LIBRARY_ID" "" "$OUT_FILE" "$ERR_FILE"
    exit "$STATUS"
  fi

  if "$CTX7_BIN" docs "$LIBRARY_ID" "$QUERY" "$@" >"$OUT_FILE" 2>"$ERR_FILE"; then
    cat "$OUT_FILE"
    cat "$ERR_FILE" >&2
    exit 0
  fi
  STATUS="$?"
  NEW_ID="$(sed -n 's/^New ID: //p' "$OUT_FILE" | head -1)"
  if [[ -n "$NEW_ID" ]]; then
    "$CTX7_BIN" docs "$NEW_ID" "$QUERY" "$@"
    exit "$?"
  fi

  cat "$OUT_FILE"
  cat "$ERR_FILE" >&2
  exit "$STATUS"
fi

exec "$CTX7_BIN" "$@"
