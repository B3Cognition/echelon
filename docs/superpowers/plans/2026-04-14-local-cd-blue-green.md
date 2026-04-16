# Local CD — Blue/Green Deployment Implementation Plan

> **SUPERSEDED** — see README.md "Local CD" section for current architecture. Architecture change 2026-04-16: `active_port` removed, path-prefix routing, Traefik started once, SPA base-path auto-correction added.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add zero-downtime blue/green deployment to the echelon extension — after `harness.run` merges to main, a git hook fires `deploy.sh` which builds a Docker image and swaps the live slot via Traefik.

**Architecture:** Three bash scripts (`deploy-init.sh`, `deploy.sh`, `deploy-status.sh`) installed into `.specify/scripts/` of the target project. `deploy-init.sh` runs lazily from `echelon.run` section 1.0 on first use. `deploy.sh` is called by a `post-merge` git hook. One shared `speckit-traefik` container acts as the reverse proxy for all apps on the machine, discovered via Docker labels.

**Tech Stack:** Bash, Docker CLI, Traefik v3 (Docker provider), Python (for JSON state reads in echelon.run.md), YAML (config-template.yml).

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `scripts/bash/deploy-init.sh` | Create | One-time setup: network, Traefik, git hook, state file |
| `scripts/bash/deploy.sh` | Create | Blue/green swap called by post-merge hook |
| `scripts/bash/deploy-status.sh` | Create | Print active slot, ports, container health |
| `commands/echelon.deploy.md` | Create | Manual deploy/status/rollback command |
| `config-template.yml` | Modify | Add `deploy:` section with annotations |
| `echelon-config.yml` | Modify | Add `deploy:` section for test project |
| `commands/echelon.run.md` | Modify | Section 1.0: validate deploy config + call deploy-init.sh |

---

## Task 1: Add `deploy:` config block

**Files:**
- Modify: `config-template.yml`
- Modify: `echelon-config.yml`

- [ ] **Step 1: Add deploy section to config-template.yml**

Append after the final `norepinephrine` decay line (end of file):

```yaml

# =============================================================================
# DEPLOY — Blue/green local CD via Traefik
# =============================================================================

deploy:
  # Host port for the blue slot container
  # [range: 1024-65535] Must not conflict with other apps registered in deploy-state.json
  blue_port: 3000

  # Host port for the green slot container
  # [range: 1024-65535] Must not conflict with other apps registered in deploy-state.json
  green_port: 3001

  # Port Traefik exposes to the host — what you type in the browser (e.g. http://localhost)
  # [range: 1-65535] Typically 80, 81, 82... one per app
  active_port: 80

  # Path to Dockerfile relative to project root. Optional — defaults to "Dockerfile"
  # dockerfile: Dockerfile
```

- [ ] **Step 2: Add deploy section to echelon-config.yml**

Append after the final `norepinephrine` decay line (end of file):

```yaml

# =============================================================================
# DEPLOY — test-echelon-refactor local deployment
# =============================================================================

deploy:
  blue_port: 3000
  green_port: 3001
  active_port: 80
```

- [ ] **Step 3: Commit**

```bash
git add config-template.yml echelon-config.yml
git commit -m "feat(deploy): add deploy: config block to templates"
```

---

## Task 2: Write `deploy-init.sh`

**Files:**
- Create: `scripts/bash/deploy-init.sh`

- [ ] **Step 1: Create the script**

```bash
cat > scripts/bash/deploy-init.sh << 'SCRIPT'
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

for f in "${GLOBAL_STATE_DIR}"/*.json 2>/dev/null; do
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
for f in "${GLOBAL_STATE_DIR}"/*.json 2>/dev/null; do
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
SCRIPT
chmod +x scripts/bash/deploy-init.sh
```

- [ ] **Step 2: Smoke-test the script syntax**

```bash
bash -n scripts/bash/deploy-init.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/bash/deploy-init.sh
git commit -m "feat(deploy): add deploy-init.sh — lazy init for Traefik + blue/green state"
```

---

## Task 3: Write `deploy.sh`

**Files:**
- Create: `scripts/bash/deploy.sh`

- [ ] **Step 1: Create the script**

