#!/usr/bin/env bash
# journal-append.sh — Validate-then-append wrapper for reasoning-journal entries.
#
# Implements DR-001 (warn-then-allow): always appends the entry, emits a
# schema_warning sibling on validation FAIL.
#
# Usage:
#   bash journal-append.sh --entry '{"type":"routing_decision",...}' --journal-path /path/to/journal.jsonl
#
# Always exits 0 (never blocks the caller).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATOR="$SCRIPT_DIR/validate-journal-entry.sh"

# ── Parse arguments ─────────────────────────────────────────────────────────
ENTRY=""
JOURNAL_PATH=""

while [ $# -gt 0 ]; do
  case "$1" in
    --entry)
      ENTRY="$2"
      shift 2
      ;;
    --journal-path)
      JOURNAL_PATH="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      shift
      ;;
  esac
done

if [ -z "$ENTRY" ]; then
  echo "ERROR: --entry is required" >&2
  exit 0
fi

if [ -z "$JOURNAL_PATH" ]; then
  echo "ERROR: --journal-path is required" >&2
  exit 0
fi

# ── Size check (>1MB: warn to stderr, still append) ────────────────────────
ENTRY_SIZE=$(printf '%s' "$ENTRY" | wc -c)
if [ "$ENTRY_SIZE" -gt 1048576 ]; then
  echo "WARNING: Entry exceeds 1MB ($ENTRY_SIZE bytes) — appending anyway" >&2
fi

# ── Quality-scores provenance defense-in-depth (T-016) ─────────────────────
# If entry type is quality_check or data references quality assessment and
# lacks a source field, emit a stderr warning.
ENTRY_TYPE=$(printf '%s' "$ENTRY" | jq -r '.type // ""' 2>/dev/null) || ENTRY_TYPE=""
HAS_SOURCE=$(printf '%s' "$ENTRY" | jq -r '.data.source // ""' 2>/dev/null) || HAS_SOURCE=""

if [ "$ENTRY_TYPE" = "quality_check" ] && [ -z "$HAS_SOURCE" ]; then
  echo "WARNING: quality_check entry missing 'source' provenance field" >&2
fi

# ── Invoke validator ────────────────────────────────────────────────────────
set +e
VERDICT=$(printf '%s' "$ENTRY" | bash "$VALIDATOR" 2>/dev/null)
VALIDATOR_RC=$?
set -e

# ── Append entry unconditionally (DR-001: preserve journal continuity) ─────
# Create journal file if it does not exist
if [ ! -f "$JOURNAL_PATH" ]; then
  touch "$JOURNAL_PATH"
fi

# Compact the entry to a single line
COMPACT_ENTRY=$(printf '%s' "$ENTRY" | jq -c '.' 2>/dev/null) || COMPACT_ENTRY="$ENTRY"
echo "$COMPACT_ENTRY" >> "$JOURNAL_PATH"

# ── On FAIL (exit 1): construct and append schema_warning sibling ──────────
if [ "$VALIDATOR_RC" -eq 1 ]; then
  VIOLATING_ID=$(printf '%s' "$ENTRY" | jq -r '.id // "unknown"' 2>/dev/null) || VIOLATING_ID="unknown"
  ERROR_DETAILS=$(printf '%s' "$VERDICT" | jq -r '.errors[0] // "validation failed"' 2>/dev/null) || ERROR_DETAILS="validation failed"

  # Determine violation_type
  if printf '%s' "$ERROR_DETAILS" | grep -qi "size limit"; then
    VIOLATION_TYPE="size_limit_exceeded"
  elif printf '%s' "$ERROR_DETAILS" | grep -qi "malformed\|parse"; then
    VIOLATION_TYPE="malformed_json"
  else
    VIOLATION_TYPE="missing_required_field"
  fi

  CURRENT_PHASE=$(printf '%s' "$ENTRY" | jq -r '.phase // "unknown"' 2>/dev/null) || CURRENT_PHASE="unknown"
  TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  WARNING_ENTRY=$(jq -n \
    --arg vid "$VIOLATING_ID" \
    --arg vtype "$VIOLATION_TYPE" \
    --arg details "$ERROR_DETAILS" \
    --arg phase "$CURRENT_PHASE" \
    --arg ts "$TIMESTAMP" \
    '{
      type: "schema_warning",
      phase: $phase,
      agent: "speckit-echelon-commander",
      timestamp: $ts,
      data: {
        violating_entry_id: $vid,
        violation_type: $vtype,
        details: $details
      }
    }')

  echo "$WARNING_ENTRY" | jq -c '.' >> "$JOURNAL_PATH"
  echo "SCHEMA_WARNING: $ERROR_DETAILS (entry $VIOLATING_ID)" >&2
fi

# ── On WARN (exit 2): log to stderr only, no warning entry ─────────────────
if [ "$VALIDATOR_RC" -eq 2 ]; then
  WARN_MSG=$(printf '%s' "$VERDICT" | jq -r '.warnings[0] // "unknown warning"' 2>/dev/null) || WARN_MSG="unknown warning"
  echo "VALIDATION_WARN: $WARN_MSG" >&2
fi

# ── tool_output_ref cross-check for tool: sources ──────────────────────────
if printf '%s' "$HAS_SOURCE" | grep -q "^tool:" 2>/dev/null; then
  TOOL_REF=$(printf '%s' "$ENTRY" | jq -r '.data.tool_output_ref // ""' 2>/dev/null) || TOOL_REF=""
  if [ -z "$TOOL_REF" ]; then
    echo "WARNING: source=$HAS_SOURCE but tool_output_ref is missing" >&2
  fi
fi

# Always exit 0 — never block the caller
exit 0
