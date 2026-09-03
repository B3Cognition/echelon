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

- `${SQUAD_DIR}/constitution.draft.md` — filled, verified, no unfilled
  placeholders. The controller alone validates and publishes this run-local
  draft to the canonical workspace constitution.

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
    - ${SQUAD_DIR}/constitution.draft.md
  state_updates:
    constitution_status: "exists"
```

## Mode-Specific Notes

- If `${SQUAD_DIR}/constitution.draft.md` already exists with real content (no
  `[PROJECT_NAME]` marker), the draft was previously created. Emit `verdict:
  DONE` immediately without re-invoking the skill.
- `constitution_status: "exists"` in state.json skips this phase on subsequent
  runs — the harness will not re-dispatch CHIEF for creation.
