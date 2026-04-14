#!/usr/bin/env bash
# deploy.sh — blue/green swap via Traefik
# Called by .git/hooks/post-merge (or manually via echelon.deploy)
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel)
STATE_FILE="${PROJECT_ROOT}/.specify/squad/deploy-state.json"

if [ ! -f "${STATE_FILE}" ]; then
  echo "✗ deploy-state.json not found. Run echelon.run first to initialize deploy." >&2
  exit 1
fi

# ── Read state ────────────────────────────────────────────────────────────────
_state=$(STATE_FILE="${STATE_FILE}" python3 - <<'PYEOF'
import os, sys, json
try:
    d = json.load(open(os.environ['STATE_FILE']))
    print(d['app'])
    print(d['active'])
    print(d['blue_port'])
    print(d['green_port'])
    print(d.get('dockerfile', 'Dockerfile'))
except Exception as e:
    sys.exit(f'Cannot read deploy state: {e}')
PYEOF
)
APP=$(echo "${_state}"       | sed -n '1p')
ACTIVE=$(echo "${_state}"    | sed -n '2p')
BLUE_PORT=$(echo "${_state}" | sed -n '3p')
GREEN_PORT=$(echo "${_state}"| sed -n '4p')
DOCKERFILE=$(echo "${_state}"| sed -n '5p')

INACTIVE=$([ "${ACTIVE}" = "blue" ] && echo "green" || echo "blue")
INACTIVE_PORT=$([ "${INACTIVE}" = "blue" ] && echo "${BLUE_PORT}" || echo "${GREEN_PORT}")

echo "deploy: ${APP} ${ACTIVE} → ${INACTIVE} (port ${INACTIVE_PORT})"

# ── Traefik health ────────────────────────────────────────────────────────────
TRAEFIK_STATUS=$(docker inspect --format='{{.State.Status}}' speckit-traefik 2>/dev/null || echo "missing")
if [ "${TRAEFIK_STATUS}" != "running" ]; then
  echo "✗ speckit-traefik is not running (status: ${TRAEFIK_STATUS})." >&2
  echo "  Run: docker start speckit-traefik" >&2
  exit 1
fi

# ── Remove stale inactive container if present ────────────────────────────────
if docker inspect "${APP}-${INACTIVE}" >/dev/null 2>&1; then
  echo "deploy: removing stale ${APP}-${INACTIVE}..."
  docker rm -f "${APP}-${INACTIVE}" >/dev/null
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "deploy: building ${APP}:candidate..."
docker build -t "${APP}:candidate" -f "${PROJECT_ROOT}/${DOCKERFILE}" "${PROJECT_ROOT}"

# ── Start inactive slot ───────────────────────────────────────────────────────
echo "deploy: starting ${APP}-${INACTIVE} on port ${INACTIVE_PORT}..."
docker run -d \
  --name "${APP}-${INACTIVE}" \
  --network speckit-deploy \
  --label "traefik.enable=true" \
  --label "traefik.http.routers.${APP}.rule=PathPrefix(\`/\`)" \
  --label "traefik.http.routers.${APP}.entrypoints=${APP}" \
  --label "traefik.http.services.${APP}.loadbalancer.server.port=80" \
  -p "${INACTIVE_PORT}:80" \
  "${APP}:candidate"

# ── Health check ──────────────────────────────────────────────────────────────
echo "deploy: health check on http://localhost:${INACTIVE_PORT}..."
HEALTHY=0
for i in 1 2 3 4 5; do
  sleep 2
  if curl -sf "http://localhost:${INACTIVE_PORT}" >/dev/null 2>&1; then
    HEALTHY=1
    echo "deploy: health check passed (attempt ${i})"
    break
  fi
  echo "deploy: attempt ${i}/5 — not yet healthy..."
done

if [ "${HEALTHY}" = "0" ]; then
  echo "✗ Health check failed after 5 attempts. Rolling back." >&2
  docker stop "${APP}-${INACTIVE}" 2>/dev/null || true
  docker rm "${APP}-${INACTIVE}" 2>/dev/null || true
  echo "  Active slot '${ACTIVE}' unchanged." >&2
  exit 1
fi

# ── Stop old slot ─────────────────────────────────────────────────────────────
echo "deploy: stopping ${APP}-${ACTIVE}..."
docker stop "${APP}-${ACTIVE}" 2>/dev/null || echo "  (${APP}-${ACTIVE} was not running)"

# ── Tag and update state ──────────────────────────────────────────────────────
docker tag "${APP}:candidate" "${APP}:${INACTIVE}"
echo "deploy: tagged ${APP}:candidate → ${APP}:${INACTIVE}"

STATE_FILE="${STATE_FILE}" APP="${APP}" INACTIVE="${INACTIVE}" python3 - <<'PYEOF'
import os, sys, json, datetime

state_file = os.environ['STATE_FILE']
app = os.environ['APP']
inactive = os.environ['INACTIVE']

with open(state_file) as f:
    state = json.load(f)

state['active'] = inactive
state[f'{inactive}_image'] = f'{app}:{inactive}'
state['last_deploy'] = datetime.datetime.utcnow().isoformat() + 'Z'

with open(state_file, 'w') as f:
    json.dump(state, f, indent=2)

# Mirror to global state (always write — creates if absent)
global_dir = os.path.expanduser("~/.speckit-deploy")
os.makedirs(global_dir, exist_ok=True)
global_state = os.path.join(global_dir, f"{state['app']}.json")
with open(global_state, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

ACTIVE_DISPLAY=$(STATE_FILE="${STATE_FILE}" python3 - <<'PYEOF'
import os, json
with open(os.environ['STATE_FILE']) as f:
    d = json.load(f)
print(d.get('active_port', '?'))
PYEOF
)
echo ""
echo "════════════════════════════════════════"
echo "  ✓ ${APP} deployed"
echo "  Slot:   ${INACTIVE} (was ${ACTIVE})"
echo "  Live:   http://localhost:${ACTIVE_DISPLAY}"
echo "════════════════════════════════════════"
