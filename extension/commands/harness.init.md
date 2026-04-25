---
description: "Initialize harness for a target repository — clone mirror, detect language/image, write config"
behavior:
  invocation: explicit
---

## User Input

$ARGUMENTS

---

## Overview

One-time setup that clones a mirror of the target repository, detects its language and Docker base image, and writes `.specify/extensions/echelon/echelon.yml`. Run this before any `harness.run` invocations.

---

## Step 1: Resolve Target

If `$ARGUMENTS` is non-empty, use it as `{target}`.

Otherwise, check whether `.git` exists in the current directory:
- If yes: set `{target}` to `.` (single-repo model — harness is installed in the target repo itself).
- If no: report **"No target provided and no .git found in current directory. Usage: speckit.harness.init <repo-url-or-path>"** and stop.

---

## Step 2: Check for Existing Init

If `.specify/extensions/echelon/echelon.yml` exists:
1. Read `target_repo` from it.
2. Ask: **"Harness already initialized for `{existing_target}`. Re-initialize for `{target}`? (yes/no)"**
3. If no: stop.

---

## Step 3: Run Init

```bash
PYTHONPATH=.specify/extensions/echelon python3 -c "
from harness.init import init_harness
config = init_harness('{target}')
print('target_repo:', config.target_repo)
print('provider:', config.provider)
"
```

If the command exits non-zero, report the full error output and stop.

---

## Step 4: Display Result

Read `.specify/extensions/echelon/echelon.yml` and display:

```
Harness initialized.

  Target:   {target_repo}
  Language: {detected_language}
  Image:    {detected_image}  (source: {detected_image_source})
  Provider: {provider}

Next: speckit.harness.run <spec_id>
```

If `bind_mount_ack` is `false` in the config, append:

```
  WARNING: bind_mount_ack is false — the sandbox CAN modify your worktree.
  Set bind_mount_ack: true in .specify/extensions/echelon/echelon.yml to acknowledge.
```
