#!/usr/bin/env bash
# deploy-status.sh — print active slot, ports, container health, last deploy
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
STATE_FILE="${PROJECT_ROOT}/.specify/squad/deploy-state.json"

if [ ! -f "${STATE_FILE}" ]; then
  echo "No deploy state found. Run echelon.run first."
  exit 0
fi

_state=$(STATE_FILE="${STATE_FILE}" python3 - <<'PYEOF'
import os, sys, json
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d['app'])
    print(d['active'])
    print(d['blue_port'])
    print(d['green_port'])
    print(d['active_port'])
    print(d.get('last_deploy') or 'never')
except Exception as e:
    sys.exit(f'Cannot read deploy state: {e}')
PYEOF
)
APP=$(echo "${_state}"        | sed -n '1p')
ACTIVE=$(echo "${_state}"     | sed -n '2p')
BLUE_PORT=$(echo "${_state}"  | sed -n '3p')
GREEN_PORT=$(echo "${_state}" | sed -n '4p')
ACTIVE_PORT=$(echo "${_state}"| sed -n '5p')
LAST=$(echo "${_state}"       | sed -n '6p')

INACTIVE=$([ "${ACTIVE}" = "blue" ] && echo "green" || echo "blue")

status_of() {
  docker inspect --format='{{.State.Status}}' "$1" 2>/dev/null || echo "not found"
}

BLUE_STATUS=$(status_of "${APP}-blue")
GREEN_STATUS=$(status_of "${APP}-green")
TRAEFIK_STATUS=$(status_of speckit-traefik)

echo "════════════════════════════════════════"
echo "  ${APP} deploy status"
echo "════════════════════════════════════════"
echo "  Active slot:  ${ACTIVE} → http://localhost:${ACTIVE_PORT}"
echo "  Last deploy:  ${LAST}"
echo ""
echo "  Containers:"
printf "    %-20s port %-6s  %s\n" "${APP}-blue"  "${BLUE_PORT}"  "${BLUE_STATUS}"
printf "    %-20s port %-6s  %s\n" "${APP}-green" "${GREEN_PORT}" "${GREEN_STATUS}"
printf "    %-20s         %s\n"    "speckit-traefik"               "${TRAEFIK_STATUS}"
echo "════════════════════════════════════════"
