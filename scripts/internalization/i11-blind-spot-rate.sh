#!/usr/bin/env bash
# I-11: blind_spot_rate
# Formula: 1 - (high_confidence_failures / total_high_confidence_claims)
# High confidence = stated confidence >= 0.80
# Inputs: $1=spec (unused), $2=agent_output, $3=verdicts_file
export LC_NUMERIC=C
set -euo pipefail

OUTPUT="$2"
VERDICTS="${3:-}"

tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

if [ -z "$VERDICTS" ] || [ ! -f "$VERDICTS" ]; then
  echo '{"metric":"I-11","name":"blind_spot_rate","score":null,"reason":"requires-verdict-data"}'
  exit 0
fi

# Extract confidence values (reuse I-09 pattern)
grep -ioE 'confidence[: ]+[0-9.]+%?' "$OUTPUT" | while read -r line; do
  val=$(echo "$line" | grep -oE '[0-9.]+' | tail -1)
  if echo "$line" | grep -q '%'; then
    val=$(awk "BEGIN {printf \"%.4f\", $val / 100}")
  fi
  echo "$val"
done > "$tmpdir/all_conf.txt" || true

# Filter to high-confidence claims (>= 0.80)
awk '$1 >= 0.80' "$tmpdir/all_conf.txt" > "$tmpdir/high_conf.txt" || true
total_high=$(wc -l < "$tmpdir/high_conf.txt" | tr -d ' ')

if [ "$total_high" -eq 0 ]; then
  echo '{"metric":"I-11","name":"blind_spot_rate","score":null,"reason":"empty-denominator","high_confidence_claims":0}'
  exit 0
fi

# Count how many high-confidence items had FAIL outcomes
# Pair high-confidence positions with verdicts
fail_count=$(awk '{print ($2 == "FAIL") ? 1 : 0}' "$VERDICTS" | head -"$total_high" | awk '{s+=$1} END{print s+0}')

score=$(awk "BEGIN {printf \"%.4f\", 1 - ($fail_count / $total_high)}")

echo "{\"metric\":\"I-11\",\"name\":\"blind_spot_rate\",\"score\":$score,\"reason\":null,\"high_confidence_claims\":$total_high,\"failures\":$fail_count}"