```bash
cat > scripts/bash/deploy.sh << 'SCRIPT'
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
read_state() {
  python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d['$1'])"
}

APP=$(read_state app)
ACTIVE=$(read_state active)
BLUE_PORT=$(read_state blue_port)
GREEN_PORT=$(read_state green_port)
DOCKERFILE=$(python3 -c "
import json
d = json.load(open('${STATE_FILE}'))
print(d.get('dockerfile', 'Dockerfile'))
")

INACTIVE=$([ "${ACTIVE}" = "blue" ] && echo "green" || echo "blue")
INACTIVE_PORT=$([ "${INACTIVE}" = "blue" ] && echo "${BLUE_PORT}" || echo "${GREEN_PORT}")
ACTIVE_PORT=$([ "${ACTIVE}" = "blue" ] && echo "${BLUE_PORT}" || echo "${GREEN_PORT}")

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

python3 - << PYEOF
import json, datetime
with open('${STATE_FILE}') as f:
    state = json.load(f)
state['active'] = '${INACTIVE}'
state['${INACTIVE}_image'] = '${APP}:${INACTIVE}'
state['last_deploy'] = datetime.datetime.utcnow().isoformat() + 'Z'
with open('${STATE_FILE}', 'w') as f:
    json.dump(state, f, indent=2)

# Mirror to global state
import os
global_state = os.path.expanduser(f"~/.speckit-deploy/{state['app']}.json")
if os.path.exists(global_state):
    with open(global_state, 'w') as f:
        json.dump(state, f, indent=2)
PYEOF

ACTIVE_DISPLAY=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d.get('active_port', '?'))")
echo ""
echo "════════════════════════════════════════"
echo "  ✓ ${APP} deployed"
echo "  Slot:   ${INACTIVE} (was ${ACTIVE})"
echo "  Live:   http://localhost:${ACTIVE_DISPLAY}"
echo "════════════════════════════════════════"
SCRIPT
chmod +x scripts/bash/deploy.sh
```

- [ ] **Step 2: Check syntax**

```bash
bash -n scripts/bash/deploy.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/bash/deploy.sh
git commit -m "feat(deploy): add deploy.sh — zero-downtime blue/green swap"
```

---

## Task 4: Write `deploy-status.sh`

**Files:**
- Create: `scripts/bash/deploy-status.sh`

- [ ] **Step 1: Create the script**

```bash
cat > scripts/bash/deploy-status.sh << 'SCRIPT'
#!/usr/bin/env bash
# deploy-status.sh — print active slot, ports, container health, last deploy
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
STATE_FILE="${PROJECT_ROOT}/.specify/squad/deploy-state.json"

if [ ! -f "${STATE_FILE}" ]; then
  echo "No deploy state found. Run echelon.run first."
  exit 0
fi

APP=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d['app'])")
ACTIVE=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d['active'])")
INACTIVE=$([ "${ACTIVE}" = "blue" ] && echo "green" || echo "blue")
BLUE_PORT=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d['blue_port'])")
GREEN_PORT=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d['green_port'])")
ACTIVE_PORT=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d['active_port'])")
LAST=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d.get('last_deploy') or 'never')")

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
SCRIPT
chmod +x scripts/bash/deploy-status.sh
```

- [ ] **Step 2: Check syntax**

```bash
bash -n scripts/bash/deploy-status.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/bash/deploy-status.sh
git commit -m "feat(deploy): add deploy-status.sh — slot health display"
```

---

## Task 5: Write `echelon.deploy.md` command

**Files:**
- Create: `commands/echelon.deploy.md`

- [ ] **Step 1: Create the command file**

```bash
cat > commands/echelon.deploy.md << 'CMD'
---
name: speckit.echelon.deploy
description: "Manual deploy trigger, status, and rollback for blue/green local CD"
behavior:
  invocation: explicit
---

## User Input

$ARGUMENTS

---

## Overview

Manual control over the blue/green deployment. The automated path is the `post-merge` git hook → `deploy.sh`. Use this command for status checks, manual deploys, and rollback.

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

Rollback swaps back to the previously active slot. The inactive container is stopped but not removed — its image is still tagged `{app}:blue` or `{app}:green`.

```bash
PROJECT_ROOT=$(pwd)
STATE_FILE="${PROJECT_ROOT}/.specify/squad/deploy-state.json"

python3 - << 'PYEOF'
import json, subprocess, sys

with open('.specify/squad/deploy-state.json') as f:
    state = json.load(f)

app = state['app']
active = state['active']
inactive = 'green' if active == 'blue' else 'blue'
inactive_port = state[f'{inactive}_port']
inactive_image = state.get(f'{inactive}_image')

if not inactive_image:
    print(f"✗ No previous {inactive} image to roll back to.", file=sys.stderr)
    sys.exit(1)

print(f"rollback: {app} {active} → {inactive}")

