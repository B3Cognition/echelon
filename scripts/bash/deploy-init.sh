#!/usr/bin/env bash
# deploy-init.sh — one-time blue/green deploy infrastructure setup
# Called from echelon.run section 1.0. Idempotent: exits 0 immediately if
# .specify/squad/deploy-state.json already exists.
set -euo pipefail

# ── Args ────────────────────────────────────────────────────────────────────
PROJECT_ROOT="${1:?PROJECT_ROOT required as first argument}"
ECHELON_YML="${2:-${PROJECT_ROOT}/echelon.yml}"
STATE_FILE="${PROJECT_ROOT}/.specify/squad/deploy-state.json"
SCRIPTS_DIR="${PROJECT_ROOT}/.specify/scripts"

# ── Idempotency guard ────────────────────────────────────────────────────────
if [ -f "${STATE_FILE}" ]; then
  echo "deploy: already initialized (${STATE_FILE} exists) — skipping"
  exit 0
fi

# ── Read config ──────────────────────────────────────────────────────────────
if ! grep -q "^deploy:" "${ECHELON_YML}" 2>/dev/null; then
  echo "✗ deploy config missing in echelon.yml." >&2
  echo "  Add a deploy: block with type: http|cli." >&2
  echo "  See config-template.yml for reference." >&2
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
        print(d.get('active_port', ''))
        print('')
        print('')
    else:
        print('')
        print('')
        print('')
        print(d.get('health_check', ''))
        print(d.get('install_path', ''))
except KeyError as e:
    sys.exit(f'Cannot read deploy config key {e} from echelon.yml')
except Exception as e:
    sys.exit(f'Cannot read deploy config: {e}')
PYEOF
)
DEPLOY_TYPE=$(echo "${_config}"  | sed -n '1p')
DOCKERFILE=$(echo "${_config}"   | sed -n '2p')
BLUE_PORT=$(echo "${_config}"    | sed -n '3p')
GREEN_PORT=$(echo "${_config}"   | sed -n '4p')
ACTIVE_PORT=$(echo "${_config}"  | sed -n '5p')
HEALTH_CHECK=$(echo "${_config}" | sed -n '6p')
INSTALL_PATH=$(echo "${_config}" | sed -n '7p')

