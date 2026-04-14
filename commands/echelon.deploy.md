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
STATE_FILE="${STATE_FILE}" python3 - <<'PYEOF'
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

# Start the inactive slot (already exists as stopped container)
result = subprocess.run(['docker', 'start', f'{app}-{inactive}'], capture_output=True, text=True)
if result.returncode != 0:
    print(f"✗ Could not start {app}-{inactive}: {result.stderr}", file=sys.stderr)
    sys.exit(1)

# Stop the current active slot
subprocess.run(['docker', 'stop', f'{app}-{active}'], capture_output=True)

# Swap state
state['active'] = inactive
state['last_deploy'] = datetime.datetime.utcnow().isoformat() + 'Z'
with open('.specify/squad/deploy-state.json', 'w') as f:
    json.dump(state, f, indent=2)

# Mirror to global state
global_dir = os.path.expanduser('~/.speckit-deploy')
os.makedirs(global_dir, exist_ok=True)
global_state = os.path.join(global_dir, f"{app}.json")
with open(global_state, 'w') as f:
    json.dump(state, f, indent=2)

active_port = state['active_port']
print(f"\n✓ Rolled back to {inactive}")
print(f"  Live: http://localhost:{active_port}")
PYEOF
```

If exit code is non-zero, report the error and stop.
