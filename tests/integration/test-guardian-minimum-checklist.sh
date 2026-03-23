#!/usr/bin/env bash
# T-28: Integration test — validate GUARDIAN Minimum Security Checklist output fixture
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/../fixtures"
FIXTURE_DIR="$FIXTURES_DIR/guardian-checklist"
CHECKLIST="$FIXTURE_DIR/security-checklist.md"
FAILURES=0

# Create fixture: a sample security-checklist.md output
mkdir -p "$FIXTURE_DIR"
cat > "$CHECKLIST" << 'CHECKLIST_MD'
# Security Checklist — user-dashboard

| # | Check | Status | Finding |
|---|-------|--------|---------|
| 1 | Secrets in Config | PASS | No hardcoded secrets found; Vault integration specified in plan.md |
| 2 | Input Validation at Boundaries | FAIL | API endpoint /api/upload missing file-type validation |
| 3 | Auth/AuthZ | PASS | OAuth 2.0 + RBAC defined in spec.md section 4.2 |
| 4 | Dependency Security | PASS | Dependabot enabled; all deps pinned in package-lock.json |
| 5 | Data Handling Compliance | PASS | PII encrypted at rest (AES-256); no PII in logs confirmed |

**Overall:** 4/5 PASS, 1 FAIL, 0 N/A
**Recommendation:** PROCEED_WITH_WARNINGS
CHECKLIST_MD

echo "=== GUARDIAN Minimum Security Checklist Integration Tests ==="
echo ""

# Check all 5 items are present
CHECKLIST_ITEMS=("Secrets in Config" "Input Validation at Boundaries" "Auth/AuthZ" "Dependency Security" "Data Handling Compliance")

for item in "${CHECKLIST_ITEMS[@]}"; do
  if grep -q "$item" "$CHECKLIST"; then
    echo "PASS: Checklist contains '$item'"
  else
    echo "FAIL: Checklist missing '$item'"
    FAILURES=$((FAILURES + 1))
  fi
done

# Check all 5 numbered rows exist
for i in 1 2 3 4 5; do
  if grep -q "| $i |" "$CHECKLIST"; then
    echo "PASS: Checklist row #$i present"
  else
    echo "FAIL: Checklist row #$i missing"
    FAILURES=$((FAILURES + 1))
  fi
done

# Check statuses are valid (PASS, FAIL, or N/A)
INVALID_STATUSES=$(grep -E '^\| [1-5] \|' "$CHECKLIST" | grep -cvE '(PASS|FAIL|N/A)' || true)
if [ "$INVALID_STATUSES" -eq 0 ]; then
  echo "PASS: All statuses are valid (PASS/FAIL/N/A)"
else
  echo "FAIL: $INVALID_STATUSES rows have invalid status"
  FAILURES=$((FAILURES + 1))
fi

# Check Overall summary line exists
if grep -q '^\*\*Overall:\*\*' "$CHECKLIST"; then
  echo "PASS: Overall summary line present"
else
  echo "FAIL: Overall summary line missing"
  FAILURES=$((FAILURES + 1))
fi

# Check Recommendation line exists with valid value
if grep -qE '^\*\*Recommendation:\*\* (PROCEED|PROCEED_WITH_WARNINGS|SECURITY_REVIEW_REQUIRED)' "$CHECKLIST"; then
  echo "PASS: Recommendation line present with valid value"
else
  echo "FAIL: Recommendation line missing or invalid"
  FAILURES=$((FAILURES + 1))
fi

# Check that findings are non-empty for each item
EMPTY_FINDINGS=$(grep -E '^\| [1-5] \|' "$CHECKLIST" | grep -c '| *|$' || true)
if [ "$EMPTY_FINDINGS" -eq 0 ]; then
  echo "PASS: All checklist items have findings"
else
  echo "FAIL: $EMPTY_FINDINGS items have empty findings"
  FAILURES=$((FAILURES + 1))
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "ALL TESTS PASSED"
  echo "RESULT: PASS"
else
  echo "FAILURES: $FAILURES"
  echo "RESULT: FAIL"
  exit 1
fi
