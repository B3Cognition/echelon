# Local CD — CLI Mode (`type: cli`) Implementation Plan

> **SUPERSEDED** — see README.md "Local CD" section for current architecture. Architecture change 2026-04-16: `active_port` removed from HTTP mode; CLI mode unchanged.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the echelon blue/green deployment system with a `type: cli` mode for terminal apps running in Docker — no Traefik, no long-lived containers, just build → optional health check via `docker run --rm` → tag image → update state pointer → optional wrapper script.

**Architecture:** All existing HTTP machinery is preserved unchanged. CLI mode is a full early-exit branch (`if [ "${DEPLOY_TYPE}" = "cli" ]; then ... exit 0; fi`) in each script. A `type` field is added to both config and state. The wrapper script reads the active tag from `~/.speckit-deploy/{app}.json` at runtime so rollbacks are instantly reflected with no wrapper reinstall.

**Tech Stack:** Bash, Docker CLI, Python 3 (JSON/YAML), YAML (config-template.yml), Markdown (README).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `config-template.yml` | Modify | Add `type:` + CLI-only fields with annotation comments |
| `echelon-config.yml` | Modify | Add `type: http` to test project config |
| `scripts/bash/deploy-init.sh` | Modify | Type-aware: CLI path skips Traefik/network; installs wrapper if `install_path` set |
| `scripts/bash/deploy.sh` | Modify | Type-aware: CLI path does docker run --rm health check + tag+state only |
| `scripts/bash/deploy-status.sh` | Modify | CLI-aware display: active image + wrapper path |
| `commands/echelon.deploy.md` | Modify | CLI-aware rollback (pointer swap only, no container restart) |
| `commands/echelon.run.md` | Modify | Section 1.0 validation: type-aware port field requirements |
| `README.md` | Modify | Add "Local CD" section with HTTP + CLI examples + command reference |

---

## Backward Compatibility

All new fields (`type`, `health_check`, `install_path`) use `.get()` with safe defaults everywhere. Existing HTTP state files without a `type` field continue to work — scripts default to `'http'` via `d.get('type', 'http')`. No migration needed.

---

## Task 1: Update `config-template.yml` and `echelon-config.yml`

**Files:**
- Modify: `config-template.yml`
- Modify: `echelon-config.yml`

- [ ] **Step 1: Replace the `deploy:` block in `config-template.yml`**

Find the existing `deploy:` block (currently starts with a `# DEPLOY` comment header). Replace everything from that header to the end of the file with:

```yaml
# =============================================================================
# DEPLOY — Blue/green local CD
# =============================================================================

deploy:
  # Deployment type. Controls which infrastructure is used.
  # [values: http | cli]  Default: http
  # - http: Traefik reverse proxy, two long-lived containers (blue/green), curl health check
  # - cli:  No Traefik, no containers — build → optional health check → tag → state pointer
  type: http

  # ── HTTP only ──────────────────────────────────────────────────────────────
  # Host port for the blue slot container
  # [range: 1024-65535] Must not conflict with other apps registered in deploy-state.json
  blue_port: 3000

  # Host port for the green slot container
  # [range: 1024-65535] Must not conflict with other apps registered in deploy-state.json
  green_port: 3001

  # Traefik entry point port — the port Traefik binds on the host (e.g. 80 for http://localhost)
  # [range: 1-65535] Typically 80, 81, 82... one per app
  active_port: 80

  # ── CLI only ───────────────────────────────────────────────────────────────
  # Command run inside the candidate container to verify the build is healthy.
  # Example: "myapp --version"   Empty string (default) = skip health check.
  # health_check: ""

  # Directory where the wrapper script is installed. Empty = no wrapper installed.
  # Wrapper reads active tag at runtime — rollbacks are instant, no reinstall needed.
  # Example: "~/.local/bin"
  # install_path: ""

  # ── Shared ─────────────────────────────────────────────────────────────────
  # Path to Dockerfile relative to project root. Optional — defaults to "Dockerfile"
  # The Dockerfile must: COPY the build output, install a server/entrypoint, EXPOSE port 80.
  # Example minimal Dockerfile for a Vite/React app:
  #   FROM nginx:alpine
  #   COPY dist/ /usr/share/nginx/html/
  #   EXPOSE 80
  # dockerfile: Dockerfile
```

