# Phase: phase1-constitution
# Agent: echelon.chief (CHIEF)
# Mode: Creation

> **Dispatcher contract** — this file tells CHIEF what to read, what mode to
> operate in, and what to produce. It does NOT describe how CHIEF invokes the
> skill or verifies output — that invariant protocol lives in `chief.md`.

## Dispatch

You are CHIEF. Operate in **Creation mode**.

The five `{spec_dir}` files in your context pack (glossary, mental-model, boundaries,
assumptions, user-intent) are your raw material. Follow your Creation mode
protocol from `chief.md` exactly.

## Expected Output

- `.echelon/constitution.md` — filled, verified, no unfilled placeholders

## State Contract

The harness reads `state_updates.constitution_status` to record that the
constitution was created. Emit:

```yaml
state_updates:
  constitution_status: "exists"
```

## echelon_result Contract

```yaml
echelon_result:
  verdict: DONE
  output_files:
    - .echelon/constitution.md
  state_updates:
    constitution_status: "exists"
```

## Mode-Specific Notes

- If `.echelon/constitution.md` already exists with real content (no
  `[PROJECT_NAME]` marker), the constitution was previously created. Emit
  `verdict: DONE` immediately without re-invoking the skill.
- `constitution_status: "exists"` in state.json skips this phase on subsequent
  runs — the harness will not re-dispatch CHIEF for creation.
