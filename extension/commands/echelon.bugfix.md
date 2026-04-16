---
name: speckit.echelon.bugfix
description: "Diagnostic squad for a bug or enhancement on a delivered spec — DEBUGGER → SENTINEL → SPEC GUARD → writes bugfix plan + tasks → hand off to harness.run."
behavior:
  invocation: automatic
---

## User Input

$ARGUMENTS

---

## Overview

`echelon.bugfix` is the **diagnostic half** of the bugfix pipeline. It mirrors the same split as `echelon.run` → `harness.run`:

| Command | Does | Produces |
| ------- | ---- | -------- |
| `speckit.echelon.bugfix` | Diagnoses the issue, designs the test strategy, validates spec compliance | `bugfix-{n}.md` + updated `tasks.md` |
| `speckit.harness.run {spec_id}` | Builds the fix, verifies in Docker, deploys | Working code in production |

**`echelon.bugfix` never implements.** It produces the analysis and plan. The user then runs `harness.run` with their chosen strategy (`default` or `codegen`).

Squad agents used in this command:

| Phase | Agent | Purpose |
| ----- | ----- | ------- |
| 1. Diagnose | **DEBUGGER** | Root cause analysis — reads code, identifies exact failure mechanism |
| 2. Test strategy | **SENTINEL** | Designs the failing test that proves the bug and will prove the fix |
| 3. Spec compliance | **SPEC GUARD** | Confirms the fix scope satisfies the relevant spec requirement |

Skipped here (handled by harness): IMPLEMENTER, TEST GUARDIAN, INTEGRATOR, Docker verify, deploy.

**Use this when:**

- A delivered feature has a known bug
- A small enhancement is needed on top of an existing spec
- A previous harness run produced a broken result you want to fix

**Do NOT use this for:**

- New features — use `speckit.echelon.run`
- Major scope or architecture changes — use `speckit.echelon.change`

---

## Professional Conduct — ABSOLUTE RULE

Execute the request. Do not editorialize about whether it's too small, too large, or better handled differently. The user decides.

---

## Execution Continuity — ABSOLUTE RULE

After any agent returns, immediately execute the next step without stopping. The run ends only at the HANDOFF step or a documented BLOCKED condition.

---

## Step 1: Parse Input

Extract from `$ARGUMENTS`:

| Parameter | Default | Description |
| --------- | ------- | ----------- |
| `spec_id` | — | Required if multiple specs exist (e.g. `001`). |
| `description` | — | Required. What is broken or what needs to change. |

If `description` is missing: ask **"What needs to be fixed or changed?"** and stop.

If `spec_id` is absent and multiple specs exist under `specs/`, list them and ask which one. If only one spec exists, use it automatically.

Locate `specs/{spec_id}-*/`. Extract `{spec_name}`. If not found: report **"Spec `{spec_id}` not found."** and stop.

Read the following — pass to every agent dispatch:

- `specs/{spec_id}-{spec_name}/spec.md`
- `specs/{spec_id}-{spec_name}/coverage-map.md` (if exists)
- `specs/{spec_id}-{spec_name}/tasks.md` (if exists)
- `.specify/squad/deploy-state.json` (if exists)
- The relevant source files based on `description` (the component, hook, API call, config file, or test most likely related to the issue)

---

## Step 2: DEBUGGER — Root Cause Analysis

Dispatch `agents/build/debugger.md` with:

- The user's `description`
- `spec.md`
- The relevant source files from Step 1
- `deploy-state.json`

The DEBUGGER must produce:

- Exact root cause (file + line + mechanism — not a guess)
- Minimal fix description (what changes and why — not how to implement it)
- Risk surface (what else could break when this changes)

Store as `{debugger_report}`.

---

## Step 3: SENTINEL — Test Strategy

Dispatch `agents/solution/sentinel.md` with:

- `{debugger_report}`
- `spec.md`
- `coverage-map.md`
- Existing test files for the affected component/module

The SENTINEL must produce:

- A **failing test specification** — the test that will be red before the fix and green after (write the assertion, not the code)
- Regression test coverage: what adjacent behaviour needs protecting

Store as `{test_strategy}`.

---

## Step 4: SPEC GUARD — Scope Validation

Dispatch `agents/build/spec-guard.md` with:

- `spec.md`
- `coverage-map.md`
- `{debugger_report}` — the proposed fix scope

The SPEC GUARD confirms the fix is within the spec boundary: it addresses a real spec requirement and doesn't silently expand scope. If the fix requires changes outside the spec, it must say so explicitly.

Store as `{spec_guard_report}`.

---

## Step 5: Write Bugfix Artifacts

Determine the next bugfix index:

```bash
ls specs/{spec_id}-{spec_name}/bugfix-*.md 2>/dev/null | wc -l
```

Let `{n}` = count + 1 (e.g. `bugfix-1.md` if none exist yet).

Write `specs/{spec_id}-{spec_name}/bugfix-{n}.md`:

```markdown
# Bugfix {n}: {description}

## Root Cause
{from DEBUGGER: file, line, mechanism}

## Fix Scope
{from DEBUGGER: what changes and why}

## Risk Surface
{from DEBUGGER: what else could break}

## Test Strategy
{from SENTINEL: failing test specification + regression coverage}

## Spec Compliance
{from SPEC GUARD: which requirement(s) this addresses, any scope notes}
```

Then append the bugfix tasks to `specs/{spec_id}-{spec_name}/tasks.md`. Add a clearly delimited section at the end:

```markdown
---
## Bugfix {n}: {description}

> Source: bugfix-{n}.md
> Status: pending

- [ ] BF{n}-T1: Write failing test — {test from SENTINEL}
- [ ] BF{n}-T2: Fix {file} — {what changes from DEBUGGER}
- [ ] BF{n}-T3: Verify test passes and all prior tests still pass
- [ ] BF{n}-T4: Update coverage-map.md if coverage changed
```

---

## Step 6: Handoff

Print the handoff block and stop:

```
════════════════════════════════════════════════
  ✓ echelon.bugfix — {spec_id}: {spec_name}
════════════════════════════════════════════════
  Issue:      {description}
  Root cause: {one-liner from DEBUGGER}
  Fix:        {what changes — N files}
  Risk:       {risk surface summary}

  Artifacts written
    specs/{spec_id}-{spec_name}/bugfix-{n}.md
    specs/{spec_id}-{spec_name}/tasks.md  (BF{n} tasks appended)

  Next step — choose your build strategy:

    Default (LLM implements directly):
      speckit.harness.run {spec_id} strategy=default

    Codegen (SOAR pipeline):
      speckit.harness.run {spec_id} strategy=codegen
════════════════════════════════════════════════
```

Do not proceed further. The user runs `harness.run` when ready.
