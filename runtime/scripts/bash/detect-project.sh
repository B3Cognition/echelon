#!/usr/bin/env bash
# detect-project.sh — Detect greenfield vs brownfield
# Usage: detect-project.sh [path]
# Returns: "greenfield" or "brownfield" to stdout

set -euo pipefail

TARGET_DIR="${1:-.}"

SOURCE_COUNT=$(find "$TARGET_DIR" \
  -type f \
  \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.java" \
     -o -name "*.go" -o -name "*.rs" -o -name "*.rb" -o -name "*.php" \
     -o -name "*.cs" -o -name "*.cpp" -o -name "*.c" -o -name "*.swift" \
     -o -name "*.kt" -o -name "*.scala" -o -name "*.pas" -o -name "*.pl" \) \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/vendor/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "*/.echelon/*" \
  2>/dev/null | wc -l | tr -d ' ')

if [ "$SOURCE_COUNT" -gt 5 ]; then
  echo "brownfield"
else
  echo "greenfield"
fi
