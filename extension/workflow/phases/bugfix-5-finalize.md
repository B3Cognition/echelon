# Phase: bugfix-5-finalize
# Source: echelon.bugfix.md §Steps 5–6 — Write Artifacts + Handoff
# Read by: speckit-echelon-commander (COMMANDER) before executing finalization sequence

## Step 5: Write Bugfix Artifacts

Switch to the feature branch so the bugfix artifacts are committed there (not
on the default branch).

First, check whether the feature branch already exists:

```bash
FEATURE_BRANCH="{spec_id}-{spec_name}"
if git rev-parse --verify "$FEATURE_BRANCH" >/dev/null 2>&1; then
  echo "BRANCH_EXISTS=true"
else
  echo "BRANCH_EXISTS=false"
fi
```

**If the branch exists** (`BRANCH_EXISTS=true`): check it out directly:

```bash
git checkout "$FEATURE_BRANCH"
```

**If the branch does not exist** (`BRANCH_EXISTS=false`): create it before proceeding:

1. Strip the leading `{spec_id}-` prefix from `{spec_name}` to get the short name.
   For example, if `{spec_name}` is `042-feed-parser`, the short name is `feed-parser`.
   Derive the feature description from the short name (replace hyphens with spaces).
   For `feed-parser`, the description is `feed parser`.
2. Invoke `speckit.git.feature` via the Skill tool with the derived description.
   This creates a new branch following spec-kit's naming convention and checks it out.
3. After branch creation, capture the branch name from the skill output (the
   `BRANCH_NAME` field in the JSON response). **Update `FEATURE_BRANCH`** to match
   the actual branch name returned by the skill — always use the returned branch;
   do not assume it matches the
   original `{spec_id}-{spec_name}` value. Use this updated `FEATURE_BRANCH` for
   all subsequent steps.
4. If `speckit.git.feature` is unavailable (Skill tool errors), fall back to running
   the script directly. Use `{short_name}` (with the numeric prefix stripped) for
   both `--short-name` and the positional argument:

   ```bash
   SHORT_NAME=$(echo "{spec_name}" | sed 's/^[0-9]*-//')
   .specify/extensions/git/scripts/bash/create-new-feature.sh --json --allow-existing-branch --short-name "$SHORT_NAME" "$SHORT_NAME"
   FEATURE_BRANCH=$(git branch --show-current)
   ```

5. Confirm the branch is active: `git branch --show-current`.
6. Log: `bugfix: created missing feature branch $FEATURE_BRANCH for spec {spec_id}`.

Proceed with the rest of Step 5 on the newly created (or existing) feature branch.

Determine the next bugfix index:

```bash
ls "{spec_dir}"/bugfix-*.md 2>/dev/null | wc -l
```

Let `{n}` = count + 1 (e.g. `bugfix-1.md` if none exist yet).

Write `{spec_dir}/bugfix-{n}.md`:

```markdown
# Bugfix {n}: {description}

## Root Cause
{from speckit-echelon-debugger (DEBUGGER): file, line, mechanism}

## Fix Scope
{from speckit-echelon-debugger (DEBUGGER): what changes and why}

## Risk Surface
{from speckit-echelon-debugger (DEBUGGER): what else could break}

## Test Strategy
{from speckit-echelon-sentinel (SENTINEL): failing test specification + regression coverage}

## Spec Compliance
{from speckit-echelon-spec-guard (SPEC GUARD): which requirement(s) this addresses, any scope notes}
```

Then append the bugfix tasks to `{spec_dir}/tasks.md`. Use `extension/templates/bugfix-task-fragment.md` and the canonical task row contract. Add a clearly delimited section at the end:

```markdown
---
## Bugfix {n}: {description}

> Source: bugfix-{n}.md
> Status: pending

- [ ] T-{next} complexity=standard phase=bugfix req={FR-id} depends=none

  **Title:** BF{n}-T1 - Write failing test for {description}

- [ ] T-{next+1} complexity=standard phase=bugfix req={FR-id} depends=T-{next}

  **Title:** BF{n}-T2 - Fix {file}

- [ ] T-{next+2} complexity=standard phase=bugfix req={FR-id} depends=T-{next+1}

  **Title:** BF{n}-T3 - Verify regression and prior tests
```

After writing the artifacts, switch back to the default branch so harness.run
finds a clean starting state:

```bash
git checkout "$DEFAULT_BRANCH"
echo "Returned to $DEFAULT_BRANCH — feature branch $FEATURE_BRANCH preserved with bugfix artifacts."
```

---

## Step 6: Handoff

Print the handoff block and stop:

```
════════════════════════════════════════════════
  ✓ echelon.bugfix — {spec_id}: {spec_name}
════════════════════════════════════════════════
  Issue:      {description}
  Root cause: {one-liner from speckit-echelon-debugger (DEBUGGER)}
  Fix:        {what changes — N files}
  Risk:       {risk surface summary}

  Artifacts written
    {spec_dir}/bugfix-{n}.md
    {spec_dir}/tasks.md  (BF{n} tasks appended)

  Next step — choose your build strategy:

    Default (LLM implements directly):
      speckit.echelon.harness-run {spec_id} strategy=default

    Codegen (SOAR pipeline):
      speckit.echelon.harness-run {spec_id} strategy=codegen
════════════════════════════════════════════════
```

Always stop after this handoff. Do not proceed further; the user runs `harness.run` when ready.
