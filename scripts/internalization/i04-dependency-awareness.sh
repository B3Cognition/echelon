#!/usr/bin/env bash
# I-04: dependency_awareness
# Formula: mentioned / total_in_scope
# Inputs: $1=spec, $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"
OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Extract dependency names from spec
# Look for dependency table rows or ## Dependencies section entries
grep -oE '^\| *([A-Za-z][A-Za-z0-9_ -]+[A-Za-z0-9]) *\|' "$SPEC" | sed 's/|//g' | sed 's/^ *//;s/ *$//' | \
  grep -v -iE '^dependency$|^role$|^constraint$|^term$|^definition$|^operator$|^value$' | \
  sort -u > "$tmpdir/deps.txt" || true

total=$(grep -c . "$tmpdir/deps.txt" || true)

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-04","name":"dependency_awareness","score":null,"reason":"empty-denominator","dependencies":0,"mentioned":0}'
  exit 0
fi

mentioned=0
missing=""
while IFS= read -r dep; do
  if grep -qi "$dep" "$OUTPUT"; then
    mentioned=$((mentioned + 1))
  else
    missing="${missing}\"$dep\","
  fi
done < "$tmpdir/deps.txt"

score=$(awk "BEGIN {printf \"%.4f\", $mentioned / $total}")
missing=$(echo "$missing" | sed 's/,$//')

echo "{\"metric\":\"I-04\",\"name\":\"dependency_awareness\",\"score\":$score,\"reason\":null,\"dependencies\":$total,\"mentioned\":$mentioned,\"missing\":[$missing]}"
