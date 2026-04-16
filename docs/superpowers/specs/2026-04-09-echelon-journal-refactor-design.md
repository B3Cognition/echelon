# Echelon Journal Refactor — Design Spec

**Date:** 2026-04-09
**Status:** Approved for implementation planning
**Scope:** Workflow externalization + journal write ownership + compaction-safe orchestration

---

## Problem Statement

Echelon's orchestration has three coupled problems:

1. **Workflow definition lives in COMMANDER's prompt.** Phase graph, routing rules, convergence thresholds, and build state machine are embedded as prose in `agents/control/commander.md` (~750 lines) and `skills/b3c-echelon-run/SKILL.md` (~1873 lines). After context compaction, COMMANDER must reconstruct routing logic from an incomplete context window.

2. **Multiple agents write to `reasoning-journal.json` directly.** 42 agents append entries independently. No single writer means no atomic index maintenance, making relevance-based queries impossible. COMMANDER falls back to "last N entries" which loses critical rework history when context is tight.

3. **Journal queries are positional, not semantic.** COMMANDER injects the most recent journal entries per dispatch. Entries from earlier iterations that explain current failure patterns are evicted before they are needed.

---

## Solution Overview

Three coordinated changes:

1. **Workflow definition externalized** to `workflow/definition.yaml` (already created). COMMANDER reads it on every invocation via an explicit bootstrap loop.
2. **Agents return `echelon_result` blocks** instead of writing to the journal directly. COMMANDER becomes the sole journal writer.
3. **Sidecar index** (`reasoning-journal-index.json`) maintained atomically by COMMANDER, enabling O(1) topic-based journal queries.

---

## Section 1 — Agent Output Contract

### Motivation

Agents currently produce two side effects: write artifacts to disk, and append entries to `reasoning-journal.json`. The journal writes are uncoordinated — agents assign their own IDs, timestamps, and entry types, making index maintenance impossible without a central writer.

### Contract

Every agent appends an `echelon_result` block to the **end** of its response. COMMANDER reads this block after every dispatch.

```yaml
echelon_result:
  verdict: PASS                        # Required. Agent-specific verdict values.
  output_files:                        # Required. Paths of artifacts written to disk.
    - .specify/.../spec.md
  state_updates:                       # Optional. Fields COMMANDER writes to state.json.
    phase: phase1-why2
    quality_scores:
      - pass: 3
        overall: 0.81
        structure: 0.78
        testability: 0.82
  journal_entries:                     # Optional. COMMANDER appends these to journal.
    - id: null                         # null = COMMANDER assigns sequential RJ-NNN id
      type: quality_check              # Must be a value from workflow/journal-entry-types.yaml
      phase: phase1-what
      agent: CARTOGRAPHER
      timestamp: null                  # null = COMMANDER fills at append time
      data:
        scores: { overall: 0.81, structure: 0.78, testability: 0.82 }
        issues: []
```

### Rules

- `id` and `timestamp` are always `null` from agents. COMMANDER assigns both at write time to prevent ID conflicts.
- `state_updates` and `journal_entries` are written independently — state.json and journal can be updated without each other.
- Agents that produce no journal entries set `journal_entries: []`.
- Agents **stop** writing to `reasoning-journal.json` directly. The `echelon_result` block is the only output path for journal data.
- Entry `type` values must come from `workflow/journal-entry-types.yaml` (canonical registry). Unknown types are logged as warnings and written with type `unknown`.

### Supporting files

- `workflow/journal-entry-types.yaml` — canonical list of all valid `type` values
- `templates/echelon-result-schema.json` — machine-readable JSON Schema for the output block

---

## Section 2 — Journal Index Schema

### Motivation

With COMMANDER as sole writer, atomic index maintenance becomes possible. The index enables O(1) topic lookups replacing O(N) full-journal scans.

### File locations

```
.specify/squad/
  reasoning-journal.jsonl          # Append-only log (unchanged format)
  reasoning-journal-index.json     # COMMANDER-maintained sidecar index
```

### Index structure

