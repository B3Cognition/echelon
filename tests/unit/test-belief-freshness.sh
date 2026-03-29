#!/usr/bin/env sh
# Unit tests for scripts/bash/belief-freshness-check.sh
# Tests: expired beliefs, low_confidence beliefs, critical banners, missing graph, exit code

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/bash/belief-freshness-check.sh"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PASS=0
FAIL=0

assert_contains() {
  label="$1"
  output="$2"
  needle="$3"
  if echo "$output" | grep -qF "$needle"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        Expected output to contain: $needle"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  label="$1"
  output="$2"
  needle="$3"
  if echo "$output" | grep -qF "$needle"; then
    echo "  FAIL: $label"
    echo "        Expected output NOT to contain: $needle"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  fi
}

assert_exit_zero() {
  label="$1"
  rc="$2"
  if [ "$rc" -eq 0 ]; then
    echo "  PASS: $label (exit 0)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label (exit $rc — expected 0)"
    FAIL=$((FAIL + 1))
  fi
}

# ── Helper: write a belief graph JSON to a temp file ─────────────

write_graph() {
  dest="$1"
  beliefs_json="$2"
  cat > "$dest" <<JSONEOF
{
  "generated_at": "2026-03-28T00:00:00Z",
  "version": "1.0.0",
  "beliefs": $beliefs_json
}
JSONEOF
}

# ════════════════════════════════════════════════════════════════════
# TEST 1: Missing belief graph — silent exit 0 (FR-010)
# ════════════════════════════════════════════════════════════════════
echo "--- Test 1: Missing belief graph ---"
output=$(bash "$SCRIPT" --belief-graph "$TMP_DIR/does-not-exist.json" 2>&1 || true)
rc=0
bash "$SCRIPT" --belief-graph "$TMP_DIR/does-not-exist.json" > /dev/null 2>&1 || rc=$?
assert_exit_zero "Exit 0 when belief graph is absent" "$rc"
assert_not_contains "No output when graph is absent" "$output" "STALE"
assert_not_contains "No output when graph is absent" "$output" "Belief freshness"

# ════════════════════════════════════════════════════════════════════
# TEST 2: Corrupted JSON — graceful degradation, exit 0
# ════════════════════════════════════════════════════════════════════
echo "--- Test 2: Corrupted JSON ---"
echo "{ not valid json }" > "$TMP_DIR/corrupted.json"
rc=0
bash "$SCRIPT" --belief-graph "$TMP_DIR/corrupted.json" > /dev/null 2>&1 || rc=$?
assert_exit_zero "Exit 0 on corrupted JSON" "$rc"

# ════════════════════════════════════════════════════════════════════
# TEST 3: All-fresh beliefs — summary shows 0 stale
# ════════════════════════════════════════════════════════════════════
echo "--- Test 3: All-fresh beliefs ---"
GRAPH_FRESH="$TMP_DIR/all_fresh.json"
write_graph "$GRAPH_FRESH" '[
  {
    "belief_id": "TST-001",
    "claim": "Fresh belief about testing",
    "verified_date": "2026-03-28",
    "expires_date": "2027-03-28",
    "anchor_url": "test",
    "confidence": 0.9,
    "severity": "high",
    "source_file": "test.md",
    "source_line": 1,
    "status": "fresh"
  }
]'
rc=0
output=$(bash "$SCRIPT" --belief-graph "$GRAPH_FRESH" 2>&1) || rc=$?
assert_exit_zero "Exit 0 with all-fresh beliefs" "$rc"
assert_contains "Fresh count in summary" "$output" "1 fresh"
assert_contains "Zero stale in summary"  "$output" "0 stale"
assert_contains "Zero critical in summary" "$output" "(0 critical)"
assert_not_contains "No stale warning emitted" "$output" "STALE BELIEF"

# ════════════════════════════════════════════════════════════════════
# TEST 4: Expired belief — warning emitted
# ════════════════════════════════════════════════════════════════════
echo "--- Test 4: Expired belief ---"
GRAPH_EXPIRED="$TMP_DIR/expired.json"
write_graph "$GRAPH_EXPIRED" '[
  {
    "belief_id": "TST-002",
    "claim": "This belief has expired",
    "verified_date": "2025-01-01",
    "expires_date": "2025-06-01",
    "anchor_url": "test",
    "confidence": 0.8,
    "severity": "medium",
    "source_file": "expired.md",
    "source_line": 42,
    "status": "fresh"
  }
]'
rc=0
output=$(bash "$SCRIPT" --belief-graph "$GRAPH_EXPIRED" 2>&1) || rc=$?
assert_exit_zero "Exit 0 with expired belief (FR-009)" "$rc"
assert_contains "STALE BELIEF warning for expired" "$output" "STALE BELIEF: TST-002"
assert_contains "Status shows expired"              "$output" "Status: expired"
assert_contains "Claim text in warning"             "$output" "This belief has expired"
assert_contains "Source file:line in warning"       "$output" "expired.md:42"
assert_contains "Summary shows 1 stale"             "$output" "1 stale"

# ════════════════════════════════════════════════════════════════════
# TEST 5: Low-confidence belief — warning emitted
# ════════════════════════════════════════════════════════════════════
echo "--- Test 5: Low-confidence belief ---"
GRAPH_LOWCONF="$TMP_DIR/low_conf.json"
write_graph "$GRAPH_LOWCONF" '[
  {
    "belief_id": "TST-003",
    "claim": "Low confidence claim about something uncertain",
    "verified_date": "2026-03-28",
    "expires_date": "2027-03-28",
    "anchor_url": "test",
    "confidence": 0.35,
    "severity": "high",
    "source_file": "uncertain.md",
    "source_line": 99,
    "status": "low_confidence"
  }
]'
rc=0
output=$(bash "$SCRIPT" --belief-graph "$GRAPH_LOWCONF" 2>&1) || rc=$?
assert_exit_zero "Exit 0 with low-confidence belief (FR-009)" "$rc"
assert_contains "STALE BELIEF warning for low-conf" "$output" "STALE BELIEF: TST-003"
assert_contains "Status shows low_confidence"        "$output" "Status: low_confidence"
assert_contains "Confidence value in warning"        "$output" "Confidence: 0.35"

