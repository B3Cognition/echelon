#!/usr/bin/env bash
# validate-deploy.sh — pre-harness deploy infrastructure check
# Called from Echelon delivery before launching the harness.
# Exits 0 if all checks pass; exits 1 with actionable error on any failure.
set -euo pipefail

PROJECT_ROOT="${1:?PROJECT_ROOT required as first argument}"
SCRIPTS_DIR="$(CDPATH='' cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_resolve_squad_dir() {
  local base current_file run_id
  if [ -n "${ECHELON_SQUAD_DIR:-}" ]; then
    echo "${ECHELON_SQUAD_DIR}"
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

SQUAD_DIR="$(_resolve_squad_dir)"
STATE_FILE="${ECHELON_DEPLOY_STATE_FILE:-${SQUAD_DIR}/deploy-state.json}"

ERRORS=0

_fail() {
  echo "  ✗ $*" >&2
  ERRORS=$((ERRORS + 1))
}

# ── Deploy enabled check ──────────────────────────────────────────────────────
_DEPLOY_ENABLED="true"
if _val="$(bash "${SCRIPTS_DIR}/echelon-config-get.sh" deploy.enabled 2>/dev/null)"; then
  _DEPLOY_ENABLED="${_val}"
fi

if [ "${_DEPLOY_ENABLED}" = "false" ]; then
  echo "deploy: validation skipped (deploy.enabled = false)"
  exit 0
fi

echo "deploy: validating infrastructure before harness launch..."

# ── 1. deploy-state.json exists and is valid ─────────────────────────────────
if [ ! -f "${STATE_FILE}" ]; then
  _fail "deploy-state.json not found at ${STATE_FILE}"
  echo "     echelon.run was not completed or deploy-init failed." >&2
  echo "     Fix: re-run echelon spec run <description>" >&2
  exit 1
fi

DEPLOY_INFO=$(python3 - <<PYEOF
import json, sys
try:
    d = json.load(open('${STATE_FILE}'))
    required = {'app', 'type', 'active'}
    missing = required - d.keys()
    if missing:
        print(f"INVALID:missing keys: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    print(d['type'])
    print(d['app'])
except json.JSONDecodeError as e:
    print(f"INVALID:not valid JSON: {e}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"INVALID:{e}", file=sys.stderr)
    sys.exit(1)
PYEOF
)
DEPLOY_TYPE=$(echo "${DEPLOY_INFO}" | sed -n '1p')
APP_NAME=$(echo "${DEPLOY_INFO}" | sed -n '2p')

if [ -z "${DEPLOY_TYPE}" ]; then
  _fail "deploy-state.json is invalid or empty."
  echo "     Fix: rm ${STATE_FILE} && re-run echelon spec run <description>" >&2
  exit 1
fi

echo "  ✓ deploy-state.json valid (app=${APP_NAME}, type=${DEPLOY_TYPE})"

# ── 2. deploy.sh reachable ────────────────────────────────────────────────────
if [ ! -f "${SCRIPTS_DIR}/deploy.sh" ]; then
  _fail "deploy.sh not found at ${SCRIPTS_DIR}/deploy.sh"
  echo "     Fix: re-initialize the workspace with echelon workspace init --with-prosaic" >&2
  ERRORS=$((ERRORS + 1))
else
  echo "  ✓ deploy.sh reachable"
fi

# ── 4. Type-specific checks ───────────────────────────────────────────────────
if [ "${DEPLOY_TYPE}" = "http" ]; then
  # Traefik running
  TRAEFIK_STATUS=$(docker inspect --format='{{.State.Status}}' speckit-traefik 2>/dev/null | tr -d '[:space:]' || true)
  [ -z "${TRAEFIK_STATUS}" ] && TRAEFIK_STATUS="missing"
  if [ "${TRAEFIK_STATUS}" != "running" ]; then
    _fail "Traefik not running (status: ${TRAEFIK_STATUS})"
    echo "     Fix:" >&2
    echo "       docker rm -f speckit-traefik 2>/dev/null || true" >&2
    echo "       rm ${STATE_FILE}" >&2
    echo "       re-run echelon spec run <description>" >&2
    ERRORS=$((ERRORS + 1))
  else
    echo "  ✓ Traefik running"
  fi

  # speckit-deploy network exists
  if ! docker network inspect speckit-deploy &>/dev/null; then
    _fail "Docker network speckit-deploy missing"
    echo "     Fix: docker network create speckit-deploy" >&2
    ERRORS=$((ERRORS + 1))
  else
    echo "  ✓ Docker network speckit-deploy exists"
  fi
fi

# ── Result ────────────────────────────────────────────────────────────────────
if [ "${ERRORS}" -gt 0 ]; then
  echo "" >&2
  echo "✗ Deploy validation failed (${ERRORS} error(s)). Fix the issues above before launching harness." >&2
  exit 1
fi

echo "  ✓ Deploy infrastructure ready — harness launch approved"
