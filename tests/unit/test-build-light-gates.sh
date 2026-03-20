#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/bash/build-light-gates.sh"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

printf '#!/usr/bin/env sh\nexit 0\n' > "$TMP_DIR/ok.sh"
printf 'contract: ok\n' > "$TMP_DIR/ok.yaml"
printf 'done\n' > "$TMP_DIR/output.txt"

ok_json="$(sh "$SCRIPT" evaluate \
  --task-id T013 \
  --paths "$TMP_DIR/ok.sh,$TMP_DIR/ok.yaml" \
  --required-outputs "$TMP_DIR/output.txt" \
  --tests-cmd 'exit 0')"

echo "$ok_json" | grep -q '"build_valid": true'
echo "$ok_json" | grep -q '"tests_passed": true'
echo "$ok_json" | grep -q '"required_outputs_present": true'

set +e
sh "$SCRIPT" evaluate \
  --task-id T013 \
  --paths "$TMP_DIR/ok.sh" \
  --required-outputs "$TMP_DIR/missing.txt" \
  --tests-cmd 'exit 0' >/dev/null 2>&1
rc=$?
set -e

[ "$rc" -ne 0 ]

echo "build-light-gates unit checks: PASS"