- [ ] **Step 2: Update `echelon-config.yml` deploy block**

In `echelon-config.yml`, replace the `deploy:` block with:

```yaml
deploy:
  type: http             # http (default) | cli
  blue_port: 3000        # blue slot
  green_port: 3001       # green slot
  active_port: 80        # Traefik entry point (http://localhost)
```

- [ ] **Step 3: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('config-template.yml'))" && echo "config-template OK"
python3 -c "import yaml; yaml.safe_load(open('echelon-config.yml'))" && echo "echelon-config OK"
```

Expected: both print OK.

- [ ] **Step 4: Commit**

```bash
git add config-template.yml echelon-config.yml
git commit -m "feat(deploy): add type field and CLI-only fields to config templates"
```

---

## Task 2: Update `scripts/bash/deploy-init.sh`

**File:** `scripts/bash/deploy-init.sh`

- [ ] **Step 1: Replace the entire file**

Write the following content to `scripts/bash/deploy-init.sh`:

```bash
#!/usr/bin/env bash
# deploy-init.sh — one-time blue/green deploy infrastructure setup
# Called from echelon.run section 1.0. Idempotent: exits 0 immediately if
# .specify/squad/deploy-state.json already exists.
set -euo pipefail

# ── Args ────────────────────────────────────────────────────────────────────
PROJECT_ROOT="${1:?PROJECT_ROOT required as first argument}"
ECHELON_YML="${2:-${PROJECT_ROOT}/echelon-config.yml}"
STATE_FILE="${PROJECT_ROOT}/.specify/squad/deploy-state.json"
SCRIPTS_DIR="${PROJECT_ROOT}/.specify/scripts"

# ── Idempotency guard ────────────────────────────────────────────────────────
if [ -f "${STATE_FILE}" ]; then
  echo "deploy: already initialized (${STATE_FILE} exists) — skipping"
  exit 0
fi

# ── Read config ──────────────────────────────────────────────────────────────
if ! grep -q "^deploy:" "${ECHELON_YML}" 2>/dev/null; then
  echo "✗ deploy config missing in echelon-config.yml." >&2
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
    sys.exit(f'Cannot read deploy config key {e} from echelon-config.yml')
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

APP_NAME=$(basename "${PROJECT_ROOT}" | tr '[:upper:]' '[:lower:]')

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
  GLOBAL_STATE_FILE="${GLOBAL_STATE_DIR}/${APP_NAME}.json"
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
    EXPANDED=$(python3 -c "import os; print(os.path.expanduser('${INSTALL_PATH}'))")
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
        echo "  Choose different ports in echelon-config.yml." >&2
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
GLOBAL_STATE_FILE="${GLOBAL_STATE_DIR}/${APP_NAME}.json"
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
```

- [ ] **Step 2: Syntax check**

```bash
bash -n scripts/bash/deploy-init.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/bash/deploy-init.sh
git commit -m "feat(deploy): type-aware deploy-init.sh — CLI path skips Traefik, installs wrapper"
```

---

## Task 3: Update `scripts/bash/deploy.sh`

**File:** `scripts/bash/deploy.sh`

- [ ] **Step 1: Replace the entire file**

Write the following content to `scripts/bash/deploy.sh`:

```bash
#!/usr/bin/env bash
# deploy.sh — blue/green swap (http) or tag-pointer swap (cli)
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
    with open(os.environ['STATE_FILE']) as f:
        d = json.load(f)
    print(d.get('type', 'http'))
    print(d['app'])
    print(d['active'])
    print(d.get('blue_port') or '')
    print(d.get('green_port') or '')
    print(d.get('dockerfile', 'Dockerfile'))
    print(d.get('health_check', ''))
    print(d.get('install_path', ''))
except Exception as e:
    sys.exit(f'Cannot read deploy state: {e}')
