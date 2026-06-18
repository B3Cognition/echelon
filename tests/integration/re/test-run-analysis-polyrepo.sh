#!/usr/bin/env bash
# Tests for run-analysis.sh polyrepo mode
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/../../../extension/scripts/bash/re" && pwd)"
RUN_ANALYSIS="$SCRIPTS_ROOT/run-analysis.sh"
DISCOVER_SCRIPT="$SCRIPTS_ROOT/discover-repos.sh"
FIXTURES_DIR="$SCRIPT_DIR/fixtures"

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

assert_file_not_exists() {
    local label="$1"
    local filepath="$2"
    if [[ ! -f "$filepath" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label (file should not exist: $filepath)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_path_not_exists() {
    local label="$1"
    local path="$2"
    if [[ ! -e "$path" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label (path should not exist: $path)"
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

if [[ ! -x "$RUN_ANALYSIS" ]]; then
    echo "FATAL: $RUN_ANALYSIS not found or not executable"
    exit 1
fi

if [[ ! -x "$DISCOVER_SCRIPT" ]]; then
    echo "FATAL: $DISCOVER_SCRIPT not found or not executable"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "FATAL: jq is required"
    exit 1
fi

# ---------- Test 1: Single-repo mode (no manifest arg) — backward compat ----------

echo ""
echo "=== Test 1: single-repo mode (no manifest arg) ==="

TMPDIR1=$(mktemp -d)
trap 'rm -rf "$TMPDIR1"' EXIT

(cd "$FIXTURES_DIR/single-repo" && "$RUN_ANALYSIS" "$TMPDIR1" 2>/dev/null)

assert_file_exists "analysis.json at root output dir" "$TMPDIR1/analysis.json"
assert_file_exists "structure.json at root output dir" "$TMPDIR1/structure.json"
assert_file_exists "dependencies.json at root output dir" "$TMPDIR1/dependencies.json"
if [[ -f "$TMPDIR1/codegraph-analysis.json" ]]; then
    assert_file_exists "codegraph-summary.json at root output dir" "$TMPDIR1/codegraph-summary.json"
    assert_json_field "codegraph summary has index_state" "$TMPDIR1/codegraph-summary.json" '.index_state' "ready"
fi
assert_path_not_exists "single-repo fixture remains free of .codegraph" "$FIXTURES_DIR/single-repo/.codegraph"

# Should NOT have any subdirectories with analysis.json
SUBDIRS_WITH_ANALYSIS=$(find "$TMPDIR1" -mindepth 2 -name "analysis.json" 2>/dev/null | wc -l | tr -d ' ')
assert_eq "no subdirectory analysis.json files" "0" "$SUBDIRS_WITH_ANALYSIS"

# ---------- Test 2: Single-repo mode (manifest says single) — same behavior ----------

echo ""
echo "=== Test 2: single-repo mode (manifest says single) ==="

TMPDIR2=$(mktemp -d)
MANIFEST2=$(mktemp)
trap 'rm -rf "$TMPDIR1" "$TMPDIR2"; rm -f "$MANIFEST2"' EXIT

# Generate manifest from single-repo fixture (root itself is the repo)
(cd "$FIXTURES_DIR/single-repo" && "$DISCOVER_SCRIPT" "$MANIFEST2" 2>/dev/null)

# Verify manifest repo_count is 1 (root detected as repo)
MANIFEST2_COUNT=$(jq -r '.repo_count' "$MANIFEST2")
assert_eq "manifest repo_count is 1 (root is repo)" "1" "$MANIFEST2_COUNT"

(cd "$FIXTURES_DIR/single-repo" && "$RUN_ANALYSIS" "$TMPDIR2" "$MANIFEST2" 2>/dev/null)

assert_file_exists "analysis.json at root output dir" "$TMPDIR2/analysis.json"
assert_path_not_exists "single-repo manifest run remains free of .codegraph" "$FIXTURES_DIR/single-repo/.codegraph"

# Should have 1 subdirectory (single-repo/) with analysis.json
SUBDIRS_WITH_ANALYSIS2=$(find "$TMPDIR2" -mindepth 2 -name "analysis.json" 2>/dev/null | wc -l | tr -d ' ')
assert_eq "one subdirectory analysis.json (root repo)" "1" "$SUBDIRS_WITH_ANALYSIS2"

# ---------- Test 3: Polyrepo mode ----------

echo ""
echo "=== Test 3: polyrepo mode ==="

TMPDIR3=$(mktemp -d)
RE_OUTPUT_DIR="$TMPDIR3"
MANIFEST3=$(mktemp)
trap 'rm -rf "$TMPDIR1" "$TMPDIR2" "$TMPDIR3"; rm -f "$MANIFEST2" "$MANIFEST3"' EXIT

# Generate manifest from polyrepo fixture
(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$MANIFEST3" 2>/dev/null)

# Verify manifest repo_count is 3 (polyrepo)
MANIFEST3_COUNT=$(jq -r '.repo_count' "$MANIFEST3")
assert_eq "manifest repo_count is 3" "3" "$MANIFEST3_COUNT"

# Run analysis in polyrepo mode
(cd "$FIXTURES_DIR/polyrepo" && "$RUN_ANALYSIS" "$RE_OUTPUT_DIR" "$MANIFEST3" 2>/dev/null)

assert_file_exists "workspace-manifest.json copied to output" "$RE_OUTPUT_DIR/workspace-manifest.json"
assert_json_field "workspace manifest has 3 sources" "$RE_OUTPUT_DIR/workspace-manifest.json" '.sources | length' "3"
assert_path_not_exists "analysis output does not include workspace .specify" "$RE_OUTPUT_DIR/.specify"

# Per-repo output directories with analysis.json
assert_file_exists "repo-a/analysis.json exists" "$RE_OUTPUT_DIR/repo-a/analysis.json"
assert_file_exists "repo-b/analysis.json exists" "$RE_OUTPUT_DIR/repo-b/analysis.json"
assert_file_exists "repo-c/analysis.json exists" "$RE_OUTPUT_DIR/repo-c/analysis.json"
assert_path_not_exists "polyrepo fixture remains free of .codegraph" "$FIXTURES_DIR/polyrepo/.codegraph"

# cross-repo.json at root
assert_file_exists "cross-repo.json exists" "$RE_OUTPUT_DIR/cross-repo.json"

# Root-level aggregate analysis.json
assert_file_exists "root-level analysis.json" "$RE_OUTPUT_DIR/analysis.json"
assert_json_field "root analysis has metadata" "$RE_OUTPUT_DIR/analysis.json" '.metadata | type' "object"
assert_json_field "root analysis has repo_count" "$RE_OUTPUT_DIR/analysis.json" '.metadata.repo_count' "3"
assert_json_field "root analysis has repos array" "$RE_OUTPUT_DIR/analysis.json" '.repos | type' "array"
assert_json_field "root analysis records preferred manifest" "$RE_OUTPUT_DIR/analysis.json" '.manifest_path' "workspace-manifest.json"

# Per-repo analysis.json should have repo_name field
assert_json_field "repo-a analysis has repo_name" "$RE_OUTPUT_DIR/repo-a/analysis.json" '.repo_name' "repo-a"
assert_json_field "repo-b analysis has repo_name" "$RE_OUTPUT_DIR/repo-b/analysis.json" '.repo_name' "repo-b"
assert_json_field "repo-c analysis has repo_name" "$RE_OUTPUT_DIR/repo-c/analysis.json" '.repo_name' "repo-c"

# Per-repo analysis.json should have expected structure fields
assert_json_field "repo-a has metadata" "$RE_OUTPUT_DIR/repo-a/analysis.json" '.metadata | type' "object"
assert_json_field "repo-a has structure" "$RE_OUTPUT_DIR/repo-a/analysis.json" '.structure | type' "object"

# ---------- Test 4: Legacy repos-manifest fallback ----------

echo ""
echo "=== Test 4: legacy repos-manifest fallback ==="

TMPDIR4=$(mktemp -d)
MANIFEST4_DIR=$(mktemp -d)
MANIFEST4="$MANIFEST4_DIR/repos-manifest.json"
trap 'rm -rf "$TMPDIR1" "$TMPDIR2" "$TMPDIR3" "$TMPDIR4" "$MANIFEST4_DIR"; rm -f "$MANIFEST2" "$MANIFEST3"' EXIT

(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$MANIFEST4" 2>/dev/null)
rm -f "$MANIFEST4_DIR/workspace-manifest.json"

(cd "$FIXTURES_DIR/polyrepo" && "$RUN_ANALYSIS" "$TMPDIR4" "$MANIFEST4" 2>/dev/null)

assert_file_exists "legacy repo-a/analysis.json exists" "$TMPDIR4/repo-a/analysis.json"
assert_file_exists "legacy repo-b/analysis.json exists" "$TMPDIR4/repo-b/analysis.json"
assert_file_exists "legacy repo-c/analysis.json exists" "$TMPDIR4/repo-c/analysis.json"
assert_file_exists "legacy repos-manifest.json copied to output" "$TMPDIR4/repos-manifest.json"
assert_file_not_exists "legacy workspace-manifest.json absent" "$TMPDIR4/workspace-manifest.json"
assert_json_field "legacy root analysis records repos manifest" "$TMPDIR4/analysis.json" '.manifest_path' "repos-manifest.json"

# ---------- Test 5: Workspace manifest drives cross-repo extraction ----------

echo ""
echo "=== Test 5: workspace manifest drives cross-repo extraction ==="

TMPROOT5=$(mktemp -d)
TMPDIR5=$(mktemp -d)
MANIFEST5_DIR=$(mktemp -d)
MANIFEST5="$MANIFEST5_DIR/repos-manifest.json"
trap 'rm -rf "$TMPDIR1" "$TMPDIR2" "$TMPDIR3" "$TMPDIR4" "$TMPROOT5" "$TMPDIR5" "$MANIFEST4_DIR" "$MANIFEST5_DIR"; rm -f "$MANIFEST2" "$MANIFEST3"' EXIT

cat > "$TMPROOT5/package.json" <<'JSON'
{"name": "workspace-wrapper"}
JSON
mkdir -p "$TMPROOT5/app-a/src" "$TMPROOT5/lib/src"
cat > "$TMPROOT5/app-a/package.json" <<'JSON'
{"name": "app-a", "dependencies": {"@scope/contracts": "workspace:*"}}
JSON
cat > "$TMPROOT5/app-a/src/index.ts" <<'TS'
import "@scope/contracts";
TS
cat > "$TMPROOT5/lib/package.json" <<'JSON'
{"name": "@scope/contracts"}
JSON
cat > "$TMPROOT5/lib/src/index.ts" <<'TS'
export const value = 1;
TS

(cd "$TMPROOT5" && "$DISCOVER_SCRIPT" "$MANIFEST5" 2>/dev/null)

assert_json_field "legacy manifest sees wrapper root" "$MANIFEST5" '.repo_count' "1"
assert_json_field "workspace manifest sees child sources" "$MANIFEST5_DIR/workspace-manifest.json" '.sources | length' "2"

(cd "$TMPROOT5" && "$RUN_ANALYSIS" "$TMPDIR5" "$MANIFEST5" 2>/dev/null)

assert_file_exists "workspace-driven app-a analysis exists" "$TMPDIR5/app-a/analysis.json"
assert_file_exists "workspace-driven lib analysis exists" "$TMPDIR5/lib/analysis.json"
assert_json_field "workspace-driven root analysis repo_count" "$TMPDIR5/analysis.json" '.metadata.repo_count' "2"
assert_json_field "workspace-driven cross-repo repo_count" "$TMPDIR5/cross-repo.json" '.repo_count' "2"
assert_json_field "workspace-driven compatibility manifest repo_count" "$TMPDIR5/repos-manifest.json" '.repo_count' "2"
assert_json_field "workspace-driven package identifier derived" "$TMPDIR5/repos-manifest.json" '.repos[] | select(.name == "lib") | .pkg_identifiers[0].id' "@scope/contracts"
assert_json_field "workspace-driven dependency link detected" "$TMPDIR5/cross-repo.json" '.dependency_links | length' "1"

# ---------- summary ----------

echo ""
echo "========================"
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi

exit 0
