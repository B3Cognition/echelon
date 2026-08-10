#!/usr/bin/env bash
# CI test: verify journal-entry-types.json is in sync with the YAML source.
# Regenerates JSON from YAML and diffs against committed version.
# Exits non-zero if they differ.
# Run: bash tests/unit/test-json-freshness.sh

set -eu

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
YAML_FILE="$ROOT_DIR/runtime/workflow/journal-entry-types.yaml"
JSON_FILE="$ROOT_DIR/runtime/workflow/journal-entry-types.json"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PASS=0
FAIL=0

echo "=== JSON Freshness Check ==="

if [ ! -f "$YAML_FILE" ]; then
  echo "  FAIL: YAML source not found: $YAML_FILE"
  exit 1
fi

if [ ! -f "$JSON_FILE" ]; then
  echo "  FAIL: Committed JSON not found: $JSON_FILE"
  exit 1
fi

# Regenerate JSON from YAML using the same method as install.sh
REGEN_JSON="$TMP_DIR/regenerated.json"
python3 -c "
import yaml, json, sys
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
with open(sys.argv[2], 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
" "$YAML_FILE" "$REGEN_JSON"

# Compare
if diff -q "$JSON_FILE" "$REGEN_JSON" >/dev/null 2>&1; then
  echo "  PASS: JSON is in sync with YAML"
  PASS=$((PASS + 1))
else
  echo "  FAIL: JSON is out of sync with YAML"
  echo "  Run the following to regenerate:"
  echo "    python3 -c \"import yaml,json,sys; ..."
  echo ""
  echo "  Diff:"
  diff "$JSON_FILE" "$REGEN_JSON" || true
  FAIL=$((FAIL + 1))
fi

echo ""
echo "═══════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
