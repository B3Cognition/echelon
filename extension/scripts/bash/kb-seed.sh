#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH='' cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH='' cd "$SCRIPT_DIR/../../.." && pwd)"
. "$SCRIPT_DIR/python-detect.sh"
KB_DIR="$REPO_ROOT/knowledge-base"
FIXTURES_DIR="$REPO_ROOT/tests/fixtures/kb/valid-seeds"
ERROR_LOG="$REPO_ROOT/.specify/squad/error.log"

FILES=("calibration-profile.yaml" "estimates-log.yaml" "patterns.yaml" "pitfalls.yaml")

log_error() {
  local message="$1"
  mkdir -p "$(dirname "$ERROR_LOG")"
  printf '%s\n' "$message" >> "$ERROR_LOG"
  printf '%s\n' "$message" >&2
}

validate_file() {
  local file_path="$1"

  $PYTHON - "$file_path" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

# Minimal parser-safe contract checks for Tier 1 fixtures.
if "schema_version:" not in text:
    print("schema_version", end="")
    sys.exit(1)

name = path.name
required = {
    "calibration-profile.yaml": ["last_updated:", "confidence_policy:", "domains:"],
    "estimates-log.yaml": ["append_only:", "entries:"],
    "patterns.yaml": ["entries:"],
    "pitfalls.yaml": ["entries:"],
}

for key in required.get(name, []):
    if key not in text:
        print(key.rstrip(":"), end="")
        sys.exit(1)

# Basic malformed YAML guard used by fixtures: unmatched quote count on a line.
for line in text.splitlines():
    if line.count('"') % 2 != 0:
        print("malformed_yaml_quote", end="")
        sys.exit(1)

sys.exit(0)
PY
}

add_seed_metadata() {
  local file_path="$1"
  local source_fixture="$2"
  local seeded_at
  seeded_at="$($PYTHON -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')"

  tmp_file="$file_path.tmp.$$"
  {
    printf '# seeded_at: %s\n' "$seeded_at"
    printf '# schema_version: 1\n'
    printf '# source_fixture: %s\n' "$source_fixture"
    cat "$file_path"
  } > "$tmp_file"
  mv -f "$tmp_file" "$file_path"
}

mkdir -p "$KB_DIR"

for file in "${FILES[@]}"; do
  target="$KB_DIR/$file"
  source_fixture="$FIXTURES_DIR/$file"

  if [[ ! -f "$source_fixture" ]]; then
    log_error "KB_SCHEMA_INVALID:$source_fixture:missing_fixture"
    exit 1
  fi

  if [[ ! -s "$target" ]]; then
    cp "$source_fixture" "$target"
    add_seed_metadata "$target" "$source_fixture"
  fi

  if ! violated_key="$(validate_file "$target")"; then
    log_error "KB_SCHEMA_INVALID:$target:${violated_key:-unknown_key}"
    exit 1
  fi
done

exit 0
