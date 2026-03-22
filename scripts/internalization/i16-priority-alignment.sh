#!/usr/bin/env bash
# I-16: priority_alignment (Spearman rank correlation)
# Formula: ρ = 1 - (6 × Σd²) / (n × (n² - 1)), normalized to [0,1] as (1+ρ)/2
# Compares spec requirement priority ranks with agent decision attention ranks
# Inputs: $1=spec, $2=agent_output
# NOTE: This was classified as "deferred" but works with spec+output alone
export LC_NUMERIC=C
set -euo pipefail

SPEC="$1"; OUTPUT="$2"
tmpdir=$(mktemp -d); trap 'rm -rf "$tmpdir"' EXIT

# Extract requirements with priority indicators from spec
# Look for: Must-Have, Should-Have, Could-Have, Won't-Have or P0/P1/P2/P3
# Assign priority scores: Must-Have/P0=4, Should-Have/P1=3, Could-Have/P2=2, Won't-Have/P3=1
{
  # Pattern 1: "FR-001 ... | Must-Have |" or "| FR-001 | ... | MVP |"
  grep -oE '(FR|NFR)-[0-9]{3}' "$SPEC" | sort -u | while read -r req_id; do
    # Find the line containing this requirement and check for priority keywords
    priority=2  # default: Could-Have
    req_line=$(grep "$req_id" "$SPEC" | head -1)
    if echo "$req_line" | grep -qiE 'must.have|MVP|P0|critical'; then
      priority=4
    elif echo "$req_line" | grep -qiE 'should.have|P1|high'; then
      priority=3
    elif echo "$req_line" | grep -qiE 'could.have|P2|medium|deferred'; then
      priority=2
    elif echo "$req_line" | grep -qiE 'won.t.have|P3|low|future'; then
      priority=1
    fi
    echo "$req_id $priority"
  done
} > "$tmpdir/spec_priorities.txt" || true

n=$(wc -l < "$tmpdir/spec_priorities.txt" | tr -d ' ')

if [ "$n" -lt 3 ]; then
  echo "{\"metric\":\"I-16\",\"name\":\"priority_alignment\",\"score\":null,\"reason\":\"insufficient-ranked-requirements\",\"requirements\":$n,\"min_required\":3}"
  exit 0
fi

# Count decisions referencing each requirement in agent output
total_attention=0
while read -r req_id priority; do
  count=$(grep -c "$req_id" "$OUTPUT" 2>/dev/null || echo 0)
  count=$(echo "$count" | tr -d '[:space:]')
  total_attention=$((total_attention + count))
  echo "$req_id $priority $count"
done < "$tmpdir/spec_priorities.txt" > "$tmpdir/combined.txt"

# If agent references zero requirements, alignment is 0 (not computable)
if [ "$total_attention" -eq 0 ]; then
  echo "{\"metric\":\"I-16\",\"name\":\"priority_alignment\",\"score\":0.0000,\"reason\":\"zero-attention\",\"requirements\":$n,\"total_references\":0}"
  exit 0
fi

# Compute Spearman rank correlation
score=$(awk '
BEGIN { n = 0 }
{
  priority[n] = $2
  attention[n] = $3
  n++
}
END {
  if (n < 3) { print "null"; exit }

  # Rank priority (higher priority = lower rank number)
  for (i = 0; i < n; i++) prank[i] = i
  for (i = 0; i < n-1; i++)
    for (j = i+1; j < n; j++)
      if (priority[prank[i]] < priority[prank[j]]) {
        t = prank[i]; prank[i] = prank[j]; prank[j] = t
      }
  for (i = 0; i < n; i++) pr[prank[i]] = i + 1

  # Rank attention (higher attention = lower rank number)
  for (i = 0; i < n; i++) arank[i] = i
  for (i = 0; i < n-1; i++)
    for (j = i+1; j < n; j++)
      if (attention[arank[i]] < attention[arank[j]]) {
        t = arank[i]; arank[i] = arank[j]; arank[j] = t
      }
  for (i = 0; i < n; i++) ar[arank[i]] = i + 1

  # Compute sum of squared rank differences
  sum_d2 = 0
  for (i = 0; i < n; i++) {
    d = pr[i] - ar[i]
    sum_d2 += d * d
  }

  # Spearman rho
  rho = 1 - (6 * sum_d2) / (n * (n*n - 1))

  # Normalize to [0, 1]
  normalized = (1 + rho) / 2

  printf "%.4f", normalized
}
' "$tmpdir/combined.txt")

echo "{\"metric\":\"I-16\",\"name\":\"priority_alignment\",\"score\":$score,\"reason\":null,\"requirements\":$n}"
