#!/usr/bin/env bash
# test-token-logger.sh — Unit tests for scripts/token-logger.py
#
# Tests:
#   T1: --help exits 0
#   T2: Script runs against fixture journal and exits 0
#   T3: Output JSON has all required top-level keys
#   T4: per_agent_type contains at least one agent entry with mean/median/p90/count
#   T5: collection_method is one of live_instrumentation | post_hoc_estimation
#   T6: invocations array is non-empty
#   T7: pipeline_total has prompt_tokens, completion_tokens, total_tokens
#   T8: At least one invocation has the five required per-invocation fields
#   T9: Agents from fixture appear in per_agent_type (SCOUT, CARTOGRAPHER, SAGE)
#
# Exit 0 = ALL PASS, Exit 1 = one or more FAIL

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

SCRIPT="$ROOT/extension/scripts/token-logger.py"
FIXTURE="$ROOT/tests/fixtures/token-logger/sample-journal.json"
TMP_DIR="$(mktemp -d)"
OUTPUT="$TMP_DIR/token-baseline.json"

FAILURES=0
PASSES=0

# ── Helpers ────────────────────────────────────────────────────────────────

pass() {
  echo "PASS: $1"
  PASSES=$((PASSES + 1))
}

fail() {
  echo "FAIL: $1"
  FAILURES=$((FAILURES + 1))
}

# Run python3 with the script; capture stdout+stderr separately
run_logger() {
  python3 "$SCRIPT" "$@" 2>/dev/null
}

