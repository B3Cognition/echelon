---
name: speckit.echelon.bugfix
description: "Targeted bug fix or enhancement for a delivered spec — simplified squad run (DEBUGGER → SENTINEL → IMPLEMENTER → TEST GUARDIAN → SPEC GUARD → INTEGRATOR → harness verify → deploy)."
behavior:
  invocation: automatic
---

## User Input

$ARGUMENTS

---

## Overview

`echelon.bugfix` is the **lightweight squad pipeline** for bugs and small enhancements on features already delivered by a previous echelon run.

It runs a purposeful subset of the squad — the agents that matter for fixing something, not the ones that exist to discover and spec it from scratch:

| Phase | Agent | Purpose |
| ------- | ------- | ------- |
| 1. Diagnose | **DEBUGGER** | Root cause analysis — reads code, identifies exact failure mechanism |
| 2. Test strategy | **SENTINEL** | Designs the failing test that proves the bug exists and will prove the fix |
| 3. Implement | **IMPLEMENTER** | Writes the fix + tests in the worktree |
| 4. Coverage audit | **TEST GUARDIAN** | Ensures the fix has adequate test coverage, no gaps |
| 5. Spec compliance | **SPEC GUARD** | Confirms the fix satisfies the original spec requirement |
| 6. Verify | Harness Docker | Deterministic test run in isolation |
| 7. Integration | **INTEGRATOR** | Checks for regressions introduced by the fix |
| 8. Deploy | deploy.sh | Ships to the running environment |

Skipped intentionally: WHY2, ASSESS, HOW, CONSENSUS, CARTOGRAPHER, GATEKEEPER, ARCHITECT, SCOUT, ORACLE. That work was done for the original spec. The code exists — this pipeline fixes it.

**Use this when:**

- A delivered feature has a known bug
- A small enhancement is needed on top of an existing spec
- The verification gate caught a failure and you need to iterate

**Do NOT use this for:**

- New features with no existing spec — use `speckit.echelon.run`
- Major scope or architecture changes — use `speckit.echelon.run` or `speckit.echelon.change`

---

## Professional Conduct — ABSOLUTE RULE

Execute the request. Do not editorialize about whether it's too small, too large, or better handled differently. The user decides.

---

## Execution Continuity — ABSOLUTE RULE

After any agent returns, immediately execute the next step. Do not stop between phases. The run ends only at DONE or a documented BLOCKED condition.

---

## Step 1: Parse Input

Extract from `$ARGUMENTS`:

| Parameter | Default | Description |
| --------- | ------- | ----------- |
| `spec_id` | — | Required if multiple specs exist (e.g. `001`). |
| `description` | — | Required. What is broken or what needs to change. |
| `auto_deploy` | `true` | Deploy after successful verification. |

If `description` is missing: **"What needs to be fixed or changed?"** and stop.

If `spec_id` is absent and multiple specs exist under `specs/`, list them and ask. If only one exists, use it automatically.

Locate `specs/{spec_id}-*/`. Extract `{spec_name}`.

Read the following context — you will pass it to every agent:

- `specs/{spec_id}-{spec_name}/spec.md`
- `specs/{spec_id}-{spec_name}/coverage-map.md` (if exists)
- `.specify/squad/deploy-state.json` (if exists)
- The relevant source files (read based on `description` — the component, hook, API call, config file, or test file most likely related to the issue)

---

## Step 2: DEBUGGER — Root Cause Analysis

Dispatch `agents/build/debugger.md` with:

- The user's `description`
- The spec (`spec.md`)
- The relevant source files read in Step 1
- The deploy context (`deploy-state.json`)

The DEBUGGER must produce:

- Exact root cause (file + line + mechanism)
- Minimal fix description (what changes, not how to implement it)
- Risk surface (what else could break)

Store the DEBUGGER output as `{debugger_report}`.

---

## Step 3: SENTINEL — Test Strategy

Dispatch `agents/solution/sentinel.md` with:

- The `{debugger_report}`
- The `spec.md`
- The `coverage-map.md`
- Existing test files for the affected component/module

The SENTINEL must produce:

- A **failing test** that proves the bug exists (red test)
- The assertion that will turn green when the fix is correct
- Any regression tests needed to protect adjacent behaviour

Store the SENTINEL output as `{test_strategy}`.

---

## Step 4: Create Worktree

```bash
PYTHONPATH=.specify/extensions/harness python3 -c "
import sys
sys.path.insert(0, '.specify/extensions/harness')
from harness.config import load_config
from harness.gitops import GitOpsManager

config = load_config()
gitops = GitOpsManager(config)
feature_branch = gitops.find_feature_branch('{spec_id}')
worktree_path = gitops.create_worktree(
    '{spec_id}',
    'bugfix',
    0,
    base_branch=feature_branch or None,
)
print(worktree_path)
"
```

Store as `{worktree_path}`. All implementation writes go here — never to CWD.

