#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/bash/build-light-gates.sh"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

printf '#!/usr/bin/env sh\nexit 0\n' > "$TMP_DIR/task-a.sh"
printf '#!/usr/bin/env sh\nexit 0\n' > "$TMP_DIR/task-b.sh"
printf 'ok\n' > "$TMP_DIR/out-b.txt"

set +e
sh "$SCRIPT" evaluate \
  --task-id T014-A \
  --paths "$TMP_DIR/task-a.sh" \
  --required-outputs "$TMP_DIR/missing-a.txt" \
  --tests-cmd 'exit 0' >/dev/null 2>&1
rc_a=$?
set -e

json_b="$(sh "$SCRIPT" evaluate \
  --task-id T014-B \
  --paths "$TMP_DIR/task-b.sh" \
  --required-outputs "$TMP_DIR/out-b.txt" \
  --tests-cmd 'exit 0')"

[ "$rc_a" -ne 0 ]
echo "$json_b" | grep -q '"task_id": "T014-B"'
echo "$json_b" | grep -q '"required_outputs_present": true'

echo "parallel light-gate partial failure checks: PASS"
