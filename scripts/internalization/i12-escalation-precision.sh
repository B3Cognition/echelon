#!/usr/bin/env bash
# I-12: escalation_precision
# Formula: justified_escalations / total_escalations
# An escalation is "justified" if the area it flagged had a FAIL outcome or needed human intervention
# Inputs: $1=spec (unused), $2=reasoning_journal, $3=verdicts_file
# Reasoning journal: JSON with entries of type "escalation"
export LC_NUMERIC=C
set -euo pipefail

JOURNAL="$2"
VERDICTS="${3:-}"

tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

if [ -z "$VERDICTS" ] || [ ! -f "$VERDICTS" ]; then
  echo '{"metric":"I-12","name":"escalation_precision","score":null,"reason":"requires-verdict-data"}'
  exit 0
fi

if [ ! -f "$JOURNAL" ]; then
  echo '{"metric":"I-12","name":"escalation_precision","score":null,"reason":"no-reasoning-journal"}'
  exit 0
fi

# Extract escalation entries from reasoning journal
# Look for escalation-related entries: type "escalation", "human_escalation", "blocked"
grep -ioE '"type"[: ]+"(escalation|human_escalation|blocked)"' "$JOURNAL" > "$tmpdir/escalations.txt" || true
total=$(wc -l < "$tmpdir/escalations.txt" | tr -d ' ')

# Require minimum 3 escalations (FR-018)
if [ "$total" -lt 3 ]; then
  echo "{\"metric\":\"I-12\",\"name\":\"escalation_precision\",\"score\":null,\"reason\":\"insufficient-escalation-data\",\"escalations\":$total,\"min_required\":3}"
  exit 0
fi

# Count FAIL verdicts as "justified" — if anything failed, escalations were warranted
fail_count=$(grep -c "FAIL" "$VERDICTS" || echo 0)

if [ "$fail_count" -gt 0 ]; then
  # At least some failures — escalations were at least partially justified
  justified=$(( total < fail_count ? total : fail_count ))
else
  justified=0
fi

score=$(awk "BEGIN {printf \"%.4f\", $justified / $total}")

echo "{\"metric\":\"I-12\",\"name\":\"escalation_precision\",\"score\":$score,\"reason\":null,\"escalations\":$total,\"justified\":$justified,\"fail_count\":$fail_count}"