```json
{
  "schema_version": 1,
  "last_entry_id": "RJ-047",
  "last_updated": "2026-04-09T14:32:00Z",
  "by_phase": {
    "phase1-what": ["RJ-012", "RJ-013"],
    "build": ["RJ-031", "RJ-032", "RJ-044"]
  },
  "by_type": {
    "quality_check": ["RJ-012", "RJ-021", "RJ-044"],
    "qa_failed": ["RJ-031"],
    "routing_decision": ["RJ-013", "RJ-032"],
    "conflict_resolution": ["RJ-022"]
  },
  "by_agent": {
    "SAGE": ["RJ-012", "RJ-021"],
    "IMPLEMENTER": ["RJ-031", "RJ-044"],
    "CARTOGRAPHER": ["RJ-013"]
  },
  "by_task": {
    "T-001": ["RJ-031", "RJ-032"],
    "T-002": ["RJ-044"]
  },
  "by_severity": {
    "CRITICAL": ["RJ-022", "RJ-044"],
    "HIGH": ["RJ-031"],
    "MEDIUM": ["RJ-013", "RJ-021"]
  },
  "by_iteration": {
    "0": ["RJ-001", "RJ-002", "RJ-003"],
    "1": ["RJ-021", "RJ-022"],
    "2": ["RJ-044", "RJ-045"]
  },
  "by_verdict": {
    "PASS": ["RJ-012", "RJ-013"],
    "FAIL": ["RJ-031"],
    "BLOCKED": ["RJ-044"],
    "KILL": []
  },
  "timeline": ["RJ-001", "RJ-002", "RJ-003", "RJ-013", "RJ-021", "RJ-022", "RJ-031", "RJ-032", "RJ-044", "RJ-045", "RJ-046", "RJ-047"]
}
```

### Dimensions

| Dimension | COMMANDER use case | RADAR use case |
|-----------|-------------------|----------------|
| `by_phase` | Fetch routing context for current phase | Phase progress timeline |
| `by_type` | Pull all `qa_failed` entries before rework dispatch | Event type filter |
| `by_agent` | Prior performance context before re-dispatching an agent | Per-agent activity feed |
| `by_task` | Full history for a task before SPEC_GUARD or CODE_REVIEWER | Task drill-down panel |
| `by_severity` | Escalation check — any unresolved CRITICALs? | Live alerts panel |
| `by_iteration` | Quality delta between iteration N and N-1 | Iteration comparison view |
| `by_verdict` | Rework count — how many FAILs for T-001? | Pass/fail ratio per phase |
| `timeline` | Loop detection — same type+agent in last 10 entries? | Real-time event feed with cursor |

### Rules

- The index holds entry IDs only — no content. Size is bounded regardless of journal length.
- COMMANDER updates the index atomically after writing each journal entry (single writer, no sync risk).
- If the index is absent or corrupt, COMMANDER rebuilds it by scanning `reasoning-journal.jsonl` — full scan, one-time recovery, log `index_rebuilt` to journal.
- Index entries are never deleted. This is an append-only structure matching the journal.

---

## Section 3 — COMMANDER Bootstrap Contract

### Motivation

Routing logic embedded in COMMANDER's prompt is lost when context is compacted. The bootstrap contract moves routing decisions to file reads — compaction-safe because agents always receive their full system prompt, and system prompts trigger explicit file reads rather than relying on in-context knowledge.

### The contract

This section replaces approximately 400 lines of routing rules in `commander.md`. It is added as a top-level section titled `## Bootstrap Contract`.

```markdown
## Bootstrap Contract

On every invocation — including after context compaction — execute this loop exactly:

### 1. Read workflow definition
Read `workflow/definition.yaml`.
This file is the authoritative source for all routing rules, thresholds, phase transitions,
and agent dispatch conditions. Never rely on remembered values.

### 2. Read runtime state
Read `.specify/squad/state.json`.
Extract: `phase`, `status`, `iteration`, `workflow_state`, `token_ledger`, `issues_log`.

### 3. Locate current node
Look up `state.phase` in `definition.yaml phases[]`.
This node defines: which agent to dispatch, what context to inject, what transitions apply.

### 4. Read relevant journal entries
Read `.specify/squad/reasoning-journal-index.json`.
Query by the dimensions relevant to the current decision:
- Routing decision    → by_phase[current_phase], by_iteration[current_iteration]
- Rework decision     → by_task[task_id], by_verdict[FAIL], by_verdict[BLOCKED]
- Escalation check    → by_severity[CRITICAL], by_type[qa_failed]
- Convergence check   → by_iteration[N], by_iteration[N-1], by_type[quality_check]
Fetch only the matched entry IDs from reasoning-journal.jsonl. Never read the full journal.

### 5. Execute current node
Assemble context pack as defined in the phase node.
Dispatch the agent.
Read the agent's echelon_result block from its response.

### 6. Write outputs — in this order, never skip a step
a. Append journal_entries[] from echelon_result to reasoning-journal.jsonl
b. Update reasoning-journal-index.json with new entry IDs across all 8 dimensions
c. Apply state_updates[] from echelon_result to state.json
d. Run state-backup.sh before any major phase transition

### 7. Evaluate transitions
Read transitions[] for the current phase node from definition.yaml.
First matching condition wins. Write new state.phase to state.json.

### 8. Repeat from step 1.
```

