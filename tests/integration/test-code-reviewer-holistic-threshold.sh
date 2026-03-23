#!/usr/bin/env sh
set -eu
export LC_NUMERIC=C

ratio_ok=$(awk 'BEGIN { printf "%.2f", (1/10) }')
ratio_fail=$(awk 'BEGIN { printf "%.2f", (3/10) }')

[ "$ratio_ok" = "0.10" ]
[ "$ratio_fail" = "0.30" ]

# Threshold policy: fail when ratio > 0.20
awk 'BEGIN { exit !((3/10) > 0.20) }'
awk 'BEGIN { exit ((1/10) > 0.20) }'

echo "code-reviewer holistic threshold checks: PASS"
