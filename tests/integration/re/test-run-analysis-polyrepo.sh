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
MANIFEST3=$(mktemp)
trap 'rm -rf "$TMPDIR1" "$TMPDIR2" "$TMPDIR3"; rm -f "$MANIFEST2" "$MANIFEST3"' EXIT

# Generate manifest from polyrepo fixture
(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$MANIFEST3" 2>/dev/null)

# Verify manifest repo_count is 3 (polyrepo)
MANIFEST3_COUNT=$(jq -r '.repo_count' "$MANIFEST3")
assert_eq "manifest repo_count is 3" "3" "$MANIFEST3_COUNT"

# Run analysis in polyrepo mode
(cd "$FIXTURES_DIR/polyrepo" && "$RUN_ANALYSIS" "$TMPDIR3" "$MANIFEST3" 2>/dev/null)

# Per-repo output directories with analysis.json
assert_file_exists "repo-a/analysis.json exists" "$TMPDIR3/repo-a/analysis.json"
assert_file_exists "repo-b/analysis.json exists" "$TMPDIR3/repo-b/analysis.json"
assert_file_exists "repo-c/analysis.json exists" "$TMPDIR3/repo-c/analysis.json"
assert_path_not_exists "polyrepo fixture remains free of .codegraph" "$FIXTURES_DIR/polyrepo/.codegraph"

# cross-repo.json at root
assert_file_exists "cross-repo.json exists" "$TMPDIR3/cross-repo.json"

# Root-level aggregate analysis.json
assert_file_exists "root-level analysis.json" "$TMPDIR3/analysis.json"
assert_json_field "root analysis has metadata" "$TMPDIR3/analysis.json" '.metadata | type' "object"
assert_json_field "root analysis has repo_count" "$TMPDIR3/analysis.json" '.metadata.repo_count' "3"
assert_json_field "root analysis has repos array" "$TMPDIR3/analysis.json" '.repos | type' "array"

# Per-repo analysis.json should have repo_name field
assert_json_field "repo-a analysis has repo_name" "$TMPDIR3/repo-a/analysis.json" '.repo_name' "repo-a"
assert_json_field "repo-b analysis has repo_name" "$TMPDIR3/repo-b/analysis.json" '.repo_name' "repo-b"
assert_json_field "repo-c analysis has repo_name" "$TMPDIR3/repo-c/analysis.json" '.repo_name' "repo-c"

# Per-repo analysis.json should have expected structure fields
assert_json_field "repo-a has metadata" "$TMPDIR3/repo-a/analysis.json" '.metadata | type' "object"
assert_json_field "repo-a has structure" "$TMPDIR3/repo-a/analysis.json" '.structure | type' "object"

# ---------- summary ----------

echo ""
echo "========================"
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi

exit 0
