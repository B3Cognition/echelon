# Phase: phase3-how
# Source: echelon.run.md §8 — HOW Phase (Architecture)
# Agent: speckit-echelon-architect (ARCHITECT)
# Read by: speckit-echelon-commander (COMMANDER) before dispatching speckit-echelon-architect (ARCHITECT)

## 8. HOW Phase (Architecture)

### Context Pack Assembly

Read and include in the subagent prompt:

- `spec.md` + `feasibility.md` + `prioritization.md`
- `constitution.md` (read-only published Phase A snapshot)
- All specialist outputs (threat-model.md, performance-requirements.md, etc.)
- `extension/templates/plan-template.md`
- `extension/templates/architecture-research-template.md`
- `extension/templates/architecture-adr-template.md`
- `extension/templates/data-model-template.md`
- `extension/templates/contracts-template.md`
- `extension/templates/constitution-amendment-candidates-template.md`
- `reasoning-journal.jsonl`

### Dispatch

Use the Agent tool to dispatch a subagent with:

- **prompt:**

  ```xml
  <context>
  [include spec.md, feasibility.md, prioritization.md, read-only constitution.md snapshot, all specialist outputs, architecture output templates including constitution-amendment-candidates-template.md, reasoning-journal.jsonl]
  </context>

  <instructions>
  You are ARCHITECT. Read agents/solution/architect.md for your complete protocol.
  Treat IMPLEMENTATION_TARGETS from the squad context as the authoritative writable destination list. Design the implementation only for those repositories. Other workspace sources and reverse-engineering artifacts are read-only evidence. If the requested architecture requires another repository, return BLOCKED and name it; never add or infer a target.
  Select technology stack with explicit rationale. For current technology documentation, use `.specify/extensions/echelon/scripts/bash/context7-docs.sh library "<technology name>" --json` then `.specify/extensions/echelon/scripts/bash/context7-docs.sh docs "<context7-library-id>" "<question>" --json` when the wrapper is installed; parse only the normalized `schema: "echelon.context7.v1"` envelope and read native Context7 data from `result` after `ok: true`; do not call connector-based Context7 tools. If the wrapper is unavailable, use official vendor/platform documentation through normal available search/browse tools and grade evidence conservatively. Design system structure (data model, API contracts, component architecture). Define cross-cutting concerns as architectural decisions. Produce `plan.md`, `research.md`, `data-model.md`, and `contracts/` using the provided templates. Treat `constitution.md` as read-only governance context: do not edit, rewrite, append to, or output `constitution.md`. If architecture work reveals a new governance principle, write it to `constitution-amendment-candidates.md` using the provided template as a proposed amendment for later CHIEF/spec-kit handling. Keep required sections and add domain-specific sections only when useful. Return journal entries in `echelon_result.journal_entries`.
  </instructions>
  ```

- **description:** "speckit-echelon-architect (ARCHITECT): architecture design and technology decisions"

### Expected Outputs — ALL REQUIRED

speckit-echelon-architect (ARCHITECT) produces these files in `{spec_dir}/`. Missing any of them breaks downstream phases: speckit-echelon-sentinel (SENTINEL) needs `plan.md`, speckit-echelon-orchestrator (ORCHESTRATOR) needs `contracts/`.

| Output | Notes |
| --- | --- |
| `plan.md` | High-level implementation plan with phases, stack decisions, and component breakdown. Required by speckit-echelon-sentinel (SENTINEL) and speckit-echelon-orchestrator (ORCHESTRATOR). |
| `research.md` | ADR rationale, technology comparisons, references. |
| `data-model.md` | Entity definitions, relationships, validation rules. |
| `contracts/` | API / interface specifications directory. At minimum one file per external boundary. |
| `constitution-amendment-candidates.md` | Optional. Proposed governance amendments only; do not edit or output `constitution.md`. |

**Post-dispatch verification (MANDATORY — run before transitioning to phase3-sentinel):**

```bash
for f in plan.md research.md data-model.md; do
  [ -f "{spec_dir}/$f" ] || { echo "ERROR: speckit-echelon-architect (ARCHITECT) missing $f" >&2; exit 1; }
done
[ -d "{spec_dir}/contracts" ] || { echo "ERROR: speckit-echelon-architect (ARCHITECT) missing contracts/" >&2; exit 1; }
python -m harness validate-plan "{spec_dir}/plan.md"
```

**Transition:** `phases[phase3-sentinel]` — see `workflow/definition.yaml`