PYEOF
)
DEPLOY_TYPE=$(echo "${_state}"   | sed -n '1p')
APP=$(echo "${_state}"           | sed -n '2p')
ACTIVE=$(echo "${_state}"        | sed -n '3p')
BLUE_PORT=$(echo "${_state}"     | sed -n '4p')
GREEN_PORT=$(echo "${_state}"    | sed -n '5p')
DOCKERFILE=$(echo "${_state}"    | sed -n '6p')
HEALTH_CHECK=$(echo "${_state}"  | sed -n '7p')
INSTALL_PATH=$(echo "${_state}"  | sed -n '8p')

INACTIVE=$([ "${ACTIVE}" = "blue" ] && echo "green" || echo "blue")

# ══════════════════════════════════════════════════════════════════════════════
# CLI PATH
# ══════════════════════════════════════════════════════════════════════════════
if [ "${DEPLOY_TYPE}" = "cli" ]; then
  echo "deploy: ${APP} (cli) ${ACTIVE} → ${INACTIVE}"

  # ── Build ─────────────────────────────────────────────────────────────────
  echo "deploy: building ${APP}:candidate..."
  docker build -t "${APP}:candidate" -f "${PROJECT_ROOT}/${DOCKERFILE}" "${PROJECT_ROOT}"

  # ── Health check (optional) ───────────────────────────────────────────────
  # HEALTH_CHECK is intentionally unquoted so multi-word commands split correctly
  # (e.g. "myapp --version" becomes: docker run --rm myapp:candidate myapp --version)
  if [ -n "${HEALTH_CHECK}" ]; then
    echo "deploy: health check — docker run --rm ${APP}:candidate ${HEALTH_CHECK}"
    # shellcheck disable=SC2086
    if ! docker run --rm "${APP}:candidate" ${HEALTH_CHECK}; then
      echo "✗ Health check failed. Rolling back (build discarded)." >&2
      echo "  Active slot '${ACTIVE}' unchanged." >&2
      exit 1
    fi
    echo "deploy: health check passed"
  else
    echo "deploy: health check skipped (health_check not configured)"
  fi

  # ── Tag ───────────────────────────────────────────────────────────────────
  docker tag "${APP}:candidate" "${APP}:${INACTIVE}"
  echo "deploy: tagged ${APP}:candidate → ${APP}:${INACTIVE}"

  # ── Update state ──────────────────────────────────────────────────────────
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

global_dir = os.path.expanduser("~/.speckit-deploy")
os.makedirs(global_dir, exist_ok=True)
global_state = os.path.join(global_dir, f"{state['app']}.json")
with open(global_state, 'w') as f:
    json.dump(state, f, indent=2)
PYEOF

  echo ""
  echo "════════════════════════════════════════"
  echo "  ✓ ${APP} deployed (cli)"
  echo "  Slot:   ${INACTIVE} (was ${ACTIVE})"
  echo "  Image:  ${APP}:${INACTIVE}"
  if [ -n "${INSTALL_PATH}" ]; then
    EXPANDED=$(python3 -c "import os; print(os.path.expanduser('${INSTALL_PATH}'))")
    echo "  Run:    ${EXPANDED}/${APP} [args...]"
  else
    echo "  Run:    docker run --rm ${APP}:${INACTIVE} [args...]"
  fi
  echo "════════════════════════════════════════"
  exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