### What stays in COMMANDER.md

| Section | Reason |
|---------|--------|
| Identity and prime directive | Shapes reasoning quality, not routing |
| Evidence hierarchy + Toulmin protocol | Active conflict resolution reasoning, not a lookup |
| Meta-cognition checklist | Judgment prompts, not data |
| EVOI reasoning method | How to think, not what to decide |
| Human escalation judgment | Nuanced, context-dependent |
| Endocrine system protocol | Behavioral modifier, not a graph node |

### What moves out of COMMANDER.md

| Section | Destination |
|---------|-------------|
| Convergence thresholds table | `workflow/definition.yaml convergence:` |
| Token budget allocation table | `workflow/definition.yaml budget:` |
| Phase transition routing | `workflow/definition.yaml phases[].transitions[]` |
| Build state machine diagram | `workflow/definition.yaml build:` |
| Diagnostic pipeline trigger conditions | `workflow/definition.yaml escalation:` |

**Net result:** `commander.md` reduces from ~750 lines to ~200 lines.

---

## Section 4 — Migration Batching Plan

### New files to create before Batch 1

| File | Purpose |
|------|---------|
| `workflow/definition.yaml` | Phase graph and routing rules (already created) |
| `workflow/journal-entry-types.yaml` | Canonical registry of valid `type` values |
| `templates/echelon-result-schema.json` | JSON Schema for the `echelon_result` output block |

### Batch sequence

| Batch | Agents | Gate |
|-------|--------|------|
| 1 | COMMANDER | Bootstrap contract replaces routing prose. Index writer logic added. |
| 2 | Control layer | PROSPECTOR, SCOREKEEPER, TRACKER, CHECKPOINT, STRATEGIST — simplest contracts, validates the pattern |
| 3 | Exploration layer | SCOUT, SYNTHESIZER, SAGE, CARTOGRAPHER, MODELER, GOLDDIGGER — most journal-heavy; validates `quality_check` entries and `by_phase` index dimension |
| 4 | Feasibility + Solution | GATEKEEPER, VALIDATOR, ARCHITECT, ORCHESTRATOR, SENTINEL — verdict-heavy; validates `by_verdict` index dimension |
| — | **Smoke test gate** | Run a full Phase 1–3 squad run before proceeding to build layer |
| 5 | Specialists | INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCATE, MAVERICK |
| 6 | Build layer | IMPLEMENTER, SPEC_GUARD, CODE_REVIEWER, TEST_GUARDIAN, DEBUGGER, INTEGRATOR, ENGINEERING_MANAGER, CHANGE_CONTROLLER, VISUAL_VALIDATOR, PROGRESS_TRACKER, VERIFICATION |
| 7 | Learning layer | MIRROR, ADAPTIVE, AUDITOR, REALIST, VETERAN, CONSOLIDATOR, others |

Agents within each batch are independent and can be updated in parallel.

### What "updating an agent" means per batch

Each agent update is three steps:
1. Remove any direct `reasoning-journal.json` write instructions from its prompt
2. Add the `echelon_result` output block to its output format section
3. Map its existing journal writes to `journal_entries[]` entries with correct `type` (from `journal-entry-types.yaml`) and `data` fields

### Transition state

During migration (batches 2–7), COMMANDER handles both old-format agents (no `echelon_result` block) and new-format agents. Rule: if `echelon_result` is absent from the response, COMMANDER falls back to reading the journal for that agent's entries as before. This is removed once all agents conform.

---

## Out of Scope

- RADAR server implementation (deferred — the `timeline` index dimension is designed to support it when built)
- Relevance-scored journal queries beyond the 8 index dimensions (future optimization)
- Further COMMANDER.md prompt optimizations beyond the bootstrap contract

---

## Success Criteria

1. `commander.md` contains no hardcoded thresholds, phase routing rules, or build state machine logic
2. All 42 agents produce `echelon_result` blocks; none write to `reasoning-journal.jsonl` directly
3. `reasoning-journal-index.json` is maintained by COMMANDER after every dispatch
4. A full Phase 1–4 squad run completes without COMMANDER losing routing context after context compaction
5. `workflow/definition.yaml` is the single source of truth for all routing decisions
