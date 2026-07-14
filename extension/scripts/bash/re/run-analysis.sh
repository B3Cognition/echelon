#!/usr/bin/env bash
# Main analysis runner - combines all extraction scripts
# Usage:
#   run-analysis.sh [OUTPUT_DIR] [MANIFEST_PATH]  # legacy positional form
#   run-analysis.sh --output DIR --manifest PATH --profile full --depth full \
#       --max-lines-per-file 5000 --git-history-limit 2500 \
#       --source-output-root DIR
set -euo pipefail

# Helper: resolve output directory, supporting echelon re-* config
re_dir() {
  echo "${ECHELON_CFG_RE_OUTPUT_DIRECTORY:-.specify/echelon/re}"
}

# Check jq availability
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR=""
SOURCE_OUTPUT_ROOT=""
MANIFEST_PATH=""
PROFILE="${ECHELON_CFG_RE_PROFILE:-full}"
DEPTH_LEVEL="${ECHELON_CFG_RE_DEPTH_LEVEL:-}"
MAX_LINES_PER_FILE="${ECHELON_CFG_RE_DEPTH_MAX_LINES_PER_FILE:-5000}"
GIT_HISTORY_LIMIT="${ECHELON_CFG_RE_SOURCES_GIT_HISTORY_LIMIT:-2500}"

usage() {
    cat >&2 <<'EOF'
Usage:
  run-analysis.sh [OUTPUT_DIR] [MANIFEST_PATH]
  run-analysis.sh --output DIR [--manifest PATH] [--profile full|survey|deep]
                  [--depth metadata|signatures|logic|full]
                  [--max-lines-per-file N] [--git-history-limit N]
                  [--source-output-root DIR]
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output|--output-dir)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --manifest|--repos-manifest|--workspace-manifest)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            MANIFEST_PATH="$2"
            shift 2
            ;;
        --source-output-root)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            SOURCE_OUTPUT_ROOT="$2"
            shift 2
            ;;
        --profile)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            PROFILE="$2"
            shift 2
            ;;
        --depth|--depth-level)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            DEPTH_LEVEL="$2"
            shift 2
            ;;
        --max-lines-per-file)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            MAX_LINES_PER_FILE="$2"
            shift 2
            ;;
        --git-history-limit)
            [[ $# -ge 2 ]] || { echo "run-analysis.sh: $1 requires a value" >&2; exit 64; }
            GIT_HISTORY_LIMIT="$2"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --*)
            echo "run-analysis.sh: unknown argument: $1" >&2
            usage
            exit 64
            ;;
        *)
            if [[ -z "$OUTPUT_DIR" ]]; then
                OUTPUT_DIR="$1"
            elif [[ -z "$MANIFEST_PATH" ]]; then
                MANIFEST_PATH="$1"
            else
                echo "run-analysis.sh: unexpected positional argument: $1" >&2
                usage
                exit 64
            fi
            shift
            ;;
    esac
done

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$(re_dir)"
fi
if [[ -z "$DEPTH_LEVEL" ]]; then
    case "$PROFILE" in
        survey) DEPTH_LEVEL="logic" ;;
        *) DEPTH_LEVEL="full" ;;
    esac
fi

export ECHELON_CFG_RE_PROFILE="$PROFILE"
export ECHELON_CFG_RE_DEPTH_LEVEL="$DEPTH_LEVEL"
export ECHELON_CFG_RE_DEPTH_MAX_LINES_PER_FILE="$MAX_LINES_PER_FILE"
export ECHELON_CFG_RE_SOURCES_GIT_HISTORY_LIMIT="$GIT_HISTORY_LIMIT"

resolve_workspace_manifest() {
    local repos_manifest="$1"
    local candidate

    if [[ -z "$repos_manifest" ]]; then
        printf '%s\n' ""
        return 0
    fi

    if jq -e '.sources | type == "array"' "$repos_manifest" >/dev/null 2>&1; then
        printf '%s\n' "$repos_manifest"
        return 0
    fi

    candidate="$(dirname "$repos_manifest")/workspace-manifest.json"
    if [[ -f "$candidate" ]]; then
        printf '%s\n' "$candidate"
    else
        printf '%s\n' ""
    fi
}

