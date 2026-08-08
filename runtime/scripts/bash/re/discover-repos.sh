#!/usr/bin/env bash
# Scan immediate children of CWD for project markers and output a JSON manifest.
# Usage: discover-repos.sh [output_file]
# Default output: .echelon/re/repos-manifest.json
set -euo pipefail

OUTPUT_FILE="${1:-${ECHELON_CFG_RE_OUTPUT_DIRECTORY:-.echelon/re}/repos-manifest.json}"

# ---------- prerequisites ----------

if ! command -v jq &>/dev/null; then
    echo "ERROR: jq is required but not installed." >&2
    exit 1
fi

# ---------- constants ----------

# Directories to skip (hidden dirs handled separately via leading-dot check)
SKIP_DIRS="node_modules .echelon dist build vendor __pycache__ .venv venv target"

# Exact-name project markers
EXACT_MARKERS="package.json pyproject.toml go.mod Cargo.toml pom.xml build.gradle build.gradle.kts CMakeLists.txt composer.json Gemfile setup.py Makefile"

# Source file extensions for counting
SOURCE_EXTS="py js ts java go rs rb php cs cpp c swift kt scala pas pl"

# ---------- helpers ----------

is_skipped() {
    local name="$1"
    # Skip hidden directories (start with dot)
    case "$name" in
        .*) return 0 ;;
    esac
    # Skip known non-project directories
    for skip in $SKIP_DIRS; do
        if [[ "$name" == "$skip" ]]; then
            return 0
        fi
    done
    return 1
}

count_source_files() {
    local dir="$1"
    # Single find with all extensions, pruning heavy directories for performance
    find "$dir" -maxdepth 5 \
        \( -name ".*" -o -name "node_modules" -o -name "vendor" -o -name "dist" -o -name "build" -o -name "__pycache__" -o -name ".venv" -o -name "venv" -o -name "target" \) -prune -o \
        -type f \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.java" -o -name "*.go" -o -name "*.rs" -o -name "*.rb" -o -name "*.php" -o -name "*.cs" -o -name "*.cpp" -o -name "*.c" -o -name "*.swift" -o -name "*.kt" -o -name "*.scala" -o -name "*.pas" -o -name "*.pl" \) -print 2>/dev/null | wc -l | tr -d ' '
}

# ---------- scan ----------

ROOT_DIR="$(pwd)"
REPOS_JSON="[]"
ROOT_IS_REPO=false
ROOT_HAS_NON_GIT_MARKER=false

