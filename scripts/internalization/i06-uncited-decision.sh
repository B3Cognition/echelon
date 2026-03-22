#!/usr/bin/env bash
# I-06: uncited_decision_rate (deterministic proxy)
# Formula: 1 - (uncited_decisions / total_decisions)
# Detects decisions by keyword, checks for requirement ID citations
# Inputs: $1=spec (unused but kept for interface consistency), $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Extract decision lines using keywords and structural markers
grep -inE '(^decision:|^### decision|decided|selected|chose|choosing|adopted|will use|opted|implemented)' "$OUTPUT" \
  | grep -ivE '^\s*$' > "$tmpdir/decisions.txt" || true

total=$(grep -c . "$tmpdir/decisions.txt" || true)

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-06","name":"uncited_decision_rate","score":null,"reason":"empty-denominator","proxy":true,"signal":"~80%","decisions":0}'
  exit 0
fi

# For each decision line, check if it contains a requirement ID citation
uncited=0
cited=0
while IFS= read -r line; do
  if echo "$line" | grep -qoE '(FR|NFR|AC|C)-[0-9]{3}'; then
    cited=$((cited + 1))
  else
    uncited=$((uncited + 1))
  fi
done < "$tmpdir/decisions.txt"

score=$(awk "BEGIN {printf \"%.4f\", 1 - ($uncited / $total)}")

echo "{\"metric\":\"I-06\",\"name\":\"uncited_decision_rate\",\"score\":$score,\"reason\":null,\"proxy\":true,\"signal\":\"~80%\",\"decisions\":$total,\"cited\":$cited,\"uncited\":$uncited}"