Apply deployment context: if `deploy-state.json` has `type = http`, run SPA base correction on the worktree before any build:

```bash
bash .specify/extensions/echelon/scripts/bash/fix-spa-base.sh "{worktree_path}" "{app_name}"
```

---

## Step 5: IMPLEMENTER — Write the Fix

Dispatch `agents/build/implementer.md` with:

- The `{debugger_report}`
- The `{test_strategy}` (failing test to write first, then fix to make it pass)
- The `spec.md`
- The worktree path: `{worktree_path}`
- The relevant source files

The IMPLEMENTER must:

1. Write the failing test from `{test_strategy}` to the worktree first (TDD red step)
2. Write the minimal fix that makes it pass (TDD green step)
3. Write a `bugfix-{timestamp}.md` to `specs/{spec_id}-{spec_name}/` documenting: root cause, files changed, tests added

All files written to `{worktree_path}` — never to CWD.

---

## Step 6: TEST GUARDIAN — Coverage Audit

Dispatch `agents/build/test-guardian.md` with:

- The IMPLEMENTER's output (what was written)
- The `{test_strategy}`
- The `spec.md`

The TEST GUARDIAN must confirm:

- The failing test from SENTINEL was written and covers the root cause
- No reachable edge cases are left uncovered by the fix
- Regression tests for adjacent behaviour are in place

If TEST GUARDIAN identifies gaps: return to IMPLEMENTER with the specific gaps. Maximum 1 feedback loop. If gaps remain after the loop, document them in `bugfix-{timestamp}.md` as known gaps and continue.

---

## Step 7: SPEC GUARD — Spec Compliance

Dispatch `agents/build/spec-guard.md` with:

- The `spec.md`
- The `coverage-map.md`
- The list of files changed by IMPLEMENTER

The SPEC GUARD must confirm the fix satisfies the relevant spec requirement(s) that the bug violated. If the fix is compliant, continue. If non-compliant, return the finding and stop with:

```
✗ SPEC GUARD: fix does not satisfy {requirement_id} — {reason}
  Review the SPEC GUARD output above and re-run speckit.echelon.bugfix with an updated description.
```

---

## Step 8: Verify (Docker)

Read `detected_image` from `.specify/extensions/harness/harness-config.yml`. Fallback: `ubuntu:24.04`.

```bash
docker run --rm \
  -v "{worktree_path}:/workspace:ro" \
  {docker_image} \
  sh /workspace/verify.sh
```

Parse exit code:

- `0` → proceed to Step 9
- non-zero → dispatch `agents/build/debugger.md` again with the verify failure output. Fix in the worktree. Re-run verify. Maximum `max_outer = 3` attempts total. If still failing, report and stop — do not deploy.

---

## Step 9: INTEGRATOR — Regression Check

Dispatch `agents/build/integrator.md` with:

- The list of files changed
- The verify output (passing tests)
- The `spec.md`

The INTEGRATOR checks for regressions: does the fix break any behaviour specified in the original spec that wasn't in the failing test? If regressions are found, return to IMPLEMENTER. Maximum 1 feedback loop.

---

## Step 10: Commit, Push, Deploy

```bash
PYTHONPATH=.specify/extensions/harness python3 -c "
import sys
sys.path.insert(0, '.specify/extensions/harness')
from harness.config import load_config
from harness.gitops import GitOpsManager

config = load_config()
gitops = GitOpsManager(config)
feature_branch = gitops.find_feature_branch('{spec_id}')
push_branch = feature_branch or 'bugfix/{spec_id}/iter-0'
gitops.commit('{worktree_path}', 'fix({spec_id}): {short_description} [skip ci]')
gitops.push('{worktree_path}', push_branch)
print('branch:', push_branch)
"
```

If `auto_deploy = true`:

```bash
bash .specify/extensions/echelon/scripts/bash/deploy.sh
```

---

## Step 11: Report

```
════════════════════════════════════════════════
  ✓ bugfix — {spec_id}: {spec_name}
════════════════════════════════════════════════
  Status:     {DEPLOYED | VERIFIED}
  Issue:      {description}
  Root cause: {one-liner from DEBUGGER}
  Fix:        {N files changed}
  Tests:      {N passing}  (+{N new})
  Live:       http://localhost/{app_name}/

  Squad used
    DEBUGGER      ✓ root cause identified
    SENTINEL      ✓ test strategy defined
    IMPLEMENTER   ✓ fix written
    TEST GUARDIAN ✓ coverage verified
    SPEC GUARD    ✓ spec compliance confirmed
    INTEGRATOR    ✓ no regressions
════════════════════════════════════════════════
```

If verification failed:

```
════════════════════════════════════════════════
  ✗ bugfix — {spec_id}: {spec_name}
════════════════════════════════════════════════
  Status:   FAILED — {N} verify attempts exhausted
  Stopped at: Step {N}
  Reason:   {key error from last verify run}
  Branch:   {feature_branch} (changes committed, not deployed)
════════════════════════════════════════════════
```
