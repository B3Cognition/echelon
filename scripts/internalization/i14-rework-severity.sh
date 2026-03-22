#!/usr/bin/env bash
# I-14: rework_severity
# Formula: 1 - (sum_weights / (total_outputs × 3))
# Weights: SPEC_GUARD=3, CODE_REVIEWER=2, TEST_GUARDIAN=1
# Inputs: $1=spec (unused), $2=agent_output (unused), $3=verdicts_file
# Verdicts file format: "TASK_ID GATE VERDICT CYCLE" per line
export LC_NUMERIC=C
set -euo pipefail

VERDICTS="${3:-}"

tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

if [ -z "$VERDICTS" ] || [ ! -f "$VERDICTS" ]; then
  echo '{"metric":"I-14","name":"rework_severity","score":null,"reason":"requires-verdict-data"}'
  exit 0
fi

# Get unique tasks
awk '{print $1}' "$VERDICTS" | sort -u > "$tmpdir/tasks.txt"
total=$(wc -l < "$tmpdir/tasks.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-14","name":"rework_severity","score":null,"reason":"empty-denominator","tasks":0}'
  exit 0
fi

# Sum rework weights for FAIL verdicts
sum_weights=$(awk '
$3 == "FAIL" {
  if ($2 == "SPEC_GUARD") w += 3
  else if ($2 == "CODE_REVIEWER") w += 2
  else if ($2 == "TEST_GUARDIAN") w += 1
}
END { print w+0 }
' "$VERDICTS")

# max_possible = total_tasks * 3 (worst case: every task fails SPEC_GUARD)
score=$(awk "BEGIN {printf \"%.4f\", 1 - ($sum_weights / ($total * 3))}")

echo "{\"metric\":\"I-14\",\"name\":\"rework_severity\",\"score\":$score,\"reason\":null,\"tasks\":$total,\"sum_weights\":$sum_weights,\"max_possible\":$((total * 3))}"
