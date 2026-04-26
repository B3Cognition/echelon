---
name: speckit.echelon.deploy
description: "Manual deploy trigger, status, and rollback for blue/green and CLI local CD"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER handling deployment operations — triggering, checking status, or rolling back a deployment.

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
ECHELON_EXT="$(git rev-parse --show-toplevel)/.specify/extensions/echelon"
bash "${ECHELON_EXT}/scripts/bash/deploy.sh"
```

Report the full output. If exit code is non-zero, report the error and stop.

---

## Show Status

```bash
ECHELON_EXT="$(git rev-parse --show-toplevel)/.specify/extensions/echelon"
bash "${ECHELON_EXT}/scripts/bash/deploy-status.sh"
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
state['last_deploy'] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')

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
state['last_deploy'] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')
with open('.specify/squad/deploy-state.json', 'w') as f:
    json.dump(state, f, indent=2)

global_dir = os.path.expanduser('~/.speckit-deploy')
os.makedirs(global_dir, exist_ok=True)
with open(os.path.join(global_dir, f"{app}.json"), 'w') as f:
    json.dump(state, f, indent=2)

app = state['app']
print(f"\n✓ Rolled back to {inactive}")
print(f"  Live: http://localhost/{app}/")
PYEOF
```

If exit code is non-zero, report the error and stop.
