#!/usr/bin/env bash
# Main analysis runner - combines all extraction scripts
# Usage: run-analysis.sh [OUTPUT_DIR] [MANIFEST_PATH]
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
OUTPUT_DIR="${1:-$(re_dir)}"
MANIFEST_PATH="${2:-}"

mkdir -p "$OUTPUT_DIR"
# Resolve to absolute paths — required because polyrepo mode cd's into repo dirs
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
if [[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]]; then
    MANIFEST_PATH="$(cd "$(dirname "$MANIFEST_PATH")" && pwd)/$(basename "$MANIFEST_PATH")"
fi

# ---------- Determine mode ----------
# If manifest exists and has repos, use manifest-driven mode (cd into each repo)
# Otherwise, use single-repo mode (run extraction in CWD)

USE_MANIFEST=false
if [[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]]; then
    REPO_COUNT=$(jq '.repos | length' "$MANIFEST_PATH" 2>/dev/null || echo 0)
    if [[ "$REPO_COUNT" -gt 0 ]]; then
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

# ---------- Manifest-driven mode (1 or more repos in subdirectories) ----------

if [[ "$USE_MANIFEST" == "true" ]]; then
    echo "Running reverse engineering analysis ($REPO_COUNT repo(s))..." >&2
    echo "Output directory: $OUTPUT_DIR" >&2
    echo "" >&2

    for (( i=0; i<REPO_COUNT; i++ )); do
        REPO_NAME=$(jq -r ".repos[$i].name" "$MANIFEST_PATH")
        REPO_PATH=$(jq -r ".repos[$i].path" "$MANIFEST_PATH")

        # Remove trailing slash for clean cd
        REPO_PATH="${REPO_PATH%/}"

        if [[ ! -d "$REPO_PATH" ]]; then
            echo "  WARNING: repo path not found, skipping: $REPO_PATH" >&2
            continue
        fi

        REPO_OUTPUT="$OUTPUT_DIR/$REPO_NAME"
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
            --slurpfile structure "$REPO_OUTPUT/structure.json" \
            --slurpfile dependencies "$REPO_OUTPUT/dependencies.json" \
            --slurpfile git_history "$REPO_OUTPUT/git-history.json" \
            --slurpfile configs "$REPO_OUTPUT/configs.json" \
            '{
                repo_name: $repo_name,
                extracted_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
                metadata: {
                    total_files: $total_files,
                    total_lines: $total_lines
                },
                structure: $structure[0],
                dependencies: $dependencies[0],
                git_history: $git_history[0],
                configs: $configs[0]
            }' > "$REPO_OUTPUT/analysis.json"

        echo "" >&2
    done

    # Cross-repo extraction only makes sense with multiple repos
    CROSS_REPO_PATH=""
    if [[ "$REPO_COUNT" -gt 1 ]]; then
        "$SCRIPT_DIR/extract-cross-repo.sh" "$OUTPUT_DIR" "$MANIFEST_PATH"
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
    REPO_NAMES=$(jq -r '.repos[].name' "$MANIFEST_PATH")

    for REPO_NAME in $REPO_NAMES; do
        REPO_ANALYSIS="$OUTPUT_DIR/$REPO_NAME/analysis.json"
        if [[ -f "$REPO_ANALYSIS" ]]; then
            repo_files=$(jq -r '.metadata.total_files // 0' "$REPO_ANALYSIS" 2>/dev/null || echo 0)
            repo_lines=$(jq -r '.metadata.total_lines // 0' "$REPO_ANALYSIS" 2>/dev/null || echo 0)
            total_files=$((total_files + repo_files))
            total_lines=$((total_lines + repo_lines))
            repo_analyses=$(echo "$repo_analyses" | jq --arg name "$REPO_NAME" --arg path "$REPO_NAME/analysis.json" '. + [{name: $name, path: $path}]')
        fi
    done

    # Write aggregate analysis.json (cross_repo_path only if multiple repos)
    if [[ -n "$CROSS_REPO_PATH" ]]; then
        jq -n \
            --argjson repo_count "$REPO_COUNT" \
            --argjson total_files "$total_files" \
            --argjson total_lines "$total_lines" \
            --argjson repos "$repo_analyses" \
            --arg cross_repo "$CROSS_REPO_PATH" \
            '{
                metadata: { repo_count: $repo_count, total_files: $total_files, total_lines: $total_lines },
                repos: $repos,
                cross_repo_path: $cross_repo,
                manifest_path: "repos-manifest.json"
            }' > "$OUTPUT_DIR/analysis.json"
    else
        jq -n \
            --argjson repo_count "$REPO_COUNT" \
            --argjson total_files "$total_files" \
            --argjson total_lines "$total_lines" \
            --argjson repos "$repo_analyses" \
            '{
                metadata: { repo_count: $repo_count, total_files: $total_files, total_lines: $total_lines },
                repos: $repos,
                manifest_path: "repos-manifest.json"
            }' > "$OUTPUT_DIR/analysis.json"
    fi

    # Structural Code Intelligence (conditional — fail-open, non-blocking)
    # Runs once at root level covering all repos via aggregate analysis
    RE_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/re"
    BRIDGE_SCRIPT="$RE_NODE_DIR/codegraph-bridge.js"
    NODE_MODULES_DIR="$RE_NODE_DIR/node_modules"
    if command -v node >/dev/null 2>&1 && [[ -f "$BRIDGE_SCRIPT" ]]; then
        if [[ ! -d "$NODE_MODULES_DIR" ]]; then
            echo "⚠️  CodeGraph structural analysis skipped: node_modules not found." >&2
            echo "   Run: npm ci --prefix \"$RE_NODE_DIR\"" >&2
        else
            echo "Running structural analysis (CodeGraph)..." >&2
            run_codegraph_bridge "$BRIDGE_SCRIPT" "$OUTPUT_DIR/codegraph-analysis.json"
            write_codegraph_summary "$OUTPUT_DIR/codegraph-analysis.json" "$OUTPUT_DIR/codegraph-summary.json"
        fi
    fi

    echo "Analysis complete! ($REPO_COUNT repo(s))" >&2
    echo "Per-repo outputs in: $OUTPUT_DIR/{repo-name}/" >&2
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
    --slurpfile structure "$OUTPUT_DIR/structure.json" \
    --slurpfile dependencies "$OUTPUT_DIR/dependencies.json" \
    --slurpfile git_history "$OUTPUT_DIR/git-history.json" \
    --slurpfile configs "$OUTPUT_DIR/configs.json" \
    '{
        extracted_at: (now | strftime("%Y-%m-%dT%H:%M:%SZ")),
        metadata: {
            total_files: $total_files,
            total_lines: $total_lines
        },
        structure: $structure[0],
        dependencies: $dependencies[0],
        git_history: $git_history[0],
        configs: $configs[0]
    }' > "$OUTPUT_DIR/analysis.json"

# Structural Code Intelligence (conditional — fail-open, non-blocking)
RE_NODE_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")/node/re"
BRIDGE_SCRIPT="$RE_NODE_DIR/codegraph-bridge.js"
NODE_MODULES_DIR="$RE_NODE_DIR/node_modules"
if command -v node >/dev/null 2>&1 && [[ -f "$BRIDGE_SCRIPT" ]]; then
    if [[ ! -d "$NODE_MODULES_DIR" ]]; then
        echo "⚠️  CodeGraph structural analysis skipped: node_modules not found." >&2
        echo "   Run: npm ci --prefix \"$RE_NODE_DIR\"" >&2
    else
        echo "Running structural analysis (CodeGraph)..." >&2
        run_codegraph_bridge "$BRIDGE_SCRIPT" "$OUTPUT_DIR/codegraph-analysis.json"
        write_codegraph_summary "$OUTPUT_DIR/codegraph-analysis.json" "$OUTPUT_DIR/codegraph-summary.json"
    fi
fi

echo "" >&2
echo "Analysis complete!" >&2
echo "Main output: $OUTPUT_DIR/analysis.json" >&2
