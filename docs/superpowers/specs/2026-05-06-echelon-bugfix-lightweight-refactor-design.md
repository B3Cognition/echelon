# Design: echelon.bugfix.md Lightweight Orchestrator Refactor

**Date:** 2026-05-06  
**Status:** Approved  
**Scope:** `~/work/evolution/echelon`  
**Predecessor:** `docs/superpowers/specs/2026-05-06-echelon-run-lightweight-refactor-design.md`

---

## Problem

`extension/commands/echelon.bugfix.md` (307 lines) is self-contained: it embeds its full 6-step workflow inline and does not load `commander.md`. This means:

- COMMANDER runs the diagnostic without the behavioral framework (NEVER rules, Post-Dispatch Protocol, Calibration Injection, Evidence Hierarchy, etc.)
- "Professional Conduct" and "Execution Continuity" behavioral rules are duplicated inline rather than inherited from `commander.md`
- The workflow is not represented in `workflow/definition.yaml` — no `spec_file:` links, no phase graph

The same architectural gap as `echelon.run.md` before its refactor, at smaller scale.

---

## Design

### Principle: Same pattern as `echelon.run.md`

| Responsibility | File | Read by |
|---|---|---|
| Entry point — load commander, state entry phase | `extension/commands/echelon.bugfix.md` | AI coding tool |
| Behavioral framework | `extension/agents/control/commander.md` | COMMANDER at load time |
| Phase graph, transitions, `spec_file:` links | `workflow/definition.yaml` `phases[]` | COMMANDER for routing |
| Per-phase execution detail | `workflow/phases/bugfix-{N}-{name}.md` | COMMANDER before each dispatch |

---

### Change 1: `extension/commands/echelon.bugfix.md` — thin wrapper

Keep frontmatter unchanged. Replace body with:

```markdown
## Role

You are MANAGER executing a diagnostic triage for a delivered spec.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, and all NEVER rules.

Then read `workflow/definition.yaml` `phases[]`. Start at phase `bugfix-1-init`,
before each dispatch read the phase node's `spec_file` for context pack assembly,
dispatch prompt, and expected outputs.

**This command diagnoses and plans only. It never implements.**

---

## Scope Boundary

NEVER write, modify, or delete application source files. NEVER run tests, builds,
or linters on target project code. NEVER fix bugs or implement features directly.
The output of this command is `bugfix-{n}.md` + updated `tasks.md`, ready for
`speckit.echelon.harness-run`.

---

## User Input

$ARGUMENTS
```

---

### Change 2: `workflow/phases/` — 5 new phase files

Named `bugfix-{N}-{name}.md` (numbered-collapsed convention matching user preference).

| File | Source section | Content |
|---|---|---|
| `bugfix-1-init.md` | Steps 0–1 | Branch check, parse args, locate spec dir, read source files |
| `bugfix-2-diagnose.md` | Step 2 | DEBUGGER dispatch — context pack, prompt, expected outputs |
| `bugfix-3-test-strategy.md` | Step 3 | SENTINEL dispatch — context pack, prompt, expected outputs |
| `bugfix-4-spec-compliance.md` | Step 4 | SPEC GUARD dispatch — context pack, prompt, expected outputs |
| `bugfix-5-finalize.md` | Steps 5–6 | Write bugfix-{n}.md, append BF{n} tasks to tasks.md, branch switch, handoff banner |

Each file uses the standard 4-line header:

```
# Phase: bugfix-2-diagnose
# Source: echelon.bugfix.md §2 — DEBUGGER Root Cause Analysis
# Agent: DEBUGGER
# Read by: COMMANDER before dispatching DEBUGGER
```

---

### Change 3: `workflow/definition.yaml` — 6 new nodes in `phases[]`

Appended after the `escalate` terminal node. Linear `always` transitions — no routing logic.

