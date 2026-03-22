#!/usr/bin/env bash
# I-02: constraint_adherence_score
# Formula: satisfied / total_matched_constraints
# Extracts numeric constraints from spec, checks agent output for violations
# Inputs: $1=spec, $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"
OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Extract constraints from spec — supports both inline and table formats
# Inline: "max_latency <= 200ms"
# Table:  "| max_latency | <= | 200ms |"
{
  grep -oE '[a-z_]+ +[<>=!]+ +[0-9.]+' "$SPEC" 2>/dev/null || true
  grep -E '^\|.*[<>=]' "$SPEC" 2>/dev/null | awk -F'|' '{
    gsub(/[ \t]+/, "", $2); gsub(/[ \t]+/, "", $3); gsub(/[^<>=!]/, "", $3); gsub(/[ \t]+/, "", $4);
    gsub(/[^0-9.]/, "", $4);
    if ($2 != "" && $3 != "" && $4 != "") print $2" "$3" "$4
  }' || true
} | sed 's/  */ /g' | sort -u > "$tmpdir/constraints.txt" || true

total=$(wc -l < "$tmpdir/constraints.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-02","name":"constraint_adherence_score","score":null,"reason":"empty-denominator","constraints_found":0,"matched":0,"satisfied":0}'
  exit 0
fi

satisfied=0
matched=0
details=""

while IFS= read -r constraint; do
  param=$(echo "$constraint" | awk '{print $1}')
  op=$(echo "$constraint" | awk '{print $2}')
  spec_val=$(echo "$constraint" | awk '{print $3}')

  # Search output for the same parameter with a numeric value
  # Patterns: "latency target: 150ms", "retries: 2", "timeout = 600ms", "latency 150"
  output_val=$(grep -ioE "${param}[^0-9]*[0-9.]+" "$OUTPUT" | grep -oE '[0-9.]+' | tail -1 || true)

  if [ -z "$output_val" ]; then
    continue
  fi

  matched=$((matched + 1))

  # Compare using the operator
  case "$op" in
    "<=") result=$(awk "BEGIN {print ($output_val <= $spec_val) ? 1 : 0}") ;;
    ">=") result=$(awk "BEGIN {print ($output_val >= $spec_val) ? 1 : 0}") ;;
    "<")  result=$(awk "BEGIN {print ($output_val < $spec_val) ? 1 : 0}") ;;
    ">")  result=$(awk "BEGIN {print ($output_val > $spec_val) ? 1 : 0}") ;;
    "="|"==") result=$(awk "BEGIN {print ($output_val == $spec_val) ? 1 : 0}") ;;
    *)    result=0 ;;
  esac

  if [ "$result" -eq 1 ]; then
    satisfied=$((satisfied + 1))
  fi

  details="${details}{\"param\":\"$param\",\"op\":\"$op\",\"spec\":$spec_val,\"output\":$output_val,\"pass\":$result},"
done < "$tmpdir/constraints.txt"

if [ "$matched" -eq 0 ]; then
  echo '{"metric":"I-02","name":"constraint_adherence_score","score":null,"reason":"empty-denominator","constraints_found":'"$total"',"matched":0,"satisfied":0}'
  exit 0
fi

score=$(awk "BEGIN {printf \"%.4f\", $satisfied / $matched}")
details=$(echo "$details" | sed 's/,$//')

echo "{\"metric\":\"I-02\",\"name\":\"constraint_adherence_score\",\"score\":$score,\"reason\":null,\"constraints_found\":$total,\"matched\":$matched,\"satisfied\":$satisfied,\"details\":[$details]}"
