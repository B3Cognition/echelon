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
  echo "  Add a deploy: block with blue_port, green_port, active_port." >&2
  echo "  See config-template.yml for reference." >&2
  exit 1
fi

BLUE_PORT=$(python3 -c "
import sys
try:
    import yaml
    c = yaml.safe_load(open('${ECHELON_YML}'))
    print(c['deploy']['blue_port'])
except Exception as e:
    sys.exit(f'Cannot read blue_port: {e}')
")
GREEN_PORT=$(python3 -c "
import sys
try:
    import yaml
    c = yaml.safe_load(open('${ECHELON_YML}'))
    print(c['deploy']['green_port'])
except Exception as e:
    sys.exit(f'Cannot read green_port: {e}')
")
ACTIVE_PORT=$(python3 -c "
import sys
try:
    import yaml
    c = yaml.safe_load(open('${ECHELON_YML}'))
    print(c['deploy']['active_port'])
except Exception as e:
    sys.exit(f'Cannot read active_port: {e}')
")
DOCKERFILE=$(python3 -c "
import sys
try:
    import yaml
    c = yaml.safe_load(open('${ECHELON_YML}'))
    print(c.get('deploy', {}).get('dockerfile', 'Dockerfile'))
except Exception:
    print('Dockerfile')
")

APP_NAME=$(basename "${PROJECT_ROOT}" | tr '[:upper:]' '[:lower:]')

# ── Port conflict check ──────────────────────────────────────────────────────
# Scan all deploy-state.json files under ~/.speckit-deploy/ for port conflicts
GLOBAL_STATE_DIR="${HOME}/.speckit-deploy"
mkdir -p "${GLOBAL_STATE_DIR}"

for f in "${GLOBAL_STATE_DIR}"/*.json; do
  [ -f "${f}" ] || continue
  OTHER_APP=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('app','?'))")
  OTHER_BLUE=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('blue_port',''))")
  OTHER_GREEN=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('green_port',''))")
  OTHER_ACTIVE=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('active_port',''))")
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
  EP=$(python3 -c "import json; d=json.load(open('${f}')); print(d.get('active_port',''))")
  [ -n "${EA}" ] && [ -n "${EP}" ] && ENTRYPOINT_FLAGS="${ENTRYPOINT_FLAGS} --entrypoints.${EA}.address=:${EP}"
done
# Add this app's entrypoint
ENTRYPOINT_FLAGS="${ENTRYPOINT_FLAGS} --entrypoints.${APP_NAME}.address=:${ACTIVE_PORT}"

# Check if Traefik exists
TRAEFIK_STATUS=$(docker inspect --format='{{.State.Status}}' speckit-traefik 2>/dev/null || echo "missing")

if [ "${TRAEFIK_STATUS}" = "running" ]; then
  echo "deploy: Traefik running — recreating with updated entrypoints..."
  docker stop speckit-traefik >/dev/null
  docker rm speckit-traefik >/dev/null
elif [ "${TRAEFIK_STATUS}" != "missing" ]; then
  echo "deploy: Traefik container exists but is not running (status: ${TRAEFIK_STATUS}) — removing..."
  docker rm -f speckit-traefik >/dev/null
fi

echo "deploy: starting speckit-traefik..."
# shellcheck disable=SC2086
docker run -d \
  --name speckit-traefik \
  --network speckit-deploy \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  --restart unless-stopped \
  $(for port in $(echo "${ENTRYPOINT_FLAGS}" | grep -oP ':\d+' | tr -d ':' | sort -u); do
      echo "-p ${port}:${port}"; done) \
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
cat > "${GIT_HOOK}" << HOOK
#!/usr/bin/env bash
# Installed by echelon deploy-init.sh
exec "${SCRIPTS_DIR}/deploy.sh"
HOOK
chmod +x "${GIT_HOOK}"
echo "deploy: hook installed at ${GIT_HOOK}"

# ── Global state registration ────────────────────────────────────────────────
GLOBAL_STATE_FILE="${GLOBAL_STATE_DIR}/${APP_NAME}.json"
python3 - << PYEOF
import json, datetime
state = {
    "app": "${APP_NAME}",
    "project_root": "${PROJECT_ROOT}",
    "active": "blue",
    "blue_port": ${BLUE_PORT},
    "green_port": ${GREEN_PORT},
    "active_port": ${ACTIVE_PORT},
    "dockerfile": "${DOCKERFILE}",
    "last_deploy": None,
    "blue_image": None,
    "green_image": None
}
with open("${GLOBAL_STATE_FILE}", "w") as f:
    json.dump(state, f, indent=2)
print(f"deploy: global state written to ${GLOBAL_STATE_FILE}")
PYEOF

# ── Local state (copy) ───────────────────────────────────────────────────────
mkdir -p "$(dirname "${STATE_FILE}")"
cp "${GLOBAL_STATE_FILE}" "${STATE_FILE}"
echo "deploy: local state written to ${STATE_FILE}"

echo ""
echo "════════════════════════════════════════"
echo "  Deploy initialized for ${APP_NAME}"
echo "  Blue:    http://localhost:${BLUE_PORT}"
echo "  Green:   http://localhost:${GREEN_PORT}"
echo "  Active:  http://localhost:${ACTIVE_PORT}"
echo "  Hook:    ${GIT_HOOK}"
echo "════════════════════════════════════════"
