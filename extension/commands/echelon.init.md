---
name: speckit.echelon.init
description: "One-time project initialization — bootstrap echelon.yml, validate deploy config, install Traefik/git hook infrastructure. Run once per project before speckit.echelon.run."
behavior:
  invocation: explicit
---

## User Input

$ARGUMENTS

---

## Overview

One-time setup for a project. Must be run before `speckit.echelon.run` on any new project.

What it does:
1. Bootstrap `echelon.yml` from template if absent
2. Validate the deploy config block
3. Run `deploy-init.sh` — installs Docker/Traefik (http type) or CLI wrapper, writes `deploy-state.json`, installs the git post-merge hook

Idempotent: safe to re-run. If deploy infrastructure already exists and is valid, it exits immediately. If the post-merge hook is missing but state is valid, it reinstalls the hook.

---

## Step 1: Anchor Project Root

```bash
PROJECT_ROOT=$(pwd)
ECHELON_EXT="${PROJECT_ROOT}/.specify/extensions/echelon"
echo "PROJECT_ROOT=${PROJECT_ROOT}"
echo "ECHELON_EXT=${ECHELON_EXT}"
```

---

## Step 2: Bootstrap echelon.yml

If `echelon.yml` does not exist at the project root, copy a starter config from the extension:

```bash
if [ ! -f "${PROJECT_ROOT}/echelon.yml" ]; then
  if [ -f "${ECHELON_EXT}/echelon-config.yml" ]; then
    cp "${ECHELON_EXT}/echelon-config.yml" "${PROJECT_ROOT}/echelon.yml"
    echo "✓ Bootstrapped echelon.yml from echelon-config.yml"
  elif [ -f "${ECHELON_EXT}/config-template.yml" ]; then
    cp "${ECHELON_EXT}/config-template.yml" "${PROJECT_ROOT}/echelon.yml"
    echo "✓ Bootstrapped echelon.yml from config-template.yml"
  else
    echo "✗ echelon.yml not found and no template available in ${ECHELON_EXT}" >&2
    echo "  Create echelon.yml at the project root before running echelon init." >&2
    exit 1
  fi
else
  echo "✓ echelon.yml already exists"
fi
```

If the file was bootstrapped, tell the user to review and configure the `deploy:` block before continuing — particularly `type`, ports (http) or `install_path` (cli), and `dockerfile`.

---

## Step 3: Validate deploy config

```bash
python3 -c "
import sys, yaml
try:
    c = yaml.safe_load(open('${PROJECT_ROOT}/echelon.yml'))
    d = c.get('deploy', {})
    deploy_type = d.get('type', 'http')
    if deploy_type not in ('http', 'cli'):
        print(f'✗ deploy.type must be http or cli, got: {deploy_type}', file=sys.stderr)
        sys.exit(1)
    if deploy_type == 'http':
        missing = [k for k in ['blue_port','green_port','active_port'] if k not in d]
        if missing:
            print('✗ deploy config incomplete in echelon.yml.', file=sys.stderr)
            print(f'  HTTP type requires: {missing}', file=sys.stderr)
            print('  See config-template.yml for reference.', file=sys.stderr)
            sys.exit(1)
    print(f'✓ deploy config valid (type={deploy_type})')
except FileNotFoundError:
    print('✗ echelon.yml not found.', file=sys.stderr)
    sys.exit(1)
"
```

If exit code is non-zero, stop. User must fix `echelon.yml` before proceeding.

---

## Step 4: Run deploy-init.sh

```bash
bash "${ECHELON_EXT}/scripts/bash/deploy-init.sh" "${PROJECT_ROOT}" "${PROJECT_ROOT}/echelon.yml"
```

If exit code is non-zero, report the full output and stop. Common failures:

| Error | Fix |
|-------|-----|
| Traefik not healthy | `docker rm -f speckit-traefik` then re-run `speckit.echelon.init` |
| Port already claimed by another app | Change `blue_port`/`green_port`/`active_port` in `echelon.yml` |
| deploy config missing | Add `deploy:` block to `echelon.yml` (see `config-template.yml`) |
| Docker not running | Start Docker Desktop, then re-run |

---

## Step 5: Confirm

Print a summary:

```
╔══════════════════════════════════════════╗
║         echelon init — complete          ║
╚══════════════════════════════════════════╝

  echelon.yml      → {PROJECT_ROOT}/echelon.yml
  deploy-state     → {PROJECT_ROOT}/.specify/squad/deploy-state.json
  post-merge hook  → {PROJECT_ROOT}/.git/hooks/post-merge

Next step:
  speckit.echelon.run — start the cognitive squad run
```
