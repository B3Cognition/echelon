#!/usr/bin/env bash
# T-39: Integration test — verify code-reviewer.md references dynamic language rule loading
# and that the language-rules directory integrates with the review workflow
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CODE_REVIEWER="$ROOT/prosaic/subagents/echelon.code-reviewer.md"
LANG_RULES_DIR="$ROOT/knowledge-base/language-rules"
FAILURES=0

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

echo "=== Code Reviewer Language Loading Integration Tests ==="
echo ""

# --- code-reviewer.md references language rules ---
echo "--- Code Reviewer References ---"
assert_grep "language-rules" "$CODE_REVIEWER" "code-reviewer.md references language-rules directory"
assert_grep "language.*rules\|Language.*Rule" "$CODE_REVIEWER" "code-reviewer.md mentions language rules concept"
assert_grep "{language}.md\|language}.md" "$CODE_REVIEWER" "code-reviewer.md uses dynamic language placeholder"

# --- Language rule files are loadable ---
echo ""
echo "--- Language Rule Files Loadable ---"
for lang_file in "$LANG_RULES_DIR"/*.md; do
  lang_name="$(basename "$lang_file" .md)"
  assert_file_exists "$lang_file" "Language rule file exists: $lang_name"

  # Verify each file has a markdown heading (is a valid rule file)
  if head -1 "$lang_file" | grep -q "^# "; then
    echo "PASS: $lang_name.md has a valid markdown heading"
  else
    echo "FAIL: $lang_name.md missing markdown heading"
    FAILURES=$((FAILURES + 1))
  fi
done

# --- Integration: code-reviewer.md section exists for dynamic loading ---
echo ""
echo "--- Dynamic Loading Section ---"
assert_grep "knowledge-base/language-rules/{language}.md" "$CODE_REVIEWER" "code-reviewer.md has dynamic loading path pattern"
assert_grep "[Ll]oad.*rules\|[Aa]pply.*rules" "$CODE_REVIEWER" "code-reviewer.md describes loading/applying rules"

# --- Integration: at least 3 starter language files exist ---
echo ""
echo "--- Starter Language Coverage ---"
lang_count=0
for f in "$LANG_RULES_DIR"/*.md; do
  [[ -f "$f" ]] && lang_count=$((lang_count + 1))
done

if [[ "$lang_count" -ge 3 ]]; then
  echo "PASS: At least 3 language rule files exist ($lang_count found)"
else
  echo "FAIL: Expected at least 3 language rule files, found $lang_count"
  FAILURES=$((FAILURES + 1))
fi

echo ""
echo "=== Results ==="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "FAILURES: $FAILURES"
  exit 1
fi
