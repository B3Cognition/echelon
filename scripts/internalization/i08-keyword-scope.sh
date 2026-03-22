#!/usr/bin/env bash
# I-08: keyword_scope_rate (deterministic proxy)
# Formula: scoped_decisions / total_decisions
# Checks if decisions contain scope keywords (requirement IDs + dependency names)
# Inputs: $1=spec, $2=agent_output
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"
OUTPUT="$2"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

# Build scope keyword set: requirement IDs + dependency names + glossary terms
{
  grep -oE '(FR|NFR)-[0-9]{3}' "$SPEC" || true
  grep -oE '^\| *([A-Za-z][A-Za-z0-9_ -]+[A-Za-z0-9]) *\|' "$SPEC" | sed 's/|//g' | sed 's/^ *//;s/ *$//' | \
    grep -v -iE '^dependency$|^role$|^constraint$|^term$|^definition$|^operator$|^value$'
} | tr '[:upper:]' '[:lower:]' | sort -u > "$tmpdir/scope_keywords.txt" || true

# Extract decision lines (reuse I-06 pattern)
grep -inE '(^decision:|^### decision|decided|selected|chose|choosing|adopted|will use|opted|implemented)' "$OUTPUT" \
  | grep -ivE '^\s*$' > "$tmpdir/decisions.txt" || true

total=$(grep -c . "$tmpdir/decisions.txt" || true)

if [ "$total" -eq 0 ]; then
  echo '{"metric":"I-08","name":"keyword_scope_rate","score":null,"reason":"empty-denominator","proxy":true,"signal":"~70%","decisions":0}'
  exit 0
fi

scoped=0
while IFS= read -r line; do
  line_lower=$(echo "$line" | tr '[:upper:]' '[:lower:]')
  found=0
  while IFS= read -r kw; do
    if echo "$line_lower" | grep -q "$kw"; then
      found=1
      break
    fi
  done < "$tmpdir/scope_keywords.txt"
  if [ "$found" -eq 1 ]; then
    scoped=$((scoped + 1))
  fi
done < "$tmpdir/decisions.txt"

score=$(awk "BEGIN {printf \"%.4f\", $scoped / $total}")

echo "{\"metric\":\"I-08\",\"name\":\"keyword_scope_rate\",\"score\":$score,\"reason\":null,\"proxy\":true,\"signal\":\"~70%\",\"decisions\":$total,\"scoped\":$scoped}"