# Helper to check if a directory has repo markers
check_markers() {
    local dir="$1"
    local found_markers=()
    local found_git=false

    if [[ -d "$dir/.git" || -f "$dir/.git" ]]; then
        found_git=true
        found_markers+=(".git")
    fi

    for marker in $EXACT_MARKERS; do
        [[ -f "$dir/$marker" ]] && found_markers+=("$marker")
    done

    for pattern in "*.sln" "*.dpr"; do
        for f in "$dir"/$pattern; do
            [[ -f "$f" ]] && found_markers+=("$(basename "$f")")
        done
    done

    [[ ${#found_markers[@]} -gt 0 ]] && return 0 || return 1
}

# First check if ROOT_DIR itself is a repo (single-repo layout)
if check_markers "$ROOT_DIR"; then
    ROOT_IS_REPO=true
fi

for marker in $EXACT_MARKERS; do
    if [[ -f "$ROOT_DIR/$marker" ]]; then
        ROOT_HAS_NON_GIT_MARKER=true
    fi
done
for pattern in "*.sln" "*.dpr"; do
    for f in "$ROOT_DIR"/$pattern; do
        [[ -f "$f" ]] && ROOT_HAS_NON_GIT_MARKER=true
    done
done

CHILD_ENTRIES=()
for child in "$ROOT_DIR"/*/; do
    [[ -d "$child" ]] || continue
    dir_name=$(basename "$child")
    is_skipped "$dir_name" && continue
    if check_markers "${child%/}"; then
        CHILD_ENTRIES+=("$child")
    fi
done

if [[ -d "$ROOT_DIR/sources" ]]; then
    for child in "$ROOT_DIR/sources"/*/; do
        [[ -d "$child" ]] || continue
        dir_name=$(basename "$child")
        is_skipped "$dir_name" && continue
        if check_markers "${child%/}"; then
            CHILD_ENTRIES+=("$child")
        fi
    done
fi

# Scan entries: a wrapper with only .git at root and child project repos is a polyrepo.
# A root with its own project markers remains single-repo unless explicitly analyzed as children.
SCAN_ENTRIES=()
if [[ "$ROOT_IS_REPO" == "true" && "$ROOT_HAS_NON_GIT_MARKER" == "true" ]]; then
    SCAN_ENTRIES=("$ROOT_DIR")
elif [[ ${#CHILD_ENTRIES[@]} -gt 0 ]]; then
    SCAN_ENTRIES=("${CHILD_ENTRIES[@]}")
elif [[ "$ROOT_IS_REPO" == "true" ]]; then
    SCAN_ENTRIES=("$ROOT_DIR")
else
    SCAN_ENTRIES=()
fi

for entry in "${SCAN_ENTRIES[@]}"; do
    [[ -d "$entry" ]] || continue

    dir_name=$(basename "$entry")

    # Apply skip rules only to child directories
    if [[ "$entry" != "$ROOT_DIR" ]]; then
        is_skipped "$dir_name" && continue
    fi

    markers=()
    has_git=false

    # Check for .git
    if [[ -d "$entry/.git" || -f "$entry/.git" ]]; then
        has_git=true
        markers+=(".git")
    fi

    # Check exact-name markers
    for marker in $EXACT_MARKERS; do
        if [[ -f "$entry/$marker" ]]; then
            markers+=("$marker")
        fi
    done

    # Check glob markers: *.sln, *.dpr
    for pattern in "*.sln" "*.dpr"; do
        for f in "$entry"/$pattern; do
            if [[ -f "$f" ]]; then
                markers+=("$(basename "$f")")
            fi
        done
    done

    # Count source files
    src_count=$(count_source_files "$entry")

    # Qualify: must have at least one project marker (or .git)
    # This avoids classifying ordinary source directories (e.g., src/) as repos
    marker_count=${#markers[@]}
    if [[ "$marker_count" -eq 0 ]]; then
        continue
    fi

    # Build markers JSON array
    markers_json="[]"
    if [[ "$marker_count" -gt 0 ]]; then
        markers_json=$(printf '%s\n' "${markers[@]}" | jq -R . | jq -s .)
    fi

    # Extract package identifiers for cross-repo dependency matching
    pkg_identifiers="[]"

    # NPM: package.json name field
    if [[ -f "$entry/package.json" ]]; then
        npm_name=$(jq -r '.name // empty' "$entry/package.json" 2>/dev/null || true)
        if [[ -n "$npm_name" ]]; then
            pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$npm_name" --arg type "npm" '. + [{id: $id, type: $type}]')
        fi
    fi

    # Go: go.mod module line
    if [[ -f "$entry/go.mod" ]]; then
        go_module=$(head -1 "$entry/go.mod" | sed -n 's/^module //p' | tr -d '\r' || true)
        if [[ -n "$go_module" ]]; then
            pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$go_module" --arg type "go" '. + [{id: $id, type: $type}]')
        fi
    fi

    # Python: pyproject.toml name or setup.py name
    # Use Python/tomllib for proper TOML parsing (avoids false positives from unrelated sections)
    if [[ -f "$entry/pyproject.toml" ]] && command -v python3 &>/dev/null; then
        py_name=$(python3 - "$entry/pyproject.toml" 2>/dev/null <<'PY' || true
import sys
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        sys.exit(0)

try:
    with open(sys.argv[1], "rb") as f:
        data = tomllib.load(f)
except Exception:
    sys.exit(0)

name = data.get("project", {}).get("name")
if not name:
    name = data.get("tool", {}).get("poetry", {}).get("name")

if isinstance(name, str):
    print(name)
PY
)
        if [[ -n "$py_name" ]]; then
            pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$py_name" --arg type "pip" '. + [{id: $id, type: $type}]')
        fi
    elif [[ -f "$entry/setup.py" ]]; then
        # Fallback: grep for setup.py (less reliable but no TOML parsing needed)
        py_name=$(grep -E 'name[[:space:]]*=' "$entry/setup.py" 2>/dev/null | head -1 | sed 's/.*name[ ]*=[ ]*["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/' || true)
        if [[ -n "$py_name" ]]; then
            pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$py_name" --arg type "pip" '. + [{id: $id, type: $type}]')
        fi
    fi

    # Build repo JSON object
    repo_json=$(jq -n \
        --arg name "$dir_name" \
        --arg path "${entry%/}" \
        --argjson has_git "$has_git" \
        --argjson markers "$markers_json" \
        --argjson source_file_count "$src_count" \
        --argjson pkg_identifiers "$pkg_identifiers" \
        '{name: $name, path: $path, has_git: $has_git, markers: $markers, source_file_count: $source_file_count, pkg_identifiers: $pkg_identifiers}')

    REPOS_JSON=$(echo "$REPOS_JSON" | jq --argjson repo "$repo_json" '. + [$repo]')
done

# ---------- build output ----------
# Mode is stored explicitly and also derivable from repo_count (>1 = polyrepo).

REPO_COUNT=$(echo "$REPOS_JSON" | jq 'length')
if [[ "$REPO_COUNT" -gt 1 ]]; then
    MODE="polyrepo"
else
    MODE="single"
fi
DISCOVERED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

OUTPUT_JSON=$(jq -n \
    --arg discovered_at "$DISCOVERED_AT" \
    --arg root "$ROOT_DIR" \
    --arg mode "$MODE" \
    --argjson repo_count "$REPO_COUNT" \
    --argjson repos "$REPOS_JSON" \
    '{discovered_at: $discovered_at, root: $root, mode: $mode, repo_count: $repo_count, repos: $repos}')

# ---------- write ----------

OUTPUT_DIR=$(dirname "$OUTPUT_FILE")
mkdir -p "$OUTPUT_DIR"

echo "$OUTPUT_JSON" > "$OUTPUT_FILE"

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required to write workspace-manifest.json." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
WORKSPACE_MANIFEST_FILE="$OUTPUT_DIR/workspace-manifest.json"
PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m echelon.workspace_model "$ROOT_DIR" "$WORKSPACE_MANIFEST_FILE"

echo "Discovered $REPO_COUNT repo(s) → $OUTPUT_FILE" >&2
