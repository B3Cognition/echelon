#!/usr/bin/env bash
# Extract cross-repo integration map from per-repo analysis artifacts.
# Usage: extract-cross-repo.sh OUTPUT_DIR MANIFEST_PATH [SOURCE_OUTPUT_ROOT]
set -euo pipefail

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

OUTPUT_DIR="${1:?Usage: extract-cross-repo.sh OUTPUT_DIR MANIFEST_PATH [SOURCE_OUTPUT_ROOT]}"
MANIFEST_PATH="${2:?Usage: extract-cross-repo.sh OUTPUT_DIR MANIFEST_PATH [SOURCE_OUTPUT_ROOT]}"
SOURCE_OUTPUT_ROOT="${3:-$OUTPUT_DIR}"

if [[ ! -f "$MANIFEST_PATH" ]]; then
    echo "Error: manifest file not found: $MANIFEST_PATH" >&2
    exit 1
fi

echo "Extracting cross-repo integration map..." >&2

# Read repo names from manifest
REPO_NAMES=$(jq -r '.repos[].name' "$MANIFEST_PATH")
REPO_COUNT=$(jq '.repos | length' "$MANIFEST_PATH")

# ---------- 1. Shared technology ----------
# Map file extensions to language names, then build language -> [repo names]

# We'll build the shared_tech JSON incrementally
SHARED_TECH="{}"

