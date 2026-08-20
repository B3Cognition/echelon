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
  placeholders. This is the CHIEF-authored candidate for the canonical
  constitution.

The controller owns the protected `.echelon/` root. After CHIEF returns
`DONE`, it validates this draft and atomically publishes it as
`.echelon/constitution.md`; CHIEF must never write that canonical path.

## State Contract

Do not emit `constitution_status`. The controller records
`constitution_status: "exists"` only after draft validation and canonical
publication succeed.

## echelon_result Contract

```yaml
echelon_result:
  verdict: DONE
  output_files:
    - ${SQUAD_DIR}/constitution.draft.md
  state_updates: {}
```

## Mode-Specific Notes

- If `${SQUAD_DIR}/constitution.current.md` is present, it is a
  controller-staged read-only snapshot of the current canonical constitution.
  Use it only for Amendment mode and write the amended result to
  `${SQUAD_DIR}/constitution.draft.md`.
- `constitution_status: "exists"` in state.json skips this phase on subsequent
  runs — the harness will not re-dispatch CHIEF for creation.
