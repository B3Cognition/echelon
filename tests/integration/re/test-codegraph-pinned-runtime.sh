#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CODEGRAPH_NODE_DIR="$ROOT/runtime/scripts/node/codegraph"
PACKAGE_NAME='@colbymchenry/codegraph'
EXPECTED_VERSION='1.4.1'

npm ci --prefix "$CODEGRAPH_NODE_DIR" --ignore-scripts --no-audit --no-fund >/dev/null

ACTUAL_VERSION="$(node -e "console.log(require('$CODEGRAPH_NODE_DIR/node_modules/$PACKAGE_NAME/package.json').version)")"
[[ "$ACTUAL_VERSION" == "$EXPECTED_VERSION" ]]

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
PROJECT_DIR="$TMP_DIR/project"
OUTPUT_PATH="$TMP_DIR/codegraph-analysis.json"
mkdir -p "$PROJECT_DIR"

printf '%s\n' \
  'export function greet(name: string): string {' \
  '  return `hello ${name}`;' \
  '}' > "$PROJECT_DIR/example.ts"

node "$CODEGRAPH_NODE_DIR/codegraph-bridge.js" analyze \
  --repo-path "$PROJECT_DIR" \
  --output-path "$OUTPUT_PATH" \
  --languages typescript

node - "$OUTPUT_PATH" "$PROJECT_DIR" <<'NODE'
const fs = require('fs');
const path = require('path');
const [outputPath, projectDir] = process.argv.slice(2);
const analysis = JSON.parse(fs.readFileSync(outputPath, 'utf8'));

if (analysis.repo_path !== fs.realpathSync(projectDir)) {
  throw new Error(`analysis used unexpected repository path: ${analysis.repo_path}`);
}
if (!analysis.symbols.some((symbol) => symbol.name === 'greet')) {
  throw new Error('analysis did not include the fixture function');
}
if (analysis.index_stats.index_state !== 'ready') {
  throw new Error(`unexpected index state: ${analysis.index_stats.index_state}`);
}
if (!path.isAbsolute(outputPath)) {
  throw new Error('test output path must be absolute');
}
NODE