for repo_name in $REPO_NAMES; do
    STRUCTURE_FILE="$SOURCE_OUTPUT_ROOT/$repo_name/structure.json"
    if [[ ! -f "$STRUCTURE_FILE" ]]; then
        continue
    fi

    # Extract extension keys from file_counts
    EXTENSIONS=$(jq -r '.file_counts | keys[]' "$STRUCTURE_FILE" 2>/dev/null || true)

    # Check if repo has C++ family extensions (for .h header classification)
    HAS_CPP_FAMILY=0
    if printf '%s\n' "$EXTENSIONS" | grep -Eq '^(cpp|cxx|cc|hpp|hh|hxx)$'; then
        HAS_CPP_FAMILY=1
    fi

    # Collect (lang, repo) pairs to reduce jq calls
    LANG_PAIRS=""
    for ext in $EXTENSIONS; do
        lang=""
        case "$ext" in
            ts|tsx)   lang="typescript" ;;
            js|jsx)   lang="javascript" ;;
            py)       lang="python" ;;
            go)       lang="go" ;;
            rs)       lang="rust" ;;
            java)     lang="java" ;;
            kt)       lang="kotlin" ;;
            cs)       lang="csharp" ;;
            c)        lang="c" ;;
            h)        if [[ "$HAS_CPP_FAMILY" -eq 1 ]]; then lang="cpp"; else lang="c"; fi ;;
            cpp|cxx|cc|hpp|hh|hxx) lang="cpp" ;;
            rb)       lang="ruby" ;;
            php)      lang="php" ;;
            swift)    lang="swift" ;;
            pas)      lang="delphi" ;;
            pl|pm)    lang="perl" ;;
            *)        continue ;;
        esac
        LANG_PAIRS="$LANG_PAIRS$lang $repo_name"$'\n'
    done

    # Single jq call per repo to update SHARED_TECH
    if [[ -n "$LANG_PAIRS" ]]; then
        SHARED_TECH=$(printf '%s' "$LANG_PAIRS" | jq -R --argjson tech "$SHARED_TECH" '
            split(" ") | select(length == 2) | {lang: .[0], repo: .[1]}
        ' | jq -s --argjson tech "$SHARED_TECH" '
            reduce .[] as $pair ($tech;
                if .[$pair.lang] then
                    .[$pair.lang] += [$pair.repo] | .[$pair.lang] |= unique
                else
                    .[$pair.lang] = [$pair.repo]
                end
            )
        ')
    fi
done

# ---------- 2. Dependency cross-references ----------

DEPENDENCY_LINKS="[]"

# Build lookup map: package identifier -> repo name
# This allows matching deps like "@company/shared-utils" to repo "shared-utils"
PKG_ID_TO_REPO="{}"
for repo_name in $REPO_NAMES; do
    # Add repo name itself as an identifier (fallback)
    PKG_ID_TO_REPO=$(echo "$PKG_ID_TO_REPO" | jq --arg id "$repo_name" --arg repo "$repo_name" '.[$id] = $repo')

    # Add package identifiers from manifest (handles both object {id:...} and plain string formats)
    REPO_IDENTIFIERS=$(jq -r --arg name "$repo_name" '
        .repos[]
        | select(.name == $name)
        | .pkg_identifiers[]?
        | if type == "object" then .id else . end
        | select(. != null and . != "")
    ' "$MANIFEST_PATH" 2>/dev/null || true)
    for pkg_id in $REPO_IDENTIFIERS; do
        [[ -z "$pkg_id" || "$pkg_id" == "null" ]] && continue
        PKG_ID_TO_REPO=$(echo "$PKG_ID_TO_REPO" | jq --arg id "$pkg_id" --arg repo "$repo_name" '.[$id] = $repo')
    done
done

# Helper: check if dependency matches any repo (by package id or partial repo name match)
# Note: dep_type is accepted for future type-specific matching rules (e.g., npm scoped packages
# vs go modules) but currently uses the same matching logic for all types.
match_dep_to_repo() {
    local dep_name="$1"
    local dep_type="$2"  # Reserved for type-specific matching (npm, pip, go, etc.)
    local source_repo="$3"
    local dep_lower matched_repo other_lower

    dep_lower=$(echo "$dep_name" | tr '[:upper:]' '[:lower:]')

    # First: exact match against package identifiers
    matched_repo=$(echo "$PKG_ID_TO_REPO" | jq -r --arg dep "$dep_name" '.[$dep] // empty' 2>/dev/null || true)
    if [[ -n "$matched_repo" && "$matched_repo" != "$source_repo" ]]; then
        echo "$matched_repo"
        return
    fi

    # Second: partial match (e.g., "@company/shared-utils" contains "shared-utils")
    for other_repo in $REPO_NAMES; do
        [[ "$other_repo" == "$source_repo" ]] && continue
        other_lower=$(echo "$other_repo" | tr '[:upper:]' '[:lower:]')
        if echo "$dep_lower" | grep -qiF "$other_lower"; then
            echo "$other_repo"
            return
        fi
    done
}

for repo_name in $REPO_NAMES; do
    DEPS_FILE="$SOURCE_OUTPUT_ROOT/$repo_name/dependencies.json"
    if [[ ! -f "$DEPS_FILE" ]]; then
        continue
    fi

    # Check npm dependencies
    NPM_DEP_NAMES=$(jq -r '.[] | select(.type == "npm") | .dependencies // {} | keys[]' "$DEPS_FILE" 2>/dev/null || true)

    for dep_name in $NPM_DEP_NAMES; do
        matched=$(match_dep_to_repo "$dep_name" "npm" "$repo_name")
        if [[ -n "$matched" ]]; then
            DEPENDENCY_LINKS=$(echo "$DEPENDENCY_LINKS" | jq \
                --arg from "$repo_name" \
                --arg to "$matched" \
                --arg dep "$dep_name" \
                '. + [{"from": $from, "to": $to, "dependency": $dep, "type": "npm"}]')
        fi
    done

    # Check pip/pyproject dependencies (packages[] array)
    # Use while-read to preserve package strings with spaces (e.g., PEP 508 "name @ url")
    # Handles both type: "pip" (requirements.txt) and type: "pyproject" (pyproject.toml)
    while IFS= read -r pkg; do
        [[ -z "$pkg" ]] && continue
        # Strip version specifiers/direct references and trim whitespace
        # (e.g., "flask==2.0.0" -> "flask", "name @ https://..." -> "name")
        pkg_name=$(echo "$pkg" | sed 's/[>=<!\[@].*$//' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        matched=$(match_dep_to_repo "$pkg_name" "pip" "$repo_name")
        if [[ -n "$matched" ]]; then
            DEPENDENCY_LINKS=$(echo "$DEPENDENCY_LINKS" | jq \
                --arg from "$repo_name" \
                --arg to "$matched" \
                --arg dep "$pkg" \
                '. + [{"from": $from, "to": $to, "dependency": $dep, "type": "pip"}]')
        fi
    done < <(jq -r '.[] | select(.type == "pip" or .type == "pyproject") | .packages[]?' "$DEPS_FILE" 2>/dev/null || true)

    # Check go dependencies (from go.mod if parsed)
    # Use while-read to preserve full dependency strings (may include versions like "module/path v1.2.3")
    while IFS= read -r go_dep; do
        [[ -z "$go_dep" ]] && continue
        # Strip version suffix for matching (e.g., "github.com/org/mod v1.2.3" -> "github.com/org/mod")
        go_module_path=$(echo "$go_dep" | awk '{print $1}')
        matched=$(match_dep_to_repo "$go_module_path" "go" "$repo_name")
        if [[ -n "$matched" ]]; then
            DEPENDENCY_LINKS=$(echo "$DEPENDENCY_LINKS" | jq \
                --arg from "$repo_name" \
                --arg to "$matched" \
                --arg dep "$go_dep" \
                '. + [{"from": $from, "to": $to, "dependency": $dep, "type": "go"}]')
        fi
    done < <(jq -r '.[] | select(.type == "go") | .dependencies[]?' "$DEPS_FILE" 2>/dev/null || true)
done

# Deduplicate dependency links
DEPENDENCY_LINKS=$(echo "$DEPENDENCY_LINKS" | jq 'unique_by({from, to, dependency, type})')

# ---------- 3. Build output ----------

ANALYZED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

jq -n \
    --arg analyzed_at "$ANALYZED_AT" \
    --argjson repo_count "$REPO_COUNT" \
    --argjson dependency_links "$DEPENDENCY_LINKS" \
    --argjson shared_tech "$SHARED_TECH" \
    '{
        analyzed_at: $analyzed_at,
        repo_count: $repo_count,
        dependency_links: $dependency_links,
        shared_tech: $shared_tech,
        potential_integrations: []
    }' > "$OUTPUT_DIR/cross-repo.json"

echo "Cross-repo integration map saved to $OUTPUT_DIR/cross-repo.json" >&2
