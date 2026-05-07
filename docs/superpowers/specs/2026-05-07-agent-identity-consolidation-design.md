# Agent Identity Consolidation Design

**Date:** 2026-05-07
**Status:** Draft — awaiting implementation plan

## Problem

Echelon's 42-agent system has fragmented identity metadata spread across four locations:

| File | What it holds |
|------|--------------|
| `extension/extension.yml` | Deployment: name, file, description, behavior |
| `extension/agents.yaml` | Metadata: codename, function, layer, phase, inputs, outputs, routing |
| `workflow/definition.yaml` | Operational: phase graph, routing, agent dispatch order, context packs |
| `extension/agents/control/commander.md` | Prose rules using a third naming layer (functional names: HOW, WHY, DISCOVER, etc.) |

### The naming mess

Three distinct naming systems are in use simultaneously:

| System | Example | Used for |
|--------|---------|----------|
| Spec-kit deployed name | `speckit-echelon-auditor` | Actual Agent tool dispatch (subagent_type) |
| Codename | `AUDITOR` | Human-readable references in prose |
| Functional name | `CALIBRATE` (agents.yaml) or `WHY`/`HOW`/`DISCOVER` (commander.md) | Inconsistently mixed into routing prose and the Role Separation table |

The functional names in `commander.md` introduce a third layer that is:
- Only partially covering 7 of 42 agents
- Inconsistent with `agents.yaml` function labels (e.g., INVESTIGATOR's function is `RESEARCH` but commander calls it `SCIENTIST`)
- Inconsistent with the workflow phase IDs in `definition.yaml` (which use a different functional vocabulary)

### The redundancy

`agents.yaml` was the original agent registry. Since the workflow externalization to `definition.yaml`, its content is fully covered elsewhere:

| agents.yaml field | Already in |
|------------------|-----------|
| file | extension.yml |
| layer | File path: `extension/agents/{layer}/` |
| phase | definition.yaml phase nodes |
| when | definition.yaml phase nodes |
| context_pack / inputs | definition.yaml context_pack per phase |
| outputs | definition.yaml outputs per phase |
| routing section | definition.yaml routing section |
| never rules | Each agent's .md file |
| role one-liner | Each agent's .md Role section |

### Authoring friction

Adding or renaming an agent currently requires changes in 4 places: extension.yml, agents.yaml, commander.md table, and the .md file. This creates drift.

---

## Design

### Canonical identity rule

The canonical identifier for any echelon agent is its **spec-kit-injected deployed name**.

**Pattern:** `speckit-echelon-{filename_without_extension}`

Examples:
- `commander.md` → `speckit-echelon-commander`
- `auditor.md` → `speckit-echelon-auditor`
- `spec-guard.md` → `speckit-echelon-spec-guard`

This name is deterministically derived by spec-kit from the extension.yml entry:
`speckit.echelon.auditor` → dots-to-hyphens → `speckit-echelon-auditor`.

It is written to the deployed file's frontmatter as `name:` by spec-kit at install time. No manual derivation needed.

**Dispatch rule:** All Agent tool calls use this name as `subagent_type`. All routing references (in commander.md, definition.yaml, phase .md files) use this name when identifying which agent to invoke.

**Prose rule:** Codenames (AUDITOR, SCOUT, etc.) may be used in descriptive prose for readability. They MUST NOT be used in actionable dispatch or routing contexts — use the spec-kit name there.

**Functional names (HOW, WHY, DISCOVER, etc.):** Removed from all agent references. Phase-level labels in journal entries (DISCOVER, WHAT, WHY, BUILD, FINALIZE) are kept as coarse-grained phase group identifiers consistent with definition.yaml phase ID prefixes.

---

### Change 1: Delete `extension/agents.yaml`

Delete the file entirely.

Rationale: All content is covered by definition.yaml (routing, phases, context), extension.yml (deployment), and individual .md files (role, never rules). The `function` field (CALIBRATE, SCHEMA_CONSOLIDATION, etc.) is not machine-consumed and disappears with the file.

When adding a new agent after this change, the author updates two files:
1. `extension.yml` — add deployment entry
2. `extension/agents/{layer}/{name}.md` — write the agent prompt

No registry maintenance required.

---

### Change 2: Fix `commander.md` — Role Separation Table

Replace the functional-name Role Separation table with a spec-kit-name + codename table:

```markdown
| Spec-kit name | Codename | PRODUCES | NEVER does |
|---------------|----------|----------|------------|
| speckit-echelon-scout | SCOUT | glossary, mental-model, boundaries, assumptions, unknowns | Never writes requirements, never makes architecture decisions |
| speckit-echelon-cartographer | CARTOGRAPHER | spec.md, requirements | Never validates own specs (speckit-echelon-sage does that), never designs architecture |
| speckit-echelon-sage | SAGE | issues.md, quality-gates.md | NEVER rewrites specs/plans/tasks — finds problems only. Responsible agent fixes. |
| speckit-echelon-gatekeeper | GATEKEEPER | feasibility, estimates, prioritization | Never writes requirements, never designs architecture |
| speckit-echelon-architect | ARCHITECT | plan.md, research.md, ADRs, data-model, contracts | Never writes requirements, never estimates effort |
| speckit-echelon-orchestrator | ORCHESTRATOR | tasks.md, critical-path, risk-matrix | Never designs architecture, never writes requirements |
| speckit-echelon-investigator | INVESTIGATOR | investigation reports, experiment results | Never makes architecture decisions (speckit-echelon-architect does that) |
```

Remove the "Naming convention" note below the table (no longer needed).

---

### Change 3: Fix `commander.md` — Routing Rules Section

The routing rules section currently uses functional names in actionable dispatch instructions. Replace with spec-kit names:

**Before:**
```
- Spec issues → dispatch **WHAT** (CARTOGRAPHER) to fix → then **WHY** re-validates
- Architecture issues → dispatch **HOW** (ARCHITECT) to fix → then **WHY** re-validates
- Task issues → dispatch **PLAN** (ORCHESTRATOR) to fix → then **WHY** re-validates
- Unknown questions → dispatch **SCIENTIST** (INVESTIGATOR) to investigate → feed results to the relevant agent
```

**After:**
```
- Spec issues → dispatch **speckit-echelon-cartographer** → then **speckit-echelon-sage** re-validates
- Architecture issues → dispatch **speckit-echelon-architect** → then **speckit-echelon-sage** re-validates
- Task issues → dispatch **speckit-echelon-orchestrator** → then **speckit-echelon-sage** re-validates
- Unknown questions → dispatch **speckit-echelon-investigator** → feed results to the relevant agent
```

---

### Change 4: Fix `commander.md` — Constitution Rules and Other Prose

Replace all functional name agent references in prose with spec-kit names. Codenames may be retained in parenthetical or descriptive context.

Substitution map for actionable agent references:

| Replace | With |
|---------|------|
| `HOW` (as agent reference) | `speckit-echelon-architect` |
| `WHY` (as agent reference) | `speckit-echelon-sage` |
| `WHAT` (as agent reference) | `speckit-echelon-cartographer` |
| `ASSESS` (as agent reference) | `speckit-echelon-gatekeeper` |
| `DISCOVER` (as agent reference) | `speckit-echelon-scout` |
| `PLAN` (as agent reference) | `speckit-echelon-orchestrator` |
| `SCIENTIST` | `speckit-echelon-investigator` |
| `INNOVATE` (as agent reference) | `speckit-echelon-maverick` |

Key examples:

**Constitution section:**
- `"HOW may APPEND technical principles"` → `"speckit-echelon-architect (ARCHITECT) may APPEND technical principles"`
- `"validated by WHY"` → `"validated by speckit-echelon-sage"`
- `"HOW, ASSESS, PLAN, INNOVATE — every agent"` → `"speckit-echelon-architect, speckit-echelon-gatekeeper, speckit-echelon-orchestrator, speckit-echelon-maverick — every agent"`

**Dispatch Mechanism section:**
- The pattern note `speckit-echelon-<codename-lowercase>` is already correct — keep it, but make it explicit that the source is the extension.yml name entry.

**Exception — journal phase labels:**
Keep functional names as coarse-grained phase labels in the journal entry schema:
```
"phase": "DISCOVER, WHAT, WHY, HOW, PLAN, ASSESS, SPECIALISTS, BUILD, FINALIZE"
```
These are phase group identifiers matching definition.yaml phase ID prefixes (`phase1-discover`, `phase1-what`, etc.), not agent dispatch names.

---

### Change 5: Verify `workflow/definition.yaml`

No changes expected. Verify that all `agent:` fields in definition.yaml already use codenames (SCOUT, SAGE, etc.) and that dispatch instructions in phase .md files use the spec-kit name pattern. File any corrections found.

---

### Change 6 (Optional): Add `layer:` to `extension.yml` agent entries

Add an explicit `layer:` field to each agent entry in extension.yml. This is currently derivable from the file path but making it explicit aids tooling and grep.

```yaml
- name: "speckit.echelon.auditor"
  file: "agents/learning/auditor.md"
  layer: learning
  description: "AUDITOR — calibration engineer tracking squad confidence profile"
  behavior:
    execution: agent
    capability: balanced
    tools: full
    color: yellow
```

Layers: `control`, `exploration`, `feasibility`, `solution`, `specialists`, `build`, `learning`.

This is optional and does not affect dispatch reliability.

---

## Authoring contract after consolidation

When **adding a new agent**:
1. Create `extension/agents/{layer}/{name}.md`
2. Add one entry to `extension.yml` `provides/commands`
3. Add the agent to the appropriate phase node in `workflow/definition.yaml`

When **dispatching an agent** (in commander.md, phase .md files, or definition.yaml):
- Always use `speckit-echelon-{filename}` as the dispatch identifier
- Codename may appear in description field for human readability

When **referencing an agent** in prose:
- Use codename (AUDITOR, SCOUT) for readability
- Use spec-kit name when the reference is to a dispatch action

---

## Files changed

| File | Change |
|------|--------|
| `extension/agents.yaml` | **DELETE** |
| `extension/agents/control/commander.md` | Rewrite Role Separation table; replace ~20 functional-name agent references with spec-kit names in routing, constitution, and dispatch sections |
| `workflow/definition.yaml` | Verify agent references; no changes expected |
| `extension/extension.yml` | Optional: add `layer:` field to each agent entry |
| Individual agent `.md` files | No changes |

## Non-goals

- Do not change `definition.yaml` routing logic
- Do not change individual agent `.md` file content
- Do not change how spec-kit deploys agents (the transformation from dots to hyphens)
- Do not change the journal phase label vocabulary (DISCOVER, WHAT, etc. remain as phase labels)
