---
description: "Initialize delivery runtime — clone mirror, detect language/image, write config"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER performing one-time delivery runtime initialization — clone the workspace mirror, detect language and Docker image from the current workspace, and write runtime configuration. Implementation targets are selected per spec, not in harness config.

---

## User Input

$ARGUMENTS

---

## Overview

One-time setup that clones a mirror of the workspace, detects its language and Docker base image, and writes `.echelon/config.yml`. Legacy workspaces may still read `.specify/extensions/echelon/echelon-config.yml` during migration. Run this before any delivery build invocation.

---

## Step 1: Reject Target Arguments

If `$ARGUMENTS` is non-empty, report:

```
Harness init no longer accepts a target repository.
Set implementation targets per spec:
  echelon spec target <spec_id> <source-path>
  echelon spec target <spec_id> sources/<new-repo> --init
Then rerun: echelon delivery init
```

Then stop.

Otherwise, check whether `.git` exists in the current directory:
- If yes: continue.
- If no: report **"Workspace root is not a Git repo. Run `echelon workspace init` first."** and stop.

---

## Step 2: Check for Existing Init

If `.echelon/config.yml` exists, reuse it and update runtime-detection fields only. Do not add `harness.target_repo`.

---

## Step 3: Run Init

```bash
PYTHONPATH=.specify/extensions/echelon python3 -c "
from harness.init import init_harness
config = init_harness('.')
print('provider:', config.provider)
"
```

If the command exits non-zero, report the full error output and stop.

---

## Step 4: Display Result

Read `.echelon/config.yml` and display:

```
Harness initialized.

  Language: {detected_language}
  Image:    {detected_image}  (source: {detected_image_source})
  Provider: {provider}

Next:
  echelon spec target <spec_id> <source-path>
  echelon delivery run <spec_id>
```

If `bind_mount_ack` is `false` in the config, append:

```
  WARNING: bind_mount_ack is false — the sandbox CAN modify your worktree.
  Set bind_mount_ack: true in .echelon/config.yml to acknowledge.
```
