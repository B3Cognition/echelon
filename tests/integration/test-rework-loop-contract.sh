#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
CONTRACT="$ROOT_DIR/specs/002-build-qa-phase-split/contracts/rework-loop-transition.contract.yaml"

[ -f "$CONTRACT" ]
grep -q 'default_routing_mode: PER_AFFECTED' "$CONTRACT"
grep -q 'fallback_routing_mode: FULL_CYCLE' "$CONTRACT"
grep -q 'max_iterations: 3' "$CONTRACT"
grep -q 're_entry_dispatch:' "$CONTRACT"

echo "rework-loop contract checks: PASS"
