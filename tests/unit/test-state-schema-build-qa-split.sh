#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCHEMA="$ROOT_DIR/templates/state-schema.json"

require_token() {
  token="$1"
  if ! grep -q "$token" "$SCHEMA"; then
    echo "missing token in schema: $token" >&2
    exit 1
  fi
}

require_token '"build_done"'
require_token '"build_init"'
require_token '"build_loop"'
require_token '"BUILD_IN_PROGRESS"'
require_token '"QA_IN_PROGRESS"'
require_token '"QA_COMPLETE"'
require_token '"CHANGE_PENDING"'

echo "state-schema build-qa split checks: PASS"