# Extract a JSON value using python3 (no jq dependency)
json_get() {
  local file="$1" key="$2"
  python3 -c "
import json, sys
try:
    d = json.load(open('$file'))
    val = d
    for part in '$key'.split('.'):
        val = val[part]
    print(json.dumps(val))
except Exception as e:
    print('__MISSING__', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null
}

json_has_key() {
  local file="$1" key="$2"
  python3 -c "
import json, sys
try:
    d = json.load(open('$file'))
    val = d
    for part in '$key'.split('.'):
        val = val[part]
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

# ── Preconditions ──────────────────────────────────────────────────────────

echo "=== Token Logger Unit Tests ==="
echo "Script : $SCRIPT"
echo "Fixture: $FIXTURE"
echo "Output : $OUTPUT"
echo ""

if [ ! -f "$SCRIPT" ]; then
  echo "FATAL: Script not found: $SCRIPT"
  exit 1
fi

if [ ! -f "$FIXTURE" ]; then
  echo "FATAL: Fixture not found: $FIXTURE"
  exit 1
fi

# ── T1: --help exits 0 ─────────────────────────────────────────────────────

if python3 "$SCRIPT" --help >/dev/null 2>&1; then
  pass "T1: --help exits 0"
else
  fail "T1: --help should exit 0"
fi

# ── T2: Runs against fixture journal, exits 0 ─────────────────────────────

if python3 "$SCRIPT" \
    --journal "$FIXTURE" \
    --output  "$OUTPUT" \
    >/dev/null 2>&1; then
  pass "T2: script exits 0 on valid fixture journal"
else
  fail "T2: script should exit 0 on valid fixture journal"
fi

# Guard: if output was not produced, remaining tests cannot run
if [ ! -f "$OUTPUT" ]; then
  echo "FATAL: Output file not created — remaining tests skipped."
  echo ""
  echo "FAILURES: $FAILURES / $((FAILURES + PASSES))"
  echo "RESULT: FAIL"
  rm -rf "$TMP_DIR"
  exit 1
fi

# ── T3: Required top-level keys ────────────────────────────────────────────

REQUIRED_KEYS=("run_id" "generated_at" "collection_method" "invocations" "per_agent_type" "pipeline_total")
all_keys_present=true
for key in "${REQUIRED_KEYS[@]}"; do
  if ! json_has_key "$OUTPUT" "$key"; then
    fail "T3: output JSON missing required top-level key: $key"
    all_keys_present=false
  fi
done
if $all_keys_present; then
  pass "T3: all required top-level keys present (run_id, generated_at, collection_method, invocations, per_agent_type, pipeline_total)"
fi

# ── T4: per_agent_type has at least one entry with mean/median/p90/count ──

per_agent_valid=$(python3 - "$OUTPUT" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
pa = data.get("per_agent_type", {})
if not pa:
    print("no_agents")
    sys.exit(0)
agent_name, stats = next(iter(pa.items()))
required = {"mean", "median", "p90", "count"}
missing = required - set(stats.keys())
if missing:
    print(f"missing_fields:{','.join(sorted(missing))}")
else:
    print(f"ok:{agent_name}")
PYEOF
)

if [[ "$per_agent_valid" == ok:* ]]; then
  pass "T4: per_agent_type has at least one agent entry with mean, median, p90, count"
elif [[ "$per_agent_valid" == no_agents ]]; then
  fail "T4: per_agent_type is empty"
else
  fail "T4: per_agent_type entry missing fields — $per_agent_valid"
fi

# ── T5: collection_method is one of the two valid values ──────────────────

collection_method=$(json_get "$OUTPUT" "collection_method" | tr -d '"')
if [[ "$collection_method" == "live_instrumentation" || "$collection_method" == "post_hoc_estimation" ]]; then
  pass "T5: collection_method is valid ('$collection_method')"
else
  fail "T5: collection_method must be 'live_instrumentation' or 'post_hoc_estimation', got: '$collection_method'"
fi

# ── T6: invocations array is non-empty ────────────────────────────────────

inv_count=$(python3 -c "
import json, sys
d = json.load(open('$OUTPUT'))
print(len(d.get('invocations', [])))
" 2>/dev/null)

if [ "${inv_count:-0}" -gt 0 ]; then
  pass "T6: invocations array is non-empty ($inv_count entries)"
else
  fail "T6: invocations array is empty"
fi

# ── T7: pipeline_total has all three token fields ─────────────────────────

pipeline_valid=$(python3 - "$OUTPUT" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
pt = data.get("pipeline_total", {})
required = {"prompt_tokens", "completion_tokens", "total_tokens"}
missing = required - set(pt.keys())
if missing:
    print(f"missing:{','.join(sorted(missing))}")
else:
    print(f"ok:{pt['total_tokens']}")
PYEOF
)

if [[ "$pipeline_valid" == ok:* ]]; then
  total="${pipeline_valid#ok:}"
  pass "T7: pipeline_total has prompt_tokens, completion_tokens, total_tokens (total=$total)"
else
  fail "T7: pipeline_total missing fields — $pipeline_valid"
fi

# ── T8: At least one invocation has the five AC-003-001 required fields ──────
# AC-003-001 requires: prompt_tokens, completion_tokens, agent, spec_run_id, codebase_id

inv_fields_valid=$(python3 - "$OUTPUT" <<'PYEOF'
import json, sys
data = json.load(open(sys.argv[1]))
invocations = data.get("invocations", [])
if not invocations:
    print("empty")
    sys.exit(0)
# AC-003-001 mandatory fields per invocation
required = {"agent", "prompt_tokens", "completion_tokens", "spec_run_id", "codebase_id"}
inv = invocations[0]
missing = required - set(inv.keys())
if missing:
    print(f"missing:{','.join(sorted(missing))}")
else:
    print("ok")
PYEOF
)

if [[ "$inv_fields_valid" == "ok" ]]; then
  pass "T8: invocations[0] has all five AC-003-001 fields (agent, prompt_tokens, completion_tokens, spec_run_id, codebase_id)"
else
  fail "T8: invocations[0] missing AC-003-001 required fields — $inv_fields_valid"
fi

# ── T9: Expected agents from fixture appear in per_agent_type ─────────────

EXPECTED_AGENTS=("SCOUT" "CARTOGRAPHER" "SAGE")
all_agents_found=true
for agent in "${EXPECTED_AGENTS[@]}"; do
  found=$(python3 -c "
import json, sys
data = json.load(open('$OUTPUT'))
pa = data.get('per_agent_type', {})
print('yes' if '$agent' in pa else 'no')
" 2>/dev/null)
  if [ "$found" != "yes" ]; then
    fail "T9: Expected agent '$agent' not found in per_agent_type"
    all_agents_found=false
  fi
done
if $all_agents_found; then
  pass "T9: all expected agents (SCOUT, CARTOGRAPHER, SAGE) present in per_agent_type"
fi

# ── Cleanup and result ─────────────────────────────────────────────────────

rm -rf "$TMP_DIR"

echo ""
TOTAL=$((FAILURES + PASSES))
echo "Tests: $PASSES/$TOTAL passed"
if [ "$FAILURES" -eq 0 ]; then
  echo "RESULT: PASS"
  exit 0
else
  echo "FAILURES: $FAILURES"
  echo "RESULT: FAIL"
  exit 1
fi
