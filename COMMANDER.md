# COMMANDER — CA Overlay Integration Reference

**Amendment version**: 1.0.0
**Amendment date**: 2026-04-03
**References**: ADR-005 (CA Overlay Integration), spec 017 FR-CAO-001 through FR-CAO-006
**P-006 override**: Human authorization received 2026-04-03 ("build it anyway")

---

## CA Overlay Integration Hook-Points

The five cognitive architecture overlays below are integrated into COMMANDER's dispatch
cycle as context enrichment steps. **Overlays are strictly read-only on COMMANDER state.**
They enrich only the context_pack dict passed to each agent dispatch — they CANNOT and
MUST NOT modify COMMANDER routing logic, quality gate thresholds, or endocrine triggers
(FR-CAO-006).

The overlays are enabled only when `experiments/uca004-results.json` is present and
`verdict == "POSITIVE"` (FR-CAO-000 gate, enforced by `scripts/ca/verify_gate.sh`).
For this build, the human authorized overlay implementation despite a NEGATIVE verdict
(Cohen's d = 0.40; override 2026-04-03).

---

## Pre-Dispatch Sequence (for each agent dispatch)

Run these enrichment calls in order, before the `Agent` tool call:

```python
from scripts.ca import goal_stack, actr_buffer, gwt_workspace, episodic_memory
import subprocess, json, os

# 1. Goal Stack
context_pack = goal_stack.enrich_context(context_pack, run_id)

# 2. ACT-R Typed Buffer
# ISS-004-REG-001 fix: actr_buffer returns only {"actr_buffers": ...} (no original keys),
# so use .update() to merge into context_pack instead of replacing it.
context_pack.update(actr_buffer.enrich_context(context_pack, run_id))

# 3. LIDA Broadcast — check for pending broadcast payload
lida_payload_path = ".specify/squad/lida-payload.json"
if os.path.isfile(lida_payload_path):
    with open(lida_payload_path) as f:
        lida_payload = json.load(f)
    os.remove(lida_payload_path)          # consume-once semantics (FR-CAO-003)
    context_pack["lida_broadcast"] = lida_payload

# 4. GWT Bounded Workspace
context_pack = gwt_workspace.enrich_context(context_pack, run_id)

# 5. Episodic Memory
context_pack = episodic_memory.enrich_context(context_pack, run_id, agent_type=AGENT_CODENAME)

# 6. SOAR Cognitive Architecture Overlay (position 6)
try:
    from scripts.ca import soar
    context_pack = soar.enrich_context(context_pack, run_id)
except Exception as _soar_exc:  # noqa: BLE001
    # NFR-SOAR-004 / AC-6.1: exception does not block dispatch
    _log(f"SOAR overlay exception (non-blocking): {_soar_exc}")
```

---

## Post-Dispatch Sequence (for each agent dispatch, after result received)

```python
outcome = {
    "completed_goal_id": None,   # set if this dispatch closed a goal
    "new_goal": None,            # set if a sub-goal was opened
}

# 1. Goal Stack — update with dispatch outcome
goal_stack.update_goal_stack(outcome, run_id)

# 2. Episodic Memory — index artifact produced by this agent
import time
episodic_memory.index_artifact(
    agent_type=AGENT_CODENAME,
    artifact_path=primary_artifact_path,   # e.g., "specs/017-.../spec.md"
    stage_timestamp=time.time(),
    artifact_category=ARTIFACT_CATEGORY,   # e.g., "spec", "tasks", "report"
    run_id=run_id,
)

# 3. GWT Workspace — add key insight from this dispatch
gwt_workspace.add_to_workspace(
    item_text=f"{AGENT_CODENAME}: {short_summary_of_output}",
    run_id=run_id,
)

# ACT-R Buffer and LIDA Broadcast: no post-dispatch action required.

# 4. SOAR Cognitive Architecture Overlay — post-dispatch learning
try:
    from scripts.ca import soar as _soar_mod
    _soar_mod.update_soar_memory(outcome, run_id)
except Exception as _soar_exc:  # noqa: BLE001
    # NFR-SOAR-004 / AC-6.2: exception does not corrupt dispatch outcome
    _log(f"SOAR update_soar_memory exception (non-blocking): {_soar_exc}")
```

---

## Run-End Cleanup

At the end of each run (before BUILD_DONE or KILL state):

```bash
# Remove any unconsumed LIDA broadcast payload
scripts/bash/lida_broadcast.sh cleanup "${run_id}"

# Runtime overlay files are gitignored via .specify/squad/ exclusion.
# No manual cleanup needed for goal-stack-*.json, gwt-workspace-*.json,
# episodic-index-*.json.
```

---

## Overlay Specifications

### 1. Goal Stack (`scripts/ca/goal_stack.py`)

| Aspect | Detail |
|--------|--------|
| Pre-dispatch | `goal_stack.enrich_context(context_pack, run_id)` |
| Post-dispatch | `goal_stack.update_goal_stack(outcome, run_id)` |
| Injects | `context_pack["active_goal"]` = `{goal_text, priority, depth}` |
| State file | `.specify/squad/goal-stack-<run_id>.json` (gitignored) |
| Initialization | Root goal = spec feature name, depth=0, priority=1.0 |
| Constraint | Read-only on COMMANDER state. Stack JSON is the only write target. |

### 2. ACT-R Typed Buffer (`scripts/ca/actr_buffer.py`)

| Aspect | Detail |
|--------|--------|
| Pre-dispatch | `actr_buffer.enrich_context(context_pack, run_id)` |
| Post-dispatch | None |
| Injects | `context_pack["actr_buffers"]` = `{declarative, procedural, goal, imaginal, retrieval_buffer}` |
| TF-IDF | Top-3 relevant declarative excerpts by cosine similarity to goal+procedural |
| Eviction | Declarative entries evicted oldest-first when token bound exceeded (FR-CAO-002) |
| Constraint | Standard library only (no sklearn/numpy). Read-only on COMMANDER state. |

### 3. LIDA Broadcast (`scripts/bash/lida_broadcast.sh`)

| Aspect | Detail |
|--------|--------|
| Pre-dispatch | Check for `.specify/squad/lida-payload.json`; read + delete + inject |
| Post-dispatch | None (produce broadcast only when needed, via `lida_broadcast.sh broadcast <json>`) |
| Injects | `context_pack["lida_broadcast"]` = parsed payload JSON |
| Semantics | Replace-not-append (FR-CAO-003). Consume-once: file deleted after read. |
| Run-end | `lida_broadcast.sh cleanup <run_id>` removes any unconsumed payload |
| Constraint | Does not modify routing or gates. Payload is advisory context only. |

### 4. GWT Bounded Workspace (`scripts/ca/gwt_workspace.py`)

| Aspect | Detail |
|--------|--------|
| Pre-dispatch | `gwt_workspace.enrich_context(context_pack, run_id)` |
| Post-dispatch | `gwt_workspace.add_to_workspace(item_text, run_id)` |
| Injects | `context_pack["gwt_workspace"]` = list of current workspace items |
| State file | `.specify/squad/gwt-workspace-<run_id>.json` (gitignored) |
| Token bound | `ca_overlays.gwt.max_tokens` from `squad-config.yml` (default: 2000 tokens) |
| Eviction | Oldest-first (lowest timestamp). Priority = recency. |
| Constraint | Read-only on COMMANDER routing. Workspace is a sliding context window. |

### 5. Episodic Memory (`scripts/ca/episodic_memory.py`)

| Aspect | Detail |
|--------|--------|
| Pre-dispatch | `episodic_memory.enrich_context(context_pack, run_id, agent_type)` |
| Post-dispatch | `episodic_memory.index_artifact(agent_type, path, timestamp, category, run_id)` |
| Injects | `context_pack["episodic_prior_artifact"]` = `{artifact_path, stage_timestamp, artifact_category}` or `None` |
| State file | `.specify/squad/episodic-index-<run_id>.json` (gitignored) |
| Query | Most-recent artifact for the dispatched agent_type (max by stage_timestamp) |
| Index policy | Append-only. No cross-run persistence (v1). |
| Constraint | Read-only on COMMANDER routing. Index is the only write target. |

### 6. SOAR Cognitive Architecture Overlay (`scripts/ca/soar.py`)

| Property | Value |
|----------|-------|
| Interface | `soar.enrich_context(context_pack, run_id) -> dict` (pre-dispatch) |
| Post-dispatch | `soar.update_soar_memory(outcome, run_id) -> None` (mandatory) |
| Injected key | `soar_state` (dict, max 200 chars serialized) |
| State files | `soar-procedural-{run_id}.json` (ProceduralMemoryStore, gitignored) |
| | `soar-impasse-{run_id}.json` (impasse log, gitignored) |
| Seed rules | 5 hand-coded rules (seed-001 through seed-005, confidence 0.70–0.90) |
| Chunking | Disabled by default (`ca_overlays.soar.chunking_enabled: false`) |
| Exception policy | Exceptions in both hooks are caught; dispatch is never blocked (NFR-SOAR-004) |
| Write constraint | Does NOT modify `state.json` (FR-CAO-006) |

---

## Constraint Summary (FR-CAO-006)

> **All overlays are strictly read-only on COMMANDER state.** They may enrich the
> `context_pack` dict passed to an agent. They MUST NOT:
> - Modify COMMANDER routing decisions
> - Change quality gate thresholds
> - Trigger or suppress endocrine signals
> - Alter task ordering or dependency graphs
> - Write to `state.json` or `reasoning-journal.json`
>
> Violations of FR-CAO-006 constitute a constitution violation (P-001).
