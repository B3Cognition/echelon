#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../.." && pwd)"

_resolve_squad_dir() {
  local base current_file run_id
  if [[ -n "${ECHELON_SQUAD_DIR:-}" ]]; then
    echo "$ECHELON_SQUAD_DIR"
    return 0
  fi

  for base in runs squad; do
    current_file="$REPO_ROOT/$base/.current"
    if [[ -f "$current_file" ]]; then
      run_id=$(tr -d '[:space:]' < "$current_file")
      if [[ -n "$run_id" && -d "$REPO_ROOT/$base/$run_id" ]]; then
        echo "$REPO_ROOT/$base/$run_id"
        return 0
      fi
    fi
  done

  echo "$REPO_ROOT/.specify/squad"
}

SQUAD_DIR="$(_resolve_squad_dir)"
CACHE_DIR="${ECHELON_KB_CACHE_DIR:-$SQUAD_DIR/cache}"
CHECKSUM_FILE="$CACHE_DIR/kb-checksums.json"

usage() {
  cat >&2 <<'USAGE'
usage:
  kb-write.sh append_entry --file <kb_file> --payload <yaml_fragment> --run-id <id> --operation-id <id> [--source <agent>]
  kb-write.sh validate_append_only --file <kb_file>
USAGE
}

now_iso_utc() {
  python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
}

ensure_checksum_store() {
  mkdir -p "$CACHE_DIR"
  if [[ ! -f "$CHECKSUM_FILE" ]]; then
    printf '{"files":{}}\n' > "$CHECKSUM_FILE"
  fi
}

append_entry() {
  local file_path="$1"
  local payload="$2"
  local run_id="$3"
  local operation_id="$4"
  local source="$5"

  local created_at
  created_at="$(now_iso_utc)"

  python3 - "$file_path" "$payload" "$run_id" "$operation_id" "$source" "$created_at" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

file_path = Path(sys.argv[1])
payload = sys.argv[2]
run_id = sys.argv[3]
operation_id = sys.argv[4]
source = sys.argv[5]
created_at = sys.argv[6]

if not file_path.exists():
    print(f"KB_WRITE_FILE_NOT_FOUND:{file_path}", file=sys.stderr)
    sys.exit(1)

content = file_path.read_text(encoding="utf-8")

# Keep append-only semantics simple and deterministic for YAML fixtures used in this repo.
if "entries:" not in content:
    print(f"KB_WRITE_SCHEMA_MISSING_ENTRIES:{file_path}", file=sys.stderr)
    sys.exit(1)

entry_lines = []
entry_lines.append("  - operation_id: " + operation_id)
entry_lines.append("    created_at: " + created_at)
entry_lines.append("    run_id: " + run_id)
entry_lines.append("    source: " + source)

for raw_line in payload.splitlines():
    stripped = raw_line.rstrip("\n")
    if not stripped.strip():
        continue
    if stripped.startswith("  - "):
        stripped = stripped[4:]
    if stripped.startswith("- "):
        stripped = stripped[2:]
    entry_lines.append("    " + stripped)

# Ensure metadata keys exist even if caller provided conflicting values in payload.
seen = set()
normalized = []
for line in entry_lines:
    key = None
    if ":" in line:
        key = line.strip().split(":", 1)[0]
    if key in {"operation_id", "created_at", "run_id", "source"}:
        if key in seen:
            continue
        seen.add(key)
    normalized.append(line)
entry_lines = normalized

new_block = "\n".join(entry_lines) + "\n"

if not content.endswith("\n"):
    content += "\n"

if "\nentries:\n" in content:
    updated = content + new_block
else:
    # Handle compact files where entries: is the last line.
    updated = content + new_block

tmp_path = file_path.with_name(file_path.name + f".tmp.{os.getpid()}")
try:
    tmp_path.write_text(updated, encoding="utf-8")
    os.replace(tmp_path, file_path)
except Exception:
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass
    raise

print("KB_WRITE_OK")
PY
}

validate_append_only() {
  local file_path="$1"
  ensure_checksum_store

  python3 - "$file_path" "$CHECKSUM_FILE" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

file_path = Path(sys.argv[1])
checksum_path = Path(sys.argv[2])

if not file_path.exists():
  print(f"KB_APPEND_ONLY_VIOLATION:{file_path}:missing_file", file=sys.stderr)
  sys.exit(1)

raw = file_path.read_text(encoding="utf-8")
lines = raw.splitlines()
entry_lines = [ln.rstrip() for ln in lines if ln.lstrip().startswith("-") or ln.startswith("  -") or ln.startswith("    ")]
entry_count = sum(1 for ln in lines if ln.lstrip().startswith("- "))
sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()

try:
  data = json.loads(checksum_path.read_text(encoding="utf-8"))
except Exception:
  data = {"files": {}}

files = data.setdefault("files", {})
key = str(file_path)
baseline = files.get(key)

if baseline is None:
  files[key] = {
    "entry_count": entry_count,
    "sha256": sha,
    "entry_slice_sha256": hashlib.sha256("\n".join(entry_lines).encode("utf-8")).hexdigest(),
  }
  checksum_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  print("KB_APPEND_ONLY_BASELINE_CREATED")
  sys.exit(0)

previous_count = int(baseline.get("entry_count", 0))
if entry_count < previous_count:
  print(f"KB_APPEND_ONLY_VIOLATION:{file_path}:entry_count_decreased", file=sys.stderr)
  sys.exit(1)

# Any full-file hash mismatch with unchanged count indicates mutation in existing entries.
if entry_count == previous_count and baseline.get("sha256") != sha:
  print(f"KB_APPEND_ONLY_VIOLATION:{file_path}:content_changed_without_append", file=sys.stderr)
  sys.exit(1)

# Update baseline after successful validation.
files[key] = {
  "entry_count": entry_count,
  "sha256": sha,
  "entry_slice_sha256": hashlib.sha256("\n".join(entry_lines).encode("utf-8")).hexdigest(),
}
checksum_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("KB_APPEND_ONLY_VALID")
PY
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 64
  fi

  local command="$1"
  shift

  local file_path=""
  local payload=""
  local run_id=""
  local operation_id=""
  local source="AUDITOR"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --file)
        shift
        file_path="${1:-}"
        ;;
      --payload)
        shift
        payload="${1:-}"
        ;;
      --run-id)
        shift
        run_id="${1:-}"
        ;;
      --operation-id)
        shift
        operation_id="${1:-}"
        ;;
      --source)
        shift
        source="${1:-}"
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

  case "$command" in
    append_entry)
      if [[ -z "$file_path" || -z "$run_id" || -z "$operation_id" ]]; then
        usage
        exit 64
      fi
      append_entry "$file_path" "$payload" "$run_id" "$operation_id" "$source"
      ;;
    validate_append_only)
      if [[ -z "$file_path" ]]; then
        usage
        exit 64
      fi
      validate_append_only "$file_path"
      ;;
    *)
      usage
      exit 64
      ;;
  esac
}

main "$@"
