#!/usr/bin/env bash
# I-09: confidence_accuracy (Brier Score)
# Formula: 1 - mean((confidence_i - outcome_i)^2)
# Inputs: $1=spec (unused), $2=agent_output, $3=verdicts_file (PASS/FAIL per item)
# Verdicts file format: one line per item, "ITEM_ID PASS" or "ITEM_ID FAIL"
# Agent output must contain confidence statements: "confidence: 0.85" or "confidence 85%"
export LC_NUMERIC=C
set -euo pipefail

OUTPUT="$2"
VERDICTS="${3:-}"

tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

if [ -z "$VERDICTS" ] || [ ! -f "$VERDICTS" ]; then
  echo '{"metric":"I-09","name":"confidence_accuracy","score":null,"reason":"requires-verdict-data","pairs":0}'
  exit 0
fi

# Extract confidence statements from output: "confidence: 0.XX" or "confidence XX%"
grep -ioE 'confidence[: ]+[0-9.]+%?' "$OUTPUT" | while read -r line; do
  val=$(echo "$line" | grep -oE '[0-9.]+' | tail -1)
  # Normalize percentage to decimal
  if echo "$line" | grep -q '%'; then
    val=$(awk "BEGIN {printf \"%.4f\", $val / 100}")
  fi
  # Clamp to 0-1
  val=$(awk "BEGIN {v=$val; if(v>1) v=1; if(v<0) v=0; printf \"%.4f\", v}")
  echo "$val"
done > "$tmpdir/confidences.txt" || true

total_conf=$(wc -l < "$tmpdir/confidences.txt" | tr -d ' ')
total_verdicts=$(wc -l < "$VERDICTS" | tr -d ' ')

# Pair confidences with outcomes (positional matching)
pairs=0
sum_sq=0

# Read verdicts and pair with confidences
paste "$tmpdir/confidences.txt" <(awk '{print ($2 == "PASS") ? 1.0 : 0.0}' "$VERDICTS") 2>/dev/null | while read -r conf outcome; do
  if [ -n "$conf" ] && [ -n "$outcome" ]; then
    echo "$conf $outcome"
  fi
done > "$tmpdir/pairs.txt" || true

pairs=$(wc -l < "$tmpdir/pairs.txt" | tr -d ' ')

# Require minimum 5 pairs (FR-049)
if [ "$pairs" -lt 5 ]; then
  echo "{\"metric\":\"I-09\",\"name\":\"confidence_accuracy\",\"score\":null,\"reason\":\"insufficient-confidence-outcome-data\",\"pairs\":$pairs,\"min_required\":5}"
  exit 0
fi

# Compute Brier Score: 1 - mean((conf - outcome)^2)
score=$(awk '
BEGIN { sum = 0; n = 0 }
{
  diff = $1 - $2
  sum += diff * diff
  n++
}
END {
  if (n > 0) printf "%.4f", 1 - (sum / n)
  else print "null"
}
' "$tmpdir/pairs.txt")

echo "{\"metric\":\"I-09\",\"name\":\"confidence_accuracy\",\"score\":$score,\"reason\":null,\"pairs\":$pairs,\"confidences_found\":$total_conf,\"verdicts_found\":$total_verdicts}"
