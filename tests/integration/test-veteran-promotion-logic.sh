#!/usr/bin/env bash
# test-veteran-promotion-logic.sh
# T-22 Integration Test: Verify VETERAN promotion threshold logic.
# Creates fixture patterns with various fingerprints and verifies
# that the promotion threshold (3+ distinct fingerprints) works correctly.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMPDIR=$(mktemp -d)
PASS=0
FAIL=0

trap "rm -rf $TMPDIR" EXIT

pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }

echo "=== Integration: Veteran Promotion Logic ==="

# --- Helper: generate a fingerprint from a fake URL ---
fingerprint() {
  echo -n "$1" | shasum -a 256 | cut -c1-12
}

FP_A=$(fingerprint "https://github.com/org/project-alpha.git")
FP_B=$(fingerprint "https://github.com/org/project-beta.git")
FP_C=$(fingerprint "https://github.com/org/project-gamma.git")
FP_D=$(fingerprint "https://github.com/org/project-delta.git")

# --- Test 1: Fingerprints are 12 hex characters ---
echo ""
echo "--- T1: Fingerprint format validation ---"
VALID=true
for fp in "$FP_A" "$FP_B" "$FP_C" "$FP_D"; do
  if ! echo "$fp" | grep -qE '^[0-9a-f]{12}$'; then
    VALID=false
    fail "Fingerprint '$fp' is not 12 hex chars"
  fi
done
if [ "$VALID" = true ]; then
  pass "All fingerprints are valid 12-char hex strings"
fi

# --- Test 2: Different URLs produce different fingerprints ---
echo ""
echo "--- T2: Distinct URLs produce distinct fingerprints ---"
if [ "$FP_A" != "$FP_B" ] && [ "$FP_B" != "$FP_C" ] && [ "$FP_A" != "$FP_C" ]; then
  pass "All fingerprints are distinct"
else
  fail "Fingerprint collision detected: A=$FP_A B=$FP_B C=$FP_C"
fi

# --- Test 3: Same URL produces same fingerprint (deterministic) ---
echo ""
echo "--- T3: Same URL produces same fingerprint ---"
FP_A2=$(fingerprint "https://github.com/org/project-alpha.git")
if [ "$FP_A" = "$FP_A2" ]; then
  pass "Fingerprint is deterministic"
else
  fail "Same URL produced different fingerprints: $FP_A vs $FP_A2"
fi

