#!/usr/bin/env bash
# I-01: requirement_coverage_rate
# Formula: |spec_ids ∩ output_ids| / |spec_ids|
# Inputs: $1=spec, $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"; OUTPUT="$2"
tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

grep -oE '(FR|NFR)-[0-9]{3}' "$SPEC" | sort -u > "$tmpdir/spec.txt" || true
grep -oE '(FR|NFR)-[0-9]{3}' "$OUTPUT" | sort -u > "$tmpdir/out.txt" || true

total=$(wc -l < "$tmpdir/spec.txt" | tr -d ' ')
out_count=$(wc -l < "$tmpdir/out.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-01","name":"requirement_coverage_rate","score":null,"reason":"empty-denominator","spec_ids":0,"output_ids":0,"intersection":0}'
  exit 0
fi

if [ "$out_count" -eq 0 ]; then
  echo "{\"metric\":\"I-01\",\"name\":\"requirement_coverage_rate\",\"score\":0.0000,\"reason\":null,\"spec_ids\":$total,\"output_ids\":0,\"intersection\":0}"
  exit 0
fi

covered=$(comm -12 "$tmpdir/spec.txt" "$tmpdir/out.txt" | wc -l | tr -d ' ')
score=$(awk "BEGIN {printf \"%.4f\", $covered / $total}")

echo "{\"metric\":\"I-01\",\"name\":\"requirement_coverage_rate\",\"score\":$score,\"reason\":null,\"spec_ids\":$total,\"output_ids\":$out_count,\"intersection\":$covered}"
