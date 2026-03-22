#!/usr/bin/env bash
# I-07: cross_reference_accuracy
# Formula: valid_citations / total_citations
# Checks if requirement IDs cited in output actually exist in spec
# Inputs: $1=spec, $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"
OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Build valid ID set from spec
grep -oE '(FR|NFR|AC|C)-[0-9]{3}[a-z]?' "$SPEC" | sort -u > "$tmpdir/valid_ids.txt" || true

# Extract all citations from output
grep -oE '(FR|NFR|AC|C)-[0-9]{3}[a-z]?' "$OUTPUT" | sort -u > "$tmpdir/cited_ids.txt" || true

total=$(wc -l < "$tmpdir/cited_ids.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-07","name":"cross_reference_accuracy","score":null,"reason":"empty-denominator","citations":0,"valid":0,"invalid":0}'
  exit 0
fi

valid=$(comm -12 "$tmpdir/valid_ids.txt" "$tmpdir/cited_ids.txt" | wc -l | tr -d ' ')
invalid=$(comm -23 "$tmpdir/cited_ids.txt" "$tmpdir/valid_ids.txt" | wc -l | tr -d ' ')
invalid_list=$(comm -23 "$tmpdir/cited_ids.txt" "$tmpdir/valid_ids.txt" | tr '\n' ',' | sed 's/,$//')

score=$(awk "BEGIN {printf \"%.4f\", $valid / $total}")

echo "{\"metric\":\"I-07\",\"name\":\"cross_reference_accuracy\",\"score\":$score,\"reason\":null,\"citations\":$total,\"valid\":$valid,\"invalid\":$invalid,\"invalid_ids\":\"$invalid_list\"}"