```yaml
  # --------------------------------------------------------------------------
  # BUGFIX WORKFLOW
  # Invoked via speckit.echelon.bugfix. Entry point: bugfix-1-init.
  # --------------------------------------------------------------------------
  - id: bugfix-1-init
    label: "Bugfix Init"
    spec_file: workflow/phases/bugfix-1-init.md
    type: commander_internal
    description: >
      Parse arguments, verify default branch, locate spec dir,
      identify relevant source files. No agent dispatch.
    steps:
      - id: branch_check
        label: "Ensure on default branch"
      - id: parse_args
        label: "Parse spec_id and description from $ARGUMENTS"
      - id: locate_spec
        label: "Locate specs/{spec_id}-{spec_name}/ directory"
      - id: read_context
        label: "Read spec files and source files into context"
        files:
          - spec.md
          - coverage-map.md
          - tasks.md
          - deploy-state.json
        missing_files: skip_gracefully
      - id: identify_source_files
        label: "Identify relevant source files from description"
    transitions:
      - to: bugfix-2-diagnose
        condition: always

  - id: bugfix-2-diagnose
    label: "Root Cause Analysis (DEBUGGER)"
    spec_file: workflow/phases/bugfix-2-diagnose.md
    type: agent
    agent: DEBUGGER
    tier: build
    context_pack:
      - user description
      - spec.md
      - relevant source files (from bugfix-1-init)
      - deploy-state.json (if exists)
    outputs:
      - debugger_report (root cause, fix description, risk surface)
    transitions:
      - to: bugfix-3-test-strategy
        condition: always

  - id: bugfix-3-test-strategy
    label: "Test Strategy (SENTINEL)"
    spec_file: workflow/phases/bugfix-3-test-strategy.md
    type: agent
    agent: SENTINEL
    tier: solution
    context_pack:
      - debugger_report
      - spec.md
      - coverage-map.md (if exists)
      - existing test files for affected component
    outputs:
      - test_strategy (failing test spec + regression coverage)
    transitions:
      - to: bugfix-4-spec-compliance
        condition: always

  - id: bugfix-4-spec-compliance
    label: "Spec Compliance (SPEC GUARD)"
    spec_file: workflow/phases/bugfix-4-spec-compliance.md
    type: agent
    agent: SPEC_GUARD
    tier: build
    context_pack:
      - spec.md
      - coverage-map.md (if exists)
      - debugger_report
    outputs:
      - spec_guard_report (scope validation, requirement mapping)
    transitions:
      - to: bugfix-5-finalize
        condition: always

  - id: bugfix-5-finalize
    label: "Bugfix Finalize"
    spec_file: workflow/phases/bugfix-5-finalize.md
    type: commander_internal
    description: >
      Write bugfix-{n}.md from all three reports. Append BF{n} tasks
      to tasks.md. Switch to feature branch for artifact commit.
      Return to default branch. Print handoff banner.
    context_pack:
      - debugger_report
      - test_strategy
      - spec_guard_report
    outputs:
      - specs/{spec_id}-{spec_name}/bugfix-{n}.md   # harness.run input
      - specs/{spec_id}-{spec_name}/tasks.md         # BF{n} tasks appended
    transitions:
      - to: bugfix-done
        condition: always

  - id: bugfix-done
    label: "Bugfix Complete"
    type: terminal
```

---

## What Does Not Change

- Individual agent files (`debugger.md`, `sentinel.md`, `spec-guard.md`) — untouched
- `workflow/journal-entry-types.yaml` — untouched
- `extension.yml` — untouched (phase files are runtime-read data, not registered capabilities)
- All other commands — untouched

---

## Success Criteria

- `echelon.bugfix.md` is ≤ 25 lines
- 5 `workflow/phases/bugfix-*.md` files exist, each > 10 lines
- `workflow/definition.yaml` has 5 new `spec_file:` entries under bugfix nodes, all pointing to existing files
- `bugfix-done` terminal node present
- COMMANDER behavioral framework accessible via `commander.md` delegation
- Existing bugfix-related tests pass (or are updated to check new locations)