# Start the inactive slot (already exists as stopped container)
result = subprocess.run(['docker', 'start', f'{app}-{inactive}'], capture_output=True, text=True)
if result.returncode != 0:
    print(f"✗ Could not start {app}-{inactive}: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Stop the current active slot
subprocess.run(['docker', 'stop', f'{app}-{active}'], capture_output=True)

# Swap state
import datetime
state['active'] = inactive
state['last_deploy'] = datetime.datetime.utcnow().isoformat() + 'Z'
with open('.specify/squad/deploy-state.json', 'w') as f:
    json.dump(state, f, indent=2)

active_port = state['active_port']
print(f"\n✓ Rolled back to {inactive}")
print(f"  Live: http://localhost:{active_port}")
PYEOF
```

If exit code is non-zero, report the error and stop.

---
CMD
```

- [ ] **Step 2: Commit**

```bash
git add commands/echelon.deploy.md
git commit -m "feat(deploy): add echelon.deploy.md command — status, manual deploy, rollback"
```

---

## Task 6: Register `echelon.deploy` in `extension.yml`

**Files:**
- Modify: `extension.yml`

- [ ] **Step 1: Add the command entry**

In `extension.yml`, under `provides: commands:`, add after the last existing command entry (before the `# ── Agent Definitions ──` comment):

```yaml
    - name: "speckit.echelon.deploy"
      file: "commands/echelon.deploy.md"
      description: "Manual deploy trigger, status, and rollback for blue/green local CD"
      behavior:
        execution: skill
        capability: balanced
        tools: write
        color: blue
```

- [ ] **Step 2: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('extension.yml'))" && echo "YAML valid"
```

Expected: `YAML valid`

- [ ] **Step 3: Commit**

```bash
git add extension.yml
git commit -m "feat(deploy): register speckit.echelon.deploy in extension.yml"
```

---

## Task 7: Update `echelon.run.md` — validate config + call init

**Files:**
- Modify: `commands/echelon.run.md`

- [ ] **Step 1: Extend section 1.0 in echelon.run.md**

Find the existing section 1.0 block:

```markdown
Store `PROJECT_ROOT` in your context. All paths written to state.json, passed to agents, or used in file operations **must be absolute paths** derived from `${PROJECT_ROOT}`. Never use bare relative paths like `specs/003-...` — always `${PROJECT_ROOT}/specs/003-...`.
```

Append immediately after it (before `### 1.1`):

```markdown

**Validate deploy config:**

```bash
python3 -c "
import sys, yaml
try:
    c = yaml.safe_load(open('echelon.yml'))
    d = c.get('deploy', {})
    missing = [k for k in ['blue_port','green_port','active_port'] if k not in d]
    if missing:
        print('✗ deploy config missing in echelon.yml.', file=sys.stderr)
        print('  Add a deploy: block with blue_port, green_port, active_port.', file=sys.stderr)
        print('  See config-template.yml for reference.', file=sys.stderr)
        sys.exit(1)
except FileNotFoundError:
    print('✗ echelon.yml not found.', file=sys.stderr)
    sys.exit(1)
"
```

If exit code is non-zero, stop immediately — do not proceed with the run.

**Run deploy init (idempotent):**

```bash
ECHELON_EXT=".specify/extensions/echelon"
bash ${ECHELON_EXT}/scripts/bash/deploy-init.sh "${PROJECT_ROOT}" "echelon.yml"
```

If exit code is non-zero, report the error and stop.
```

- [ ] **Step 2: Commit**

```bash
git add commands/echelon.run.md
git commit -m "feat(deploy): wire deploy validation + lazy init into echelon.run section 1.0"
```

---

## Task 8: Write a `Dockerfile` template note in `config-template.yml`

**Files:**
- Modify: `config-template.yml`

The deploy system assumes the target project has a `Dockerfile`. Echelon should surface this requirement clearly. Add a comment to the deploy section in `config-template.yml` (already added in Task 1):

- [ ] **Step 1: Update the dockerfile comment in config-template.yml**

Find the existing `dockerfile` line added in Task 1:

```yaml
  # dockerfile: Dockerfile
```

Replace with:

```yaml
  # Path to Dockerfile relative to project root.
  # The Dockerfile must: COPY the build output (e.g. dist/), install a static
  # server (e.g. nginx or serve), and EXPOSE port 80.
  # Example minimal Dockerfile for a Vite/React app:
  #   FROM nginx:alpine
  #   COPY dist/ /usr/share/nginx/html/
  #   EXPOSE 80
  # dockerfile: Dockerfile
```

- [ ] **Step 2: Commit**

```bash
git add config-template.yml
git commit -m "docs(deploy): add Dockerfile guidance comment to config-template.yml"
```

---

## Task 9: Push

- [ ] **Step 1: Push branch**

```bash
git push
```

Expected: branch pushed to remote, no errors.

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `deploy:` block in config-template.yml and echelon-config.yml | Task 1 |
| App name derived from `basename(PROJECT_ROOT)` | Task 2 (deploy-init.sh) |
| Fail fast if `deploy:` missing from echelon.yml | Task 7 (echelon.run.md) |
| Port conflict detection against global state | Task 2 (deploy-init.sh) |
| `speckit-deploy` Docker network creation | Task 2 |
| Traefik startup with per-app entrypoints | Task 2 |
| Traefik recreate when adding second app | Task 2 |
| Traefik health check before proceeding | Task 2 |
| Git post-merge hook installation | Task 2 |
| `deploy-state.json` written to `.specify/squad/` | Task 2 |
| Zero-downtime blue/green swap | Task 3 (deploy.sh) |
| Health check with 5× retry + auto-rollback on failure | Task 3 |
| State update after swap | Task 3 |
| `deploy-status.sh` print slot/port/health | Task 4 |
| `echelon.deploy` manual command (deploy/status/rollback) | Task 5 |
| Rollback via stopped inactive container | Task 5 |
| `extension.yml` registration | Task 6 |
| `echelon.run.md` section 1.0 wired to init | Task 7 |
| Dockerfile guidance | Task 8 |