# HTTP PATH (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════
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
```

- [ ] **Step 2: Syntax check**

```bash
bash -n scripts/bash/deploy.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/bash/deploy.sh
git commit -m "feat(deploy): type-aware deploy.sh — CLI path with docker run --rm health check"
```

---

## Task 4: Update `scripts/bash/deploy-status.sh`

**File:** `scripts/bash/deploy-status.sh`

- [ ] **Step 1: Replace the entire file**

Write the following content to `scripts/bash/deploy-status.sh`:

```bash
#!/usr/bin/env bash
# deploy-status.sh — print active slot, image/port info, last deploy
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
    EXPANDED=$(python3 -c "import os; print(os.path.expanduser('${INSTALL_PATH}'))")
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
```

- [ ] **Step 2: Syntax check**

```bash
bash -n scripts/bash/deploy-status.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/bash/deploy-status.sh
git commit -m "feat(deploy): type-aware deploy-status.sh — CLI shows active image + wrapper path"
```

---

## Task 5: Update `commands/echelon.deploy.md`

**File:** `commands/echelon.deploy.md`

- [ ] **Step 1: Replace the entire file**

Write the following content to `commands/echelon.deploy.md`:

```markdown
---
name: speckit.echelon.deploy
description: "Manual deploy trigger, status, and rollback for blue/green and CLI local CD"
behavior:
  invocation: explicit
---

## User Input

$ARGUMENTS

---

## Overview

Manual control over the deployment. The automated path is the `post-merge` git hook → `deploy.sh`. Use this command for status checks, manual deploys, and rollback.

---

## Routing

Parse `$ARGUMENTS`:

- Empty or `deploy` → **Run Deploy**
- `status` → **Show Status**
- `rollback` → **Run Rollback**

---

## Run Deploy

```bash
bash .specify/scripts/deploy.sh
```

Report the full output. If exit code is non-zero, report the error and stop.

---

## Show Status

```bash
bash .specify/scripts/deploy-status.sh
```

Report the full output.

---

## Run Rollback

First read the deploy type:

```bash
python3 -c "
import json
with open('.specify/squad/deploy-state.json') as f:
    d = json.load(f)
print(d.get('type', 'http'))
"
```

### If type = cli

CLI rollback: swap the active pointer in state.json. No containers to restart — the wrapper script picks up the change on next invocation.

```bash
python3 - <<'PYEOF'
import sys, json, datetime, os

with open('.specify/squad/deploy-state.json') as f:
    state = json.load(f)

app = state['app']
active = state['active']
inactive = 'green' if active == 'blue' else 'blue'
inactive_image = state.get(f'{inactive}_image')

if not inactive_image:
    print(f"✗ No previous {inactive} image to roll back to.", file=sys.stderr)
    sys.exit(1)

print(f"rollback: {app} (cli) {active} → {inactive}")

state['active'] = inactive
state['last_deploy'] = datetime.datetime.utcnow().isoformat() + 'Z'

with open('.specify/squad/deploy-state.json', 'w') as f:
    json.dump(state, f, indent=2)

global_dir = os.path.expanduser('~/.speckit-deploy')
os.makedirs(global_dir, exist_ok=True)
with open(os.path.join(global_dir, f"{app}.json"), 'w') as f:
    json.dump(state, f, indent=2)

install_path = state.get('install_path', '')
if install_path:
    expanded = os.path.expanduser(install_path)
    print(f"\n✓ Rolled back to {inactive}")
    print(f"  Image: {inactive_image}")
    print(f"  Run:   {expanded}/{app} [args...]")
else:
    print(f"\n✓ Rolled back to {inactive}")
    print(f"  Image: {inactive_image}")
    print(f"  Run:   docker run --rm {inactive_image} [args...]")
PYEOF
```

If exit code is non-zero, report the error and stop.

### If type = http

HTTP rollback: restart the previously-stopped inactive container and flip the state pointer.

```bash
python3 - <<'PYEOF'
import os, sys, json, subprocess, datetime

with open('.specify/squad/deploy-state.json') as f:
    state = json.load(f)

app = state['app']
active = state['active']
inactive = 'green' if active == 'blue' else 'blue'
inactive_image = state.get(f'{inactive}_image')

if not inactive_image:
    print(f"✗ No previous {inactive} image to roll back to.", file=sys.stderr)
    sys.exit(1)

print(f"rollback: {app} {active} → {inactive}")

# Start the inactive slot (stopped, not removed)
result = subprocess.run(['docker', 'start', f'{app}-{inactive}'], capture_output=True, text=True)
if result.returncode != 0:
    print(f"✗ Could not start {app}-{inactive}: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Stop the current active slot
subprocess.run(['docker', 'stop', f'{app}-{active}'], capture_output=True)

state['active'] = inactive
state['last_deploy'] = datetime.datetime.utcnow().isoformat() + 'Z'
with open('.specify/squad/deploy-state.json', 'w') as f:
    json.dump(state, f, indent=2)

global_dir = os.path.expanduser('~/.speckit-deploy')
os.makedirs(global_dir, exist_ok=True)
with open(os.path.join(global_dir, f"{app}.json"), 'w') as f:
    json.dump(state, f, indent=2)

active_port = state.get('active_port', '?')
print(f"\n✓ Rolled back to {inactive}")
print(f"  Live: http://localhost:{active_port}")
PYEOF
```

