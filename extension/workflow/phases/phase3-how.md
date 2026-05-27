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
- `reasoning-journal.jsonl`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include spec.md, feasibility.md, prioritization.md, constitution.md if available, all specialist outputs, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ARCHITECT. Read agents/solution/architect.md for your complete protocol.
  Select technology stack with explicit rationale. Design system structure (data model, API contracts, component architecture). Define cross-cutting concerns as architectural decisions. Document every decision in ADR format. Produce outputs in `specs/{NNN}-{feature}/`. Append entries to `reasoning-journal.jsonl`.
  </instructions>
  ```

- **description:** "speckit-echelon-architect (ARCHITECT): architecture design and technology decisions"

### Expected Outputs — ALL REQUIRED

speckit-echelon-architect (ARCHITECT) produces these files in `specs/{NNN}-{feature}/`. Missing any of them breaks downstream phases: speckit-echelon-sentinel (SENTINEL) needs `plan.md`, speckit-echelon-orchestrator (ORCHESTRATOR) needs `contracts/`.

| Output | Notes |
| --- | --- |
| `plan.md` | High-level implementation plan with phases, stack decisions, and component breakdown. Required by speckit-echelon-sentinel (SENTINEL) and speckit-echelon-orchestrator (ORCHESTRATOR). |
| `research.md` | ADR rationale, technology comparisons, references. |
| `data-model.md` | Entity definitions, relationships, validation rules. |
| `contracts/` | API / interface specifications directory. At minimum one file per external boundary. |
| `constitution.md` | Only if new technical principles were added; append-only to existing file. |

**Post-dispatch verification (MANDATORY — run before transitioning to phase3-sentinel):**

```bash
for f in plan.md research.md data-model.md; do
  [ -f "specs/${SPEC_DIR}/$f" ] || { echo "ERROR: speckit-echelon-architect (ARCHITECT) missing $f" >&2; exit 1; }
done
[ -d "specs/${SPEC_DIR}/contracts" ] || { echo "ERROR: speckit-echelon-architect (ARCHITECT) missing contracts/" >&2; exit 1; }
```

**Transition:** `phases[phase3-sentinel]` — see `workflow/definition.yaml`
