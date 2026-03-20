#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
SCHEMA="$ROOT_DIR/templates/state-schema.json"
CHANGE_CMD="$ROOT_DIR/commands/squad.change.md"

[ -f "$SCHEMA" ]
[ -f "$CHANGE_CMD" ]

grep -q '"CHANGE_PENDING"' "$SCHEMA"
grep -q 'CHANGE_PENDING' "$CHANGE_CMD"
grep -q 'BUILD_RESTART' "$CHANGE_CMD"
grep -q 'QA_RESTART' "$CHANGE_CMD"

echo "qa scope-change restart checks: PASS"