manifest_source_count() {
    local manifest_path="$1"
    local workspace_manifest="$2"

    if [[ -n "$workspace_manifest" ]]; then
        jq '.sources | length' "$workspace_manifest" 2>/dev/null || echo 0
    else
        jq '.repos | length' "$manifest_path" 2>/dev/null || echo 0
    fi
}

manifest_source_name() {
    local manifest_path="$1"
    local workspace_manifest="$2"
    local index="$3"
    local source_id
    local source_path
    local workspace_root

    if [[ -n "$workspace_manifest" ]]; then
        source_id="$(jq -r ".sources[$index].id // empty" "$workspace_manifest")"
        source_path="$(jq -r ".sources[$index].path // empty" "$workspace_manifest")"
        if [[ -n "$source_id" && "$source_id" != "." ]]; then
            printf '%s\n' "$source_id"
        elif [[ -n "$source_path" && "$source_path" != "." ]]; then
            basename "$source_path"
        else
            workspace_root="$(jq -r ".workspace.root // empty" "$workspace_manifest")"
            basename "$workspace_root"
        fi
    else
        jq -r ".repos[$index].name" "$manifest_path"
    fi
}

manifest_source_path() {
    local manifest_path="$1"
    local workspace_manifest="$2"
    local index="$3"
    local source_path
    local workspace_root

    if [[ -n "$workspace_manifest" ]]; then
        source_path="$(jq -r ".sources[$index].path // empty" "$workspace_manifest")"
        workspace_root="$(jq -r ".workspace.root // empty" "$workspace_manifest")"
        if [[ "$source_path" = /* ]]; then
            printf '%s\n' "$source_path"
        elif [[ -n "$workspace_root" ]]; then
            printf '%s\n' "$workspace_root/$source_path"
        else
            printf '%s\n' "$source_path"
        fi
    else
        jq -r ".repos[$index].path" "$manifest_path"
    fi
}

copy_manifest_artifacts() {
    local repos_manifest="$1"
    local workspace_manifest="$2"

    if [[ -n "$repos_manifest" && -f "$repos_manifest" \
        && "$repos_manifest" != "$OUTPUT_DIR/repos-manifest.json" \
        && "$(jq -r 'has("repos")' "$repos_manifest" 2>/dev/null || echo false)" == "true" ]]; then
        cp "$repos_manifest" "$OUTPUT_DIR/repos-manifest.json"
    fi
    if [[ -n "$workspace_manifest" && -f "$workspace_manifest" \
        && "$workspace_manifest" != "$OUTPUT_DIR/workspace-manifest.json" \
        && ! -f "$OUTPUT_DIR/workspace-manifest.json" ]]; then
        cp "$workspace_manifest" "$OUTPUT_DIR/workspace-manifest.json"
    fi
}

write_workspace_compat_repos_manifest() {
    local workspace_manifest="$1"
    local legacy_repos_manifest="$2"
    local output_path="$3"
    local legacy_json="{}"

    if [[ -n "$legacy_repos_manifest" && -f "$legacy_repos_manifest" ]]; then
        legacy_json="$(cat "$legacy_repos_manifest")"
    fi

    jq -n \
        --slurpfile workspace "$workspace_manifest" \
        --argjson legacy "$legacy_json" \
        --arg generated_at "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        '
        def basename_path:
            split("/") | map(select(. != "")) | last;

        ($workspace[0]) as $wm
        | ($wm.workspace.root // "") as $root
        | [
            ($wm.sources // [])[]
            | . as $source
            | (
                if (($source.id // "") != "" and ($source.id // "") != ".") then
                    $source.id
                elif (($source.path // "") != "" and ($source.path // "") != ".") then
                    ($source.path | basename_path)
                else
                    ($root | basename_path)
                end
              ) as $name
            | (
                if (($source.path // "") | startswith("/")) then
                    $source.path
                elif (($source.path // "") == "." or ($source.path // "") == "") then
                    $root
                else
                    ($root + "/" + $source.path)
                end
              ) as $abs_path
            | (
                ($legacy.repos // [])
                | map(select(.name == $name or .path == $abs_path or (.path | endswith("/" + $name))))
                | first
              ) as $legacy_repo
            | {
                name: $name,
                path: $abs_path,
                has_git: ($source.git_present // false),
                markers: ($source.project_markers // []),
                source_file_count: ($source.source_file_count // 0),
                pkg_identifiers: (($legacy_repo.pkg_identifiers // []))
              }
          ] as $repos
        | {
            discovered_at: $generated_at,
            root: $root,
            mode: (if ($repos | length) > 1 then "polyrepo" else "single" end),
            repo_count: ($repos | length),
            repos: $repos
          }
        ' > "$output_path"

    local repo_count
    local i
    local repo_path
    local pkg_identifiers
    local npm_name
    local go_module
    local py_name
    local tmp_path

    repo_count=$(jq '.repos | length' "$output_path")
    for (( i=0; i<repo_count; i++ )); do
        repo_path=$(jq -r ".repos[$i].path" "$output_path")
        pkg_identifiers=$(jq -c ".repos[$i].pkg_identifiers // []" "$output_path")

        if [[ -f "$repo_path/package.json" ]]; then
            npm_name=$(jq -r '.name // empty' "$repo_path/package.json" 2>/dev/null || true)
            if [[ -n "$npm_name" ]]; then
                pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$npm_name" --arg type "npm" '. + [{id: $id, type: $type}] | unique_by(.id, .type)')
            fi
        fi

        if [[ -f "$repo_path/go.mod" ]]; then
            go_module=$(head -1 "$repo_path/go.mod" | sed -n 's/^module //p' | tr -d '\r' || true)
            if [[ -n "$go_module" ]]; then
                pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$go_module" --arg type "go" '. + [{id: $id, type: $type}] | unique_by(.id, .type)')
            fi
        fi

        if [[ -f "$repo_path/pyproject.toml" ]] && command -v python3 >/dev/null 2>&1; then
            py_name=$(python3 - "$repo_path/pyproject.toml" 2>/dev/null <<'PY' || true
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
                pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$py_name" --arg type "pip" '. + [{id: $id, type: $type}] | unique_by(.id, .type)')
            fi
        elif [[ -f "$repo_path/setup.py" ]]; then
            py_name=$(grep -E 'name[[:space:]]*=' "$repo_path/setup.py" 2>/dev/null | head -1 | sed 's/.*name[ ]*=[ ]*["'"'"']\([^"'"'"']*\)["'"'"'].*/\1/' || true)
            if [[ -n "$py_name" ]]; then
                pkg_identifiers=$(echo "$pkg_identifiers" | jq --arg id "$py_name" --arg type "pip" '. + [{id: $id, type: $type}] | unique_by(.id, .type)')
            fi
        fi

        tmp_path="$output_path.tmp"
        jq --argjson index "$i" --argjson pkg_identifiers "$pkg_identifiers" \
            '.repos[$index].pkg_identifiers = $pkg_identifiers' \
            "$output_path" > "$tmp_path"
        mv "$tmp_path" "$output_path"
    done
}

extraction_profile_json() {
    jq -n \
        --arg profile "$PROFILE" \
        --arg depth_level "$DEPTH_LEVEL" \
        --argjson max_lines_per_file "$MAX_LINES_PER_FILE" \
        --argjson git_history_limit "$GIT_HISTORY_LIMIT" \
        '{
            profile: $profile,
            depth_level: $depth_level,
            max_lines_per_file: $max_lines_per_file,
            git_history_limit: $git_history_limit
        }'
}

mkdir -p "$OUTPUT_DIR"
# Resolve to absolute paths because workspace analysis changes into source roots.
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
if [[ -z "$SOURCE_OUTPUT_ROOT" ]]; then
    SOURCE_OUTPUT_ROOT="$OUTPUT_DIR"
fi
mkdir -p "$SOURCE_OUTPUT_ROOT"
SOURCE_OUTPUT_ROOT="$(cd "$SOURCE_OUTPUT_ROOT" && pwd)"
case "$SOURCE_OUTPUT_ROOT" in
    "$OUTPUT_DIR"|"$OUTPUT_DIR"/*) ;;
    *)
        echo "run-analysis.sh: --source-output-root must be inside --output" >&2
        exit 64
        ;;
esac
if [[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]]; then
    MANIFEST_PATH="$(cd "$(dirname "$MANIFEST_PATH")" && pwd)/$(basename "$MANIFEST_PATH")"
fi
WORKSPACE_MANIFEST="$(resolve_workspace_manifest "$MANIFEST_PATH")"
EXTRACTION_PROFILE_JSON="$(extraction_profile_json)"

# ---------- Determine mode ----------
# A source or repository manifest is authoritative even when it selects zero sources.

USE_MANIFEST=false
if [[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]]; then
    if [[ -n "$WORKSPACE_MANIFEST" ]] \
        || jq -e '.repos | type == "array"' "$MANIFEST_PATH" >/dev/null 2>&1; then
        REPO_COUNT=$(manifest_source_count "$MANIFEST_PATH" "$WORKSPACE_MANIFEST")
        USE_MANIFEST=true
    fi
fi

run_codegraph_bridge() {
    local bridge_script="$1"
    local output_path="$2"
    local codegraph_dir
    local codegraph_preexisted=false

    codegraph_dir="$(pwd)/.codegraph"
    if [[ -e "$codegraph_dir" ]]; then
        codegraph_preexisted=true
    fi

    node "$bridge_script" analyze \
        --repo-path "$(pwd)" \
        --output-path "$output_path" \
        2>&1 | grep -v "^$" >&2 || true

    # Echelon only needs the normalized JSON artifact. Avoid dirtying target repos
    # with a transient CodeGraph index, while preserving any pre-existing index.
    if [[ "$codegraph_preexisted" == "false" && -d "$codegraph_dir" ]]; then
        rm -rf "$codegraph_dir"
    fi
}

write_codegraph_summary() {
    local analysis_path="$1"
    local summary_path="$2"

    if [[ ! -f "$analysis_path" ]]; then
        return 0
    fi

    jq '{
        version,
        generated_at,
        repo_path,
        supported,
        index_state: (.index_stats.index_state // "unknown"),
        index_stats,
        language_coverage,
        coverage,
        symbol_kinds: ((.symbols // [])
            | group_by(.kind)
            | map({kind: (.[0].kind // "unknown"), count: length})
            | sort_by(.count)
            | reverse),
        top_callers: ((.call_graph // [])
            | group_by(.caller)
            | map({symbol: (.[0].caller // "unknown"), outgoing_calls: length})
            | sort_by(.outgoing_calls)
            | reverse
            | .[:25]),
        top_callees: ((.call_graph // [])
            | group_by(.callee)
            | map({symbol: (.[0].callee // "unknown"), incoming_calls: length})
            | sort_by(.incoming_calls)
            | reverse
            | .[:25])
    }' "$analysis_path" > "$summary_path" || true
}

write_polyrepo_codegraph_summary() {
    local output_dir="$1"
    local manifest_path="$2"
    local workspace_manifest="$3"
    local source_output_root="$4"
    local summary_path="$output_dir/codegraph-summary.json"
    local repo_summaries="[]"
    local repo_count
    local repo_name
    local repo_summary
    local index_state
    local symbols

    repo_count=$(manifest_source_count "$manifest_path" "$workspace_manifest")
    for (( i=0; i<repo_count; i++ )); do
        repo_name=$(manifest_source_name "$manifest_path" "$workspace_manifest" "$i")
        repo_summary="$source_output_root/$repo_name/codegraph-summary.json"
        if [[ -f "$repo_summary" ]]; then
            index_state=$(jq -r '.index_state // "unknown"' "$repo_summary" 2>/dev/null || echo "unknown")
            symbols=$(jq -r '.index_stats.total_symbols // .index_stats.symbol_count // 0' "$repo_summary" 2>/dev/null || echo 0)
            repo_summaries=$(echo "$repo_summaries" | jq \
                --arg name "$repo_name" \
                --arg path "${repo_summary#"$output_dir"/}" \
                --arg state "$index_state" \
                --argjson symbols "$symbols" \
                '. + [{repo: $name, summary_path: $path, index_state: $state, symbols: $symbols}]')
        fi
    done

    if [[ "$(echo "$repo_summaries" | jq 'length')" -eq 0 ]]; then
        return 0
    fi

    jq -n \
        --arg generated_at "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
        --argjson repo_count "$repo_count" \
        --argjson repos "$repo_summaries" \
        '{
            "mode": "polyrepo",
            "generated_at": $generated_at,
            "index_state": "polyrepo",
            "repo_count": $repo_count,
            "repos": $repos
        }' > "$summary_path"
}

# ---------- Manifest-driven mode (1 or more repos in subdirectories) ----------

if [[ "$USE_MANIFEST" == "true" ]]; then
    copy_manifest_artifacts "$MANIFEST_PATH" "$WORKSPACE_MANIFEST"
    ANALYSIS_REPOS_MANIFEST="$MANIFEST_PATH"
    if [[ -n "$WORKSPACE_MANIFEST" ]]; then
        ANALYSIS_REPOS_MANIFEST="$OUTPUT_DIR/repos-manifest.json"
        write_workspace_compat_repos_manifest "$WORKSPACE_MANIFEST" "$MANIFEST_PATH" "$ANALYSIS_REPOS_MANIFEST"
    fi

    echo "Running reverse engineering analysis ($REPO_COUNT repo(s))..." >&2
    echo "Output directory: $OUTPUT_DIR" >&2
    if [[ -n "$WORKSPACE_MANIFEST" ]]; then
        echo "Manifest: workspace-manifest.json (preferred)" >&2
    else
        echo "Manifest: repos-manifest.json (compatibility fallback)" >&2
    fi
    echo "" >&2

    CODEGRAPH_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/codegraph"
    BRIDGE_SCRIPT="$CODEGRAPH_NODE_DIR/codegraph-bridge.js"
    NODE_MODULES_DIR="$CODEGRAPH_NODE_DIR/node_modules"
    CODEGRAPH_AVAILABLE=false
    if command -v node >/dev/null 2>&1 && [[ -f "$BRIDGE_SCRIPT" ]]; then
        if [[ ! -d "$NODE_MODULES_DIR" ]]; then
            echo "⚠️  CodeGraph structural analysis skipped: node_modules not found." >&2
            echo "   Run: npm ci --prefix \"$CODEGRAPH_NODE_DIR\"" >&2
        else
            CODEGRAPH_AVAILABLE=true
        fi
    fi

    for (( i=0; i<REPO_COUNT; i++ )); do
        REPO_NAME=$(manifest_source_name "$MANIFEST_PATH" "$WORKSPACE_MANIFEST" "$i")
        REPO_PATH=$(manifest_source_path "$MANIFEST_PATH" "$WORKSPACE_MANIFEST" "$i")

        # Remove trailing slash for clean cd
        REPO_PATH="${REPO_PATH%/}"

        if [[ ! -d "$REPO_PATH" ]]; then
            echo "  WARNING: repo path not found, skipping: $REPO_PATH" >&2
            continue
        fi

        REPO_OUTPUT="$SOURCE_OUTPUT_ROOT/$REPO_NAME"
        mkdir -p "$REPO_OUTPUT"

        echo "--- Analyzing repo: $REPO_NAME ($REPO_PATH) ---" >&2

        # Pre-seed output files so jq --slurpfile never fails if an extraction script errors out
        echo '{}' > "$REPO_OUTPUT/structure.json"
        echo '{}' > "$REPO_OUTPUT/dependencies.json"
        echo '{}' > "$REPO_OUTPUT/git-history.json"
        echo '{}' > "$REPO_OUTPUT/configs.json"

        # Run the 4 extraction scripts from within the repo directory
        # Capture errors to log file and warn on failure (but continue processing)
        REPO_LOG="$REPO_OUTPUT/extraction.log"
        : > "$REPO_LOG"

        (cd "$REPO_PATH" && "$SCRIPT_DIR/extract-structure.sh" "$REPO_OUTPUT/structure.json") 2>>"$REPO_LOG" || echo "  WARNING: extract-structure.sh failed for $REPO_NAME" >&2
        (cd "$REPO_PATH" && "$SCRIPT_DIR/extract-dependencies.sh" "$REPO_OUTPUT/dependencies.json") 2>>"$REPO_LOG" || echo "  WARNING: extract-dependencies.sh failed for $REPO_NAME" >&2
        (cd "$REPO_PATH" && "$SCRIPT_DIR/extract-git-history.sh" "$REPO_OUTPUT/git-history.json") 2>>"$REPO_LOG" || echo "  WARNING: extract-git-history.sh failed for $REPO_NAME" >&2
        (cd "$REPO_PATH" && "$SCRIPT_DIR/extract-configs.sh" "$REPO_OUTPUT/configs.json") 2>>"$REPO_LOG" || echo "  WARNING: extract-configs.sh failed for $REPO_NAME" >&2

        # Count source files and lines for this repo
        SOURCE_EXTENSIONS="ts|tsx|js|jsx|py|go|rs|java|kt|cs|rb|php|swift|c|cpp|h|hpp"
        total_files=$(find "$REPO_PATH" -type f \
            -not -path '*/.*/*' \
            -not -path '*/.git/*' \
            -not -path '*/node_modules/*' \
            -not -path '*/vendor/*' \
            -not -path '*/dist/*' \
            -not -path '*/build/*' \
            -not -path '*/__pycache__/*' \
            -not -path '*/target/*' \
            -not -path '*/.venv/*' \
            -not -path '*/venv/*' \
            2>/dev/null | { grep -cE "\.($SOURCE_EXTENSIONS)$" || true; })

        total_lines=0
        while IFS= read -r file; do
            if [[ -f "$file" ]]; then
                lines=$(wc -l < "$file" 2>/dev/null || echo 0)
                total_lines=$((total_lines + lines))
            fi
        done < <(find "$REPO_PATH" -type f \
            -not -path '*/.*/*' \
            -not -path '*/.git/*' \
            -not -path '*/node_modules/*' \
            -not -path '*/vendor/*' \
            -not -path '*/dist/*' \
            -not -path '*/build/*' \
            -not -path '*/__pycache__/*' \
            -not -path '*/target/*' \
            -not -path '*/.venv/*' \
            -not -path '*/venv/*' \
            2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" || true)

        echo "  Source files: $total_files" >&2
        echo "  Total lines: $total_lines" >&2

        # Build per-repo analysis.json (with repo_name field)
        jq -n \
            --arg repo_name "$REPO_NAME" \
            --argjson total_files "$total_files" \
            --argjson total_lines "$total_lines" \
            --argjson extraction_profile "$EXTRACTION_PROFILE_JSON" \
            --slurpfile structure "$REPO_OUTPUT/structure.json" \
            --slurpfile dependencies "$REPO_OUTPUT/dependencies.json" \
            --slurpfile git_history "$REPO_OUTPUT/git-history.json" \
            --slurpfile configs "$REPO_OUTPUT/configs.json" \
            '{
                repo_name: $repo_name,
                extracted_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
                metadata: {
                    total_files: $total_files,
                    total_lines: $total_lines,
                    extraction_profile: $extraction_profile
                },
                structure: $structure[0],
                dependencies: $dependencies[0],
                git_history: $git_history[0],
                configs: $configs[0]
            }' > "$REPO_OUTPUT/analysis.json"

        if [[ "$CODEGRAPH_AVAILABLE" == "true" ]]; then
            echo "  Running structural analysis (CodeGraph) for $REPO_NAME..." >&2
            (cd "$REPO_PATH" && run_codegraph_bridge "$BRIDGE_SCRIPT" "$REPO_OUTPUT/codegraph-analysis.json") 2>>"$REPO_LOG" || true
            write_codegraph_summary "$REPO_OUTPUT/codegraph-analysis.json" "$REPO_OUTPUT/codegraph-summary.json"
        fi

        echo "" >&2
    done

    # Cross-repo extraction only makes sense with multiple repos
    CROSS_REPO_PATH=""
    if [[ "$REPO_COUNT" -gt 1 ]]; then
        "$SCRIPT_DIR/extract-cross-repo.sh" "$OUTPUT_DIR" "$ANALYSIS_REPOS_MANIFEST" "$SOURCE_OUTPUT_ROOT"
        CROSS_REPO_PATH="cross-repo.json"
    fi

    # Generate aggregate root analysis.json
    # This satisfies command docs that expect $(re_dir)/analysis.json
    echo "Generating aggregate analysis.json..." >&2

    # Aggregate totals from all per-repo analyses
    total_files=0
    total_lines=0
    repo_analyses="[]"

    # Get repo names from manifest
    for (( i=0; i<REPO_COUNT; i++ )); do
        REPO_NAME=$(manifest_source_name "$MANIFEST_PATH" "$WORKSPACE_MANIFEST" "$i")
        REPO_ANALYSIS="$SOURCE_OUTPUT_ROOT/$REPO_NAME/analysis.json"
        if [[ -f "$REPO_ANALYSIS" ]]; then
            repo_files=$(jq -r '.metadata.total_files // 0' "$REPO_ANALYSIS" 2>/dev/null || echo 0)
            repo_lines=$(jq -r '.metadata.total_lines // 0' "$REPO_ANALYSIS" 2>/dev/null || echo 0)
            total_files=$((total_files + repo_files))
            total_lines=$((total_lines + repo_lines))
            REPO_ANALYSIS_RELATIVE="${REPO_ANALYSIS#"$OUTPUT_DIR"/}"
            repo_analyses=$(echo "$repo_analyses" | jq --arg name "$REPO_NAME" --arg path "$REPO_ANALYSIS_RELATIVE" '. + [{name: $name, path: $path}]')
        fi
    done

    # Write aggregate analysis.json (cross_repo_path only if multiple repos)
    aggregate_manifest_path="repos-manifest.json"
    if [[ -n "$WORKSPACE_MANIFEST" ]]; then
        case "$WORKSPACE_MANIFEST" in
            "$OUTPUT_DIR"/*) aggregate_manifest_path="${WORKSPACE_MANIFEST#"$OUTPUT_DIR"/}" ;;
            *) aggregate_manifest_path="workspace-manifest.json" ;;
        esac
    fi

    if [[ -n "$CROSS_REPO_PATH" ]]; then
        jq -n \
            --argjson repo_count "$REPO_COUNT" \
            --argjson total_files "$total_files" \
            --argjson total_lines "$total_lines" \
            --argjson extraction_profile "$EXTRACTION_PROFILE_JSON" \
            --argjson repos "$repo_analyses" \
            --arg cross_repo "$CROSS_REPO_PATH" \
            --arg manifest_path "$aggregate_manifest_path" \
            '{
                metadata: {
                    repo_count: $repo_count,
                    total_files: $total_files,
                    total_lines: $total_lines,
                    extraction_profile: $extraction_profile
                },
                repos: $repos,
                cross_repo_path: $cross_repo,
                manifest_path: $manifest_path
            }' > "$OUTPUT_DIR/analysis.json"
    else
        jq -n \
            --argjson repo_count "$REPO_COUNT" \
            --argjson total_files "$total_files" \
            --argjson total_lines "$total_lines" \
            --argjson extraction_profile "$EXTRACTION_PROFILE_JSON" \
            --argjson repos "$repo_analyses" \
            --arg manifest_path "$aggregate_manifest_path" \
            '{
                metadata: {
                    repo_count: $repo_count,
                    total_files: $total_files,
                    total_lines: $total_lines,
                    extraction_profile: $extraction_profile
                },
                repos: $repos,
                manifest_path: $manifest_path
            }' > "$OUTPUT_DIR/analysis.json"
    fi

    write_polyrepo_codegraph_summary "$OUTPUT_DIR" "$MANIFEST_PATH" "$WORKSPACE_MANIFEST" "$SOURCE_OUTPUT_ROOT"

    echo "Analysis complete! ($REPO_COUNT repo(s))" >&2
    echo "Per-source outputs in: $SOURCE_OUTPUT_ROOT/{source-id}/" >&2
    [[ -n "$CROSS_REPO_PATH" ]] && echo "Cross-repo map: $OUTPUT_DIR/cross-repo.json" >&2
    echo "Aggregate analysis: $OUTPUT_DIR/analysis.json" >&2
    exit 0
fi

# ---------- Single-repo mode (original behavior — unchanged) ----------

echo "Running reverse engineering analysis..." >&2
echo "Output directory: $OUTPUT_DIR" >&2
echo "" >&2

# Step 1: Run extraction scripts
"$SCRIPT_DIR/extract-structure.sh" "$OUTPUT_DIR/structure.json"
"$SCRIPT_DIR/extract-dependencies.sh" "$OUTPUT_DIR/dependencies.json"
"$SCRIPT_DIR/extract-git-history.sh" "$OUTPUT_DIR/git-history.json"
"$SCRIPT_DIR/extract-configs.sh" "$OUTPUT_DIR/configs.json"

# Step 2: Count total source lines for metadata
SOURCE_EXTENSIONS="ts|tsx|js|jsx|py|go|rs|java|kt|cs|rb|php|swift|c|cpp|h|hpp"
total_files=$(find . -type f \
    -not -path '*/.*/*' \
    -not -path './.git/*' \
    -not -path './node_modules/*' \
    -not -path './vendor/*' \
    -not -path './dist/*' \
    -not -path './build/*' \
    -not -path './__pycache__/*' \
    -not -path './target/*' \
    -not -path './.venv/*' \
    -not -path './venv/*' \
    2>/dev/null | { grep -cE "\.($SOURCE_EXTENSIONS)$" || true; })

total_lines=0
while IFS= read -r file; do
    if [[ -f "$file" ]]; then
        lines=$(wc -l < "$file" 2>/dev/null || echo 0)
        total_lines=$((total_lines + lines))
    fi
done < <(find . -type f \
    -not -path '*/.*/*' \
    -not -path './.git/*' \
    -not -path './node_modules/*' \
    -not -path './vendor/*' \
    -not -path './dist/*' \
    -not -path './build/*' \
    -not -path './__pycache__/*' \
    -not -path './target/*' \
    -not -path './.venv/*' \
    -not -path './venv/*' \
    2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" || true)

echo "  Source files: $total_files" >&2
echo "  Total lines: $total_lines" >&2

# Step 3: Combine into analysis.json
jq -n \
    --argjson total_files "$total_files" \
    --argjson total_lines "$total_lines" \
    --argjson extraction_profile "$EXTRACTION_PROFILE_JSON" \
    --slurpfile structure "$OUTPUT_DIR/structure.json" \
    --slurpfile dependencies "$OUTPUT_DIR/dependencies.json" \
    --slurpfile git_history "$OUTPUT_DIR/git-history.json" \
    --slurpfile configs "$OUTPUT_DIR/configs.json" \
    '{
        extracted_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
        metadata: {
            total_files: $total_files,
            total_lines: $total_lines,
            extraction_profile: $extraction_profile
        },
        structure: $structure[0],
        dependencies: $dependencies[0],
        git_history: $git_history[0],
        configs: $configs[0]
    }' > "$OUTPUT_DIR/analysis.json"

# Structural Code Intelligence (conditional — fail-open, non-blocking)
CODEGRAPH_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/codegraph"
BRIDGE_SCRIPT="$CODEGRAPH_NODE_DIR/codegraph-bridge.js"
NODE_MODULES_DIR="$CODEGRAPH_NODE_DIR/node_modules"
if command -v node >/dev/null 2>&1 && [[ -f "$BRIDGE_SCRIPT" ]]; then
    if [[ ! -d "$NODE_MODULES_DIR" ]]; then
        echo "⚠️  CodeGraph structural analysis skipped: node_modules not found." >&2
        echo "   Run: npm ci --prefix \"$CODEGRAPH_NODE_DIR\"" >&2
    else
        echo "Running structural analysis (CodeGraph)..." >&2
        run_codegraph_bridge "$BRIDGE_SCRIPT" "$OUTPUT_DIR/codegraph-analysis.json"
        write_codegraph_summary "$OUTPUT_DIR/codegraph-analysis.json" "$OUTPUT_DIR/codegraph-summary.json"
    fi
fi

echo "" >&2
echo "Analysis complete!" >&2
echo "Main output: $OUTPUT_DIR/analysis.json" >&2
