#!/usr/bin/env bash
# T-18 Unit Test: Validate sage-decisions.yaml schema structure
# Usage: bash tests/unit/test-sage-decisions-schema.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILE="$REPO_ROOT/knowledge-base/sage-decisions.yaml"
PASS=0
FAIL=0

# NOTE: `((PASS++))` returns the OLD value (0 initially), which is falsy
# arithmetic and trips `set -e`, causing this whole script to exit silently
# after the first PASS. Use pre-increment OR `|| true` OR plain arithmetic.
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== sage-decisions.yaml schema validation ==="
echo ""

# Check file exists
if [[ ! -f "$FILE" ]]; then
  fail "sage-decisions.yaml does not exist at $FILE"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi
pass "File exists"

# Check schema_version
if grep -q '^schema_version: 2' "$FILE"; then
  pass "schema_version is 2"
else
  fail "schema_version must be 2"
fi

# Check append_only
if grep -q '^append_only: true' "$FILE"; then
  pass "append_only is true"
else
  fail "append_only must be true"
fi

# Check max_entries
if grep -q '^max_entries: 100' "$FILE"; then
  pass "max_entries is 100"
else
  fail "max_entries must be 100"
fi

# Check entries key exists
if grep -q '^entries:' "$FILE"; then
  pass "entries key exists"
else
  fail "entries key must exist"
fi

# Check that entries is an array (empty [] or list items starting with -)
ENTRIES_LINE=$(grep '^entries:' "$FILE")
if echo "$ENTRIES_LINE" | grep -q '\[\]'; then
  pass "entries is an empty array (seed state)"
elif grep -qA1 '^entries:' "$FILE" | grep -q '^ *-'; then
  pass "entries contains array items"
else
  # Could be empty with no [] — check if next non-blank line is indented with -
  NEXT_LINE=$(sed -n '/^entries:/,/^[^ ]/{ /^entries:/d; /^$/d; p; }' "$FILE" | head -1)
  if [[ -z "$NEXT_LINE" ]]; then
    pass "entries is empty (valid seed state)"
  elif echo "$NEXT_LINE" | grep -q '^ *-'; then
    pass "entries contains array items"
  else
    fail "entries must be an array ([] or list of - items)"
  fi
fi

# Check no unexpected top-level keys
EXPECTED_KEYS="schema_version append_only max_entries entries"
while IFS= read -r line; do
  # Skip blank lines, comments, array items, and indented lines
  [[ -z "$line" ]] && continue
  [[ "$line" =~ ^# ]] && continue
  [[ "$line" =~ ^[[:space:]] ]] && continue
  KEY=$(echo "$line" | cut -d: -f1)
  if ! echo "$EXPECTED_KEYS" | grep -qw "$KEY"; then
    fail "Unexpected top-level key: $KEY"
  fi
done < "$FILE"
pass "No unexpected top-level keys"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
