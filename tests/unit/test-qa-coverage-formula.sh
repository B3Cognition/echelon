#!/usr/bin/env sh
set -eu

# QA_COVERAGE = 0.60*R + 0.25*L + 0.15*B
calc() {
  R="$1"
  L="$2"
  B="$3"
  awk -v r="$R" -v l="$L" -v b="$B" 'BEGIN { printf "%.2f", (0.60*r + 0.25*l + 0.15*b) }'
}

v1="$(calc 1.0 1.0 1.0)"
[ "$v1" = "1.00" ]

v2="$(calc 0.9 1.0 1.0)"
[ "$v2" = "0.94" ]

# PARTIAL/MISSING should still fail by policy; this test asserts arithmetic only.

echo "qa coverage formula checks: PASS"
