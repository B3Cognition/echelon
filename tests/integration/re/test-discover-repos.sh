#!/usr/bin/env bash
# Tests for discover-repos.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/../../../extension/scripts/bash/re" && pwd)"
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

assert_contains() {
    local label="$1"
    local needle="$2"
    local haystack="$3"
    if echo "$haystack" | grep -qF "$needle"; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label (expected to contain '$needle')"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_file_exists() {
    local label="$1"
    local path="$2"
    if [[ -f "$path" ]]; then
        echo "  PASS: $label"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "  FAIL: $label (missing: $path)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ---------- prerequisites ----------

if [[ ! -x "$DISCOVER_SCRIPT" ]]; then
    echo "FATAL: $DISCOVER_SCRIPT not found or not executable"
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "FATAL: jq is required"
    exit 1
fi

# ---------- Test 1: polyrepo detection ----------

echo ""
echo "=== Test 1: polyrepo detection ==="

TMPOUT1_DIR=$(mktemp -d)
TMPOUT1="$TMPOUT1_DIR/repos-manifest.json"
trap 'rm -rf "$TMPOUT1_DIR"' EXIT

(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$TMPOUT1")

REPO_COUNT=$(jq '.repo_count' "$TMPOUT1")
assert_eq "repo_count is 3" "3" "$REPO_COUNT"

MODE=$(jq -r '.mode' "$TMPOUT1")
assert_eq "mode is polyrepo" "polyrepo" "$MODE"

REPOS_LEN=$(jq '.repos | length' "$TMPOUT1")
assert_eq "discovers 3 repos" "3" "$REPOS_LEN"

# Should include repo-a, repo-b, repo-c
REPO_NAMES=$(jq -r '.repos[].name' "$TMPOUT1" | sort | tr '\n' ',' | sed 's/,$//')
assert_eq "repo names" "repo-a,repo-b,repo-c" "$REPO_NAMES"

WORKSPACE_MANIFEST1="$TMPOUT1_DIR/workspace-manifest.json"
assert_file_exists "workspace manifest written next to repos manifest" "$WORKSPACE_MANIFEST1"

WORKSPACE_SCHEMA_VERSION=$(jq '.schema_version' "$WORKSPACE_MANIFEST1")
assert_eq "workspace manifest schema_version is 1" "1" "$WORKSPACE_SCHEMA_VERSION"

WORKSPACE_GIT_ROLE=$(jq -r '.workspace.git_role' "$WORKSPACE_MANIFEST1")
assert_eq "workspace git_role is orchestration" "orchestration" "$WORKSPACE_GIT_ROLE"

WORKSPACE_SOURCES_LEN=$(jq '.sources | length' "$WORKSPACE_MANIFEST1")
assert_eq "workspace manifest has 3 sources" "3" "$WORKSPACE_SOURCES_LEN"

WORKSPACE_SOURCE_PATHS=$(jq -r '.sources[].path' "$WORKSPACE_MANIFEST1" | sort | tr '\n' ',' | sed 's/,$//')
assert_eq "workspace source paths" "repo-a,repo-b,repo-c" "$WORKSPACE_SOURCE_PATHS"

# ---------- Test 1b: canonical sources/ landing zone ----------

echo ""
echo "=== Test 1b: sources/ landing zone detection ==="

TMP_SOURCES_ROOT=$(mktemp -d)
mkdir -p "$TMP_SOURCES_ROOT/.specify" "$TMP_SOURCES_ROOT/specs"
mkdir -p "$TMP_SOURCES_ROOT/sources/spec-kit" "$TMP_SOURCES_ROOT/sources/ruler" "$TMP_SOURCES_ROOT/sources/agent-registry-starter"
printf '[project]\nname = "spec-kit"\n' > "$TMP_SOURCES_ROOT/sources/spec-kit/pyproject.toml"
printf '{"name":"ruler"}\n' > "$TMP_SOURCES_ROOT/sources/ruler/package.json"
printf '{"name":"agent-registry-starter"}\n' > "$TMP_SOURCES_ROOT/sources/agent-registry-starter/package.json"
TMPOUT1B_DIR=$(mktemp -d)
TMPOUT1B="$TMPOUT1B_DIR/repos-manifest.json"
trap 'rm -rf "$TMPOUT1_DIR" "$TMP_SOURCES_ROOT" "$TMPOUT1B_DIR"' EXIT

(cd "$TMP_SOURCES_ROOT" && "$DISCOVER_SCRIPT" "$TMPOUT1B")

MODE_1B=$(jq -r '.mode' "$TMPOUT1B")
assert_eq "sources/ workspace mode is polyrepo" "polyrepo" "$MODE_1B"

REPO_COUNT_1B=$(jq '.repo_count' "$TMPOUT1B")
assert_eq "sources/ workspace repo_count is 3" "3" "$REPO_COUNT_1B"

REPO_PATHS_1B=$(jq -r '.repos[].path' "$TMPOUT1B" | sed "s#^$TMP_SOURCES_ROOT/##" | sort | tr '\n' ',' | sed 's/,$//')
assert_eq "sources/ workspace repo paths" "sources/agent-registry-starter,sources/ruler,sources/spec-kit" "$REPO_PATHS_1B"

WORKSPACE_MANIFEST1B="$TMPOUT1B_DIR/workspace-manifest.json"
WORKSPACE_SOURCE_PATHS_1B=$(jq -r '.sources[].path' "$WORKSPACE_MANIFEST1B" | sort | tr '\n' ',' | sed 's/,$//')
assert_eq "sources/ workspace manifest source paths" "sources/agent-registry-starter,sources/ruler,sources/spec-kit" "$WORKSPACE_SOURCE_PATHS_1B"

# Should NOT include .specify or not-a-repo
NAMES_RAW=$(jq -r '.repos[].name' "$TMPOUT1")
if echo "$NAMES_RAW" | grep -qF ".specify"; then
    echo "  FAIL: .specify should be excluded"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    echo "  PASS: .specify excluded"
    PASS_COUNT=$((PASS_COUNT + 1))
fi

if echo "$NAMES_RAW" | grep -qF "not-a-repo"; then
    echo "  FAIL: not-a-repo should be excluded"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    echo "  PASS: not-a-repo excluded"
    PASS_COUNT=$((PASS_COUNT + 1))
fi

# ---------- Test 2: single-repo detection ----------

echo ""
echo "=== Test 2: single-repo detection ==="

TMPOUT2=$(mktemp)
# update trap to clean both
trap 'rm -rf "$TMPOUT1_DIR"; rm -f "$TMPOUT2"' EXIT

(cd "$FIXTURES_DIR/single-repo" && "$DISCOVER_SCRIPT" "$TMPOUT2")

# Single-repo fixture has markers at root, so root itself should be detected
REPO_COUNT2=$(jq '.repo_count' "$TMPOUT2")
assert_eq "repo_count is 1 for single-repo (root detected)" "1" "$REPO_COUNT2"

REPOS_LEN2=$(jq '.repos | length' "$TMPOUT2")
assert_eq "repos array has 1 entry" "1" "$REPOS_LEN2"

# Verify the detected repo is the root (name = "single-repo")
REPO_NAME2=$(jq -r '.repos[0].name' "$TMPOUT2")
assert_eq "single-repo root name" "single-repo" "$REPO_NAME2"

# ---------- Test 3: root field is absolute path ----------

echo ""
echo "=== Test 3: root field ==="

ROOT_VAL=$(jq -r '.root' "$TMPOUT1")
case "$ROOT_VAL" in
    /*)
        echo "  PASS: root is absolute path"
        PASS_COUNT=$((PASS_COUNT + 1))
        ;;
    *)
        echo "  FAIL: root should be absolute (got: $ROOT_VAL)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        ;;
esac

# ---------- Test 4: has_git detection ----------

echo ""
echo "=== Test 4: has_git detection ==="

# Create temporary .git dir in repo-b to simulate a git repo
mkdir -p "$FIXTURES_DIR/polyrepo/repo-b/.git"

TMPOUT4=$(mktemp)
trap 'rm -rf "$TMPOUT1_DIR"; rm -f "$TMPOUT2" "$TMPOUT4"; rm -rf "$FIXTURES_DIR/polyrepo/repo-b/.git"' EXIT

(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$TMPOUT4")

HAS_GIT_B=$(jq -r '.repos[] | select(.name == "repo-b") | .has_git' "$TMPOUT4")
assert_eq "repo-b has_git true" "true" "$HAS_GIT_B"

# Clean up the .git dir immediately
rm -rf "$FIXTURES_DIR/polyrepo/repo-b/.git"

# Simulate a checked-out Git submodule/worktree where .git is a file.
printf 'gitdir: ../.git/modules/repo-b\n' > "$FIXTURES_DIR/polyrepo/repo-b/.git"

TMPOUT4_FILE=$(mktemp)
trap 'rm -rf "$TMPOUT1_DIR"; rm -f "$TMPOUT2" "$TMPOUT4" "$TMPOUT4_FILE"; rm -f "$FIXTURES_DIR/polyrepo/repo-b/.git"' EXIT

(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$TMPOUT4_FILE")

HAS_GIT_FILE_B=$(jq -r '.repos[] | select(.name == "repo-b") | .has_git' "$TMPOUT4_FILE")
assert_eq "repo-b .git file has_git true" "true" "$HAS_GIT_FILE_B"

MARKERS_FILE_B=$(jq -r '.repos[] | select(.name == "repo-b") | .markers | join(",")' "$TMPOUT4_FILE")
assert_contains "repo-b .git file marker recorded" ".git" "$MARKERS_FILE_B"

rm -f "$FIXTURES_DIR/polyrepo/repo-b/.git"

# Re-run without .git to check repo-c has_git false
TMPOUT4b=$(mktemp)
trap 'rm -rf "$TMPOUT1_DIR"; rm -f "$TMPOUT2" "$TMPOUT4" "$TMPOUT4b"' EXIT

(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$TMPOUT4b")

HAS_GIT_C=$(jq -r '.repos[] | select(.name == "repo-c") | .has_git' "$TMPOUT4b")
assert_eq "repo-c has_git false" "false" "$HAS_GIT_C"

# ---------- Test 5: markers ----------

echo ""
echo "=== Test 5: markers ==="

MARKERS_A=$(jq -r '.repos[] | select(.name == "repo-a") | .markers | join(",")' "$TMPOUT1")
assert_contains "repo-a has package.json marker" "package.json" "$MARKERS_A"

MARKERS_B=$(jq -r '.repos[] | select(.name == "repo-b") | .markers | join(",")' "$TMPOUT1")
assert_contains "repo-b has CMakeLists.txt marker" "CMakeLists.txt" "$MARKERS_B"

# ---------- Test 6: source_file_count ----------

echo ""
echo "=== Test 6: source_file_count ==="

SRC_COUNT_A=$(jq '.repos[] | select(.name == "repo-a") | .source_file_count' "$TMPOUT1")
assert_gt "repo-a source_file_count > 0" 0 "$SRC_COUNT_A"

# ---------- Test 6b: wrapper repo with child repos remains polyrepo ----------

echo ""
echo "=== Test 6b: wrapper repo with child repos ==="

mkdir -p "$FIXTURES_DIR/polyrepo/.git"

TMPOUT6B=$(mktemp)
trap 'rm -rf "$TMPOUT1_DIR"; rm -f "$TMPOUT2" "$TMPOUT4" "$TMPOUT4b" "$TMPOUT4_FILE" "$TMPOUT6B"; rm -rf "$FIXTURES_DIR/polyrepo/.git"; rm -f "$FIXTURES_DIR/polyrepo/repo-b/.git"' EXIT

(cd "$FIXTURES_DIR/polyrepo" && "$DISCOVER_SCRIPT" "$TMPOUT6B")

MODE_6B=$(jq -r '.mode' "$TMPOUT6B")
assert_eq "wrapper with child repos is polyrepo" "polyrepo" "$MODE_6B"

REPO_COUNT_6B=$(jq '.repo_count' "$TMPOUT6B")
assert_eq "wrapper repo itself is not the only discovered repo" "3" "$REPO_COUNT_6B"

rm -rf "$FIXTURES_DIR/polyrepo/.git"

# ---------- Test 7: discovered_at field ----------

echo ""
echo "=== Test 7: discovered_at ISO 8601 ==="

DISCOVERED_AT=$(jq -r '.discovered_at' "$TMPOUT1")
# Basic check: should match pattern like 2026-03-26T...Z
if echo "$DISCOVERED_AT" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
    echo "  PASS: discovered_at is ISO 8601 UTC"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo "  FAIL: discovered_at not ISO 8601 (got: $DISCOVERED_AT)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ---------- Test 8: path has NO trailing slash (normalized) ----------

echo ""
echo "=== Test 8: path no trailing slash ==="

PATH_A=$(jq -r '.repos[] | select(.name == "repo-a") | .path' "$TMPOUT1")
case "$PATH_A" in
    */)
        echo "  FAIL: path should not have trailing slash (got: $PATH_A)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        ;;
    *)
        echo "  PASS: path has no trailing slash"
        PASS_COUNT=$((PASS_COUNT + 1))
        ;;
esac

# ---------- summary ----------

echo ""
echo "========================"
echo "Results: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "========================"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    exit 1
fi

exit 0