If exit code is non-zero, report the error and stop.
```

- [ ] **Step 2: Commit**

```bash
git add commands/echelon.deploy.md
git commit -m "feat(deploy): type-aware rollback — CLI pointer swap, HTTP container restart"
```

---

## Task 6: Update `commands/echelon.run.md` section 1.0 validation

**File:** `commands/echelon.run.md`

- [ ] **Step 1: Replace the validation Python snippet**

Find the `**Validate deploy config:**` block in section 1.0. Replace only the `python3 -c "..."` snippet (everything from the opening triple-backtick through the closing one) with:

```bash
python3 -c "
import sys, yaml
try:
    c = yaml.safe_load(open('echelon-config.yml'))
    d = c.get('deploy', {})
    deploy_type = d.get('type', 'http')
    if deploy_type not in ('http', 'cli'):
        print(f'✗ deploy.type must be http or cli, got: {deploy_type}', file=sys.stderr)
        sys.exit(1)
    if deploy_type == 'http':
        missing = [k for k in ['blue_port','green_port','active_port'] if k not in d]
        if missing:
            print('✗ deploy config missing in echelon-config.yml.', file=sys.stderr)
            print('  HTTP type requires: blue_port, green_port, active_port.', file=sys.stderr)
            print('  See config-template.yml for reference.', file=sys.stderr)
            sys.exit(1)
except FileNotFoundError:
    print('✗ echelon-config.yml not found.', file=sys.stderr)
    sys.exit(1)
"
```

Also update the error hint text in the surrounding paragraph from:

> Add a deploy: block with blue_port, green_port, active_port.

to:

> Add a deploy: block with type: http|cli. For http, include blue_port, green_port, active_port.

- [ ] **Step 2: Commit**

```bash
git add commands/echelon.run.md
git commit -m "feat(deploy): type-aware deploy config validation in echelon.run.md"
```

---

## Task 7: Update `README.md` — Add "Local CD" section

**File:** `README.md`

- [ ] **Step 1: Add the deploy command row to the Commands table**

Find the Commands table (line ~209). Add a row for `speckit.echelon.deploy` after `speckit.echelon.feedback`:

```markdown
| `speckit.echelon.deploy` | Trigger deploy, check status, or rollback |
```

- [ ] **Step 2: Insert the "Local CD" section**

Insert the following section after the Configuration section (after the `See config-template.yml for full reference...` line) and before `## Innovation Templates`:

```markdown
## Local CD

Echelon includes built-in local continuous delivery. After `harness.run` merges a feature branch to main, a `post-merge` git hook fires `deploy.sh` automatically. Two deployment types are supported — `http` for web services and `cli` for terminal apps.

Both types run the app in Docker to keep the dev machine clean.

### HTTP — Zero-downtime blue/green via Traefik

For web apps. Two Docker containers run concurrently. On each deploy, the inactive slot is started, health-checked via `curl`, then Traefik switches traffic.

**Config (`echelon-config.yml`):**

```yaml
deploy:
  type: http
  blue_port: 3000    # blue slot host port
  green_port: 3001   # green slot host port
  active_port: 80    # Traefik entry point (http://localhost)
