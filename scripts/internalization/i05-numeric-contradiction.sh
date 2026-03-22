#!/usr/bin/env bash
# I-05: numeric_contradiction_rate (deterministic proxy)
# Formula: 1 - (violations / total_checked)
# Reuses constraint extraction from I-02 but inverts: measures compliance rate
# Inputs: $1=spec, $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"
OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Extract constraints — supports inline and table formats
{
  grep -oE '[a-z_]+ +[<>=!]+ +[0-9.]+' "$SPEC" 2>/dev/null || true
  grep -E '^\|.*[<>=]' "$SPEC" 2>/dev/null | awk -F'|' '{
    gsub(/[ \t]+/, "", $2); gsub(/[ \t]+/, "", $3); gsub(/[^<>=!]/, "", $3); gsub(/[ \t]+/, "", $4);
    gsub(/[^0-9.]/, "", $4);
    if ($2 != "" && $3 != "" && $4 != "") print $2" "$3" "$4
  }' || true
} | sed 's/  */ /g' | sort -u > "$tmpdir/constraints.txt" || true

total_constraints=$(wc -l < "$tmpdir/constraints.txt" | tr -d ' ')

if [ "$total_constraints" -eq 0 ]; then
  echo '{"metric":"I-05","name":"numeric_contradiction_rate","score":null,"reason":"empty-denominator","proxy":true,"signal":"~60-70%","constraints":0}'
  exit 0
fi

checked=0
violations=0
details=""

while IFS= read -r constraint; do
  param=$(echo "$constraint" | awk '{print $1}')
  op=$(echo "$constraint" | awk '{print $2}')
  spec_val=$(echo "$constraint" | awk '{print $3}')

  output_val=$(grep -ioE "${param}[^0-9]*[0-9.]+" "$OUTPUT" | grep -oE '[0-9.]+' | tail -1 || true)

  if [ -z "$output_val" ]; then
    continue
  fi

  checked=$((checked + 1))

  case "$op" in
    "<=") violated=$(awk "BEGIN {print ($output_val > $spec_val) ? 1 : 0}") ;;
    ">=") violated=$(awk "BEGIN {print ($output_val < $spec_val) ? 1 : 0}") ;;
    "<")  violated=$(awk "BEGIN {print ($output_val >= $spec_val) ? 1 : 0}") ;;
    ">")  violated=$(awk "BEGIN {print ($output_val <= $spec_val) ? 1 : 0}") ;;
    "="|"==") violated=$(awk "BEGIN {print ($output_val != $spec_val) ? 1 : 0}") ;;
    *)    violated=0 ;;
  esac

  if [ "$violated" -eq 1 ]; then
    violations=$((violations + 1))
    details="${details}{\"param\":\"$param\",\"spec\":\"$op $spec_val\",\"output\":$output_val,\"violated\":true},"
  else
    details="${details}{\"param\":\"$param\",\"spec\":\"$op $spec_val\",\"output\":$output_val,\"violated\":false},"
  fi
done < "$tmpdir/constraints.txt"

if [ "$checked" -eq 0 ]; then
  echo '{"metric":"I-05","name":"numeric_contradiction_rate","score":null,"reason":"empty-denominator","proxy":true,"signal":"~60-70%","constraints":'"$total_constraints"',"checked":0}'
  exit 0
fi

score=$(awk "BEGIN {printf \"%.4f\", 1 - ($violations / $checked)}")
details=$(echo "$details" | sed 's/,$//')

echo "{\"metric\":\"I-05\",\"name\":\"numeric_contradiction_rate\",\"score\":$score,\"reason\":null,\"proxy\":true,\"signal\":\"~60-70%\",\"checked\":$checked,\"violations\":$violations,\"details\":[$details]}"
