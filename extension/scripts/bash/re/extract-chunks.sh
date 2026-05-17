#!/usr/bin/env bash
# Detect codebase size and create chunk metadata
# Compatible with bash 3.x (macOS default)
set -euo pipefail

# Check jq availability
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

OUTPUT_FILE="${1:-/tmp/chunks.json}"

# Configuration (can be overridden via env vars)
THRESHOLD_FILES="${ECHELON_CFG_RE_CHUNKING_THRESHOLD_FILES:-500}"
THRESHOLD_LINES="${ECHELON_CFG_RE_CHUNKING_THRESHOLD_LINES:-100000}"
MAX_CHUNK_FILES="${ECHELON_CFG_RE_CHUNKING_MAX_FILES:-50}"
MAX_CHUNK_LINES="${ECHELON_CFG_RE_CHUNKING_MAX_LINES:-15000}"
CHUNKING_MODE="${ECHELON_CFG_RE_CHUNKING_MODE:-auto}"
STRATEGY="${ECHELON_CFG_RE_CHUNKING_STRATEGY:-directory}"

echo "Analyzing codebase size for chunking..." >&2

# Source file extensions to count
SOURCE_EXTENSIONS="ts|tsx|js|jsx|py|go|rs|java|kt|cs|rb|php|swift|c|cpp|h|hpp"

# Count total source files (excluding common non-source directories)
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
    2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" | wc -l | tr -d ' ')

# Count total lines in source files
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

# Determine if chunking is needed
needs_chunking=false
chunking_reason=""

if [[ "$CHUNKING_MODE" == "off" ]]; then
    needs_chunking=false
elif [[ "$total_files" -gt "$THRESHOLD_FILES" ]]; then
    needs_chunking=true
    chunking_reason="File count ($total_files) exceeds threshold ($THRESHOLD_FILES)"
elif [[ "$total_lines" -gt "$THRESHOLD_LINES" ]]; then
    needs_chunking=true
    chunking_reason="Line count ($total_lines) exceeds threshold ($THRESHOLD_LINES)"
fi

# If chunking mode is "suggest", just report but don't create chunks
if [[ "$CHUNKING_MODE" == "suggest" ]] && [[ "$needs_chunking" == "true" ]]; then
    echo "" >&2
    echo "Chunking recommended: $chunking_reason" >&2
    echo "Set ECHELON_CFG_RE_CHUNKING_MODE=auto to enable" >&2
fi

# Create chunks based on strategy
chunks_json="[]"

if [[ "$needs_chunking" == "true" ]] && [[ "$CHUNKING_MODE" == "auto" ]]; then
    echo "" >&2
    echo "Chunking enabled: $chunking_reason" >&2
    echo "Strategy: $STRATEGY" >&2
    echo "" >&2

    case "$STRATEGY" in
        directory)
            # Find top-level directories with source files
            chunks_json=$(
                # Get unique top-level directories containing source files
                find . -type f \
                    -not -path './.git/*' \
                    -not -path './node_modules/*' \
                    -not -path './vendor/*' \
                    -not -path './dist/*' \
                    -not -path './build/*' \
                    2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" | \
                while IFS= read -r file; do
                    # Extract first meaningful directory component
                    dir=$(dirname "$file" | sed 's|^\./||' | cut -d'/' -f1)
                    if [[ -n "$dir" ]] && [[ "$dir" != "." ]]; then
                        echo "$dir"
                    else
                        echo "(root)"
                    fi
                done | sort | uniq -c | sort -rn | \
                while read -r count dir; do
                    # Get line count for this directory
                    if [[ "$dir" == "(root)" ]]; then
                        dir_path="."
                        dir_lines=$(find . -maxdepth 1 -type f 2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}' || echo 0)
                    else
                        dir_path="./$dir"
                        dir_lines=$(find "$dir_path" -type f \
                            -not -path './node_modules/*' \
                            -not -path './vendor/*' \
                            -not -path './dist/*' \
                            2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}' || echo 0)
                    fi
                    # Output JSON object
                    jq -n \
                        --arg id "$dir" \
                        --arg path "$dir_path" \
                        --argjson files "$count" \
                        --argjson lines "${dir_lines:-0}" \
                        '{id: $id, path: $path, files: $files, lines: $lines}'
                done | jq -s '.'
            )
            ;;

        filetype)
            # Group by file type
            chunks_json=$(
                find . -type f \
                    -not -path './.git/*' \
                    -not -path './node_modules/*' \
                    -not -path './vendor/*' \
                    -not -path './dist/*' \
                    -not -path './build/*' \
                    2>/dev/null | grep -E "\.($SOURCE_EXTENSIONS)$" | \
                while IFS= read -r file; do
                    ext="${file##*.}"
                    echo "$ext"
                done | sort | uniq -c | sort -rn | \
                while read -r count ext; do
                    # Get line count for this extension
                    ext_lines=$(find . -type f -name "*.$ext" \
                        -not -path './.git/*' \
                        -not -path './node_modules/*' \
                        -not -path './vendor/*' \
                        2>/dev/null | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}' || echo 0)
                    jq -n \
                        --arg id "$ext" \
                        --arg path "**/*.$ext" \
                        --argjson files "$count" \
                        --argjson lines "${ext_lines:-0}" \
                        '{id: $id, path: $path, files: $files, lines: $lines}'
                done | jq -s '.'
            )
            ;;

        *)
            # Default to directory strategy
            echo "Unknown strategy '$STRATEGY', using 'directory'" >&2
            STRATEGY="directory"
            ;;
    esac

    # Report chunks
    echo "Chunks created:" >&2
    echo "$chunks_json" | jq -r '.[] | "  - \(.id) (\(.files) files, \(.lines) lines)"' >&2
fi

# Output final JSON
jq -n \
    --argjson total_files "$total_files" \
    --argjson total_lines "$total_lines" \
    --argjson threshold_files "$THRESHOLD_FILES" \
    --argjson threshold_lines "$THRESHOLD_LINES" \
    --arg mode "$CHUNKING_MODE" \
    --arg strategy "$STRATEGY" \
    --argjson enabled "$needs_chunking" \
    --arg reason "$chunking_reason" \
    --argjson chunks "$chunks_json" \
    '{
        metadata: {
            total_files: $total_files,
            total_lines: $total_lines,
            thresholds: {
                files: $threshold_files,
                lines: $threshold_lines
            }
        },
        chunking: {
            enabled: $enabled,
            mode: $mode,
            strategy: $strategy,
            reason: $reason,
            chunks: $chunks
        }
    }' > "$OUTPUT_FILE"

echo "" >&2
echo "Chunk analysis saved to $OUTPUT_FILE" >&2
