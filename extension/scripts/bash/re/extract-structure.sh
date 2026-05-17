#!/usr/bin/env bash
# Extract file structure information
# Compatible with bash 3.x (macOS default)
set -euo pipefail

# Check jq availability
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

OUTPUT_FILE="${1:-/tmp/structure.json}"

echo "Extracting file structure..." >&2

# Count files by extension using a temp file (bash 3.x compatible)
TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

# Find all files and extract extensions
find . -type f -not -path './.git/*' -not -path './node_modules/*' -not -path './vendor/*' 2>/dev/null | while IFS= read -r file; do
    basename_file=$(basename "$file")
    if [[ "$basename_file" == *.* ]]; then
        echo "${basename_file##*.}"
    else
        echo "(no extension)"
    fi
done | sort | uniq -c | sort -rn > "$TMPFILE"

# Convert extension counts to JSON using jq
ext_json=$(awk '{print $2 "\t" $1}' "$TMPFILE" | jq -R 'split("\t") | {(.[0]): (.[1] | tonumber)}' | jq -s 'add // {}')

# Find entry points
entry_points_json=$(
    for f in main.py app.py index.js index.ts main.go cmd/main.go src/main.rs Cargo.toml package.json pyproject.toml; do
        if [[ -f "$f" ]]; then
            echo "$f"
        fi
    done | jq -R . | jq -s '.'
)

# Count total files
total_files=$(find . -type f -not -path './.git/*' -not -path './node_modules/*' -not -path './vendor/*' 2>/dev/null | wc -l | tr -d ' ')

# Output JSON
jq -n \
    --argjson file_counts "$ext_json" \
    --argjson entry_points "$entry_points_json" \
    --argjson total "$total_files" \
    '{
        file_counts: $file_counts,
        entry_points: $entry_points,
        total_files: $total
    }' > "$OUTPUT_FILE"

echo "File structure saved to $OUTPUT_FILE" >&2
