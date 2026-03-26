#!/usr/bin/env bash
# run-understanding.sh — Run Understanding CLI on a spec file
# Usage: run-understanding.sh <spec-file> [--validate] [--json]

set -euo pipefail

SPEC_FILE="${1:?Usage: run-understanding.sh <spec-file> [--validate] [--json]}"
shift

# Ensure ~/.local/bin is in PATH (subagents may not inherit user's shell profile)
export PATH="$HOME/.local/bin:$PATH"

# Find understanding CLI — no fallback, hard stop if not found
UNDERSTANDING_BIN=""
if command -v understanding &>/dev/null; then
  UNDERSTANDING_BIN="understanding"
elif [ -x "$HOME/.local/bin/understanding" ]; then
  UNDERSTANDING_BIN="$HOME/.local/bin/understanding"
elif [ -x "/usr/local/bin/understanding" ]; then
  UNDERSTANDING_BIN="/usr/local/bin/understanding"
fi

if [ -z "$UNDERSTANDING_BIN" ]; then
  echo "HARD STOP: understanding CLI not found in PATH, ~/.local/bin, or /usr/local/bin" >&2
  echo "Install: pip install understanding  OR  uv tool install understanding" >&2
  exit 1
fi

"$UNDERSTANDING_BIN" scan "$SPEC_FILE" --enhanced "$@"