```

**Dockerfile (minimal Vite/React example):**

```dockerfile
FROM nginx:alpine
COPY dist/ /usr/share/nginx/html/
EXPOSE 80
```

**What happens on first `echelon.run`:**
- Docker network `speckit-deploy` created (shared across all apps on this machine)
- `speckit-traefik` container started (one per machine, auto-discovers apps via Docker labels)
- `.git/hooks/post-merge` installed

**Deploy flow (automatic after merge to main):**
1. `docker build` → `{app}:candidate`
2. Start inactive slot with Traefik labels, expose on its port
3. `curl -sf http://localhost:{port}` — 5 attempts, 2s apart
4. On success: stop old slot, tag image, update state
5. On failure: stop new slot, old slot unchanged (automatic rollback)

**Rollback:** `speckit.echelon.deploy rollback` restarts the stopped inactive container and flips Traefik routing.

---

### CLI — Image-tag pointer swap

For terminal apps. No Traefik, no long-lived containers. Each deploy builds a new image, optionally verifies it, then updates an active-tag pointer. An optional wrapper script at `install_path` reads the active tag on every invocation.

**Config (`echelon-config.yml`):**

```yaml
deploy:
  type: cli
  health_check: "myapp --version"  # command run inside container; empty = skip
  install_path: "~/.local/bin"     # where to install wrapper; empty = no wrapper
```

**Dockerfile (minimal Python CLI example):**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
ENTRYPOINT ["myapp"]
```

**What happens on first `echelon.run`:**
- `.git/hooks/post-merge` installed
- Wrapper script installed to `install_path/myapp` (if `install_path` set)

**Deploy flow (automatic after merge to main):**
1. `docker build` → `{app}:candidate`
2. If `health_check` set: `docker run --rm {app}:candidate {health_check_cmd}` (exit 0 = healthy)
3. On success: tag image → `{app}:{inactive_slot}`, update state pointer
4. On failure: build discarded, active pointer unchanged

**Running the app:**
```bash
# Via wrapper (transparent — always runs the active version):
myapp --help

# Or directly:
docker run --rm myapp:blue --help
```

**Rollback:** `speckit.echelon.deploy rollback` flips the active pointer — the wrapper picks it up on next invocation, no reinstall needed.

---

### Deploy Commands

| Command | Purpose |
|---------|---------|
| `speckit.echelon.deploy` | Trigger a deploy manually (same as post-merge hook) |
| `speckit.echelon.deploy status` | Show active slot, image, ports, last deploy time |
| `speckit.echelon.deploy rollback` | Roll back to the previous slot |

Deploy state lives in two locations (kept in sync on every deploy and rollback):
- `.specify/squad/deploy-state.json` — project-local copy
- `~/.speckit-deploy/{app}.json` — global registry (used for Traefik entrypoint aggregation and CLI wrapper scripts)
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): add Local CD section with HTTP and CLI examples"
```

---

## Task 8: Push

- [ ] **Step 1: Push branch**

```bash
git push
```

Expected: branch pushed to remote, no errors.

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| `type: http \| cli` field in config-template.yml | Task 1 |
| `health_check` and `install_path` CLI-only fields in config-template.yml | Task 1 |
| `type: http` explicit in echelon-config.yml | Task 1 |
| CLI path in deploy-init.sh: skip Traefik/network | Task 2 |
| CLI path in deploy-init.sh: install wrapper script if `install_path` set | Task 2 |
| HTTP path in deploy-init.sh: `type`, `health_check`, `install_path` added to state JSON | Task 2 |
| CLI path in deploy.sh: docker run --rm health check | Task 3 |
| CLI path in deploy.sh: no container lifecycle, tag+state only | Task 3 |
| HTTP path in deploy.sh: reads `type` from state, backward compatible | Task 3 |
| CLI status: active image + wrapper path | Task 4 |
| HTTP status: unchanged | Task 4 |
| CLI rollback: pointer swap, no container restart | Task 5 |
| HTTP rollback: container restart (unchanged) | Task 5 |
| echelon.run.md validation: `cli` skips port field check | Task 6 |
| README: HTTP example with config + Dockerfile | Task 7 |
| README: CLI example with config + Dockerfile | Task 7 |
| README: deploy command table | Task 7 |
