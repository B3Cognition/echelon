#!/usr/bin/env bash
# I-03: terminology_fidelity (glossary recall)
# Formula: |glossary_terms ∩ output_terms| / |glossary_terms|
# Inputs: $1=spec (with glossary section), $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"
OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Extract glossary terms from spec
# Look for table rows: "| term | definition |" — extract first column
# Also look for bold terms: **term**
{
  grep -oE '^\| *([A-Za-z][A-Za-z_ -]+[A-Za-z]) *\|' "$SPEC" | sed 's/|//g' | sed 's/^ *//;s/ *$//' | tr '[:upper:]' '[:lower:]'
  grep -oE '\*\*[A-Za-z][A-Za-z_ -]+[A-Za-z]\*\*' "$SPEC" | sed 's/\*\*//g' | tr '[:upper:]' '[:lower:]'
} | sort -u | grep -v '^term$\|^constraint$\|^dependency$\|^definition$\|^operator$\|^value$\|^role$' > "$tmpdir/glossary.txt" || true

total=$(grep -c . "$tmpdir/glossary.txt" || true)

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-03","name":"terminology_fidelity","score":null,"reason":"empty-denominator","glossary_terms":0,"found":0}'
  exit 0
fi

# Tokenize agent output: lowercase, one word per line
tr '[:upper:]' '[:lower:]' < "$OUTPUT" | tr -cs 'a-z' '\n' | sort -u > "$tmpdir/output_tokens.txt"

# For multi-word glossary terms, check substring match
found=0
missing=""
while IFS= read -r term; do
  if grep -qi "$term" "$OUTPUT"; then
    found=$((found + 1))
  else
    missing="${missing}\"$term\","
  fi
done < "$tmpdir/glossary.txt"

score=$(awk "BEGIN {printf \"%.4f\", $found / $total}")
missing=$(echo "$missing" | sed 's/,$//')

echo "{\"metric\":\"I-03\",\"name\":\"terminology_fidelity\",\"score\":$score,\"reason\":null,\"glossary_terms\":$total,\"found\":$found,\"missing\":[$missing]}"
