#!/usr/bin/env bash
# I-13: first_pass_acceptance
# Formula: first_pass_accepted / total_outputs
# An output is "first pass accepted" if ALL gates (SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN) passed on first submission
# Inputs: $1=spec (unused), $2=agent_output (unused), $3=verdicts_file
# Verdicts file format: "TASK_ID GATE VERDICT CYCLE" per line
#   e.g., "T-001 SPEC_GUARD PASS 1" or "T-001 CODE_REVIEWER FAIL 1"
export LC_NUMERIC=C
set -euo pipefail

VERDICTS="${3:-}"

tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

if [ -z "$VERDICTS" ] || [ ! -f "$VERDICTS" ]; then
  echo '{"metric":"I-13","name":"first_pass_acceptance","score":null,"reason":"requires-verdict-data"}'
  exit 0
fi

# Get unique tasks
awk '{print $1}' "$VERDICTS" | sort -u > "$tmpdir/tasks.txt"
total=$(wc -l < "$tmpdir/tasks.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-13","name":"first_pass_acceptance","score":null,"reason":"empty-denominator","tasks":0}'
  exit 0
fi

# A task is "first pass accepted" if no FAIL verdict exists for cycle 1
first_pass=0
while IFS= read -r task; do
  # Check if this task has any FAIL in cycle 1
  has_fail=$(grep "^$task " "$VERDICTS" | awk '$4 == 1 && $3 == "FAIL"' | wc -l | tr -d ' ')
  if [ "$has_fail" -eq 0 ]; then
    first_pass=$((first_pass + 1))
  fi
done < "$tmpdir/tasks.txt"

score=$(awk "BEGIN {printf \"%.4f\", $first_pass / $total}")

echo "{\"metric\":\"I-13\",\"name\":\"first_pass_acceptance\",\"score\":$score,\"reason\":null,\"tasks\":$total,\"first_pass\":$first_pass,\"reworked\":$((total - first_pass))}"
