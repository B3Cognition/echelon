#!/usr/bin/env sh
# T-12: Wave 1 Validation Checklist
# Structurally validates all 3 Wave 1 prompt changes are in place.
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

PASS_COUNT=0
FAIL_COUNT=0
TOTAL=0

check() {
  TOTAL=$((TOTAL + 1))
  desc="$1"
  file="$ROOT_DIR/$2"
  pattern="$3"

  if grep -q "$pattern" "$file" 2>/dev/null; then
    printf "  PASS  %s\n" "$desc"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    printf "  FAIL  %s\n" "$desc"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

# ---------------------------------------------------------------------------
# A-REQ-01: SENTINEL flakiness management (agents/solution/sentinel.md)
# ---------------------------------------------------------------------------
SENTINEL="agents/solution/sentinel.md"

printf "\n=== A-REQ-01: SENTINEL Flakiness Management ===\n"
check "Detection Protocol heading"      "$SENTINEL" "Detection Protocol"
check "Quarantine Process heading"       "$SENTINEL" "Quarantine Process"
check "Root Cause Taxonomy heading"      "$SENTINEL" "Root Cause Taxonomy"
check "Stability Targets heading"        "$SENTINEL" "Stability Targets"
check "Review Cadence heading"           "$SENTINEL" "Review Cadence"

# ---------------------------------------------------------------------------
# A-REQ-02: CODE_REVIEWER confidence filtering (agents/build/code-reviewer.md)
# ---------------------------------------------------------------------------
REVIEWER="agents/build/code-reviewer.md"

printf "\n=== A-REQ-02: CODE_REVIEWER Confidence Filtering ===\n"
check "80% confidence threshold"         "$REVIEWER" "80%"
check "Consolidation Rules section"      "$REVIEWER" "Consolidation Rules"
check "Severity-Based Verdicts section"  "$REVIEWER" "Severity-Based Verdicts"
check "APPROVED verdict"                 "$REVIEWER" "APPROVED"
check "CHANGES_REQUESTED verdict"        "$REVIEWER" "CHANGES_REQUESTED"
check "BLOCKED verdict"                  "$REVIEWER" "BLOCKED"
check "Stylistic Suppression section"    "$REVIEWER" "Stylistic Suppression"

# ---------------------------------------------------------------------------
# B-REQ-05: SAGE contradiction detection (agents/exploration/sage.md)
# ---------------------------------------------------------------------------
SAGE="agents/exploration/sage.md"

printf "\n=== B-REQ-05: SAGE Contradiction Detection ===\n"
check "Requirement conflicts type"               "$SAGE" "Requirement conflicts"
check "Assumption-requirement misalignment type"  "$SAGE" "Assumption-requirement"
check "Boundary violations type"                  "$SAGE" "Boundary violations"
check "Priority inversions type"                  "$SAGE" "Priority inversions"
check "Acceptance criteria conflicts type"        "$SAGE" "Acceptance criteria conflicts"
check "Structured report format (contradiction_type field)" "$SAGE" "contradiction_type"
check "Report format (artifact_a field)"          "$SAGE" "artifact_a"
check "Report format (artifact_b field)"          "$SAGE" "artifact_b"
check "Report format (suggested_resolution field)" "$SAGE" "suggested_resolution"
check "Zero-contradictions explicit statement"    "$SAGE" "No contradictions detected"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf "\n=== Summary ===\n"
printf "Total: %d  Passed: %d  Failed: %d\n" "$TOTAL" "$PASS_COUNT" "$FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
  printf "\nRESULT: FAIL — %d check(s) did not pass\n" "$FAIL_COUNT"
  exit 1
fi

printf "\nRESULT: PASS — all %d checks passed\n" "$TOTAL"
exit 0