APP_NAME=$(basename "${PROJECT_ROOT}" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')

GLOBAL_STATE_DIR="${HOME}/.speckit-deploy"
mkdir -p "${GLOBAL_STATE_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
# CLI PATH
# ══════════════════════════════════════════════════════════════════════════════
if [ "${DEPLOY_TYPE}" = "cli" ]; then
  echo "deploy: type=cli — skipping Traefik/network setup"

  # ── Git hook ───────────────────────────────────────────────────────────────
  GIT_HOOK="${PROJECT_ROOT}/.git/hooks/post-merge"
  echo "deploy: installing git post-merge hook..."
  cat > "${GIT_HOOK}" << 'HOOK'
#!/usr/bin/env bash
# Installed by echelon deploy-init.sh
SCRIPTS_DIR="$(git rev-parse --show-toplevel)/.specify/scripts"
exec "${SCRIPTS_DIR}/deploy.sh"
HOOK
  chmod +x "${GIT_HOOK}"
  echo "deploy: hook installed at ${GIT_HOOK}"

  # ── Global state ──────────────────────────────────────────────────────────
  APP_NAME="${APP_NAME}" PROJECT_ROOT="${PROJECT_ROOT}" DOCKERFILE="${DOCKERFILE}" \
  HEALTH_CHECK="${HEALTH_CHECK}" INSTALL_PATH="${INSTALL_PATH}" python3 - <<'PYEOF'
import json, os

state = {
    "app": os.environ['APP_NAME'],
    "type": "cli",
    "project_root": os.environ['PROJECT_ROOT'],
    "active": "blue",
    "blue_port": None,
    "green_port": None,
    "active_port": None,
    "dockerfile": os.environ['DOCKERFILE'],
    "health_check": os.environ['HEALTH_CHECK'],
    "install_path": os.environ['INSTALL_PATH'],
    "last_deploy": None,
    "blue_image": None,
    "green_image": None
}
global_dir = os.path.expanduser("~/.speckit-deploy")
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
    APP_NAME="${APP_NAME}" INSTALL_PATH="${INSTALL_PATH}" python3 - <<'PYEOF'
import os, stat

app = os.environ['APP_NAME']
install_path = os.path.expanduser(os.environ['INSTALL_PATH'])
os.makedirs(install_path, exist_ok=True)

content = f"""#!/usr/bin/env bash
# {app} — wrapper installed by echelon deploy
# Reads active image tag from ~/.speckit-deploy/{app}.json and runs via Docker.
set -euo pipefail
_state_file="$HOME/.speckit-deploy/{app}.json"
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
  echo "  Hook:    ${GIT_HOOK}"
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
# HTTP PATH (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════

# ── Port conflict check ──────────────────────────────────────────────────────
for f in "${GLOBAL_STATE_DIR}"/*.json; do
  [ -f "${f}" ] || continue
  OTHER_APP=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('app','?'))")
  OTHER_BLUE=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('blue_port','') or '')")
  OTHER_GREEN=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('green_port','') or '')")
  OTHER_ACTIVE=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('active_port','') or '')")
  for CLAIMED in "${OTHER_BLUE}" "${OTHER_GREEN}" "${OTHER_ACTIVE}"; do
    for WANTED in "${BLUE_PORT}" "${GREEN_PORT}" "${ACTIVE_PORT}"; do
      if [ "${CLAIMED}" = "${WANTED}" ] && [ -n "${CLAIMED}" ]; then
        echo "✗ Port ${WANTED} is already claimed by app '${OTHER_APP}' (${f})." >&2
        echo "  Choose different ports in echelon.yml." >&2
        exit 1
      fi
    done
  done
done

# ── Docker network ───────────────────────────────────────────────────────────
echo "deploy: creating speckit-deploy network..."
docker network create speckit-deploy 2>/dev/null || echo "deploy: network already exists"

# ── Traefik: build merged entrypoint flags from all registered apps ──────────
ENTRYPOINT_FLAGS=""
for f in "${GLOBAL_STATE_DIR}"/*.json; do
  [ -f "${f}" ] || continue
  EA=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('app',''))")
  EP=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('active_port','') or '')")
  [ -n "${EA}" ] && [ -n "${EP}" ] && ENTRYPOINT_FLAGS="${ENTRYPOINT_FLAGS} --entrypoints.${EA}.address=:${EP}"
done
ENTRYPOINT_FLAGS="${ENTRYPOINT_FLAGS} --entrypoints.${APP_NAME}.address=:${ACTIVE_PORT}"

# Check if Traefik exists
TRAEFIK_STATUS=$(docker inspect --format='{{.State.Status}}' speckit-traefik 2>/dev/null || echo "missing")

if [ "${TRAEFIK_STATUS}" = "running" ]; then
  echo "deploy: Traefik running — recreating with updated entrypoints..."
  docker stop speckit-traefik >/dev/null
  docker rm speckit-traefik >/dev/null
elif [ "${TRAEFIK_STATUS}" != "missing" ]; then
  echo "✗ speckit-traefik exists but is not healthy (status: ${TRAEFIK_STATUS})." >&2
  echo "  Run: docker rm speckit-traefik" >&2
  echo "  Then re-run echelon.run to reinitialize." >&2
  exit 1
fi

echo "deploy: starting speckit-traefik..."
# shellcheck disable=SC2086
docker run -d \
  --name speckit-traefik \
  --network speckit-deploy \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --restart unless-stopped \
  $(echo "${ENTRYPOINT_FLAGS}" | grep -oE ':[0-9]+' | tr -d ':' | sort -u | while IFS= read -r port; do echo "-p ${port}:${port}"; done) \
  traefik:v3 \
    --providers.docker=true \
    --providers.docker.network=speckit-deploy \
    ${ENTRYPOINT_FLAGS}

# Verify Traefik healthy
echo "deploy: waiting for Traefik health check..."
for i in 1 2 3 4 5; do
  sleep 1
  STATUS=$(docker inspect --format='{{.State.Status}}' speckit-traefik 2>/dev/null || echo "missing")
  if [ "${STATUS}" = "running" ]; then
    echo "deploy: Traefik is healthy"
    break
  fi
  if [ "${i}" = "5" ]; then
    echo "✗ Traefik failed to start. Check: docker logs speckit-traefik" >&2
    exit 1
  fi
done

# ── Git hook ─────────────────────────────────────────────────────────────────
GIT_HOOK="${PROJECT_ROOT}/.git/hooks/post-merge"
echo "deploy: installing git post-merge hook..."
cat > "${GIT_HOOK}" << 'HOOK'
#!/usr/bin/env bash
# Installed by echelon deploy-init.sh
SCRIPTS_DIR="$(git rev-parse --show-toplevel)/.specify/scripts"
exec "${SCRIPTS_DIR}/deploy.sh"
HOOK
chmod +x "${GIT_HOOK}"
echo "deploy: hook installed at ${GIT_HOOK}"

# ── Global state registration ────────────────────────────────────────────────
APP_NAME="${APP_NAME}" PROJECT_ROOT="${PROJECT_ROOT}" DOCKERFILE="${DOCKERFILE}" \
BLUE_PORT="${BLUE_PORT}" GREEN_PORT="${GREEN_PORT}" ACTIVE_PORT="${ACTIVE_PORT}" python3 - <<'PYEOF'
import json, os

state = {
    "app": os.environ['APP_NAME'],
    "type": "http",
    "project_root": os.environ['PROJECT_ROOT'],
    "active": "blue",
    "blue_port": int(os.environ['BLUE_PORT']),
    "green_port": int(os.environ['GREEN_PORT']),
    "active_port": int(os.environ['ACTIVE_PORT']),
    "dockerfile": os.environ['DOCKERFILE'],
    "health_check": "",
    "install_path": "",
    "last_deploy": None,
    "blue_image": None,
    "green_image": None
}
global_dir = os.path.expanduser("~/.speckit-deploy")
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

echo ""
echo "════════════════════════════════════════"
echo "  Deploy initialized for ${APP_NAME}"
echo "  Blue:    http://localhost:${BLUE_PORT}"
echo "  Green:   http://localhost:${GREEN_PORT}"
echo "  Active:  http://localhost:${ACTIVE_PORT}"
echo "  Hook:    ${GIT_HOOK}"
echo "════════════════════════════════════════"
