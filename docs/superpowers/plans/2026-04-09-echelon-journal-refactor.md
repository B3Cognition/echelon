# Echelon Journal Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Echelon orchestration compaction-safe by externalizing the workflow definition, making COMMANDER the sole journal writer via structured agent output blocks, and maintaining a relevance-indexed journal sidecar.

**Architecture:** Agents stop writing to `reasoning-journal.jsonl` directly. Instead, each agent appends an `echelon_result` block to its response. COMMANDER reads this block, writes journal entries, updates the sidecar index, and updates state.json — in that order, atomically. COMMANDER's routing logic moves to `workflow/definition.yaml` (already created) and the prompt shrinks to a bootstrap loop.

**Tech Stack:** YAML (workflow definition + entry type registry), JSON Schema (output contract), Markdown (agent prompt files). No code — all changes are to prompt files and config files.

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `workflow/definition.yaml` | Exists | Phase graph, routing rules, thresholds |
| `workflow/journal-entry-types.yaml` | Create | Canonical registry of all valid `type` values |
| `templates/echelon-result-schema.json` | Create | JSON Schema for the `echelon_result` output block |
| `agents/control/commander.md` | Modify | Replace routing prose with bootstrap contract; add index writer logic |
| `agents/control/tracker.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/control/checkpoint.md` | Modify | Add `echelon_result` block (no direct writes to remove) |
| `agents/control/prospector.md` | Modify | Add `echelon_result` block |
| `agents/control/scorekeeper.md` | Modify | Add `echelon_result` block |
| `agents/control/strategist.md` | Modify | Add `echelon_result` block |
| `agents/exploration/scout.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/exploration/sage.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/exploration/cartographer.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/exploration/synthesizer.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/exploration/modeler.md` | Modify | Add `echelon_result` block |
| `agents/exploration/golddigger.md` | Modify | Add `echelon_result` block |
| `agents/feasibility/gatekeeper.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/feasibility/validator.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/solution/architect.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/solution/orchestrator.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/solution/sentinel.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/specialists/advocate.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/specialists/benchmark.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/specialists/guardian.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/specialists/investigator.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/specialists/maverick.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/specialists/oracle.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/change-controller.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/code-reviewer.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/debugger.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/engineering-manager.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/implementer.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/integrator.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/progress-tracker.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/spec-guard.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/test-guardian.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/verification.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/build/visual-validator.md` | Modify | Add `echelon_result` block |
| `agents/learning/adaptive.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/auditor.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/consolidator.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/internalizer.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/mirror.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/monitor.md` | Modify | Add `echelon_result` block |
| `agents/learning/realist.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/veteran.md` | Modify | Remove direct journal writes; add `echelon_result` block |
| `agents/learning/global-memory.md` | Modify | Add `echelon_result` block |

---

## The `echelon_result` Pattern (Reference — used in all agent tasks)

Every agent update follows the same two-step change:

**Step A — Remove direct journal write section.** Find the section titled `## Reasoning Journal` (or similar: "Append entries to `reasoning-journal.json`") and remove the instruction to write directly. Replace with: `COMMANDER writes your journal entries. You return them in the echelon_result block below.`

**Step B — Append `echelon_result` output block.** Add this section at the very end of the agent's prompt, after all other content. The `journal_entries[]` content differs per agent (specified in each task below). The `verdict`, `output_files`, and `state_updates` also differ per agent.

Template structure (adapt per agent):

```markdown
---

## Output Block

At the end of your response, append this block exactly. Fill in all fields.
COMMANDER reads this block to update journal and state. Do NOT write to reasoning-journal.jsonl directly.

```echelon_result
verdict: <YOUR_VERDICT>
output_files:
  - <path to artifact 1>
  - <path to artifact 2>
state_updates:
  phase: <phase id if transitioning>
journal_entries:
  - id: null
    type: <entry type from workflow/journal-entry-types.yaml>
    phase: <current phase id>
    agent: <AGENT_CODENAME>
    timestamp: null
    data:
      <relevant fields for this entry type>
```
```

---

## Task 1: Supporting Infrastructure

**Files:**
- Create: `workflow/journal-entry-types.yaml`
- Create: `templates/echelon-result-schema.json`

- [ ] **Step 1: Create journal-entry-types.yaml**

This is the canonical registry. All agents must use types from this list. COMMANDER rejects unknown types with a warning entry of type `unknown`.