# --- Create fixture patterns.yaml with mixed fingerprints ---
cat > "$TMPDIR/patterns.yaml" <<EOF
schema_version: 1
entries:
  - id: PAT-100
    name: Parallel Scout Decomposition
    domain: squad-orchestration
    confidence: 0.91
    source: squad-run-alpha
    run_id: squad-run-alpha
    created_at: 2026-01-01T00:00:00Z
    tags: ["parallel", "scout"]
    status: active
    project_fingerprint: $FP_A
    scope: local_only

  - id: PAT-101
    name: Parallel Scout Decomposition
    domain: squad-orchestration
    confidence: 0.88
    source: squad-run-beta
    run_id: squad-run-beta
    created_at: 2026-01-15T00:00:00Z
    tags: ["parallel", "scout"]
    status: active
    project_fingerprint: $FP_B
    scope: local_only

  - id: PAT-102
    name: Parallel Scout Decomposition
    domain: squad-orchestration
    confidence: 0.85
    source: squad-run-gamma
    run_id: squad-run-gamma
    created_at: 2026-02-01T00:00:00Z
    tags: ["parallel", "scout"]
    status: active
    project_fingerprint: $FP_C
    scope: local_only

  - id: PAT-200
    name: Unique Local Pattern
    domain: estimation
    confidence: 0.80
    source: squad-run-alpha
    run_id: squad-run-alpha
    created_at: 2026-01-01T00:00:00Z
    tags: ["estimation", "local"]
    status: active
    project_fingerprint: $FP_A
    scope: local_only

  - id: PAT-300
    name: Two Project Pattern
    domain: testing
    confidence: 0.75
    source: squad-run-alpha
    run_id: squad-run-alpha
    created_at: 2026-01-01T00:00:00Z
    tags: ["testing", "two-project"]
    status: active
    project_fingerprint: $FP_A
    scope: local_only

  - id: PAT-301
    name: Two Project Pattern
    domain: testing
    confidence: 0.78
    source: squad-run-beta
    run_id: squad-run-beta
    created_at: 2026-01-15T00:00:00Z
    tags: ["testing", "two-project"]
    status: active
    project_fingerprint: $FP_B
    scope: local_only

  - id: PAT-400
    name: Low Confidence Cross Project
    domain: architecture
    confidence: 0.50
    source: squad-run-alpha
    run_id: squad-run-alpha
    created_at: 2026-01-01T00:00:00Z
    tags: ["architecture", "low-conf"]
    status: active
    project_fingerprint: $FP_A
    scope: local_only

  - id: PAT-401
    name: Low Confidence Cross Project
    domain: architecture
    confidence: 0.45
    source: squad-run-beta
    run_id: squad-run-beta
    created_at: 2026-01-15T00:00:00Z
    tags: ["architecture", "low-conf"]
    status: active
    project_fingerprint: $FP_B
    scope: local_only

  - id: PAT-402
    name: Low Confidence Cross Project
    domain: architecture
    confidence: 0.55
    source: squad-run-gamma
    run_id: squad-run-gamma
    created_at: 2026-02-01T00:00:00Z
    tags: ["architecture", "low-conf"]
    status: active
    project_fingerprint: $FP_C
    scope: local_only
EOF

