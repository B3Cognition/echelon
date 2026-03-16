#!/usr/bin/env bash
# migrate-kb.sh — Migrate knowledge base files between schema versions
# Usage: migrate-kb.sh <kb-dir> <from-version> <to-version>

set -euo pipefail

KB_DIR="${1:?Usage: migrate-kb.sh <kb-dir> <from-version> <to-version>}"
FROM_V="${2:?Missing from-version}"
TO_V="${3:?Missing to-version}"

echo "Migrating knowledge base from v${FROM_V} to v${TO_V}"
echo "Directory: ${KB_DIR}"

if [ "$FROM_V" -eq 1 ] && [ "$TO_V" -eq 1 ]; then
  echo "Already at v1. No migration needed."
  exit 0
fi

echo "No migration path from v${FROM_V} to v${TO_V}"
exit 1
