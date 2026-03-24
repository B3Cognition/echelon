#!/usr/bin/env bash
# run-understanding.sh — Run Understanding CLI on a spec file
# Usage: run-understanding.sh <spec-file> [--validate] [--json]

set -euo pipefail

SPEC_FILE="${1:?Usage: run-understanding.sh <spec-file> [--validate] [--json]}"
shift

if ! command -v understanding &>/dev/null; then
  echo '{"error": "understanding CLI not found", "fallback": true}' >&2
  exit 1
fi

understanding scan "$SPEC_FILE" --enhanced "$@"