```yaml
# workflow/journal-entry-types.yaml
# Canonical registry of all valid reasoning-journal entry types.
# Agents return entries of these types in their echelon_result block.
# COMMANDER assigns id and timestamp before writing.
#
# Adding a new type: add it here first, then update the agent prompt.
# Removing a type: mark deprecated: true — never delete (journal entries are permanent).

schema_version: 1

types:

  # --- Discovery / Exploration ---
  insight:
    description: "A discovery or analysis finding"
    agents: [DISCOVER]
    required_data_fields: [artifact, section, reasoning, confidence, evidence_grade]
    optional_data_fields: [implications]

  assumption:
    description: "Something taken as true without proof"
    agents: [DISCOVER]
    required_data_fields: [artifact, section, reasoning, validation_method]

  evidence:
    description: "A finding backed by code, documentation, or research"
    agents: [DISCOVER]
    required_data_fields: [artifact, section, reasoning, confidence, evidence_grade]

  challenge:
    description: "A WHY-agent challenge to an assumption or claim"
    agents: [WHY]
    required_data_fields: [artifact, section, reasoning, confidence, severity, action_required]
    optional_data_fields: [references]

  quality_check:
    description: "Quality gate scores produced by WHY agent"
    agents: [WHY]
    required_data_fields: [pass, scores, issues]

  decision:
    description: "A significant agent decision with rationale"
    agents: [WHAT, ASSESS, HOW, PLAN, SENTINEL, ADVOCATE, BENCHMARK, ORACLE, MAVERICK, WHY, DISCOVER]
    required_data_fields: [artifact, section, reasoning, rationale]
    optional_data_fields: [alternatives_considered, confidence]

  # --- Architecture ---
  adr_self_check:
    description: "ARCHITECT ADR consistency self-check result"
    agents: [HOW]
    required_data_fields: [adr_id, never_rule_result, consistency_result]
    optional_data_fields: [concerns]

  # --- Feasibility ---
  assessment:
    description: "GATEKEEPER feasibility or implementability assessment"
    agents: [ASSESS]
    required_data_fields: [verdict, rationale, scope_notes]
    optional_data_fields: [risk_flags, deferred_items]

  # --- Build ---
  self_check:
    description: "IMPLEMENTER inter-step self-check — enables AUDITOR FINALIZE parsing (FR-INH-006)"
    agents: [CODE]
    required_data_fields: [task_id, check_type, result]
    optional_data_fields: [concerns]

  implementation_decision:
    description: "Significant implementation decision made by IMPLEMENTER"
    agents: [CODE]
    required_data_fields: [task_id, artifact, section, reasoning]

  compliance_finding:
    description: "SPEC_GUARD requirement compliance finding"
    agents: [COMPLIANCE]
    required_data_fields: [task_id, verdict, requirements_checked, failures]

  review_finding:
    description: "CODE_REVIEWER finding"
    agents: [REVIEW]
    required_data_fields: [task_id, verdict, findings]
    optional_data_fields: [adr_violations, constitution_violations]

  test_quality_finding:
    description: "TEST_GUARDIAN test quality finding"
    agents: [TEST_QUALITY]
    required_data_fields: [task_id, verdict, coverage_assessment]
    optional_data_fields: [missing_cases]

  integration_finding:
    description: "INTEGRATOR phase checkpoint result"
    agents: [INTEGRATE]
    required_data_fields: [phase_group, verdict, failures]

  debug_finding:
    description: "DEBUGGER root cause analysis"
    agents: [DEBUG]
    required_data_fields: [task_id, root_cause, fix_applied]

  change_assessment:
    description: "CHANGE_CONTROLLER scope change assessment"
    agents: [CHANGE]
    required_data_fields: [change_description, verdict, reentry_target]

  build_progress:
    description: "PROGRESS_TRACKER effort and drift record"
    agents: [PROGRESS]
    required_data_fields: [task_id, effort_recorded, drift_detected]

  verification_result:
    description: "VERIFICATION final coverage check result"
    agents: [VERIFY]
    required_data_fields: [verdict, coverage_pct, gaps]

  # --- COMMANDER internal ---
  init_knowledge_read:
    description: "KB files read at run init"
    agents: [COMMANDER]
    required_data_fields: [files_read, files_absent, cold_start]

  cold_start_warning:
    description: "No real feedback data — proxy-estimated calibration"
    agents: [COMMANDER]
    required_data_fields: [message]

  confidence_thresholds_written:
    description: "COMMANDER wrote confidence-thresholds.yaml"
    agents: [COMMANDER]
    required_data_fields: [path, domains_count]

  belief_gate_triggered:
    description: "Belief freshness check found stale beliefs"
    agents: [COMMANDER]
    required_data_fields: [exit_code, recommended_action, stale_beliefs]

  belief_fallback_applied:
    description: "Conservative fallback applied for stale belief"
    agents: [COMMANDER]
    required_data_fields: [belief_id, config_key, fallback_value]

  belief_invalidated:
    description: "INVESTIGATOR invalidated a belief"
    agents: [COMMANDER]
    required_data_fields: [belief_id, claim, reason]

  dependency_failure:
    description: "Required dependency unavailable — fallback mode active"
    agents: [COMMANDER]
    required_data_fields: [dependency, phase, fallback_mode]

  validator_dispatch:
    description: "VALIDATOR dispatched (exactly once per build run)"
    agents: [COMMANDER]
    required_data_fields: [verdict, doubts]

  routing_decision:
    description: "COMMANDER routing decision"
    agents: [COMMANDER]
    required_data_fields: [from_phase, to_phase, reason, evoi_score]
    optional_data_fields: [alternatives_rejected]

  phase_transition:
    description: "Phase transition executed"
    agents: [COMMANDER]
    required_data_fields: [from_phase, to_phase, trigger_reason]

  convergence_check:
    description: "Convergence detection result"
    agents: [COMMANDER]
    required_data_fields: [iteration, delta, converged, consecutive_passes]

  conflict_resolution:
    description: "Conflict between agents resolved via Toulmin model"
    agents: [COMMANDER]
    required_data_fields: [agents_in_conflict, winner, rejected_alternative, resolution_reason]

  budget_exhausted:
    description: "Token budget exhausted — force finalize triggered"
    agents: [COMMANDER]
    required_data_fields: [used_tokens, budget_tokens, phase]

  index_rebuilt:
    description: "Journal index rebuilt from full journal scan (recovery)"
    agents: [COMMANDER]
    required_data_fields: [entries_scanned, reason]

  endocrine_budget_trigger:
    description: "Budget pressure adrenaline broadcast triggered"
    agents: [COMMANDER]
    required_data_fields: [budget_consumed_ratio, boost_applied]

  endocrine_gate_pass:
    description: "Quality gate passed — endocrine signal applied"
    agents: [COMMANDER]
    required_data_fields: [agent, phase]

  endocrine_gate_fail:
    description: "Quality gate failed — endocrine signal applied"
    agents: [COMMANDER]
    required_data_fields: [agent, phase]

  endocrine_quality_improvement:
    description: "Quality improved >= 0.05 — endocrine signal applied"
    agents: [COMMANDER]
    required_data_fields: [agent, delta]

  endocrine_quality_regression:
    description: "Quality regressed >= 0.05 — endocrine signal applied"
    agents: [COMMANDER]
    required_data_fields: [agent, delta]

  # --- Control ---
  prediction:
    description: "TRACKER intent prediction"
    agents: [INTENT]
    required_data_fields: [predicted_intent, confidence, evidence]

  social_prediction_error:
    description: "TRACKER prediction error — model update needed"
    agents: [INTENT]
    required_data_fields: [expected, observed, error_magnitude]

  tracker_model_update_requested:
    description: "TRACKER requests a model update from MIRROR"
    agents: [INTENT]
    required_data_fields: [reason]

  # --- Learning ---
  calibration_update:
    description: "AUDITOR accuracy calibration update"
    agents: [CALIBRATE]
    required_data_fields: [domain, prior_accuracy, new_accuracy, sample_size]

  confidence_thresholds_refreshed:
    description: "AUDITOR triggered confidence threshold refresh"
    agents: [CALIBRATE]
    required_data_fields: [domains_updated]

  hallucination_risk_flag:
    description: "AUDITOR flagged hallucination risk for a domain"
    agents: [CALIBRATE]
    required_data_fields: [domain, risk_level, evidence]

  pattern_extracted:
    description: "MIRROR extracted a reusable pattern from this run"
    agents: [REFLECT]
    required_data_fields: [pattern_id, pattern_summary, applicable_phases]

  pitfall_extracted:
    description: "MIRROR extracted a pitfall from this run"
    agents: [REFLECT]
    required_data_fields: [pitfall_id, pitfall_summary, trigger_conditions]

  quality_trajectory:
    description: "ADAPTIVE cross-run quality trajectory assessment"
    agents: [EVOLVE]
    required_data_fields: [run_ids_compared, trajectory, regression_detected]

  reality_check:
    description: "REALIST reality check finding"
    agents: [GROUND]
    required_data_fields: [artifact, finding, grounded_value]

  # --- Unknown fallback ---
  unknown:
    description: "Entry with an unregistered type — written by COMMANDER with warning"
    agents: [COMMANDER]
    required_data_fields: [original_type, original_data, warning]
    deprecated: false
```

