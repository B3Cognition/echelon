#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"

sh "$ROOT_DIR/tests/e2e/test-e2e-build-parallel-light-gates.sh"
sh "$ROOT_DIR/tests/e2e/test-e2e-qa-scope-change-restart.sh"

echo "build-qa split regression wrapper: PASS"
