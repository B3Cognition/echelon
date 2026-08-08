#!/usr/bin/env bash
# validate-journal-entry.sh — Schema validator for reasoning-journal entries.
#
# Validates a single journal entry against journal-entry-types.json.
# See: specs/027-journal-state-integrity/contracts/validator.md
#
# Usage:
#   echo '{"type":"routing_decision","data":{...}}' | bash validate-journal-entry.sh
#   bash validate-journal-entry.sh '{"type":"routing_decision","data":{...}}'
#
# Exit codes:
#   0 — PASS (entry conforms; may have warnings for extra fields)
#   1 — FAIL (missing required fields or size limit exceeded or malformed JSON)
#   2 — WARN (type not registered in schema OR schema file unreadable)
#
# Stdout: JSON verdict object { valid, entry_type, warnings[], errors[] }
# Stderr: Diagnostic messages (human-readable)

set -euo pipefail

# ── Resolve schema path ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_PATH="${SCHEMA_PATH:-${SCRIPT_DIR}/../../workflow/journal-entry-types.json}"

# ── Read input ──────────────────────────────────────────────────────────────
if [ $# -ge 1 ] && [ -n "$1" ]; then
  ENTRY="$1"
else
  ENTRY="$(cat)"
fi

# ── Size guard (1MB = 1048576 bytes) ────────────────────────────────────────
ENTRY_SIZE=$(printf '%s' "$ENTRY" | wc -c)
if [ "$ENTRY_SIZE" -gt 1048576 ]; then
  echo '{"valid":false,"entry_type":"unknown","warnings":[],"errors":["Entry exceeds 1MB size limit"]}' >&2
  echo '{"valid":false,"entry_type":"unknown","warnings":[],"errors":["Entry exceeds 1MB size limit"]}'
  exit 1
fi

# ── Check schema file exists ───────────────────────────────────────────────
if [ ! -f "$SCHEMA_PATH" ] || [ ! -r "$SCHEMA_PATH" ]; then
  echo "ERROR: Schema file not readable: $SCHEMA_PATH" >&2
  echo '{"valid":true,"entry_type":"unknown","warnings":["Schema file unreadable — cannot validate"],"errors":[]}'
  exit 2
fi

# ── Validate entry is parseable JSON ────────────────────────────────────────
if ! ENTRY_TYPE=$(printf '%s' "$ENTRY" | jq -r '.type // empty' 2>/dev/null); then
  echo '{"valid":false,"entry_type":"unknown","warnings":[],"errors":["Malformed JSON — parse failure"]}'
  exit 1
fi

if [ -z "$ENTRY_TYPE" ]; then
  echo '{"valid":false,"entry_type":"unknown","warnings":[],"errors":["Malformed JSON — parse failure"]}'
  exit 1
fi

# ── Single jq pipeline: look up schema, validate required fields, detect extras ──
VERDICT=$(jq -n \
  --arg entry_type "$ENTRY_TYPE" \
  --argjson entry "$ENTRY" \
  --slurpfile schema "$SCHEMA_PATH" \
  '
  ($schema[0].types[$entry_type]) as $type_def |

  if $type_def == null then
    # Type not registered
    {
      valid: true,
      entry_type: $entry_type,
      warnings: ["Type not registered in schema: " + $entry_type],
      errors: []
    }
  else
    ($type_def.required_data_fields // []) as $required |
    ($type_def.optional_data_fields // []) as $optional |
    ($entry.data // {}) as $data |
    ($data | keys) as $data_keys |

    # Find missing required fields
    ([$required[] | select(. as $f | $data_keys | index($f) | not)] ) as $missing |

    # Find extra fields (in data but not in required or optional)
    ($required + $optional) as $declared |
    ([$data_keys[] | select(. as $f | $declared | index($f) | not)] ) as $extra |

    # tool_output_ref cross-check
    (if ($data.source // "" | startswith("tool:")) and (($data.tool_output_ref // "") == "") then
      ["source starts with tool: but tool_output_ref is absent or empty"]
    else
      []
    end) as $tool_warnings |

    # Build warnings for extra fields
    (if ($extra | length) > 0 then
      ["Extra fields not in schema: " + ($extra | join(", "))]
    else
      []
    end) as $extra_warnings |

    {
      valid: (($missing | length) == 0),
      entry_type: $entry_type,
      warnings: ($extra_warnings + $tool_warnings),
      errors: (if ($missing | length) > 0 then
        ["Missing required fields: " + ($missing | join(", "))]
      else
        []
      end)
    }
  end
  ' 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$VERDICT" ]; then
  echo '{"valid":false,"entry_type":"unknown","warnings":[],"errors":["Malformed JSON — parse failure"]}'
  exit 1
fi

# ── Determine exit code from verdict ────────────────────────────────────────
VALID=$(printf '%s' "$VERDICT" | jq -r '.valid')
HAS_UNREG_WARNING=$(printf '%s' "$VERDICT" | jq -r '.warnings[] | select(startswith("Type not registered"))' 2>/dev/null)

echo "$VERDICT"

if [ "$VALID" = "false" ]; then
  exit 1
elif [ -n "$HAS_UNREG_WARNING" ]; then
  exit 2
else
  exit 0
fi
