#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_NAME='@colbymchenry/codegraph'
CODEGRAPH_VERSION="${CODEGRAPH_VERSION:-latest}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
RUNTIME_DIR="$TMP_DIR/runtime"
PROJECT_DIR="$TMP_DIR/project"
OUTPUT_PATH="$TMP_DIR/codegraph-analysis.json"

mkdir -p "$RUNTIME_DIR" "$PROJECT_DIR"
cp "$ROOT/extension/scripts/node/re/codegraph-bridge.js" "$RUNTIME_DIR/"
cp "$ROOT/extension/scripts/node/re/codegraph-adapter.js" "$RUNTIME_DIR/"
printf '%s\n' \
  '{' \
  '  "private": true,' \
  "  \"dependencies\": { \"$PACKAGE_NAME\": \"$CODEGRAPH_VERSION\" }" \
  '}' > "$RUNTIME_DIR/package.json"

npm install --prefix "$RUNTIME_DIR" --ignore-scripts --no-audit --no-fund >/dev/null
ACTUAL_VERSION="$(node -e "console.log(require('$RUNTIME_DIR/node_modules/$PACKAGE_NAME/package.json').version)")"
printf 'Testing CodeGraph %s (requested %s)\n' "$ACTUAL_VERSION" "$CODEGRAPH_VERSION"

printf '%s\n' \
  'export function latestCompatibilityFixture(): string {' \
  '  return "ready";' \
  '}' > "$PROJECT_DIR/example.ts"

node "$RUNTIME_DIR/codegraph-bridge.js" analyze \
  --repo-path "$PROJECT_DIR" \
  --output-path "$OUTPUT_PATH" \
  --languages typescript

node - "$OUTPUT_PATH" <<'NODE'
const fs = require('fs');
const analysis = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (!analysis.symbols.some((symbol) => symbol.name === 'latestCompatibilityFixture')) {
  throw new Error('latest CodeGraph did not analyze the fixture symbol');
}
if (analysis.index_stats.index_state !== 'ready') {
  throw new Error(`unexpected index state: ${analysis.index_stats.index_state}`);
}
NODE