# ════════════════════════════════════════════════════════════════════
# TEST 6: Critical-severity stale belief — banner emitted (FR-011)
# ════════════════════════════════════════════════════════════════════
echo "--- Test 6: Critical stale belief banner (FR-011) ---"
GRAPH_CRITICAL="$TMP_DIR/critical.json"
write_graph "$GRAPH_CRITICAL" '[
  {
    "belief_id": "TST-004",
    "claim": "Critical claim that has expired",
    "verified_date": "2025-01-01",
    "expires_date": "2025-06-01",
    "anchor_url": "test",
    "confidence": 0.9,
    "severity": "critical",
    "source_file": "critical.md",
    "source_line": 7,
    "status": "fresh"
  }
]'
rc=0
output=$(bash "$SCRIPT" --belief-graph "$GRAPH_CRITICAL" 2>&1) || rc=$?
assert_exit_zero "Exit 0 with critical stale belief (FR-009)" "$rc"
assert_contains "Critical banner top border"    "$output" "╔"
assert_contains "CRITICAL header line"          "$output" "CRITICAL STALE BELIEF DETECTED"
assert_contains "Banner separator"              "$output" "╠"
assert_contains "Belief ID in banner"           "$output" "TST-004"
assert_contains "Bottom border"                 "$output" "╚"
assert_contains "Structured STALE warning"      "$output" "STALE BELIEF: TST-004"
assert_contains "Summary shows 1 critical"      "$output" "(1 critical)"

# ════════════════════════════════════════════════════════════════════
# TEST 7: Mixed graph — fresh + stale + critical summary
# ════════════════════════════════════════════════════════════════════
echo "--- Test 7: Mixed graph ---"
GRAPH_MIXED="$TMP_DIR/mixed.json"
write_graph "$GRAPH_MIXED" '[
  {
    "belief_id": "TST-010",
    "claim": "Fresh belief, no issues",
    "verified_date": "2026-03-28",
    "expires_date": "2027-03-28",
    "anchor_url": "test",
    "confidence": 0.9,
    "severity": "high",
    "source_file": "ok.md",
    "source_line": 1,
    "status": "fresh"
  },
  {
    "belief_id": "TST-011",
    "claim": "Expired non-critical belief",
    "verified_date": "2025-01-01",
    "expires_date": "2025-06-01",
    "anchor_url": "test",
    "confidence": 0.7,
    "severity": "medium",
    "source_file": "stale.md",
    "source_line": 5,
    "status": "fresh"
  },
  {
    "belief_id": "TST-012",
    "claim": "Critical expired belief that triggers banner",
    "verified_date": "2025-01-01",
    "expires_date": "2025-03-01",
    "anchor_url": "test",
    "confidence": 0.8,
    "severity": "critical",
    "source_file": "critical.md",
    "source_line": 10,
    "status": "fresh"
  }
]'
rc=0
output=$(bash "$SCRIPT" --belief-graph "$GRAPH_MIXED" 2>&1) || rc=$?
assert_exit_zero "Exit 0 with mixed graph (FR-009)" "$rc"
assert_contains "Summary: 1 fresh"    "$output" "1 fresh"
assert_contains "Summary: 2 stale"    "$output" "2 stale"
assert_contains "Summary: 1 critical" "$output" "(1 critical)"
assert_contains "Non-critical warning present" "$output" "STALE BELIEF: TST-011"
assert_contains "Critical banner present"      "$output" "CRITICAL STALE BELIEF DETECTED"

# ════════════════════════════════════════════════════════════════════
# TEST 8: Approaching expiry (within 30 days) — warning emitted
# ════════════════════════════════════════════════════════════════════
echo "--- Test 8: Approaching expiry ---"
GRAPH_APPROACHING="$TMP_DIR/approaching.json"
# Use a date 14 days from today — compute with python3
NEAR_EXPIRY=$(python3 -c "from datetime import date, timedelta; print((date.today() + timedelta(days=14)).isoformat())")
write_graph "$GRAPH_APPROACHING" "[
  {
    \"belief_id\": \"TST-020\",
    \"claim\": \"Belief about to expire soon\",
    \"verified_date\": \"2026-01-01\",
    \"expires_date\": \"$NEAR_EXPIRY\",
    \"anchor_url\": \"test\",
    \"confidence\": 0.8,
    \"severity\": \"high\",
    \"source_file\": \"expiring.md\",
    \"source_line\": 3,
    \"status\": \"fresh\"
  }
]"
rc=0
output=$(bash "$SCRIPT" --belief-graph "$GRAPH_APPROACHING" 2>&1) || rc=$?
assert_exit_zero "Exit 0 with approaching-expiry belief" "$rc"
assert_contains "STALE BELIEF warning for approaching" "$output" "STALE BELIEF: TST-020"
assert_contains "Status shows approaching_expiry"      "$output" "Status: approaching_expiry"
assert_contains "Summary shows 1 stale"                "$output" "1 stale"

# ════════════════════════════════════════════════════════════════════
# Results
# ════════════════════════════════════════════════════════════════════
echo ""
echo "belief-freshness unit checks: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
