#!/usr/bin/env bash
# Integration test — post-dispatch-hormone-update.sh idempotency + apply path.

set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_ROOT/scripts/bash/post-dispatch-hormone-update.sh"
ENDOCRINE="$REPO_ROOT/extension/scripts/bash/endocrine.sh"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Build a temp workspace
mkdir -p "$TMPDIR/.specify/squad"
mkdir -p "$TMPDIR/extension/scripts/bash"
ln -s "$REPO_ROOT/extension/scripts/bash"/* "$TMPDIR/extension/scripts/bash/" 2>/dev/null || true
cp "$REPO_ROOT/extension/echelon-config.yml" "$TMPDIR/extension/echelon-config.yml"

export ENDOCRINE_STATE_FILE="$TMPDIR/.specify/squad/state.json"
echo "{\"iteration\": 3, \"phase\": \"build-2-implement\", \"thresholds\": {\"token_budget_k\": 1000, \"max_squad_iterations\": 10}, \"token_ledger\": {\"total_estimated_tokens\": 200000}, \"autonomy_mode\": \"banzai\", \"quality_scores\": []}" > "$ENDOCRINE_STATE_FILE"
bash "$ENDOCRINE" init >/dev/null 2>&1

cat > "$TMPDIR/result.yaml" <<'EOF'
verdict: PASS
EOF
touch "$TMPDIR/.specify/squad/reasoning-journal.jsonl"

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
journal_1=$(wc -l < "$TMPDIR/.specify/squad/reasoning-journal.jsonl")
check "after first run, D-001 in applied_dispatches" "jq -e '.endocrine_state.applied_dispatches | index(\"D-001\")' '$ENDOCRINE_STATE_FILE' > /dev/null"
check "after first run, journal has entries" "[ $journal_1 -ge 2 ]"

# Run hook AGAIN with same dispatch_id — should be no-op
(cd "$TMPDIR" && bash "$HOOK" --agent SAGE --dispatch-id D-001 --result-file "$TMPDIR/result.yaml") > /dev/null

applied_2=$(jq -r '.endocrine_state.applied_dispatches | length' "$ENDOCRINE_STATE_FILE")
journal_2=$(wc -l < "$TMPDIR/.specify/squad/reasoning-journal.jsonl")
check "applied_dispatches did not grow on re-run" "[ $applied_1 -eq $applied_2 ]"
check "journal did not grow on re-run" "[ $journal_1 -eq $journal_2 ]"

# Run hook with different dispatch_id — should fire
(cd "$TMPDIR" && bash "$HOOK" --agent SAGE --dispatch-id D-002 --result-file "$TMPDIR/result.yaml") > /dev/null

applied_3=$(jq -r '.endocrine_state.applied_dispatches | length' "$ENDOCRINE_STATE_FILE")
check "different dispatch_id grows applied_dispatches" "[ $applied_3 -eq $((applied_1 + 1)) ]"

# Run-dir detection: when no ENDOCRINE_* override is set, the hook must use runs/.current.
RUN_WS="$TMPDIR/run-workspace"
RUN_ID="run-active"
RUN_DIR="$RUN_WS/runs/$RUN_ID"
mkdir -p "$RUN_DIR" "$RUN_WS/runs" "$RUN_WS/.specify" "$RUN_WS/extension/scripts/bash"
printf '%s\n' "$RUN_ID" > "$RUN_WS/runs/.current"
ln -s "$REPO_ROOT/extension/scripts/bash"/* "$RUN_WS/extension/scripts/bash/" 2>/dev/null || true
cp "$REPO_ROOT/extension/echelon-config.yml" "$RUN_WS/extension/echelon-config.yml"
echo "{\"iteration\": 3, \"phase\": \"build-2-implement\", \"thresholds\": {\"token_budget_k\": 1000, \"max_squad_iterations\": 10}, \"token_ledger\": {\"total_estimated_tokens\": 200000}, \"autonomy_mode\": \"banzai\", \"quality_scores\": []}" > "$RUN_DIR/state.json"
(cd "$RUN_WS" && env -u ENDOCRINE_STATE_FILE -u ENDOCRINE_SQUAD_DIR bash "$RUN_WS/extension/scripts/bash/endocrine.sh" init) >/dev/null 2>&1
: > "$RUN_DIR/reasoning-journal.jsonl"

(cd "$RUN_WS" && env -u ENDOCRINE_STATE_FILE -u ENDOCRINE_SQUAD_DIR bash "$HOOK" --agent SAGE --dispatch-id D-RUNS --result-file "$TMPDIR/result.yaml") > /dev/null

check "runs/.current state receives applied dispatch" "jq -e '.endocrine_state.applied_dispatches | index(\"D-RUNS\")' '$RUN_DIR/state.json' > /dev/null"
check "runs/.current journal receives entries" "[ \$(wc -l < '$RUN_DIR/reasoning-journal.jsonl') -ge 2 ]"
check "legacy .specify/squad journal not created for runs/.current" "[ ! -e '$RUN_WS/.specify/squad/reasoning-journal.jsonl' ]"

echo
echo "Pass: $pass  Fail: $fail"
exit $((fail == 0 ? 0 : 1))
