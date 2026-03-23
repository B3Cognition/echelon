#!/usr/bin/env bash
# T-25: Integration test — validate token_ledger schema in state.json fixture
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/../fixtures"
FIXTURE="$FIXTURES_DIR/token-tracking/state.json"
FAILURES=0

assert_jq() {
  local query="$1"
  local description="$2"
  local result
  result=$(jq -r "$query" "$FIXTURE" 2>/dev/null || echo "JQ_ERROR")
  if [ "$result" != "null" ] && [ "$result" != "JQ_ERROR" ] && [ -n "$result" ]; then
    echo "PASS: $description (value: $result)"
  else
    echo "FAIL: $description (query: $query, result: $result)"
    FAILURES=$((FAILURES + 1))
  fi
}

assert_jq_count() {
  local query="$1"
  local expected="$2"
  local description="$3"
  local result
  result=$(jq -r "$query" "$FIXTURE" 2>/dev/null || echo "JQ_ERROR")
  if [ "$result" = "$expected" ]; then
    echo "PASS: $description (count: $result)"
  else
    echo "FAIL: $description (expected: $expected, got: $result)"
    FAILURES=$((FAILURES + 1))
  fi
}

# Create fixture directory and state.json
mkdir -p "$FIXTURES_DIR/token-tracking"
cat > "$FIXTURE" << 'FIXTURE_JSON'
{
  "run_id": "squad-test-001",
  "phase": "SPECIALISTS",
  "status": "IN_PROGRESS",
  "token_ledger": {
    "total_estimated_tokens": 57000,
    "total_dispatches": 4,
    "per_agent": {
      "SCOUT": { "dispatches": 1, "estimated_tokens": 15000 },
      "SAGE": { "dispatches": 1, "estimated_tokens": 18000 },
      "ARCHITECT": { "dispatches": 1, "estimated_tokens": 12000 },
      "GUARDIAN": { "dispatches": 1, "estimated_tokens": 12000 }
    },
    "per_phase": {
      "DISCOVER": 15000,
      "WHY": 18000,
      "HOW": 12000,
      "SPECIALISTS": 12000
    },
    "dispatches": [
      {
        "dispatch_id": "D-001",
        "agent_codename": "SCOUT",
        "phase": "DISCOVER",
        "estimated_tokens": 15000,
        "timestamp": "2026-03-23T10:00:00Z"
      },
      {
        "dispatch_id": "D-002",
        "agent_codename": "SAGE",
        "phase": "WHY",
        "estimated_tokens": 18000,
        "timestamp": "2026-03-23T10:05:00Z"
      },
      {
        "dispatch_id": "D-003",
        "agent_codename": "ARCHITECT",
        "phase": "HOW",
        "estimated_tokens": 12000,
        "timestamp": "2026-03-23T10:10:00Z"
      },
      {
        "dispatch_id": "D-004",
        "agent_codename": "GUARDIAN",
        "phase": "SPECIALISTS",
        "estimated_tokens": 12000,
        "timestamp": "2026-03-23T10:15:00Z"
      }
    ]
  }
}
FIXTURE_JSON

echo "=== Token Tracking State Integration Tests ==="
echo ""

# Validate top-level token_ledger exists
assert_jq ".token_ledger" "token_ledger object exists"
assert_jq ".token_ledger.total_estimated_tokens" "total_estimated_tokens present"
assert_jq ".token_ledger.total_dispatches" "total_dispatches present"

# Validate totals are consistent
assert_jq_count ".token_ledger.total_dispatches" "4" "total_dispatches matches dispatch array length"
assert_jq_count ".token_ledger.dispatches | length" "4" "dispatches array has 4 entries"

# Validate dispatch entry schema
assert_jq ".token_ledger.dispatches[0].dispatch_id" "dispatch has dispatch_id"
assert_jq ".token_ledger.dispatches[0].agent_codename" "dispatch has agent_codename"
assert_jq ".token_ledger.dispatches[0].phase" "dispatch has phase"
assert_jq ".token_ledger.dispatches[0].estimated_tokens" "dispatch has estimated_tokens"
assert_jq ".token_ledger.dispatches[0].timestamp" "dispatch has timestamp"

# Validate per_agent aggregation
assert_jq ".token_ledger.per_agent.SCOUT.dispatches" "per_agent.SCOUT.dispatches present"
assert_jq ".token_ledger.per_agent.SCOUT.estimated_tokens" "per_agent.SCOUT.estimated_tokens present"

# Validate per_phase aggregation
assert_jq ".token_ledger.per_phase.DISCOVER" "per_phase.DISCOVER present"
assert_jq ".token_ledger.per_phase.WHY" "per_phase.WHY present"
assert_jq ".token_ledger.per_phase.HOW" "per_phase.HOW present"

# Validate sum consistency: per_phase totals should equal total_estimated_tokens
PHASE_SUM=$(jq '[.token_ledger.per_phase | to_entries[].value] | add' "$FIXTURE")
TOTAL=$(jq '.token_ledger.total_estimated_tokens' "$FIXTURE")
if [ "$PHASE_SUM" -eq "$TOTAL" ]; then
  echo "PASS: per_phase sum ($PHASE_SUM) equals total_estimated_tokens ($TOTAL)"
else
  echo "FAIL: per_phase sum ($PHASE_SUM) != total_estimated_tokens ($TOTAL)"
  FAILURES=$((FAILURES + 1))
fi

# Validate dispatch_id format (D-NNN)
INVALID_IDS=$(jq '[.token_ledger.dispatches[].dispatch_id | select(test("^D-[0-9]+$") | not)] | length' "$FIXTURE")
if [ "$INVALID_IDS" -eq 0 ]; then
  echo "PASS: all dispatch_ids match D-NNN format"
else
  echo "FAIL: $INVALID_IDS dispatch_ids have invalid format"
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
