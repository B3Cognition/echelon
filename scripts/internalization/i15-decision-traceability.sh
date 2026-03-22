#!/usr/bin/env bash
# I-15: explicit_decision_traceability
# Formula: traced_decisions / total_decisions
# Reuses I-06 decision extraction, but checks if cited IDs are VALID (exist in spec)
# Inputs: $1=spec, $2=agent_output
# NOTE: This was classified as "deferred" but actually works with spec+output alone
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"; OUTPUT="$2"
tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

# Build valid ID set from spec
grep -oE '(FR|NFR|AC|C)-[0-9]{3}[a-z]?' "$SPEC" | sort -u > "$tmpdir/valid_ids.txt" || true
valid_count=$(wc -l < "$tmpdir/valid_ids.txt" | tr -d ' ')

# Extract decision lines (reuse I-06 pattern)
grep -inE '(^decision:|^### decision|decided|selected|chose|choosing|adopted|will use|opted|implemented)' "$OUTPUT" \
  | grep -ivE '^\s*$' > "$tmpdir/decisions.txt" || true

total=$(wc -l < "$tmpdir/decisions.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-15","name":"decision_traceability","score":null,"reason":"empty-denominator","decisions":0}'
  exit 0
fi

# For each decision, check if it cites a VALID requirement ID
traced=0
while IFS= read -r line; do
  # Extract all ID citations from this decision line
  cited_ids=$(echo "$line" | grep -oE '(FR|NFR|AC|C)-[0-9]{3}[a-z]?' || true)
  if [ -z "$cited_ids" ]; then
    continue
  fi
  # Check if ANY cited ID is valid (exists in spec)
  found_valid=0
  for id in $cited_ids; do
    if grep -q "^${id}$" "$tmpdir/valid_ids.txt"; then
      found_valid=1
      break
    fi
  done
  if [ "$found_valid" -eq 1 ]; then
    traced=$((traced + 1))
  fi
done < "$tmpdir/decisions.txt"

score=$(awk "BEGIN {printf \"%.4f\", $traced / $total}")

echo "{\"metric\":\"I-15\",\"name\":\"decision_traceability\",\"score\":$score,\"reason\":null,\"decisions\":$total,\"traced\":$traced,\"untraced\":$((total - traced)),\"valid_ids_in_spec\":$valid_count}"
