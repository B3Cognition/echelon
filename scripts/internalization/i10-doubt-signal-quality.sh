#!/usr/bin/env bash
# I-10: doubt_signal_quality
# Formula: predicting_doubts / total_doubts
# A doubt "predicted rework" if the area it targeted received a FAIL verdict
# Inputs: $1=spec (unused), $2=checkpoint_report, $3=verdicts_file
# Checkpoint report: lines containing "doubt:" or "Doubt:" with category keywords
# Verdicts file: "AREA PASS" or "AREA FAIL" per line
export LC_NUMERIC=C
set -euo pipefail

CHECKPOINT_REPORT="$2"
VERDICTS="${3:-}"

tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

if [ -z "$VERDICTS" ] || [ ! -f "$VERDICTS" ]; then
  echo '{"metric":"I-10","name":"doubt_signal_quality","score":null,"reason":"requires-verdict-data"}'
  exit 0
fi

if [ ! -f "$CHECKPOINT_REPORT" ]; then
  echo '{"metric":"I-10","name":"doubt_signal_quality","score":null,"reason":"no-checkpoint-report"}'
  exit 0
fi

# Extract doubts from checkpoint report
grep -iE 'doubt|concern|uncertain|worried|unclear' "$CHECKPOINT_REPORT" > "$tmpdir/doubts.txt" || true
total=$(wc -l < "$tmpdir/doubts.txt" | tr -d ' ')

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-10","name":"doubt_signal_quality","score":null,"reason":"empty-denominator","doubts":0}'
  exit 0
fi

# Extract FAIL areas from verdicts
grep "FAIL" "$VERDICTS" | awk '{print tolower($1)}' > "$tmpdir/failed_areas.txt" || true

# Check which doubts predicted a failure (doubt text contains a failed area keyword)
predicting=0
while IFS= read -r doubt; do
  doubt_lower=$(echo "$doubt" | tr '[:upper:]' '[:lower:]')
  while IFS= read -r area; do
    if echo "$doubt_lower" | grep -q "$area"; then
      predicting=$((predicting + 1))
      break
    fi
  done < "$tmpdir/failed_areas.txt"
done < "$tmpdir/doubts.txt"

score=$(awk "BEGIN {printf \"%.4f\", $predicting / $total}")

echo "{\"metric\":\"I-10\",\"name\":\"doubt_signal_quality\",\"score\":$score,\"reason\":null,\"doubts\":$total,\"predicting\":$predicting}"
