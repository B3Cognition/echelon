#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$ROOT_DIR/tests/fixtures/kb/size-variants"
mkdir -p "$OUT_DIR"

render_file() {
  local target="$1"
  local bytes="$2"
  {
    printf 'schema_version: 1\n'
    printf 'append_only: true\n'
    printf 'entries:\n'
    i=0
    while [[ $(wc -c < "$target.tmp") -lt "$bytes" ]]; do
      printf '  - id: size-%06d\n' "$i"
      printf '    run_id: squad-fixture\n'
      printf '    created_at: 2026-03-19T00:00:00Z\n'
      printf '    agent: TEST\n'
      printf '    domain: fixture\n'
      printf '    estimate_hours: 1\n'
      printf '    actual_hours: null\n'
      printf '    delta_hours: null\n'
      printf '    confidence: 0.5\n'
      printf '    source: generated\n'
      i=$((i + 1))
    done
  } > "$target.tmp"
  mv -f "$target.tmp" "$target"
}

: > "$OUT_DIR/1mb.yaml.tmp"
render_file "$OUT_DIR/1mb.yaml" 1048576

: > "$OUT_DIR/10mb.yaml.tmp"
render_file "$OUT_DIR/10mb.yaml" 10485760
