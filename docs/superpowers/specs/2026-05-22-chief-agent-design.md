# CHIEF Agent Design

**Date:** 2026-05-22  
**Status:** Approved  
**Scope:** New `speckit-echelon-chief` agent for constitution creation and amendment

---

## Problem

`phase1-constitution` was `commander_internal` (harness no-op), leaving the
constitution as a blank template after every squad run. Users had to manually
invoke `/speckit-echelon-constitution` in a Claude Code interactive session.
COMMANDER also mixed two unrelated concerns: orchestration/routing AND
governance initialisation (constitution).

---

## Design Patterns Established

### 1. Dispatcher / Protocol Split

> **The spec file is the dispatcher + phase contract. The agent file is the
> invariant protocol.**

A spec file (`workflow/phases/phase1-constitution.md`) should only tell an
agent:
- **What to read** — context pack (which files)
- **What mode to operate in** — creation vs amendment
- **What to produce** — expected output filenames
- **What state to write** — `state_updates` keys the harness reads
- **What echelon_result to emit** — routing contract

A spec file must NOT describe how the agent does its work internally — that
belongs in the agent file. Violation leads to protocol drift (same logic in two
places with diverging details over time).

**Applies to:** all echelon agents. Existing spec files that describe agent
internals should be refactored to remove them on next revision.

---

### 2. ALWAYS / NEVER Pairs

> **Every behavioural rule in an agent file has both a positive and a negative
> form.**

The ALWAYS form states what good behaviour looks like (positive motivation,
aligned with Anthropic best-practices for effective prompting). The NEVER form
closes the escape route (prevents rationalisation). Together they form a
complete behavioural contract.

```
ALWAYS [positive behaviour]
NEVER  [its violation]
```

**Existing agents** only have NEVER rules. New agents must have paired rules.
Existing agents adopt paired rules when next revised.

---

## Agent: CHIEF

### Identity

| Field | Value |
|-------|-------|
| Name | CHIEF |
| Command ID | `speckit.echelon.chief` |
| File | `agents/control/chief.md` |
| Tier | `control` (alongside COMMANDER) |
| Capability | `balanced` |
| Tools | `full` (Skill + Bash + Write/Edit) |
| Color | `blue` |
| Invocation | `explicit` |

### Responsibility

CHIEF is the sole author of the project constitution. It has exactly two modes:

- **Creation** — first-time constitution initialisation from UNDERSTAND artifacts
- **Amendment** — targeted updates when scope, architecture, or team constraints change

CHIEF does not orchestrate other agents. CHIEF does not produce spec, plan, or
task artifacts. CHIEF does not make routing decisions. One job: the constitution.

### ALWAYS / NEVER Rules

| # | ALWAYS | NEVER |
|---|--------|-------|
| 1 | Always invoke `speckit.constitution` to write or update the constitution | Never write `constitution.md` via Write/Edit without first invoking `speckit.constitution` |
| 2 | Always extract context from the four staging inputs and pass it to the skill | Never call `speckit.constitution` with empty or placeholder context |
| 3 | Always verify the output and fix any unfilled placeholders after the skill completes | Never assume the skill succeeded without reading the result file |
| 4 | Always read the current constitution before any amendment | Never amend without loading the existing constitution first |

### Modes

#### Creation Mode

Triggered by `phase1-constitution`. Entry condition: `.specify/memory/constitution.md`
does not exist or is the blank template (`[PROJECT_NAME]` present).

Protocol:
1. Read four staging files (glossary, mental-model, boundaries, assumptions) + user-intent
2. Extract: domain concepts, hard constraints, validated assumptions to encode, team/tech constraints
3. Invoke `speckit.constitution` with extracted context (never with placeholders)
4. Verify: file exists, `[PROJECT_NAME]` absent, version/date populated
5. Fix placeholders if needed (sed, not re-invoking skill)
6. Emit `echelon_result` with `state_updates: {constitution_status: "exists"}`

#### Amendment Mode

Triggered by `echelon change` resolution and banzai escalation when constitution
gaps are identified. Entry condition: constitution exists and a specific amendment
is required.

Protocol:
1. Read current `constitution.md` (mandatory)
2. Read the amendment trigger (change description, gap report, or scope delta)
3. Identify the specific principle(s) to add/modify
4. Invoke `speckit.constitution` with the targeted amendment context
5. Verify the amendment landed; confirm no other principles were altered
6. Emit `echelon_result` with `state_updates: {constitution_status: "amended"}`

---

## Workflow Wiring

### definition.yaml

`phase1-constitution` changes from `type: commander_internal` to:

```yaml
- id: phase1-constitution
  label: "Constitution Creation"
  spec_file: workflow/phases/phase1-constitution.md
  type: agent
  agent: speckit-echelon-chief
  tier: control
  context_pack:
    - .specify/squad/staging/glossary.md
    - .specify/squad/staging/mental-model.md
    - .specify/squad/staging/boundaries.md
    - .specify/squad/staging/assumptions.md
    - .specify/squad/staging/user-intent.md
```

Amendment phases wire CHIEF separately (out of scope for this implementation).

### phase1-constitution.md (spec file)

Declares mode, expected outputs, and echelon_result contract only.
Does NOT describe how CHIEF invokes the skill or verifies output — those live
in `chief.md`.

### extension.yml

```yaml
- name: speckit.echelon.chief
  file: agents/control/chief.md
  description: "CHIEF — project constitution author and governance steward"
  behavior:
    execution: agent
    capability: balanced
    tools: full
    color: blue
    invocation: explicit
```

---

## Out of Scope (this implementation)

- Wiring CHIEF into `echelon change` amendment flow
- Wiring CHIEF into banzai escalation resolution
- Retroactively adding ALWAYS/NEVER pairs to existing agents
- `constitution_status` state field propagation beyond `phase1-constitution`

---

## Self-Review

- No placeholder or TBD sections
- No contradictions between sections
- Scope is well-bounded: one agent, one new phase wiring, two design patterns documented
- ALWAYS/NEVER pairs are complete and non-overlapping
- Amendment wiring deferred cleanly with explicit out-of-scope note
