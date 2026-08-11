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

if grep -q 'PATH="$(dirname "$PYTHON"):$PATH"' "$ROOT/tests/run-all.sh"; then
  echo "PASS: run-all routes child python3 calls through selected Python"
  PASS=$((PASS + 1))
else
  echo "FAIL: run-all routes child python3 calls through selected Python"
  FAIL=$((FAIL + 1))
fi

if grep -q 'sys.version_info >= (3, 11)' "$ROOT/tests/run-all.sh"; then
  echo "PASS: run-all enforces the project minimum Python version"
  PASS=$((PASS + 1))
else
  echo "FAIL: run-all enforces the project minimum Python version"
  FAIL=$((FAIL + 1))
fi

if grep -q 'Python: %s (%s)' "$ROOT/tests/run-all.sh"; then
  echo "PASS: run-all reports the selected interpreter and version"
  PASS=$((PASS + 1))
else
  echo "FAIL: run-all reports the selected interpreter and version"
  FAIL=$((FAIL + 1))
fi

if ! grep -q 'run_pytest_suite "Shim Tests"' "$ROOT/tests/run-all.sh"; then
  echo "PASS: run-all omits the retired empty shim suite"
  PASS=$((PASS + 1))
else
  echo "FAIL: run-all omits the retired empty shim suite"
  FAIL=$((FAIL + 1))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
