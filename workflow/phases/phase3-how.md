# Phase: phase3-how
# Source: echelon.run.md §8 — HOW Phase (Architecture)
# Agent: speckit-echelon-architect (ARCHITECT)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-architect (ARCHITECT)

## 8. HOW Phase (Architecture)

### Context Pack Assembly

Read and include in the subagent prompt:

- `spec.md` + `feasibility.md` + `prioritization.md`
- `constitution.md` (if exists from prior run or user provided)
- All specialist outputs (threat-model.md, performance-requirements.md, etc.)
- `reasoning-journal.json`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include spec.md, feasibility.md, prioritization.md, constitution.md if available, all specialist outputs, reasoning-journal.json]
  </context>

  <instructions>
  You are ARCHITECT. Read agents/solution/architect.md for your complete protocol.
  Select technology stack with explicit rationale. Design system structure (data model, API contracts, component architecture). Define cross-cutting concerns as architectural decisions. Document every decision in ADR format. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.json`.
  </instructions>
  ```

- **description:** "speckit-echelon-architect (ARCHITECT): architecture design and technology decisions"

### Expected Outputs

- `plan.md`
- `research.md`
- `data-model.md`
- `contracts/` (API/interface specs)
- `constitution.md`

**Transition:** `phases[phase3-sentinel]` — see `workflow/definition.yaml`
