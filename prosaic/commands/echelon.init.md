---
name: echelon.init
description: One-time project initialization — bootstrap .echelon/config.yml, validate
  deploy config, install Traefik. Run once per project before echelon.run.
execution: command
invocation: explicit
tools: write
model_tier: balanced
effort: medium
---
## Role

You are COMMANDER performing one-time project initialization — validating deploy config in the project config file, provisioning the MemPalace wing, and installing infrastructure. Run once per project before `echelon.run`.

---

## User Input

{{args}}

---

## Overview

One-time setup for a project. Must be run before `echelon.run` on any new project.
Requires `echelon workspace init` to have been run first (creates the project config).

What it does:

1. Confirm project config exists at `.echelon/config.yml`
2. Validate the deploy config block
3. Provision MemPalace wing
4. Run `deploy-init.sh` — installs Docker/Traefik (http type) or CLI wrapper, writes `deploy-state.json`

Idempotent: safe to re-run. If deploy infrastructure already exists and is valid, it exits immediately.

---

## Step 1: Anchor Project Root

```bash
PROJECT_ROOT=$(pwd)
ECHELON_RUNTIME="${PROJECT_ROOT}/.echelon/runtime"
ECHELON_CONFIG="${PROJECT_ROOT}/.echelon/config.yml"
echo "PROJECT_ROOT=${PROJECT_ROOT}"
echo "ECHELON_CONFIG=${ECHELON_CONFIG}"
```

---

## Step 2: Confirm project config exists

The project config is created automatically by `echelon workspace init`. If it is missing, the extension was not installed correctly.

```bash
if [ ! -f "${ECHELON_CONFIG}" ]; then
  echo "✗ Project config not found: ${ECHELON_CONFIG}" >&2
  echo "  Run: echelon workspace init" >&2
  exit 1
fi
echo "✓ Project config found: ${ECHELON_CONFIG}"
```

Tell the user to review and configure the `deploy:` block in `${ECHELON_CONFIG}` before continuing — particularly `type`, `blue_port`/`green_port` (http, must be unique per app on this machine), or `install_path` (cli), and `dockerfile`. All apps share Traefik at `:80` with path-prefix routing.

---

## Step 3: Validate deploy config

```bash
python3 -c "
import sys, yaml
try:
    c = yaml.safe_load(open('${ECHELON_CONFIG}'))
    d = c.get('deploy', {})
    deploy_type = d.get('type', 'http')
    if deploy_type not in ('http', 'cli'):
        print(f'✗ deploy.type must be http or cli, got: {deploy_type}', file=sys.stderr)
        sys.exit(1)
    if deploy_type == 'http':
        missing = [k for k in ['blue_port','green_port'] if k not in d]
        if missing:
            print('✗ deploy config incomplete in .echelon/config.yml.', file=sys.stderr)
            print(f'  HTTP type requires: {missing}', file=sys.stderr)
            print('  See config-template.yml for reference.', file=sys.stderr)
            sys.exit(1)
    print(f'✓ deploy config valid (type={deploy_type})')
except FileNotFoundError:
    print('✗ .echelon/config.yml not found.', file=sys.stderr)
    sys.exit(1)
"
```

If exit code is non-zero, stop. User must fix `${ECHELON_CONFIG}` before proceeding.

---

## Step 3b: Provision MemPalace wing

The wing is this project's stable identity in the shared MemPalace memory store.
Always keep the existing wing once set; it should never change because all clones
of this repo share the same wing so they share memory.

```bash
python3 -c "
import sys
try:
    from echelon.cli import _provision_wing
    from pathlib import Path
    _provision_wing(Path('${PROJECT_ROOT}'), Path('${ECHELON_CONFIG}'))
except ImportError:
    print('  ℹ  echelon not installed — wing provisioning skipped')
"
```

If the wing is already set in `${ECHELON_CONFIG}`, this is a no-op. If not, it prompts for a name (auto-suggests from git remote) and writes `mempalace.wing` to `${ECHELON_CONFIG}`.

---

## Step 4: Run deploy-init.sh

```bash
bash "${ECHELON_RUNTIME}/scripts/bash/deploy-init.sh" "${PROJECT_ROOT}" "${ECHELON_CONFIG}"
```

If exit code is non-zero, report the full output and stop. Common failures:

| Error | Fix |
|-------|-----|
| Traefik not healthy | Remove the container named by `deploy-state.json`, then re-run `echelon.init` |
| Port already claimed by another app | Change `blue_port`/`green_port` in `${ECHELON_CONFIG}` (use 3100/3101 for app2, 3200/3201 for app3, etc.) |
| deploy config missing | Add `deploy:` block to `${ECHELON_CONFIG}` (see `config-template.yml`) |
| Docker not running | Start Docker Desktop, then re-run |

---

## Step 5: Confirm

Print a summary:

```
╔══════════════════════════════════════════╗
║    echelon workspace init — complete     ║
╚══════════════════════════════════════════╝

  config       → {ECHELON_CONFIG}
  deploy-state → active run deploy-state.json (`runs/.current`)

Next step:
  echelon.run — start the cognitive squad run
```
