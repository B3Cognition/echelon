# Phase: bugfix-5-finalize
# Source: echelon.bugfix.md §Steps 5–6 — Write Artifacts + Handoff
# Read by: speckit-echelon-commander (COMMANDER) before executing finalization sequence

## Step 5: Write Bugfix Artifacts

Echelon owns branch creation and selection. The controller must already have
the full feature branch for `{spec_id}` active before this phase begins. NEVER
create, switch, rename, or discover a branch from this phase. If the
controller-provided `spec_dir` is unavailable, return BLOCKED and ask the
operator to select the spec through `echelon spec switch <spec-or-run-id>`.

Write all bugfix artifacts only into the controller-provided `{spec_dir}`.

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
