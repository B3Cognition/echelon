#!/usr/bin/env bash
# deploy-init.sh — one-time blue/green deploy infrastructure setup
# Called during Echelon workspace initialization. Idempotent: exits 0 immediately if
# deploy-state.json already exists and is valid.
#
# HTTP mode: single shared Traefik at :80, apps routed by PathPrefix(/{app}).
# Blue/green ports are health-check-only (host-bound for curl, not Traefik entrypoints).
set -euo pipefail

# ── Args ────────────────────────────────────────────────────────────────────
PROJECT_ROOT="${1:?PROJECT_ROOT required as first argument}"
ECHELON_YML="${2:-${PROJECT_ROOT}/.echelon/config.yml}"
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

# ── Idempotency guard ────────────────────────────────────────────────────────
if [ -f "${STATE_FILE}" ]; then
  # Validate the state file is real (not a stub): must have required keys
  VALID=$(python3 -c "
import json, sys
try:
    d = json.load(open('${STATE_FILE}'))
    required = {'app', 'type', 'active'}
    missing = required - d.keys()
    if missing:
        print('missing:' + ','.join(missing))
        sys.exit(1)
    print('ok')
except Exception as e:
    print(f'invalid: {e}')
    sys.exit(1)
" 2>&1)
  if [ "${VALID}" != "ok" ]; then
    echo "✗ deploy-state.json exists but is invalid (${VALID})." >&2
    echo "  Delete it and re-run echelon.init to reinitialize:" >&2
    echo "    rm ${STATE_FILE}" >&2
    exit 1
  fi

  echo "deploy: already initialized (${STATE_FILE} exists) — skipping"
  exit 0
fi

# ── Read config ──────────────────────────────────────────────────────────────
if ! grep -q "^deploy:" "${ECHELON_YML}" 2>/dev/null; then
  echo "✗ deploy config missing in .echelon/config.yml." >&2
  echo "  Add a deploy: block with type: http|cli." >&2
  echo "  See .echelon/runtime/config-template.yml for reference." >&2
  exit 1
fi

_config=$(ECHELON_YML="${ECHELON_YML}" python3 - <<'PYEOF'
import os, sys
try:
    import yaml
    c = yaml.safe_load(open(os.environ['ECHELON_YML']))
    d = c.get('deploy', {})
    deploy_type = d.get('type', 'http')
    print(deploy_type)
    print(d.get('dockerfile', 'Dockerfile'))
    if deploy_type == 'http':
        print(d.get('blue_port', ''))
        print(d.get('green_port', ''))
        print('')
        print('')
    else:
        print('')
        print('')
        print(d.get('health_check', ''))
        print(d.get('install_path', ''))
    print(d.get('container_port', 80))
except KeyError as e:
    sys.exit(f'Cannot read deploy config key {e} from .echelon/config.yml')
except Exception as e:
    sys.exit(f'Cannot read deploy config: {e}')
PYEOF
)
DEPLOY_TYPE=$(echo "${_config}"     | sed -n '1p')
DOCKERFILE=$(echo "${_config}"      | sed -n '2p')
BLUE_PORT=$(echo "${_config}"       | sed -n '3p')
GREEN_PORT=$(echo "${_config}"      | sed -n '4p')
HEALTH_CHECK=$(echo "${_config}"    | sed -n '5p')
INSTALL_PATH=$(echo "${_config}"    | sed -n '6p')
CONTAINER_PORT=$(echo "${_config}"  | sed -n '7p')
CONTAINER_PORT="${CONTAINER_PORT:-80}"

APP_NAME=$(basename "${PROJECT_ROOT}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')

GLOBAL_STATE_DIR="${HOME}/.echelon/deploy"
TRAEFIK_NAME="echelon-traefik"
DEPLOY_NETWORK="echelon-deploy"
LEGACY_GLOBAL_STATE_DIR="${HOME}/.speckit-deploy"

# Existing deployments keep their established shared infrastructure. Fresh
# workspaces use the Echelon namespace and never create Spec-Kit resources.
if [ -f "${LEGACY_GLOBAL_STATE_DIR}/${APP_NAME}.json" ] \
  || docker inspect "speckit-traefik" >/dev/null 2>&1 \
  || docker network inspect "speckit-deploy" >/dev/null 2>&1; then
  GLOBAL_STATE_DIR="${LEGACY_GLOBAL_STATE_DIR}"
  TRAEFIK_NAME="speckit-traefik"
  DEPLOY_NETWORK="speckit-deploy"
  echo "deploy: using legacy deployment infrastructure for compatibility"
fi
mkdir -p "${GLOBAL_STATE_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
# CLI PATH
# ══════════════════════════════════════════════════════════════════════════════
if [ "${DEPLOY_TYPE}" = "cli" ]; then
  echo "deploy: type=cli — skipping Traefik/network setup"

  # ── Global state ──────────────────────────────────────────────────────────
  APP_NAME="${APP_NAME}" PROJECT_ROOT="${PROJECT_ROOT}" DOCKERFILE="${DOCKERFILE}" GLOBAL_STATE_DIR="${GLOBAL_STATE_DIR}" TRAEFIK_NAME="${TRAEFIK_NAME}" DEPLOY_NETWORK="${DEPLOY_NETWORK}" \
  HEALTH_CHECK="${HEALTH_CHECK}" INSTALL_PATH="${INSTALL_PATH}" CONTAINER_PORT="${CONTAINER_PORT}" python3 - <<'PYEOF'
import json, os

state = {
    "app": os.environ['APP_NAME'],
    "type": "cli",
    "project_root": os.environ['PROJECT_ROOT'],
    "active": "blue",
    "blue_port": None,
    "green_port": None,
    "dockerfile": os.environ['DOCKERFILE'],
    "health_check": os.environ['HEALTH_CHECK'],
    "install_path": os.environ['INSTALL_PATH'],
    "container_port": int(os.environ.get('CONTAINER_PORT') or 80),
    "last_deploy": None,
    "blue_image": None,
    "green_image": None,
    "global_state_dir": os.environ['GLOBAL_STATE_DIR'],
    "traefik_name": os.environ['TRAEFIK_NAME'],
    "deploy_network": os.environ['DEPLOY_NETWORK']
}
global_dir = os.environ['GLOBAL_STATE_DIR']
os.makedirs(global_dir, exist_ok=True)
path = os.path.join(global_dir, f"{state['app']}.json")
with open(path, 'w') as f:
    json.dump(state, f, indent=2)
print(f"deploy: global state written to {path}")
PYEOF

  # ── Local state (copy) ───────────────────────────────────────────────────
  mkdir -p "$(dirname "${STATE_FILE}")"
  GLOBAL_STATE_FILE="${GLOBAL_STATE_DIR}/${APP_NAME}.json"
  cp "${GLOBAL_STATE_FILE}" "${STATE_FILE}"
  echo "deploy: local state written to ${STATE_FILE}"

  # ── Wrapper script (optional) ─────────────────────────────────────────────
  if [ -n "${INSTALL_PATH}" ]; then
    APP_NAME="${APP_NAME}" INSTALL_PATH="${INSTALL_PATH}" GLOBAL_STATE_DIR="${GLOBAL_STATE_DIR}" python3 - <<'PYEOF'
import os, stat

app = os.environ['APP_NAME']
install_path = os.path.expanduser(os.environ['INSTALL_PATH'])
os.makedirs(install_path, exist_ok=True)

content = f"""#!/usr/bin/env bash
# {app} — wrapper installed by echelon deploy
# Reads active image tag from the Echelon deployment state and runs via Docker.
set -euo pipefail
_state_file="{os.environ['GLOBAL_STATE_DIR']}/{app}.json"
if [ ! -f "$_state_file" ]; then
  echo "✗ deploy state not found: $_state_file" >&2
  exit 1
fi
_active=$(python3 -c "import json; d=json.load(open('$_state_file')); print(d.get('active','blue'))")
_image=$(python3 -c "import json; d=json.load(open('$_state_file')); slot=d.get('active','blue'); print(d.get(slot+'_image') or '{app}:'+slot)")
exec docker run --rm "$_image" "$@"
"""

path = os.path.join(install_path, app)
with open(path, 'w') as f:
    f.write(content)
os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
print(f"deploy: wrapper installed at {path}")
PYEOF
  fi

  echo ""
  echo "════════════════════════════════════════"
  echo "  Deploy initialized for ${APP_NAME} (cli)"
  if [ -n "${INSTALL_PATH}" ]; then
    EXPANDED=$(INSTALL_PATH="${INSTALL_PATH}" python3 -c "import os; print(os.path.expanduser(os.environ['INSTALL_PATH']))")
    echo "  Wrapper: ${EXPANDED}/${APP_NAME}"
    echo "  Run:     ${APP_NAME} [args...]"
  else
    echo "  Run:     docker run --rm ${APP_NAME}:{active} [args...]"
  fi
  echo "════════════════════════════════════════"
  exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
# HTTP PATH — shared Traefik at :80, path-prefix routing per app
# ══════════════════════════════════════════════════════════════════════════════

# ── Port conflict check (blue/green only — active_port no longer per-app) ────
for f in "${GLOBAL_STATE_DIR}"/*.json; do
  [ -f "${f}" ] || continue
  OTHER_APP=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('app','?'))")
  [ "${OTHER_APP}" = "${APP_NAME}" ] && continue  # same app re-init is fine
  OTHER_BLUE=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('blue_port','') or '')")
  OTHER_GREEN=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('green_port','') or '')")
  for CLAIMED in "${OTHER_BLUE}" "${OTHER_GREEN}"; do
    for WANTED in "${BLUE_PORT}" "${GREEN_PORT}"; do
      if [ "${CLAIMED}" = "${WANTED}" ] && [ -n "${CLAIMED}" ]; then
        echo "✗ Port ${WANTED} is already claimed by app '${OTHER_APP}' (${f})." >&2
        echo "  Choose different blue_port/green_port in .echelon/config.yml." >&2
        exit 1
      fi
    done
  done
done

# ── Docker network ───────────────────────────────────────────────────────────
echo "deploy: ensuring ${DEPLOY_NETWORK} network exists..."
docker network create "${DEPLOY_NETWORK}" 2>/dev/null || echo "deploy: network already exists"

# ── Traefik: start once, never recreated for new apps ────────────────────────
# Traefik discovers new app containers automatically via Docker labels.
TRAEFIK_STATUS=$(docker inspect --format='{{.State.Status}}' "${TRAEFIK_NAME}" 2>/dev/null | tr -d '[:space:]' || true)
[ -z "${TRAEFIK_STATUS}" ] && TRAEFIK_STATUS="missing"

if [ "${TRAEFIK_STATUS}" = "running" ]; then
  echo "deploy: Traefik already running — no restart needed (new apps auto-discovered via labels)"
elif [ "${TRAEFIK_STATUS}" = "missing" ]; then
  echo "deploy: starting ${TRAEFIK_NAME} (single shared instance at :80)..."
  # Resolve the real Docker socket path (macOS Docker Desktop uses a symlink)
  _DOCKER_SOCK=$(realpath /var/run/docker.sock 2>/dev/null || echo /var/run/docker.sock)
  docker run -d \
    --name "${TRAEFIK_NAME}" \
    --network "${DEPLOY_NETWORK}" \
    -v "${_DOCKER_SOCK}:/var/run/docker.sock:ro" \
    -p 80:80 \
    --restart unless-stopped \
    traefik:latest \
      --providers.docker=true \
      --providers.docker.network="${DEPLOY_NETWORK}" \
      --entrypoints.web.address=:80

  echo "deploy: waiting for Traefik health check..."
  for i in 1 2 3 4 5; do
    sleep 1
    STATUS=$(docker inspect --format='{{.State.Status}}' "${TRAEFIK_NAME}" 2>/dev/null | tr -d '[:space:]' || true)
    [ "${STATUS}" = "running" ] && echo "deploy: Traefik is healthy" && break
    [ "${i}" = "5" ] && echo "✗ Traefik failed to start. Check: docker logs ${TRAEFIK_NAME}" >&2 && exit 1
  done
else
  echo "✗ ${TRAEFIK_NAME} exists but is not healthy (status: ${TRAEFIK_STATUS})." >&2
  echo "  Run: docker rm ${TRAEFIK_NAME}" >&2
  echo "  Then re-run echelon.init to reinitialize." >&2
  exit 1
fi

# ── Global state registration ────────────────────────────────────────────────
APP_NAME="${APP_NAME}" PROJECT_ROOT="${PROJECT_ROOT}" DOCKERFILE="${DOCKERFILE}" GLOBAL_STATE_DIR="${GLOBAL_STATE_DIR}" TRAEFIK_NAME="${TRAEFIK_NAME}" DEPLOY_NETWORK="${DEPLOY_NETWORK}" \
BLUE_PORT="${BLUE_PORT}" GREEN_PORT="${GREEN_PORT}" CONTAINER_PORT="${CONTAINER_PORT}" python3 - <<'PYEOF'
import json, os

state = {
    "app": os.environ['APP_NAME'],
    "type": "http",
    "project_root": os.environ['PROJECT_ROOT'],
    "active": "blue",
    "blue_port": int(os.environ['BLUE_PORT']),
    "green_port": int(os.environ['GREEN_PORT']),
    "dockerfile": os.environ['DOCKERFILE'],
    "health_check": "",
    "install_path": "",
    "container_port": int(os.environ.get('CONTAINER_PORT') or 80),
    "last_deploy": None,
    "blue_image": None,
    "green_image": None,
    "global_state_dir": os.environ['GLOBAL_STATE_DIR'],
    "traefik_name": os.environ['TRAEFIK_NAME'],
    "deploy_network": os.environ['DEPLOY_NETWORK']
}
global_dir = os.environ['GLOBAL_STATE_DIR']
os.makedirs(global_dir, exist_ok=True)
path = os.path.join(global_dir, f"{state['app']}.json")
with open(path, 'w') as f:
    json.dump(state, f, indent=2)
print(f"deploy: global state written to {path}")
PYEOF

# ── Local state (copy) ───────────────────────────────────────────────────────
mkdir -p "$(dirname "${STATE_FILE}")"
cp "${GLOBAL_STATE_DIR}/${APP_NAME}.json" "${STATE_FILE}"
echo "deploy: local state written to ${STATE_FILE}"

# ── SPA base-path auto-correction ────────────────────────────────────────────
if [ -f "${SCRIPTS_DIR}/fix-spa-base.sh" ]; then
  bash "${SCRIPTS_DIR}/fix-spa-base.sh" "${PROJECT_ROOT}" "${APP_NAME}"
fi

echo ""
echo "════════════════════════════════════════"
echo "  Deploy initialized for ${APP_NAME}"
echo "  Blue:    http://localhost:${BLUE_PORT}  (health check)"
echo "  Green:   http://localhost:${GREEN_PORT}  (health check)"
echo "  Live:    http://localhost/${APP_NAME}/"
echo "════════════════════════════════════════"
