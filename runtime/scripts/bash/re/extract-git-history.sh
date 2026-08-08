#!/usr/bin/env bash
# Extract git history summary
set -euo pipefail

# Check jq availability
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed" >&2
    exit 1
fi

OUTPUT_FILE="${1:-/tmp/git-history.json}"
LIMIT="${ECHELON_CFG_RE_SOURCES_GIT_HISTORY_LIMIT:-100}"

echo "Extracting git history (last $LIMIT commits)..." >&2

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo '{"error": "Not a git repository"}' > "$OUTPUT_FILE"
    exit 0
fi

# Recent commits (use tab separator and jq for proper JSON escaping)
commits=$(git log -n "$LIMIT" --format='%h%x09%s%x09%ci' 2>/dev/null | \
    jq -R 'split("\t") | {hash: .[0], subject: .[1], date: .[2]}' | jq -s '.')

# Contributors (get full name, not just first word)
# Use here-string to avoid SIGPIPE with head in pipefail mode
_contrib_raw=$(git shortlog -sn --all 2>/dev/null || true)
_contrib_filtered=$(head -20 <<< "$_contrib_raw" | awk '{$1=""; print substr($0,2)}' | grep -v '^$' || true)
if [[ -n "$_contrib_filtered" ]]; then
    contributors=$(printf '%s\n' "$_contrib_filtered" | jq -R . | jq -s '.')
else
    contributors="[]"
fi

# File change frequency (hotspots)
# Use here-string to avoid SIGPIPE with head in pipefail mode
_hotspots_raw=$(git log --name-only --format='' -n "$LIMIT" 2>/dev/null | sort | uniq -c | sort -rn || true)
_hotspots_filtered=$(head -20 <<< "$_hotspots_raw" | awk '{print $2}' | grep -v '^$' || true)
if [[ -n "$_hotspots_filtered" ]]; then
    hotspots=$(printf '%s\n' "$_hotspots_filtered" | jq -R . | jq -s '.')
else
    hotspots="[]"
fi

# Output JSON
jq -n \
    --argjson commits "$commits" \
    --argjson contributors "$contributors" \
    --argjson hotspots "$hotspots" \
    '{commits: $commits, contributors: $contributors, hotspots: $hotspots}' > "$OUTPUT_FILE"

echo "Git history saved to $OUTPUT_FILE" >&2
