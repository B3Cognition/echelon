#!/usr/bin/env bash
# test-veteran-project-scoping.sh
# T-22 Unit Test: Verify patterns.yaml and pitfalls.yaml have project_fingerprint
# fields and that kb-schema.md documents them correctly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KB_DIR="$REPO_ROOT/knowledge-base"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== Unit: Veteran Project Scoping ==="

# --- Test 1: kb-schema.md documents project_fingerprint for patterns ---
echo ""
echo "--- T1: kb-schema.md documents project_fingerprint for patterns.yaml ---"
if grep -q 'project_fingerprint' "$KB_DIR/kb-schema.md"; then
  pass "kb-schema.md contains project_fingerprint field"
else
  fail "kb-schema.md missing project_fingerprint field"
fi

# --- Test 2: kb-schema.md documents scope enum for patterns ---
echo ""
echo "--- T2: kb-schema.md documents scope enum for patterns.yaml ---"
if grep -q 'local_only' "$KB_DIR/kb-schema.md" && grep -q 'global' "$KB_DIR/kb-schema.md"; then
  pass "kb-schema.md documents local_only and global scope values"
else
  fail "kb-schema.md missing scope enum values (local_only | global)"
fi

# --- Test 3: kb-schema.md documents SHA-256 truncated to 12 chars ---
echo ""
echo "--- T3: kb-schema.md describes SHA-256 truncated to 12 characters ---"
if grep -q 'SHA-256' "$KB_DIR/kb-schema.md" && grep -q '12' "$KB_DIR/kb-schema.md"; then
  pass "kb-schema.md describes SHA-256 with 12-char truncation"
else
  fail "kb-schema.md missing SHA-256 / 12-char description"
fi

# --- Test 4: kb-schema.md documents project_fingerprint for pitfalls ---
echo ""
echo "--- T4: kb-schema.md documents project_fingerprint for pitfalls.yaml ---"
# The field should appear in both the patterns and pitfalls sections
PATTERNS_SECTION=$(sed -n '/^## patterns.yaml/,/^## pitfalls.yaml/p' "$KB_DIR/kb-schema.md")
PITFALLS_SECTION=$(sed -n '/^## pitfalls.yaml/,/^## agent-scores.yaml/p' "$KB_DIR/kb-schema.md")
if echo "$PATTERNS_SECTION" | grep -q 'project_fingerprint' && \
   echo "$PITFALLS_SECTION" | grep -q 'project_fingerprint'; then
  pass "project_fingerprint documented in both patterns and pitfalls sections"
else
  fail "project_fingerprint not documented in both sections"
fi

# --- Test 5: patterns.yaml entries have project_fingerprint field ---
echo ""
echo "--- T5: patterns.yaml entries contain project_fingerprint ---"
PAT_FP_COUNT=$(grep -c 'project_fingerprint:' "$KB_DIR/patterns.yaml" || true)
PAT_ENTRY_COUNT=$(grep -c '^\s*- id: PAT-' "$KB_DIR/patterns.yaml" || true)
if [ "$PAT_FP_COUNT" -ge "$PAT_ENTRY_COUNT" ] && [ "$PAT_ENTRY_COUNT" -gt 0 ]; then
  pass "All $PAT_ENTRY_COUNT pattern entries have project_fingerprint ($PAT_FP_COUNT found)"
else
  fail "patterns.yaml: $PAT_FP_COUNT fingerprints for $PAT_ENTRY_COUNT entries"
fi

# --- Test 6: patterns.yaml entries have scope field ---
echo ""
echo "--- T6: patterns.yaml entries contain scope ---"
PAT_SCOPE_COUNT=$(grep -c 'scope:' "$KB_DIR/patterns.yaml" || true)
if [ "$PAT_SCOPE_COUNT" -ge "$PAT_ENTRY_COUNT" ] && [ "$PAT_ENTRY_COUNT" -gt 0 ]; then
  pass "All $PAT_ENTRY_COUNT pattern entries have scope ($PAT_SCOPE_COUNT found)"
else
  fail "patterns.yaml: $PAT_SCOPE_COUNT scope fields for $PAT_ENTRY_COUNT entries"
fi

# --- Test 7: pitfalls.yaml entries have project_fingerprint field ---
echo ""
echo "--- T7: pitfalls.yaml entries contain project_fingerprint ---"
PIT_FP_COUNT=$(grep -c 'project_fingerprint:' "$KB_DIR/pitfalls.yaml" || true)
PIT_ENTRY_COUNT=$(grep -c '^\s*- id: PIT-' "$KB_DIR/pitfalls.yaml" || true)
if [ "$PIT_FP_COUNT" -ge "$PIT_ENTRY_COUNT" ] && [ "$PIT_ENTRY_COUNT" -gt 0 ]; then
  pass "All $PIT_ENTRY_COUNT pitfall entries have project_fingerprint ($PIT_FP_COUNT found)"
else
  fail "pitfalls.yaml: $PIT_FP_COUNT fingerprints for $PIT_ENTRY_COUNT entries"
fi

# --- Test 8: pitfalls.yaml entries have scope field ---
echo ""
echo "--- T8: pitfalls.yaml entries contain scope ---"
PIT_SCOPE_COUNT=$(grep -c 'scope:' "$KB_DIR/pitfalls.yaml" || true)
if [ "$PIT_SCOPE_COUNT" -ge "$PIT_ENTRY_COUNT" ] && [ "$PIT_ENTRY_COUNT" -gt 0 ]; then
  pass "All $PIT_ENTRY_COUNT pitfall entries have scope ($PIT_SCOPE_COUNT found)"
else
  fail "pitfalls.yaml: $PIT_SCOPE_COUNT scope fields for $PIT_ENTRY_COUNT entries"
fi

# --- Test 9: scope values are valid enum ---
echo ""
echo "--- T9: scope values are valid (local_only or global) ---"
INVALID_SCOPE=$(grep 'scope:' "$KB_DIR/patterns.yaml" "$KB_DIR/pitfalls.yaml" | grep -v 'local_only' | grep -v 'global' || true)
if [ -z "$INVALID_SCOPE" ]; then
  pass "All scope values are valid enum members"
else
  fail "Invalid scope values found: $INVALID_SCOPE"
fi

# --- Test 10: VETERAN agent prompt exists ---
echo ""
echo "--- T10: veteran.md agent prompt exists ---"
if [ -f "$REPO_ROOT/extension/agents/learning/veteran.md" ]; then
  pass "veteran.md exists"
else
  fail "veteran.md not found"
fi

# --- Test 11: MIRROR agent references project_fingerprint ---
echo ""
echo "--- T11: mirror.md references project_fingerprint computation ---"
if grep -q 'project_fingerprint' "$REPO_ROOT/extension/agents/learning/mirror.md" && \
   grep -q 'shasum -a 256' "$REPO_ROOT/extension/agents/learning/mirror.md"; then
  pass "mirror.md has fingerprint computation instructions"
else
  fail "mirror.md missing fingerprint computation"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