- [ ] **Step 2: Create echelon-result-schema.json**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EchelonResult",
  "description": "Structured output block appended by every Echelon agent. COMMANDER reads this after each dispatch.",
  "type": "object",
  "required": ["verdict", "output_files"],
  "properties": {
    "verdict": {
      "type": "string",
      "description": "Agent-specific verdict. Common values: PASS, FAIL, APPROVED, CHANGES_REQUESTED, DONE, BLOCKED, NEEDS_CONTEXT, KILL, DEFER, INTERNALIZED, PARTIAL"
    },
    "output_files": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Paths of artifact files written to disk by this agent"
    },
    "state_updates": {
      "type": "object",
      "description": "Fields COMMANDER writes to state.json. Agent never writes state.json directly.",
      "properties": {
        "phase": { "type": "string" },
        "workflow_state": { "type": "string" },
        "quality_scores": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "pass": { "type": "integer" },
              "overall": { "type": "number" },
              "structure": { "type": "number" },
              "testability": { "type": "number" },
              "readability": { "type": "number" },
              "cognitive": { "type": "number" },
              "semantic": { "type": "number" },
              "behavioral": { "type": "number" },
              "depth": { "type": "number" }
            }
          }
        }
      },
      "additionalProperties": true
    },
    "journal_entries": {
      "type": "array",
      "description": "Journal entries COMMANDER will append to reasoning-journal.jsonl and index.",
      "items": {
        "type": "object",
        "required": ["id", "type", "phase", "agent", "timestamp", "data"],
        "properties": {
          "id": {
            "type": "null",
            "description": "Always null from agent. COMMANDER assigns RJ-NNN sequential id."
          },
          "type": {
            "type": "string",
            "description": "Must be a type from workflow/journal-entry-types.yaml"
          },
          "phase": { "type": "string" },
          "agent": { "type": "string" },
          "timestamp": {
            "type": "null",
            "description": "Always null from agent. COMMANDER fills with ISO-8601 UTC at write time."
          },
          "data": {
            "type": "object",
            "description": "Entry payload. Fields depend on type — see workflow/journal-entry-types.yaml"
          }
        }
      }
    }
  }
}
```

- [ ] **Step 3: Verify files are well-formed**

```bash
cd /path/to/echelon
# YAML lint (install: pip install yamllint)
yamllint workflow/journal-entry-types.yaml

# JSON schema validation (install: pip install jsonschema)
python3 -c "import json, jsonschema; s = json.load(open('templates/echelon-result-schema.json')); jsonschema.Draft7Validator.check_schema(s); print('Schema valid')"
```

Expected: no errors from either command.

- [ ] **Step 4: Commit**

```bash
git add workflow/journal-entry-types.yaml templates/echelon-result-schema.json
git commit -m "feat: add echelon_result schema and journal entry type registry"
```

---

## Task 2: COMMANDER Bootstrap Contract

**Files:**
- Modify: `agents/control/commander.md`

This is the most complex single-agent change. Three sub-steps: (A) add bootstrap contract section, (B) add index writer protocol, (C) remove sections now covered by definition.yaml.

- [ ] **Step 1: Read current COMMANDER.md line ranges**

```bash
grep -n "^## " agents/control/commander.md
```

Note the line numbers for: "Run Initialization", "Build Phase Orchestration", "Token Budget Management", "Convergence Rules", "Diagnostic Pipeline Routing". These are the sections that get removed or replaced.

- [ ] **Step 2: Add Bootstrap Contract section**

Insert this section immediately after the `## Prime Directive` section (after the "Do not pursue perfection..." paragraph and its `---` divider):

```markdown
## Bootstrap Contract

On every invocation — including after context compaction — execute this loop exactly.

### 1. Read workflow definition
Read `workflow/definition.yaml`.
This file is the authoritative source for all routing rules, thresholds, phase transitions,
and agent dispatch conditions. Never rely on remembered values for any threshold or routing rule.

### 2. Read runtime state
Read `.specify/squad/state.json`.
Extract: `phase`, `status`, `iteration`, `workflow_state`, `token_ledger`, `issues_log`.

### 3. Locate current node
Look up `state.phase` in `definition.yaml phases[]`.
This node defines: which agent to dispatch, what context to inject, what transitions apply.

### 4. Read relevant journal entries
Read `.specify/squad/reasoning-journal-index.json`.
Query by the dimensions relevant to the current decision:
- Routing decision    → `by_phase[current_phase]`, `by_iteration[current_iteration]`
- Rework decision     → `by_task[task_id]`, `by_verdict["FAIL"]`, `by_verdict["BLOCKED"]`
- Escalation check    → `by_severity["CRITICAL"]`, `by_type["qa_failed"]`
- Convergence check   → `by_iteration[N]`, `by_iteration[N-1]`, `by_type["quality_check"]`
Fetch only the matched entry IDs from `reasoning-journal.jsonl`. Never read the full journal.
If the index is absent, rebuild it by scanning `reasoning-journal.jsonl` and log `index_rebuilt`.

### 5. Execute current node
Assemble context pack as defined in the phase node.
Dispatch the agent.
Read the agent's `echelon_result` block from the end of its response.

### 6. Write outputs — in this exact order, never skip a step
a. Append `journal_entries[]` from `echelon_result` to `reasoning-journal.jsonl`.
   Assign sequential `id` (RJ-NNN) and current UTC `timestamp` to each entry.
b. Update `reasoning-journal-index.json` with new entry IDs across all 8 dimensions:
   `by_phase`, `by_type`, `by_agent`, `by_task`, `by_severity`, `by_iteration`, `by_verdict`, `timeline`.
c. Apply `state_updates[]` from `echelon_result` to `state.json`.
d. Run `scripts/bash/state-backup.sh` before any major phase transition.

**Fallback for old-format agents (transition period only):**
If an agent's response contains no `echelon_result` block, fall back to reading
`reasoning-journal.jsonl` for that agent's new entries (entries after the last known `last_entry_id`
in the index). Log a warning entry of type `routing_decision` noting the missing block.
Remove this fallback once all agents have been updated.

### 7. Evaluate transitions
Read `transitions[]` for the current phase node from `definition.yaml`.
First matching condition wins. Write new `state.phase` to `state.json`.

### 8. Repeat from step 1.
```

