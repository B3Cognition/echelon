---
name: speckit.echelon.bugfix
description: "Targeted bug fix or enhancement for an existing delivered spec — diagnose, plan, build, verify, deploy. No full squad run."
behavior:
  invocation: automatic
---

## User Input

$ARGUMENTS

---

## Overview

`echelon.bugfix` handles targeted fixes and small enhancements to features already delivered by a previous echelon run. It follows the same quality pipeline (diagnose → plan → build → verify → deploy) but skips the full WHY2/ASSESS/HOW/CONSENSUS squad machinery — that work was already done for the original spec.

**Use this when:**
- A delivered feature has a known bug (API not loading, blank page, wrong behaviour)
- A small enhancement is needed on top of an existing spec (add a status bar, change a label, tweak a threshold)
- A fix was attempted before but the verification gate caught it — iterate here, not with a full re-run

**Do NOT use this for:**
- New features with no existing spec — use `speckit.echelon.run`
- Major scope changes to an existing spec — use `speckit.echelon.change`
- Structural rearchitecting — use `speckit.echelon.run`

---

## Professional Conduct — ABSOLUTE RULE

Execute the request. Do not editorialize about whether the request is too small, too large, or better handled another way. The user decides what to run.

---

## Step 1: Parse Input

Extract from `$ARGUMENTS`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `spec_id` | — | Required if multiple specs exist. The spec being fixed (e.g., `001`). |
| `description` | — | Required. What is broken or what needs to change. |
| `auto_deploy` | `true` | Deploy after successful verification. |

If `description` is missing, ask: **"What needs to be fixed or changed?"** and stop.

If `spec_id` is not provided and multiple specs exist under `specs/`, list them and ask which one. If only one spec exists, use it automatically.

Locate the spec directory: `specs/{spec_id}-*/`. Extract `{spec_name}` from the directory name.

---

## Step 2: Diagnose

Read the following from the **current working directory** (not a worktree):

1. `specs/{spec_id}-*/spec.md` — the original requirements
2. `specs/{spec_id}-*/coverage-map.md` — what was verified and how
3. `.specify/squad/deploy-state.json` — deployment context (app name, type, ports)
4. The **deployed source files** — key implementation files relevant to the reported issue

Then read the source code relevant to the bug description. For a UI rendering issue, read the component. For an API issue, read the fetch/hook. For a routing issue, read the router config. Read what you need to understand the root cause — do not guess.

**Root Cause Analysis:** Based on what you read, identify:
- The specific file(s) causing the issue
- The exact mechanism of failure (wrong URL, missing env var, wrong base path, broken condition, etc.)
- What a correct fix looks like

Print a concise diagnosis block:

```
════════════════════════════════════════
  DIAGNOSIS: {spec_id} — {spec_name}
════════════════════════════════════════
  Issue:    {one-line description of what's broken}
  Root cause: {specific cause, referencing file:line where relevant}
  Fix:      {what will be changed}
  Scope:    {N files affected}
════════════════════════════════════════
```

---

## Step 3: Write Bugfix Plan

Create `specs/{spec_id}-{spec_name}/bugfix-{timestamp}.md` with:

```markdown
# Bugfix: {description}

## Root Cause
{diagnosis from Step 2}

## Changes Required
- {file}: {what changes and why}
- ...

## Verification Criteria
- {specific assertion that proves the fix works}
- ...

## Test Coverage
- {what new or updated tests will cover this}
```

This file is the single source of truth for the fix. It is committed with the build output.

---

## Step 4: Apply Deployment Context

Before building, read `deploy-state.json` for `app` name and `type`.

If `type = http`: run the SPA base-path correction on the **worktree** (see Step 5) before any build command, using the echelon `fix-spa-base.sh` script:

```bash
bash .specify/extensions/echelon/scripts/bash/fix-spa-base.sh "{worktree_path}" "{app_name}"
```

---

## Step 5: Build Fix (on host, in worktree)

Create a harness worktree for this fix:

```bash
PYTHONPATH=.specify/extensions/harness python3 -c "
import sys
sys.path.insert(0, '.specify/extensions/harness')
from harness.config import load_config
from harness.gitops import GitOpsManager

config = load_config()
gitops = GitOpsManager(config)
worktree_path = gitops.create_worktree('{spec_id}', 'bugfix', 0, base_branch='{feature_branch}')
print(worktree_path)
"
```

Apply the deployment context fix (Step 4) on the worktree, then implement the fix. Write all changed files to the **worktree path** — never to CWD.

For each changed file:
- Make the minimal change that fixes the root cause
- Do not refactor unrelated code
- Do not add features beyond what `$ARGUMENTS` describes

Also update or add tests in the worktree that directly verify the fix. The test must fail before the fix and pass after it.

---

## Step 6: Verify (in Docker)

Read `detected_image` from `.specify/extensions/harness/harness-config.yml`. Fallback: `ubuntu:24.04`.

```bash
docker run --rm \
  -v "{worktree_path}:/workspace:ro" \
  {docker_image} \
  sh /workspace/verify.sh
```

If `verify.sh` does not exist in the worktree, create a minimal one that:
1. Installs dependencies
2. Runs the test suite
3. For SPA builds: runs `npm run build` and checks that `dist/index.html` asset paths begin with `/{app_name}/assets/`

Parse exit code:
- `0` → proceed to Step 7
- non-zero → analyse the failure, fix in the worktree, re-run verify (up to 3 attempts). If still failing after 3 attempts, report the failure and stop — do not deploy broken code.

---

## Step 7: Commit and Push

```bash
PYTHONPATH=.specify/extensions/harness python3 -c "
import sys
sys.path.insert(0, '.specify/extensions/harness')
from harness.config import load_config
from harness.gitops import GitOpsManager

config = load_config()
gitops = GitOpsManager(config)
gitops.commit('{worktree_path}', 'fix({spec_id}): {short_description} [skip ci]')
gitops.push('{worktree_path}', '{feature_branch}')
"
```

---

## Step 8: Deploy

If `auto_deploy = true` and verification passed, run:

```bash
bash .specify/extensions/echelon/scripts/bash/deploy.sh
```

---

## Step 9: Report

```
════════════════════════════════════════════════
  ✓ bugfix — {spec_id}: {spec_name}
════════════════════════════════════════════════
  Status:   {DEPLOYED | VERIFIED (not deployed)}
  Issue:    {original description}
  Fix:      {what changed, N files}
  Tests:    {N passing}
  Live:     http://localhost/{app_name}/
════════════════════════════════════════════════
```

If verification failed after 3 attempts:

```
════════════════════════════════════════════════
  ✗ bugfix — {spec_id}: {spec_name}
════════════════════════════════════════════════
  Status:   FAILED after 3 verify attempts
  Last failure: {exit code + key error lines}
  Branch:   {feature_branch} (fix committed but not deployed)
  Next step: inspect verify output above, then re-run speckit.echelon.bugfix
════════════════════════════════════════════════
```
