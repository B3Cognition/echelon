#!/usr/bin/env bash
# T-39: Unit test — verify language rule files exist and contain required sections
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LANG_RULES_DIR="$ROOT/knowledge-base/language-rules"
FAILURES=0

assert_file_exists() {
  local file="$1"
  local description="$2"
  if [[ -f "$file" ]]; then
    echo "PASS: $description"
  else
    echo "FAIL: $description (file not found: $file)"
    FAILURES=$((FAILURES + 1))
  fi
}

assert_grep() {
  local pattern="$1"
  local file="$2"
  local description="$3"
  if grep -q "$pattern" "$file"; then
    echo "PASS: $description"
  else
    echo "FAIL: $description (pattern '$pattern' not found in $file)"
    FAILURES=$((FAILURES + 1))
  fi
}

assert_not_empty() {
  local file="$1"
  local description="$2"
  if [[ -s "$file" ]]; then
    echo "PASS: $description"
  else
    echo "FAIL: $description (file is empty: $file)"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "=== Language Rules Existence Unit Tests ==="
echo ""

# --- File existence ---
echo "--- File Existence ---"
assert_file_exists "$LANG_RULES_DIR/typescript.md" "typescript.md exists"
assert_file_exists "$LANG_RULES_DIR/python.md" "python.md exists"
assert_file_exists "$LANG_RULES_DIR/bash.md" "bash.md exists"

# --- Non-empty ---
echo ""
echo "--- Non-Empty ---"
assert_not_empty "$LANG_RULES_DIR/typescript.md" "typescript.md is not empty"
assert_not_empty "$LANG_RULES_DIR/python.md" "python.md is not empty"
assert_not_empty "$LANG_RULES_DIR/bash.md" "bash.md is not empty"

# --- TypeScript rules contain key sections ---
echo ""
echo "--- TypeScript Rule Content ---"
assert_grep "strict" "$LANG_RULES_DIR/typescript.md" "typescript.md covers strict mode"
assert_grep "any" "$LANG_RULES_DIR/typescript.md" "typescript.md covers no-any rule"
assert_grep "[Ee]rror [Hh]andling" "$LANG_RULES_DIR/typescript.md" "typescript.md covers error handling"
assert_grep "[Nn]ull" "$LANG_RULES_DIR/typescript.md" "typescript.md covers null safety"

# --- Python rules contain key sections ---
echo ""
echo "--- Python Rule Content ---"
assert_grep "[Tt]ype [Hh]int" "$LANG_RULES_DIR/python.md" "python.md covers type hints"
assert_grep "[Dd]ocstring" "$LANG_RULES_DIR/python.md" "python.md covers docstrings"
assert_grep "bare.*except\|except.*bare\|No bare" "$LANG_RULES_DIR/python.md" "python.md covers no bare except"
assert_grep "f-string" "$LANG_RULES_DIR/python.md" "python.md covers f-strings"

# --- Bash rules contain key sections ---
echo ""
echo "--- Bash Rule Content ---"
assert_grep "set -euo pipefail" "$LANG_RULES_DIR/bash.md" "bash.md covers set -euo pipefail"
assert_grep "[Qq]uot" "$LANG_RULES_DIR/bash.md" "bash.md covers variable quoting"
assert_grep "[Ss]hellcheck\|shellcheck" "$LANG_RULES_DIR/bash.md" "bash.md covers shellcheck compliance"

echo ""
echo "=== Results ==="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "FAILURES: $FAILURES"
  exit 1
fi
