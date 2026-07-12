#!/usr/bin/env bash
# Tests for extract-cross-repo.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/../../../extension/scripts/bash/re" && pwd)"
EXTRACT_CROSS_REPO="$SCRIPTS_ROOT/extract-cross-repo.sh"

PASS_COUNT=0
FAIL_COUNT=0

# ---------- helpers ----------

assert_eq() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label"
        echo "    expected: $expected"
        echo "    actual:   $actual"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_gt() {
    local label="$1"
    local threshold="$2"
    local actual="$3"
    if [[ "$actual" -gt "$threshold" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label (expected >$threshold, got $actual)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_file_exists() {
    local label="$1"
    local filepath="$2"
    if [[ -f "$filepath" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label (file not found: $filepath)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_json_field() {
    local label="$1"
    local file="$2"
    local query="$3"
    local expected="$4"
    local actual
    actual=$(jq -r "$query" "$file" 2>/dev/null || echo "__JQ_ERROR__")
    if [[ "$actual" == "$expected" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label"
        echo "    expected: $expected"
        echo "    actual:   $actual"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ---------- prerequisites ----------

if [[ ! -x "$EXTRACT_CROSS_REPO" ]]; then
    echo "FATAL: $EXTRACT_CROSS_REPO not found or not executable"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "FATAL: jq is required"
    exit 1
fi

# ---------- Setup: create mock data ----------

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Create mock per-repo output directories with structure.json and dependencies.json

# repo-alpha: TypeScript project with npm deps
mkdir -p "$TMPDIR/repo-alpha"
cat > "$TMPDIR/repo-alpha/structure.json" <<'STRUCT'
{
  "file_counts": { "ts": 10, "tsx": 5, "json": 2 },
  "entry_points": ["package.json"],
  "total_files": 17
}
STRUCT
cat > "$TMPDIR/repo-alpha/dependencies.json" <<'DEPS'
[
  {
    "type": "npm",
    "file": "package.json",
    "dependencies": {
      "express": "^4.18.0",
      "repo-beta": "^1.0.0",
      "@company/shared-lib": "^2.0.0"
    },
    "devDependencies": {}
  }
]
DEPS

# repo-beta: TypeScript + Python project with npm and pip deps
mkdir -p "$TMPDIR/repo-beta"
cat > "$TMPDIR/repo-beta/structure.json" <<'STRUCT'
{
  "file_counts": { "ts": 8, "py": 12, "json": 3 },
  "entry_points": ["package.json"],
  "total_files": 23
}
STRUCT
cat > "$TMPDIR/repo-beta/dependencies.json" <<'DEPS'
[
  {
    "type": "npm",
    "file": "package.json",
    "dependencies": {
      "lodash": "^4.17.0"
    },
    "devDependencies": {}
  },
  {
    "type": "pip",
    "file": "requirements.txt",
    "packages": ["flask==2.0.0", "repo-gamma>=1.0"]
  }
]
DEPS

# repo-gamma: Python-only project
mkdir -p "$TMPDIR/repo-gamma"
cat > "$TMPDIR/repo-gamma/structure.json" <<'STRUCT'
{
  "file_counts": { "py": 20, "yml": 2 },
  "entry_points": ["pyproject.toml"],
  "total_files": 22
}
STRUCT
cat > "$TMPDIR/repo-gamma/dependencies.json" <<'DEPS'
[
  {
    "type": "pip",
    "file": "requirements.txt",
    "packages": ["requests>=2.28", "pydantic>=1.10"]
  }
]
DEPS

# Create a manifest pointing to these repos
MANIFEST="$TMPDIR/manifest.json"
cat > "$MANIFEST" <<MANIFEST_JSON
{
  "discovered_at": "2026-03-26T00:00:00Z",
  "root": "$TMPDIR",
  "repo_count": 3,
  "repos": [
    { "name": "repo-alpha", "path": "$TMPDIR/repo-alpha/", "has_git": false, "markers": ["package.json"], "source_file_count": 15 },
    { "name": "repo-beta", "path": "$TMPDIR/repo-beta/", "has_git": false, "markers": ["package.json"], "source_file_count": 20 },
    { "name": "repo-gamma", "path": "$TMPDIR/repo-gamma/", "has_git": false, "markers": ["pyproject.toml"], "source_file_count": 20 }
  ]
}
MANIFEST_JSON

# ---------- Test 1: Produces cross-repo.json ----------

echo ""
echo "=== Test 1: produces cross-repo.json ==="

"$EXTRACT_CROSS_REPO" "$TMPDIR" "$MANIFEST" 2>/dev/null

assert_file_exists "cross-repo.json created" "$TMPDIR/cross-repo.json"

# ---------- Test 2: repo_count is correct ----------

echo ""
echo "=== Test 2: repo_count ==="

assert_json_field "repo_count is 3" "$TMPDIR/cross-repo.json" '.repo_count' "3"

# ---------- Test 3: shared_tech has entries ----------

echo ""
echo "=== Test 3: shared_tech ==="

SHARED_TECH_KEYS=$(jq '.shared_tech | keys | length' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "0")
assert_gt "shared_tech has entries" 0 "$SHARED_TECH_KEYS"

# TypeScript should be shared between repo-alpha and repo-beta
TS_REPOS=$(jq -r '.shared_tech.typescript | sort | join(",")' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "")
assert_eq "typescript shared by alpha and beta" "repo-alpha,repo-beta" "$TS_REPOS"

# Python should be shared between repo-beta and repo-gamma
PY_REPOS=$(jq -r '.shared_tech.python | sort | join(",")' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "")
assert_eq "python shared by beta and gamma" "repo-beta,repo-gamma" "$PY_REPOS"

# ---------- Test 4: analyzed_at timestamp ----------

echo ""
echo "=== Test 4: analyzed_at timestamp ==="

ANALYZED_AT=$(jq -r '.analyzed_at' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "")
if echo "$ANALYZED_AT" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
    echo "  PASS: analyzed_at is ISO 8601 UTC"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "  FAIL: analyzed_at not ISO 8601 (got: $ANALYZED_AT)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ---------- Test 5: dependency_links ----------

echo ""
echo "=== Test 5: dependency_links ==="

DEP_LINKS_COUNT=$(jq '.dependency_links | length' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "0")
assert_gt "dependency_links has entries" 0 "$DEP_LINKS_COUNT"

# repo-alpha depends on repo-beta (via npm)
ALPHA_TO_BETA=$(jq '[.dependency_links[] | select(.from == "repo-alpha" and .to == "repo-beta")] | length' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "0")
assert_gt "repo-alpha -> repo-beta link found" 0 "$ALPHA_TO_BETA"

# repo-beta depends on repo-gamma (via pip)
BETA_TO_GAMMA=$(jq '[.dependency_links[] | select(.from == "repo-beta" and .to == "repo-gamma")] | length' "$TMPDIR/cross-repo.json" 2>/dev/null || echo "0")
assert_gt "repo-beta -> repo-gamma link found" 0 "$BETA_TO_GAMMA"

# ---------- Test 6: potential_integrations is empty array ----------

echo ""
echo "=== Test 6: potential_integrations ==="

assert_json_field "potential_integrations is empty array" "$TMPDIR/cross-repo.json" '.potential_integrations | length' "0"
assert_json_field "potential_integrations is array type" "$TMPDIR/cross-repo.json" '.potential_integrations | type' "array"

# ---------- Test 7: Reads analyses from an explicit source output root ----------

echo ""
echo "=== Test 7: explicit source output root ==="

SCOPED_OUTPUT="$TMPDIR/scoped-output"
SCOPED_SOURCES="$SCOPED_OUTPUT/sources"
mkdir -p "$SCOPED_SOURCES"
cp -R "$TMPDIR/repo-alpha" "$TMPDIR/repo-beta" "$TMPDIR/repo-gamma" "$SCOPED_SOURCES/"

"$EXTRACT_CROSS_REPO" "$SCOPED_OUTPUT" "$MANIFEST" "$SCOPED_SOURCES" 2>/dev/null

assert_file_exists "source-scoped cross-repo.json created" "$SCOPED_OUTPUT/cross-repo.json"
assert_json_field "source-scoped dependency links found" "$SCOPED_OUTPUT/cross-repo.json" '.dependency_links | length' "2"
assert_json_field "source-scoped shared technology found" "$SCOPED_OUTPUT/cross-repo.json" '.shared_tech.typescript | length' "2"

# ---------- summary ----------

echo ""
echo "========================"
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi

exit 0
