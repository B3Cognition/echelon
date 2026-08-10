#!/usr/bin/env bash
# deploy-status.sh — print active slot, image/port info, last deploy
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

_resolve_run_dir() {
  local base current_file run_id
  if [ -n "${ECHELON_RUN_DIR:-}" ]; then
    echo "${ECHELON_RUN_DIR}"
    return 0
  fi

  for base in runs; do
    current_file="${PROJECT_ROOT}/${base}/.current"
    if [ -f "${current_file}" ]; then
      run_id=$(tr -d '[:space:]' < "${current_file}")
      if [ -n "${run_id}" ] && [ -d "${PROJECT_ROOT}/${base}/${run_id}" ]; then
        echo "${PROJECT_ROOT}/${base}/${run_id}"
        return 0
      fi
    fi
  done

  echo "${PROJECT_ROOT}/runs"
}

RUN_DIR="$(_resolve_run_dir)"
STATE_FILE="${ECHELON_DEPLOY_STATE_FILE:-${RUN_DIR}/deploy-state.json}"

if [ ! -f "${STATE_FILE}" ]; then
  echo "No deploy state found. Run echelon.run first."
  exit 0
fi

_state=$(STATE_FILE="${STATE_FILE}" python3 - <<'PYEOF'
import os, sys, json
try:
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('type', 'http'))
    print(d['app'])
    print(d['active'])
    print(d.get('blue_port') or '')
    print(d.get('green_port') or '')
    print(d.get('active_port') or '')
    print(d.get('last_deploy') or 'never')
    print(d.get('blue_image') or '')
    print(d.get('green_image') or '')
    print(d.get('install_path') or '')
    print(d.get('traefik_name', 'echelon-traefik'))
except Exception as e:
    sys.exit(f'Cannot read deploy state: {e}')
PYEOF
)
DEPLOY_TYPE=$(echo "${_state}"   | sed -n '1p')
APP=$(echo "${_state}"           | sed -n '2p')
ACTIVE=$(echo "${_state}"        | sed -n '3p')
BLUE_PORT=$(echo "${_state}"     | sed -n '4p')
GREEN_PORT=$(echo "${_state}"    | sed -n '5p')
ACTIVE_PORT=$(echo "${_state}"   | sed -n '6p')
LAST=$(echo "${_state}"          | sed -n '7p')
BLUE_IMAGE=$(echo "${_state}"    | sed -n '8p')
GREEN_IMAGE=$(echo "${_state}"   | sed -n '9p')
INSTALL_PATH=$(echo "${_state}"  | sed -n '10p')
TRAEFIK_NAME=$(echo "${_state}"  | sed -n '11p')

status_of() {
  docker inspect --format='{{.State.Status}}' "$1" 2>/dev/null || echo "not found"
}

# ── CLI STATUS ────────────────────────────────────────────────────────────────
if [ "${DEPLOY_TYPE}" = "cli" ]; then
  ACTIVE_IMAGE=$([ "${ACTIVE}" = "blue" ] && echo "${BLUE_IMAGE:-${APP}:blue (not yet built)}" || echo "${GREEN_IMAGE:-${APP}:green (not yet built)}")
  echo "════════════════════════════════════════"
  echo "  ${APP} deploy status (cli)"
  echo "════════════════════════════════════════"
  echo "  Active slot:  ${ACTIVE}"
  echo "  Active image: ${ACTIVE_IMAGE}"
  echo "  Last deploy:  ${LAST}"
  echo ""
  echo "  Images:"
  printf "    blue:  %s\n"  "${BLUE_IMAGE:-not built}"
  printf "    green: %s\n"  "${GREEN_IMAGE:-not built}"
  if [ -n "${INSTALL_PATH}" ]; then
    EXPANDED=$(INSTALL_PATH="${INSTALL_PATH}" python3 -c "import os; print(os.path.expanduser(os.environ['INSTALL_PATH']))")
    echo ""
    echo "  Wrapper: ${EXPANDED}/${APP}"
    echo "  Run:     ${APP} [args...]"
  else
    echo ""
    echo "  Run:     docker run --rm ${ACTIVE_IMAGE} [args...]"
  fi
  echo "════════════════════════════════════════"
  exit 0
fi

# ── HTTP STATUS ───────────────────────────────────────────────────────────────
BLUE_STATUS=$(status_of "${APP}-blue")
GREEN_STATUS=$(status_of "${APP}-green")
TRAEFIK_STATUS=$(status_of "${TRAEFIK_NAME}")

echo "════════════════════════════════════════"
echo "  ${APP} deploy status"
echo "════════════════════════════════════════"
echo "  Active slot:  ${ACTIVE} → http://localhost:${ACTIVE_PORT}"
echo "  Last deploy:  ${LAST}"
echo ""
echo "  Containers:"
printf "    %-20s port %-6s  %s\n" "${APP}-blue"  "${BLUE_PORT}"  "${BLUE_STATUS}"
printf "    %-20s port %-6s  %s\n" "${APP}-green" "${GREEN_PORT}" "${GREEN_STATUS}"
printf "    %-20s         %s\n"    "${TRAEFIK_NAME}"               "${TRAEFIK_STATUS}"
echo "════════════════════════════════════════"
