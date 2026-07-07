#!/usr/bin/env bash
# Regression tests for tests/utils/python-detect.sh interpreter selection.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

assert_eq() {
  if [[ "$1" == "$2" ]]; then
    echo "PASS: $3"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $3 (expected '$2', got '$1')"
    FAIL=$((FAIL + 1))
  fi
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

fake_python="$tmpdir/ci-python"
cat > "$fake_python" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == "-c" ]]; then
  exit 0
fi
printf 'fake ci python\n'
STUB
chmod +x "$fake_python"

PYTHON="$fake_python"
. "$ROOT/tests/utils/python-detect.sh"
assert_eq "$PYTHON" "$fake_python" "python-detect honors preselected CI interpreter"

if grep -q '^export PYTHON$' "$ROOT/tests/run-all.sh"; then
  echo "PASS: run-all exports selected Python to shell suites"
  PASS=$((PASS + 1))
else
  echo "FAIL: run-all exports selected Python to shell suites"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