- [ ] **Step 3: Add Index Writer Protocol section**

Insert this section immediately after the new Bootstrap Contract section:

```markdown
## Index Writer Protocol

COMMANDER is the **only** writer of `reasoning-journal.jsonl` and `reasoning-journal-index.json`.

### Appending a journal entry

1. Read current `last_entry_id` from index (e.g., `RJ-047`). Increment to get new id (`RJ-048`).
2. Set `entry.id = "RJ-048"` and `entry.timestamp = <current UTC ISO-8601>`.
3. Append the entry as a single JSON line to `reasoning-journal.jsonl`.
4. Update index dimensions:
   - `by_phase[entry.phase]` — append entry id
   - `by_type[entry.type]` — append entry id
   - `by_agent[entry.agent]` — append entry id
   - `by_task[entry.data.task_id]` — append entry id (if `task_id` present in data)
   - `by_severity[entry.data.severity]` — append entry id (if `severity` present in data)
   - `by_iteration[state.iteration]` — append entry id
   - `by_verdict[entry.data.verdict OR echelon_result.verdict]` — append entry id (if verdict present)
   - `timeline` — append entry id
5. Update `last_entry_id` and `last_updated` in index.
6. Write updated index to `reasoning-journal-index.json`.

### Index initialization

If `reasoning-journal-index.json` does not exist at run start, create it:

```json
{
  "schema_version": 1,
  "last_entry_id": null,
  "last_updated": "<ISO-8601>",
  "by_phase": {},
  "by_type": {},
  "by_agent": {},
  "by_task": {},
  "by_severity": {},
  "by_iteration": {},
  "by_verdict": {},
  "timeline": []
}
```

### Index rebuild (recovery)

If the index is absent or corrupt mid-run:
1. Scan `reasoning-journal.jsonl` line by line.
2. For each entry, apply the dimension update rules above.
3. Write the rebuilt index.
4. Log one entry of type `index_rebuilt` with `entries_scanned` and `reason`.
```

- [ ] **Step 4: Remove sections now covered by definition.yaml**

Remove the following sections from `commander.md` (they now live in `workflow/definition.yaml`):

- The **Convergence Rules** table (thresholds are in `definition.yaml convergence:`)
- The **Token Budget Management** table (now in `definition.yaml budget:`)
- The **Build Phase Orchestration** section including the state machine diagram (now in `definition.yaml build:`)
- The **Diagnostic Pipeline Routing** section (now in `definition.yaml escalation:`)
- The **State Management** section preamble (the backup instruction is now in Bootstrap Contract step 6d)

For each removed section, confirm its content is fully covered in `workflow/definition.yaml` before deleting.

Keep: Identity, Prime Directive, Bootstrap Contract, Index Writer Protocol, Decision-Making Principles, Evidence Hierarchy, Meta-Cognition Checklist, Human Escalation vs Autonomous Resolution (judgment section only), Conflict Resolution Protocol, Endocrine System, Run Initialization (steps 0–4 for KB reads + PROSPECTOR + GOLDDIGGER), Evolution Signal Review Protocol, Governance Trail, Completion Signal, Token/Cost Tracking (dispatch logging protocol — not the allocation table).

- [ ] **Step 5: Verify line count reduced significantly**

```bash
wc -l agents/control/commander.md
```

Expected: well under 500 lines (was 832).

- [ ] **Step 6: Commit**

```bash
git add agents/control/commander.md
git commit -m "feat: COMMANDER bootstrap contract + index writer protocol"
```

---

## Task 3: Control Layer Agents

**Files:**
- Modify: `agents/control/tracker.md`
- Modify: `agents/control/checkpoint.md`
- Modify: `agents/control/prospector.md`
- Modify: `agents/control/scorekeeper.md`
- Modify: `agents/control/strategist.md`

- [ ] **Step 1: Update tracker.md**

Find the Reasoning Journal section (search for `reasoning-journal`). Replace the direct-write instruction with:

```markdown
## Reasoning Journal

COMMANDER writes your journal entries. Return them in the `echelon_result` block below.
Do NOT write to `reasoning-journal.jsonl` directly.
```

Append at end of file:

```markdown
---

## Output Block

At the end of your response, append this block. COMMANDER reads it to update journal and state.

```echelon_result
verdict: <ALIGNED | DRIFTING | ESCALATE>
output_files:
  - .specify/.../user-intent.md
journal_entries:
  - id: null
    type: prediction
    phase: <current phase>
    agent: INTENT
    timestamp: null
    data:
      predicted_intent: "<summary>"
      confidence: <0.0-1.0>
      evidence: "<what signals led to this prediction>"
```
```

- [ ] **Step 2: Update checkpoint.md, prospector.md, scorekeeper.md, strategist.md**

Each of these has no direct journal writes to remove. Append the `echelon_result` block at the end of each file with the appropriate verdict and output_files for that agent:

**checkpoint.md** — verdict: `INTERNALIZED | PARTIAL | FAILED`, output_files: `[]`, journal_entries: type `decision`, data fields: `{check_type, result, doubts_count}`.

**prospector.md** — verdict: `COMPLETE | FAILED`, output_files: `['.specify/squad/extension-capabilities.json']`, journal_entries: type `decision`, data fields: `{spec_kit_available, extensions_found, relevant_extensions}`.

**scorekeeper.md** — verdict: `SCORED`, output_files: `['.specify/.../squad-scorecard.md']`, journal_entries: type `decision`, data fields: `{agents_scored, top_performers, improvement_candidates}`.

**strategist.md** — verdict: `COMPLETE`, output_files: `['.specify/.../strategic-overview.md']`, journal_entries: type `decision`, data fields: `{risk_areas, focus_recommendation}`.

