#!/usr/bin/env bash
# Regression tests for KB runtime path overrides.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
SCRIPTS="$REPO_ROOT/extension/scripts/bash"

pass=0
fail=0

assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1))
    printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1))
    printf 'FAIL: %s - %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result() { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
squad_dir="$tmpdir/runs/run-kb"
kb_file="$tmpdir/estimates-log.yaml"
bad_file="$tmpdir/bad.yaml"

mkdir -p "$squad_dir"
cat > "$kb_file" <<'YAML'
schema_version: 1
append_only: true
entries:
YAML
cat > "$bad_file" <<'YAML'
schema_version: 1
entries:
  - malformed: "unterminated
YAML

ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/kb-write.sh" append_entry \
  --file "$kb_file" \
  --payload "kind: estimate" \
  --run-id "run-kb" \
  --operation-id "op-kb" \
  --source "unit" >/dev/null

ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/kb-write.sh" validate_append_only \
  --file "$kb_file" >/dev/null

assert "kb-write stores checksum cache under active squad dir" "$(
  [[ -f "$squad_dir/cache/kb-checksums.json" ]] && ok_result || fail_result "missing checksum cache"
)"
assert "kb-write records checksum for target file" "$(
  grep -q "$(basename "$kb_file")" "$squad_dir/cache/kb-checksums.json" 2>/dev/null && ok_result || fail_result "checksum missing target"
)"

ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/kb-recover.sh" detect --file "$bad_file" >/dev/null 2>&1

assert "kb-recover logs errors under active squad dir" "$(
  grep -q 'KB_SCHEMA_INVALID' "$squad_dir/error.log" 2>/dev/null && ok_result || fail_result "missing active error.log entry"
)"

backup_path="$(ECHELON_SQUAD_DIR="$squad_dir" bash "$SCRIPTS/kb-recover.sh" backup --file "$kb_file" 2>/dev/null)"
assert "kb-recover stores backups under active squad dir" "$(
  [[ "$backup_path" == "$squad_dir"/recovery/* && -f "$backup_path" ]] && ok_result || fail_result "backup_path=$backup_path"
)"

rm -rf "$tmpdir"

echo ""
printf 'Results: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]] || exit 1
