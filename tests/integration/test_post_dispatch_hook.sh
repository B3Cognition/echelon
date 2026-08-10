#!/usr/bin/env bash
# Integration test — post-dispatch-hormone-update.sh idempotency + apply path.

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/scripts/bash/post-dispatch-hormone-update.sh"
ENDOCRINE="$REPO_ROOT/runtime/scripts/bash/endocrine.sh"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Build a temp workspace
RUN_ID_PRIMARY="run-primary"
TEST_RUN_DIR="$TMPDIR/runs/$RUN_ID_PRIMARY"
mkdir -p "$TEST_RUN_DIR" "$TMPDIR/.echelon"
printf '%s\n' "$RUN_ID_PRIMARY" > "$TMPDIR/runs/.current"
cp "$REPO_ROOT/runtime/config-template.yml" "$TMPDIR/.echelon/config.yml"

export ENDOCRINE_SQUAD_DIR="$TEST_RUN_DIR"
export ENDOCRINE_STATE_FILE="$TEST_RUN_DIR/state.json"
export ENDOCRINE_CONFIG_FILE="$TMPDIR/.echelon/config.yml"
echo "{\"iteration\": 3, \"phase\": \"build-2-implement\", \"thresholds\": {\"token_budget_k\": 1000, \"max_squad_iterations\": 10}, \"token_ledger\": {\"total_estimated_tokens\": 200000}, \"autonomy_mode\": \"banzai\", \"quality_scores\": []}" > "$ENDOCRINE_STATE_FILE"
bash "$ENDOCRINE" init >/dev/null 2>&1

cat > "$TMPDIR/result.yaml" <<'EOF'
verdict: PASS
EOF
touch "$TEST_RUN_DIR/reasoning-journal.jsonl"

pass=0
fail=0
check() {
  local label="$1" cond="$2"
  if eval "$cond"; then pass=$((pass+1)); printf "  PASS  %s\n" "$label"
  else fail=$((fail+1)); printf "  FAIL  %s\n" "$label"; fi
}

# Run hook
(cd "$TMPDIR" && bash "$HOOK" --agent SAGE --dispatch-id D-001 --result-file "$TMPDIR/result.yaml") > /dev/null

# Assertions after first run
applied_1=$(jq -r '.endocrine_state.applied_dispatches | length' "$ENDOCRINE_STATE_FILE")
journal_1=$(wc -l < "$TEST_RUN_DIR/reasoning-journal.jsonl")
index_1=$(cat "$TEST_RUN_DIR/reasoning-journal-index.json")
check "after first run, D-001 in applied_dispatches" "jq -e '.endocrine_state.applied_dispatches | index(\"D-001\")' '$ENDOCRINE_STATE_FILE' > /dev/null"
check "after first run, journal has entries" "[ $journal_1 -ge 2 ]"
check "journal index is created" "[ -f '$TEST_RUN_DIR/reasoning-journal-index.json' ]"
check "journal IDs are unique" "jq -s -e 'map(.id) as \$ids | (\$ids | length) == (\$ids | unique | length)' '$TEST_RUN_DIR/reasoning-journal.jsonl' > /dev/null"
check "journal index matches final row" "[ \"\$(jq -r '.last_entry_id' '$TEST_RUN_DIR/reasoning-journal-index.json')\" = \"\$(tail -1 '$TEST_RUN_DIR/reasoning-journal.jsonl' | jq -r '.id')\" ]"

# Run hook AGAIN with same dispatch_id — should be no-op
(cd "$TMPDIR" && bash "$HOOK" --agent SAGE --dispatch-id D-001 --result-file "$TMPDIR/result.yaml") > /dev/null

applied_2=$(jq -r '.endocrine_state.applied_dispatches | length' "$ENDOCRINE_STATE_FILE")
journal_2=$(wc -l < "$TEST_RUN_DIR/reasoning-journal.jsonl")
check "applied_dispatches did not grow on re-run" "[ $applied_1 -eq $applied_2 ]"
check "journal did not grow on re-run" "[ $journal_1 -eq $journal_2 ]"
check "journal index did not change on re-run" "[ '$index_1' = \"\$(cat '$TEST_RUN_DIR/reasoning-journal-index.json')\" ]"

# Run hook with different dispatch_id — should fire
(cd "$TMPDIR" && bash "$HOOK" --agent SAGE --dispatch-id D-002 --result-file "$TMPDIR/result.yaml") > /dev/null

applied_3=$(jq -r '.endocrine_state.applied_dispatches | length' "$ENDOCRINE_STATE_FILE")
check "different dispatch_id grows applied_dispatches" "[ $applied_3 -eq $((applied_1 + 1)) ]"

# Run-dir detection: when no ENDOCRINE_* override is set, the hook must use runs/.current.
RUN_WS="$TMPDIR/run-workspace"
RUN_ID="run-active"
RUN_DIR="$RUN_WS/runs/$RUN_ID"
mkdir -p "$RUN_DIR" "$RUN_WS/runs" "$RUN_WS/.echelon"
printf '%s\n' "$RUN_ID" > "$RUN_WS/runs/.current"
cp "$REPO_ROOT/runtime/config-template.yml" "$RUN_WS/.echelon/config.yml"
echo "{\"iteration\": 3, \"phase\": \"build-2-implement\", \"thresholds\": {\"token_budget_k\": 1000, \"max_squad_iterations\": 10}, \"token_ledger\": {\"total_estimated_tokens\": 200000}, \"autonomy_mode\": \"banzai\", \"quality_scores\": []}" > "$RUN_DIR/state.json"
(cd "$RUN_WS" && env -u ENDOCRINE_STATE_FILE -u ENDOCRINE_SQUAD_DIR ENDOCRINE_CONFIG_FILE="$RUN_WS/.echelon/config.yml" bash "$ENDOCRINE" init) >/dev/null 2>&1
: > "$RUN_DIR/reasoning-journal.jsonl"

(cd "$RUN_WS" && env -u ENDOCRINE_STATE_FILE -u ENDOCRINE_SQUAD_DIR bash "$HOOK" --agent SAGE --dispatch-id D-RUNS --result-file "$TMPDIR/result.yaml") > /dev/null

check "runs/.current state receives applied dispatch" "jq -e '.endocrine_state.applied_dispatches | index(\"D-RUNS\")' '$RUN_DIR/state.json' > /dev/null"
check "runs/.current journal receives entries" "[ \$(wc -l < '$RUN_DIR/reasoning-journal.jsonl') -ge 2 ]"
check "runs/.current journal index is created" "[ -f '$RUN_DIR/reasoning-journal-index.json' ]"
check "legacy .specify tree not created for runs/.current" "[ ! -e '$RUN_WS/.specify' ]"

echo
echo "Pass: $pass  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