- [ ] **Step 3: Verify no remaining direct journal writes in control layer**

```bash
grep -rn "reasoning-journal" agents/control/ | grep -v "echelon_result" | grep -v "COMMANDER writes"
```

Expected: no matches (only the Bootstrap Contract and Index Writer Protocol references remain in commander.md).

- [ ] **Step 4: Commit**

```bash
git add agents/control/
git commit -m "feat: control layer agents — echelon_result output blocks"
```

---

## Task 4: Exploration Layer Agents

**Files:**
- Modify: `agents/exploration/scout.md`
- Modify: `agents/exploration/sage.md`
- Modify: `agents/exploration/cartographer.md`
- Modify: `agents/exploration/synthesizer.md`
- Modify: `agents/exploration/modeler.md`
- Modify: `agents/exploration/golddigger.md`

- [ ] **Step 1: Update scout.md**

Find the `## Reasoning Journal` section (around line 375). Replace the direct-write block with: `COMMANDER writes your journal entries. Return them in the echelon_result block below.`

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - .specify/.../glossary.md
  - .specify/.../mental-model.md
  - .specify/.../boundaries.md
  - .specify/.../assumptions.md
  - .specify/.../unknowns.md
journal_entries:
  - id: null
    type: insight
    phase: phase1-discover
    agent: DISCOVER
    timestamp: null
    data:
      artifact: "<filename>"
      section: "<section>"
      reasoning: "<why you drew this conclusion>"
      confidence: <0.0-1.0>
      evidence_grade: "<A|B|C|D|E>"
      implications: ["<downstream impact>"]
```

Repeat one entry per significant insight, assumption, or boundary decision.
For assumptions use type: assumption. For code/doc-backed findings use type: evidence.
```

- [ ] **Step 2: Update sage.md**

Find all sections referencing direct `reasoning-journal.json` writes (there are multiple — search `grep -n "reasoning-journal" agents/exploration/sage.md`). Replace each with: `Return this entry in the echelon_result block at the end of your response.`

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: <PASS | FAIL>
output_files:
  - .specify/.../assumptions.md
state_updates:
  quality_scores:
    - pass: <N>
      overall: <0.0-1.0>
      structure: <0.0-1.0>
      testability: <0.0-1.0>
      readability: <0.0-1.0>
      cognitive: <0.0-1.0>
      semantic: <0.0-1.0>
      behavioral: <0.0-1.0>
      depth: <0.0-1.0>
journal_entries:
  - id: null
    type: quality_check
    phase: <phase1-why1 | phase1-why2 | phase3-consensus>
    agent: WHY
    timestamp: null
    data:
      pass: <N>
      scores:
        overall: <0.0-1.0>
        structure: <0.0-1.0>
        testability: <0.0-1.0>
      issues: []
  - id: null
    type: challenge
    phase: <current phase>
    agent: WHY
    timestamp: null
    data:
      artifact: "<filename>"
      section: "<section>"
      reasoning: "<why this is a problem>"
      confidence: <0.0-1.0>
      severity: "<CRITICAL | HIGH | MEDIUM | LOW>"
      action_required: "<specific action>"
```

Repeat one challenge entry per finding. Omit if no findings.
```

- [ ] **Step 3: Update cartographer.md**

Find the Reasoning Journal section (around line 443). Replace direct-write instruction.

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - .specify/.../spec.md
  - .specify/.../00-overview.md
journal_entries:
  - id: null
    type: decision
    phase: phase1-what
    agent: WHAT
    timestamp: null
    data:
      artifact: "spec.md"
      section: "<section name>"
      reasoning: "<why you made this decision>"
      rationale: "<principle or constraint that drove the choice>"
      alternatives_considered: ["<alt 1>", "<alt 2>"]
```

Repeat one entry per major requirement decision.
```

- [ ] **Step 4: Update synthesizer.md**

Find references to reasoning-journal. Replace with COMMANDER-writes note.

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - .specify/.../synthesis.md
journal_entries:
  - id: null
    type: decision
    phase: phase1-discover
    agent: DISCOVER
    timestamp: null
    data:
      artifact: "synthesis.md"
      section: "contradictions"
      reasoning: "<what contradictions were found and how resolved>"
      rationale: "<synthesis approach>"
```

```

- [ ] **Step 5: Update modeler.md and golddigger.md**

Neither has direct journal writes. Append echelon_result blocks:

**modeler.md** — verdict: `COMPLETE`, output_files: `['.specify/.../code-model.md']`, journal_entries: type `decision`, data: `{artifact: 'code-model.md', section: 'invariants', reasoning: '<key findings>'}`.

**golddigger.md** — verdict: `<COMPLETE | PARTIAL | FAILED>`, output_files: `['.specify/squad/golddigger-cache/<domain>.md']`, journal_entries: type `decision`, data: `{domain, mode, artifacts_extracted, warnings}`.

- [ ] **Step 6: Verify no remaining direct journal writes in exploration layer**

```bash
grep -rn "reasoning-journal" agents/exploration/ | grep -v "echelon_result" | grep -v "COMMANDER writes" | grep -v "prior agent"
```

