#!/usr/bin/env bash
# T-14: Verify IMPLEMENTER eval-driven development protocol
# Greps implementer.md for required eval concepts.
set -euo pipefail

FILE="$(dirname "$0")/../../extension/agents/build/implementer.md"
FAIL=0

check() {
  local label="$1"
  local pattern="$2"
  if grep -qi "$pattern" "$FILE"; then
    echo "PASS: $label"
  else
    echo "FAIL: $label (pattern: $pattern)"
    FAIL=1
  fi
}

check "capability eval"        "capability eval"
check "regression eval"        "regression eval"
check "pass@1 metric"          "pass@1"
check "pass@3 metric"          "pass@3"
check "instability detection"  "unstable implementation"

if [ "$FAIL" -ne 0 ]; then
  echo "FAILED: implementer eval protocol incomplete"
  exit 1
fi

echo "All implementer eval protocol checks passed."
exit 0
