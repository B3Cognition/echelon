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
  placeholders. Rewrite this exact run-local file during the current dispatch
  and claim it in `output_files`. The controller validates the provider receipt
  and promotes the sealed draft only after the spec step has durable authority.

## State Contract

CHIEF does not own controller state. Emit no state updates; the controller sets
`constitution_status: exists` in the same final postimage authorized by the
sealed publication step.

```yaml
state_updates: {}
```

## echelon_result Contract

```yaml
echelon_result:
  verdict: DONE
  output_files:
    - ${SQUAD_DIR}/constitution.draft.md
  state_updates: {}
```

## Mode-Specific Notes

- If `${SQUAD_DIR}/constitution.draft.md` already exists, treat it only as an
  input to amend or verify. Rewrite the exact file before claiming it; stale
  output from an earlier dispatch is not publication evidence.
- `constitution_status: "exists"` in state.json skips this phase on subsequent
  runs — the harness will not re-dispatch CHIEF for creation.