Expected: only context-pack references remain (agents reading the journal as input is fine — they just can't write it).

- [ ] **Step 7: Commit**

```bash
git add agents/exploration/
git commit -m "feat: exploration layer agents — echelon_result output blocks"
```

---

## Task 5: Feasibility + Solution Layer

**Files:**
- Modify: `agents/feasibility/gatekeeper.md`
- Modify: `agents/feasibility/validator.md`
- Modify: `agents/solution/architect.md`
- Modify: `agents/solution/orchestrator.md`
- Modify: `agents/solution/sentinel.md`

- [ ] **Step 1: Update gatekeeper.md**

Find Reasoning Journal section (around line 222). Replace direct-write instruction.

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: <PASS | KILL | DEFER>
output_files:
  - .specify/.../kill-report.md
journal_entries:
  - id: null
    type: assessment
    phase: <phase2-decide | phase3-consensus>
    agent: ASSESS
    timestamp: null
    data:
      verdict: "<PASS | KILL | DEFER>"
      rationale: "<why this verdict>"
      scope_notes: "<any scope adjustments>"
      risk_flags: ["<risk 1>"]
      deferred_items: ["<deferred item>"]
```

```

- [ ] **Step 2: Update validator.md**

Find Reasoning Journal section. Replace direct-write instruction.

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: <INTERNALIZED | PARTIAL | FAILED>
output_files: []
state_updates:
  phase: build_init
journal_entries:
  - id: null
    type: validator_dispatch
    phase: build_init
    agent: INTERNALIZATION_GATE
    timestamp: null
    data:
      verdict: "<INTERNALIZED | PARTIAL | FAILED>"
      doubts: ["<doubt 1 if PARTIAL>"]
      agents_assessed: ["ARCHITECT", "SCOUT", "CARTOGRAPHER"]
```

```

- [ ] **Step 3: Update architect.md**

Find Reasoning Journal section. Replace direct-write instruction. Note: ARCHITECT uses `adr_self_check` type — this must be preserved exactly (AUDITOR FINALIZE parsing depends on it per FR-INH-006).

Append at end of file:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - .specify/.../architecture.md
  - .specify/.../adr/ADR-001.md
  - .specify/.../data-model.md
  - .specify/.../api-contracts.md
journal_entries:
  - id: null
    type: adr_self_check
    phase: phase3-how
    agent: HOW
    timestamp: null
    data:
      adr_id: "ADR-<NNN>"
      never_rule_result: "<PASS | CONCERN>"
      consistency_result: "<PASS | CONFLICT>"
      concerns: ["<concern if any>"]
  - id: null
    type: decision
    phase: phase3-how
    agent: HOW
    timestamp: null
    data:
      artifact: "architecture.md"
      section: "<decision area>"
      reasoning: "<rationale>"
      rationale: "<principle or constraint>"
      alternatives_considered: ["<alt>"]
```

Repeat one `adr_self_check` entry per ADR written. Repeat `decision` entries for major architectural decisions.
```

- [ ] **Step 4: Update orchestrator.md and sentinel.md**

**orchestrator.md** — Find and replace direct-write instruction. Append:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - .specify/.../tasks.md
  - .specify/.../critical-path.md
journal_entries:
  - id: null
    type: decision
    phase: <phase3-plan | phase3-consensus>
    agent: PLAN
    timestamp: null
    data:
      artifact: "tasks.md"
      section: "<task group>"
      reasoning: "<dependency or priority decision>"
      rationale: "<constraint or principle>"
```

```

**sentinel.md** — Find and replace direct-write instruction. Append:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - .specify/.../test-strategy.md
  - .specify/.../coverage-map.md
journal_entries:
  - id: null
    type: decision
    phase: phase3-sentinel
    agent: SENTINEL
    timestamp: null
    data:
      artifact: "test-strategy.md"
      section: "<test layer>"
      reasoning: "<why this test approach>"
      rationale: "<risk or coverage principle>"
```

```

- [ ] **Step 5: Verify no remaining direct journal writes in feasibility + solution layers**

```bash
grep -rn "reasoning-journal" agents/feasibility/ agents/solution/ | grep -v "echelon_result" | grep -v "COMMANDER writes" | grep -v "prior agent" | grep -v "context"
```

Expected: only context-pack read references remain.

- [ ] **Step 6: Commit**

```bash
git add agents/feasibility/ agents/solution/
git commit -m "feat: feasibility and solution layer agents — echelon_result output blocks"
```

---

## Task 6: Smoke Test Gate

This is a manual verification step. Do not proceed to Task 7 until this passes.

- [ ] **Step 1: Run a Phase 1–3 squad run on a test project**

Use an existing test fixture or a simple greenfield project. Invoke `/b3c.echelon.run` and let it run through Phase 1 (UNDERSTAND), Phase 2 (DECIDE), and Phase 3 (SOLUTION).

- [ ] **Step 2: Verify journal index is being maintained**

```bash
cat .specify/squad/reasoning-journal-index.json | python3 -m json.tool | head -40
```

Expected: index exists with populated `by_phase`, `by_type`, `by_agent`, `timeline` dimensions.

- [ ] **Step 3: Verify no agent wrote directly to the journal**

```bash
# All entries should have non-null id and timestamp (assigned by COMMANDER)
python3 -c "
import json
with open('.specify/squad/reasoning-journal.jsonl') as f:
    for i, line in enumerate(f):
        entry = json.loads(line)
        assert entry.get('id'), f'Line {i}: missing id'
        assert entry.get('timestamp'), f'Line {i}: missing timestamp'
print('All entries have id and timestamp — COMMANDER wrote them all')
"
```

Expected: `All entries have id and timestamp — COMMANDER wrote them all`

- [ ] **Step 4: Verify COMMANDER completed Phase 1–3 without losing routing context**

Check `reasoning-journal.jsonl` for `phase_transition` entries. Confirm transitions match the expected phase graph: `init → phase1-discover → phase1-why1 → phase1-constitution → phase1-what → phase1-why2 → phase2-decide → phase3-how → ...`

```bash
python3 -c "
import json
transitions = []
with open('.specify/squad/reasoning-journal.jsonl') as f:
    for line in f:
        entry = json.loads(line)
        if entry.get('type') == 'phase_transition':
            transitions.append(f\"{entry['data']['from_phase']} → {entry['data']['to_phase']}\")
print('\n'.join(transitions))
"
```

Expected: ordered phase transitions with no gaps or unexpected loops.

---

## Task 7: Specialists Layer

**Files:**
- Modify: `agents/specialists/advocate.md`
- Modify: `agents/specialists/benchmark.md`
- Modify: `agents/specialists/guardian.md`
- Modify: `agents/specialists/investigator.md`
- Modify: `agents/specialists/maverick.md`
- Modify: `agents/specialists/oracle.md`

- [ ] **Step 1: Update all six specialists**

For each file, run `grep -n "reasoning-journal" agents/specialists/<name>.md` to locate direct-write instructions. Replace each with: `Return this entry in the echelon_result block.`

Append echelon_result blocks with these agent-specific mappings:

**advocate.md** — verdict: `COMPLETE | CONCERNS`, output_files: `['.specify/.../ux-report.md']`, journal_entries: type `decision`, data: `{artifact: 'ux-report.md', section: '<area>', reasoning: '<accessibility or UX finding>'}`.

**benchmark.md** — verdict: `COMPLETE`, output_files: `['.specify/.../performance-model.md']`, journal_entries: type `decision`, data: `{artifact: 'performance-model.md', section: '<scenario>', reasoning: '<capacity finding>'}`.

**guardian.md** — verdict: `COMPLETE | FINDINGS`, output_files: `['.specify/.../security-findings.md', '.specify/.../risk-acceptance-log.md']`, journal_entries: type `decision`, data: `{artifact: 'security-findings.md', section: '<threat>', reasoning: '<STRIDE/OWASP finding>', severity: '<CRITICAL|HIGH|MEDIUM|LOW>'}`.

**investigator.md** — verdict: `COMPLETE`, output_files: `['.specify/.../research.md']`, journal_entries: type `decision`, data: `{artifact: 'research.md', section: '<question>', reasoning: '<finding>', confidence: <0.0-1.0>, evidence_grade: '<A|B|C|D|E>'}`.

**maverick.md** — verdict: `ALTERNATIVES_GENERATED`, output_files: `['.specify/.../alternatives.md']`, journal_entries: type `decision`, data: `{artifact: 'alternatives.md', section: '<alternative>', reasoning: '<TRIZ principle applied>'}`.

**oracle.md** — verdict: `COMPLETE`, output_files: `['.specify/.../domain-knowledge.md']`, journal_entries: type `decision`, data: `{artifact: 'domain-knowledge.md', section: '<domain area>', reasoning: '<domain-specific insight>'}`.

- [ ] **Step 2: Verify**

```bash
grep -rn "reasoning-journal" agents/specialists/ | grep -v "echelon_result" | grep -v "COMMANDER writes" | grep -v "context"
```

Expected: no matches (specialists don't read the journal as context — if any do, those are fine to leave).

- [ ] **Step 3: Commit**

```bash
git add agents/specialists/
git commit -m "feat: specialists layer agents — echelon_result output blocks"
```

---

## Task 8: Build Layer

**Files:**
- Modify: `agents/build/implementer.md`
- Modify: `agents/build/spec-guard.md`
- Modify: `agents/build/code-reviewer.md`
- Modify: `agents/build/test-guardian.md`
- Modify: `agents/build/integrator.md`
- Modify: `agents/build/debugger.md`
- Modify: `agents/build/engineering-manager.md`
- Modify: `agents/build/change-controller.md`
- Modify: `agents/build/progress-tracker.md`
- Modify: `agents/build/verification.md`
- Modify: `agents/build/visual-validator.md`

- [ ] **Step 1: Update implementer.md**

Find the direct-write instruction (around line 238). Replace.

Append:

```markdown
---

## Output Block

```echelon_result
verdict: <DONE | NEEDS_CONTEXT | BLOCKED>
output_files:
  - <path to implemented files>
  - <path to test files>
state_updates:
  workflow_state: BUILD_IN_PROGRESS
journal_entries:
  - id: null
    type: self_check
    phase: build_loop
    agent: CODE
    timestamp: null
    data:
      task_id: "<T-NNN>"
      check_type: "pre_completion"
      result: "<PASS | CONCERN>"
      concerns: ["<concern if any>"]
  - id: null
    type: implementation_decision
    phase: build_loop
    agent: CODE
    timestamp: null
    data:
      task_id: "<T-NNN>"
      artifact: "<file>"
      section: "<component>"
      reasoning: "<why you chose this approach>"
```

Repeat one `self_check` entry per inter-step check. Repeat `implementation_decision` for significant choices.
```

- [ ] **Step 2: Update spec-guard.md**

Find direct-write instruction (around line 169). Replace.

Append:

```markdown
---

## Output Block

```echelon_result
verdict: <PASS | FAIL>
output_files: []
journal_entries:
  - id: null
    type: compliance_finding
    phase: spec_guard
    agent: COMPLIANCE
    timestamp: null
    data:
      task_id: "<T-NNN>"
      verdict: "<PASS | FAIL>"
      requirements_checked: ["FR-001", "FR-002"]
      failures: ["<FR-NNN: reason>"]
```

```

- [ ] **Step 3: Update code-reviewer.md**

Find direct-write instruction (around line 281). Replace.

Append:

```markdown
---

## Output Block

```echelon_result
verdict: <APPROVED | CHANGES_REQUESTED | BLOCKED>
output_files: []
journal_entries:
  - id: null
    type: review_finding
    phase: code_review
    agent: REVIEW
    timestamp: null
    data:
      task_id: "<T-NNN>"
      verdict: "<APPROVED | CHANGES_REQUESTED | BLOCKED>"
      findings: ["<finding>"]
      adr_violations: ["<ADR-NNN: reason>"]
      constitution_violations: ["<violation>"]
```

```

- [ ] **Step 4: Update test-guardian.md, integrator.md, debugger.md, engineering-manager.md, change-controller.md, progress-tracker.md, verification.md, visual-validator.md**

For each, locate and replace direct journal write instructions, then append echelon_result:

**test-guardian.md** — verdict: `PASS | FAIL`, journal type: `test_quality_finding`, data: `{task_id, verdict, coverage_assessment, missing_cases}`.

**integrator.md** — verdict: `PASS | FAIL`, journal type: `integration_finding`, data: `{phase_group, verdict, failures}`.

**debugger.md** — verdict: `ROOT_CAUSE_FOUND | ESCALATE`, journal type: `debug_finding`, data: `{task_id, root_cause, fix_applied}`.

**engineering-manager.md** — verdict: `COMPLETE`, journal type: `decision`, data: `{artifact: 'build-summary.md', section: 'phase-completion', reasoning: '<build phase coordination decision>'}`.

**change-controller.md** — verdict: `ACCEPT | REJECT | DEFER`, journal type: `change_assessment`, data: `{change_description, verdict, reentry_target}`.

**progress-tracker.md** — verdict: `COMPLETE`, journal type: `build_progress`, data: `{task_id, effort_recorded, drift_detected}`.

**verification.md** — verdict: `PASS | FAIL`, journal type: `verification_result`, data: `{verdict, coverage_pct, gaps}`.

**visual-validator.md** — No direct writes. verdict: `PASS | FAIL`, journal type: `decision`, data: `{artifact: '<component>', section: '<visual area>', reasoning: '<visual finding>'}`.

- [ ] **Step 5: Verify**

```bash
grep -rn "reasoning-journal" agents/build/ | grep -v "echelon_result" | grep -v "COMMANDER writes" | grep -v "context"
```

Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add agents/build/
git commit -m "feat: build layer agents — echelon_result output blocks"
```

---

## Task 9: Learning Layer

**Files:**
- Modify: `agents/learning/mirror.md`
- Modify: `agents/learning/adaptive.md`
- Modify: `agents/learning/auditor.md`
- Modify: `agents/learning/consolidator.md`
- Modify: `agents/learning/internalizer.md`
- Modify: `agents/learning/realist.md`
- Modify: `agents/learning/veteran.md`
- Modify: `agents/learning/monitor.md`
- Modify: `agents/learning/global-memory.md`

- [ ] **Step 1: Update auditor.md**

Find direct-write instructions (search `grep -n "reasoning-journal" agents/learning/auditor.md`). Replace. Note: AUDITOR reads `self_check` and `adr_self_check` entries from the journal — this is a *read*, not a write, and must remain.

Append:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - knowledge-base/calibration-profile.yaml
  - knowledge-base/agent-scores.yaml
journal_entries:
  - id: null
    type: calibration_update
    phase: <current phase>
    agent: CALIBRATE
    timestamp: null
    data:
      domain: "<domain>"
      prior_accuracy: <0.0-1.0>
      new_accuracy: <0.0-1.0>
      sample_size: <N>
  - id: null
    type: confidence_thresholds_refreshed
    phase: <current phase>
    agent: CALIBRATE
    timestamp: null
    data:
      domains_updated: ["<domain>"]
```

```

- [ ] **Step 2: Update mirror.md**

Find direct-write instructions. Replace.

Append:

```markdown
---

## Output Block

```echelon_result
verdict: COMPLETE
output_files:
  - knowledge-base/patterns.yaml
  - knowledge-base/pitfalls.yaml
journal_entries:
  - id: null
    type: pattern_extracted
    phase: phase4-document
    agent: REFLECT
    timestamp: null
    data:
      pattern_id: "PAT-<NNN>"
      pattern_summary: "<what pattern was identified>"
      applicable_phases: ["phase1-discover", "phase3-how"]
  - id: null
    type: pitfall_extracted
    phase: phase4-document
    agent: REFLECT
    timestamp: null
    data:
      pitfall_id: "PIT-<NNN>"
      pitfall_summary: "<what pitfall was identified>"
      trigger_conditions: ["<condition>"]
```

```

- [ ] **Step 3: Update adaptive.md, consolidator.md, internalizer.md, realist.md, veteran.md, monitor.md, global-memory.md**

For each with direct writes: locate, replace, append echelon_result.

**adaptive.md** — verdict: `COMPLETE`, journal type: `quality_trajectory`, data: `{run_ids_compared, trajectory, regression_detected}`.

**consolidator.md** — verdict: `COMPLETE`, output_files: `['knowledge-base/patterns.yaml']`, journal type: `pattern_extracted`, data: `{pattern_id, pattern_summary, applicable_phases}`.

**internalizer.md** — verdict: `COMPLETE`, journal type: `decision`, data: `{artifact: 'internalization-report.md', section: 'metrics', reasoning: '<internalization assessment>'}`.

**realist.md** — verdict: `COMPLETE`, output_files: `['.specify/.../reality-check.md']`, journal type: `reality_check`, data: `{artifact: '<artifact>', finding: '<grounded finding>', grounded_value: '<measured vs estimated>'}`.

**veteran.md** — verdict: `COMPLETE`, journal type: `decision`, data: `{artifact: 'agent-scores.yaml', section: 'demotion_candidates', reasoning: '<why flagged>'}`.

**monitor.md** — No direct writes. verdict: `HEALTHY | DEGRADED`, journal type: `decision`, data: `{check_type: 'health', result: '<HEALTHY|DEGRADED>', findings: ['<finding>']}`.

**global-memory.md** — No direct writes. verdict: `COMPLETE`, journal type: `decision`, data: `{artifact: '<memory file>', section: '<updated area>', reasoning: '<why updated>'}`.

- [ ] **Step 4: Verify clean — all layers**

```bash
grep -rn "reasoning-journal" agents/ | grep -v "echelon_result" | grep -v "COMMANDER writes" | grep -v "prior agent" | grep -v "context" | grep -v "^Binary"
```

Expected: only COMMANDER's Bootstrap Contract and Index Writer Protocol references remain — which are reads and write-protocol instructions, not direct agent appends.

- [ ] **Step 5: Commit**

```bash
git add agents/learning/
git commit -m "feat: learning layer agents — echelon_result output blocks"
```

---

## Task 10: Final Integration Verification

- [ ] **Step 1: Run a full Phase 1–4 squad run**

Invoke `/b3c.echelon.run` on a project that will go all the way through the build phase. Let it complete.

- [ ] **Step 2: Verify all 5 success criteria from the spec**

```bash
# Criterion 1: COMMANDER has no hardcoded thresholds
grep -n "0\.02\|40 min\|5 total\|100%" agents/control/commander.md
# Expected: zero matches (these are now in workflow/definition.yaml)

# Criterion 2: No agent writes directly to journal
grep -rln "reasoning-journal" agents/ | xargs grep -l "Append entries\|append.*reasoning" | grep -v commander
# Expected: zero matches

# Criterion 3: Index maintained after run
python3 -c "
import json
idx = json.load(open('.specify/squad/reasoning-journal-index.json'))
assert idx['timeline'], 'timeline empty'
assert idx['by_phase'], 'by_phase empty'
assert idx['by_type'], 'by_type empty'
print(f'Index healthy: {len(idx[\"timeline\"])} entries, {len(idx[\"by_phase\"])} phases, {len(idx[\"by_type\"])} types')
"

# Criterion 4: Phase transitions preserved (same check as Task 6 Step 4)
python3 -c "
import json
transitions = []
with open('.specify/squad/reasoning-journal.jsonl') as f:
    for line in f:
        entry = json.loads(line)
        if entry.get('type') == 'phase_transition':
            transitions.append(f\"{entry['data']['from_phase']} -> {entry['data']['to_phase']}\")
print('\n'.join(transitions))
"

# Criterion 5: workflow/definition.yaml is authoritative
# Manual check: open definition.yaml and confirm all routing rules
# from the original commander.md are represented there
```

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "feat: echelon journal refactor complete — compaction-safe orchestration"
```

---

## Known Limitations / Out of Scope

- RADAR server implementation deferred — `timeline` dimension is ready for it
- Relevance-scored journal queries (beyond the 8 index dimensions) deferred
- `visual-validator.md` uses Playwright — its `output_files` field should include screenshot paths once Playwright tooling is integrated
