#!/usr/bin/env bash
# T-023 — LIDA Broadcast Overlay (CA overlay, ADR-005)
#
# Usage:
#   lida_broadcast.sh broadcast <payload_json_string>
#   lida_broadcast.sh cleanup <run_id>
#
# COMMANDER integration (from T-026):
#   Before each dispatch cycle:
#     if [ -f .specify/squad/lida-payload.json ]; then
#       LIDA_PAYLOAD=$(cat .specify/squad/lida-payload.json)
#       rm -f .specify/squad/lida-payload.json
#       # inject LIDA_PAYLOAD into context_pack
#     fi
#
#   At run end:
#     lida_broadcast.sh cleanup <run_id>
#
# FR-CAO-003: Each broadcast call OVERWRITES (not appends) the payload file.
# AC-5.1:     Does not modify COMMANDER routing logic, quality gates, or endocrine triggers.
#
# Human override of P-006 authorized 2026-04-03 (user instruction: "build it anyway").

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
PAYLOAD_FILE="${REPO_ROOT}/.specify/squad/lida-payload.json"

subcommand="${1:-}"

case "${subcommand}" in
  broadcast)
    payload="${2:-}"
    if [[ -z "${payload}" ]]; then
      echo "ERROR: broadcast requires a JSON payload string argument." >&2
      exit 1
    fi
    # Validate JSON is parseable (basic sanity — requires python3 or jq)
    if command -v python3 &>/dev/null; then
      echo "${payload}" | python3 -c "import sys, json; json.load(sys.stdin)" 2>/dev/null || {
        echo "ERROR: payload is not valid JSON." >&2
        exit 1
      }
    fi
    mkdir -p "$(dirname "${PAYLOAD_FILE}")"
    # FR-CAO-003: overwrite, not append
    printf '%s' "${payload}" > "${PAYLOAD_FILE}"
    ;;

  cleanup)
    # run_id accepted but not used — cleanup removes any remaining payload
    rm -f "${PAYLOAD_FILE}"
    ;;

  *)
    echo "Usage: lida_broadcast.sh {broadcast <json>|cleanup <run_id>}" >&2
    exit 1
    ;;
esac