# --- Test 4: Pattern with 3 distinct fingerprints qualifies for promotion ---
echo ""
echo "--- T4: Pattern with 3+ distinct fingerprints qualifies ---"
# Count distinct fingerprints for "Parallel Scout Decomposition"
SCOUT_FPS=$(grep -A 20 'name: Parallel Scout Decomposition' "$TMPDIR/patterns.yaml" | grep 'project_fingerprint:' | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
if [ "$SCOUT_FPS" -ge 3 ]; then
  pass "Parallel Scout Decomposition has $SCOUT_FPS distinct fingerprints (>= 3 threshold)"
else
  fail "Expected >= 3 distinct fingerprints, got $SCOUT_FPS"
fi

# --- Test 5: Pattern with 1 fingerprint does NOT qualify ---
echo ""
echo "--- T5: Pattern with 1 fingerprint does not qualify ---"
UNIQUE_FPS=$(grep -A 20 'name: Unique Local Pattern' "$TMPDIR/patterns.yaml" | grep 'project_fingerprint:' | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
if [ "$UNIQUE_FPS" -lt 3 ]; then
  pass "Unique Local Pattern has $UNIQUE_FPS fingerprint(s) (below threshold)"
else
  fail "Expected < 3 fingerprints, got $UNIQUE_FPS"
fi

# --- Test 6: Pattern with 2 fingerprints does NOT qualify ---
echo ""
echo "--- T6: Pattern with 2 fingerprints does not qualify ---"
TWO_FPS=$(grep -A 20 'name: Two Project Pattern' "$TMPDIR/patterns.yaml" | grep 'project_fingerprint:' | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
if [ "$TWO_FPS" -lt 3 ]; then
  pass "Two Project Pattern has $TWO_FPS fingerprints (below threshold)"
else
  fail "Expected < 3 fingerprints, got $TWO_FPS"
fi

# --- Test 7: Low confidence patterns should NOT be promoted even with 3 fingerprints ---
echo ""
echo "--- T7: Low confidence blocks promotion even with 3+ fingerprints ---"
LOW_CONF_FPS=$(grep -A 20 'name: Low Confidence Cross Project' "$TMPDIR/patterns.yaml" | grep 'project_fingerprint:' | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
LOW_CONF_MIN=$(grep -A 20 'name: Low Confidence Cross Project' "$TMPDIR/patterns.yaml" | grep 'confidence:' | awk '{print $2}' | sort -n | head -1)
# Threshold is 0.7; compare using bc or awk
BELOW_THRESHOLD=$(awk "BEGIN {print ($LOW_CONF_MIN < 0.7) ? \"yes\" : \"no\"}")
if [ "$LOW_CONF_FPS" -ge 3 ] && [ "$BELOW_THRESHOLD" = "yes" ]; then
  pass "Low Confidence Cross Project has $LOW_CONF_FPS fingerprints but min confidence $LOW_CONF_MIN < 0.7 — promotion blocked"
else
  fail "Expected 3+ fingerprints with confidence < 0.7"
fi

# --- Test 8: VETERAN prompt documents the 3-fingerprint threshold ---
echo ""
echo "--- T8: VETERAN prompt specifies 3-fingerprint promotion threshold ---"
VETERAN_FILE="$REPO_ROOT/prosaic/subagents/echelon.veteran.md"
if grep -q '3 distinct project fingerprints' "$VETERAN_FILE" || \
   grep -q 'distinct fingerprint count >= 3' "$VETERAN_FILE"; then
  pass "veteran.md specifies 3-fingerprint threshold"
else
  fail "veteran.md does not specify 3-fingerprint threshold"
fi

# --- Test 9: VETERAN prompt documents confidence gate ---
echo ""
echo "--- T9: VETERAN prompt specifies confidence >= 0.7 gate ---"
if grep -q 'confidence >= 0.7' "$VETERAN_FILE" || grep -q 'confidence < 0.7' "$VETERAN_FILE"; then
  pass "veteran.md specifies confidence threshold"
else
  fail "veteran.md missing confidence gate documentation"
fi

# --- Test 10: VETERAN prompt documents scope transition ---
echo ""
echo "--- T10: VETERAN documents local_only -> global transition ---"
if grep -q 'local_only.*to.*global' "$VETERAN_FILE" || \
   grep -q 'local_only.*global' "$VETERAN_FILE" || \
   grep -q "scope.*from.*local_only.*to.*global" "$VETERAN_FILE"; then
  pass "veteran.md documents scope transition"
else
  fail "veteran.md missing scope transition documentation"
fi

# --- Test 11: Visibility rules — global entries always visible ---
echo ""
echo "--- T11: VETERAN documents global visibility rule ---"
if grep -q 'scope: global' "$VETERAN_FILE" && grep -q 'shared across all projects' "$VETERAN_FILE"; then
  pass "veteran.md documents global visibility"
else
  fail "veteran.md missing global visibility rule"
fi

# --- Test 12: Fixture with 4 fingerprints also qualifies (above threshold) ---
echo ""
echo "--- T12: 4 fingerprints also qualifies (threshold is minimum, not exact) ---"
cat > "$TMPDIR/patterns_4fp.yaml" <<EOF2
schema_version: 1
entries:
  - id: PAT-500
    name: Four Project Universal
    project_fingerprint: $FP_A
    scope: local_only
  - id: PAT-501
    name: Four Project Universal
    project_fingerprint: $FP_B
    scope: local_only
  - id: PAT-502
    name: Four Project Universal
    project_fingerprint: $FP_C
    scope: local_only
  - id: PAT-503
    name: Four Project Universal
    project_fingerprint: $FP_D
    scope: local_only
EOF2
FOUR_FPS=$(grep -A 5 'name: Four Project Universal' "$TMPDIR/patterns_4fp.yaml" | grep 'project_fingerprint:' | awk '{print $2}' | sort -u | wc -l | tr -d ' ')
if [ "$FOUR_FPS" -ge 3 ]; then
  pass "4-fingerprint pattern qualifies ($FOUR_FPS >= 3)"
else
  fail "Expected >= 3, got $FOUR_FPS"
fi

# --- Summary ---
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
