# Mental Model — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — unified from DISCOVER outputs  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources merged**: mental-model.md (SCOUT), glossary.md (SCOUT), boundaries.md (SCOUT), reference-architectures.md (SCOUT), reasoning-journal.json (SCOUT)

---

## Core Entities

### ProductionRule
- **Description:** An IF-THEN rule stored in the overlay's ProceduralMemoryStore. The LHS (conditions) matches WME patterns from the context_pack; the RHS (actions) specifies what to inject into context_pack via an operator payload.
- **Key attributes:**
  - `rule_id` (str) — unique identifier, prefixed `"seed-"` for hand-coded or `"chunk-"` for learned rules
  - `conditions` (list of WME patterns) — schema is open question U-002; each pattern is at minimum `{attr: str}` with optional value/type constraints
  - `actions` (list — in Echelon overlay, resolves to a single operator name + payload)
  - `confidence` (float in [0.0, 1.0]) — the preference scalar used by DecisionProcedure
  - `learned` (bool) — True if created by SOAR-inspired chunking, False if hand-coded
- **Relationships:**
  - Matched against WorkingMemory (many-to-many; all matching rules fire in parallel in elaboration)
  - Proposes exactly one Operator per rule
  - Produced by ChunkingEngine when a successful episode concludes
- **Lifecycle:** Created (hand-coded at module init, or SOAR-chunked from episode) → stored in ProceduralMemoryStore JSON → matched each dispatch cycle → never modified (immutable once created; superseded by more-specific SOAR chunks)
- **Sources:** mental-model.md (SCOUT), glossary.md (SCOUT)
- **Gaps:** WME pattern schema (U-002) not yet defined — this is a must-resolve-before-WHAT unknown.

---

### WorkingMemory
- **Description:** The set of all current WMEs derived from the incoming context_pack. In SOAR, working memory is the agent's entire knowledge state. In Echelon's overlay, it is a read-only transformation of context_pack, created fresh on each `enrich_context` call.
- **Key attributes:**
  - `wmes` (list of `{id, attr, value}` triples)
  - `state_id` (str — `"state-<run_id>"`, the root state symbol)
  - `cycle_count` (int — decision cycles run in this dispatch; always 1 in v1's single-pass model)
- **WME extraction rule:** Each top-level context_pack key → one WME. Nested dict values JSON-serialized and truncated at 200 chars (A-006).
- **Known stable WME attributes (from prior overlay injections):**
  - `active_goal` (from Goal Stack overlay)
  - `actr_buffers` (from ACT-R overlay — nested dict, see U-007 for handling concern)
  - `lida_broadcast` (from LIDA overlay)
  - `gwt_workspace` (from GWT overlay)
  - `episodic_prior_artifact` (from Episodic Memory overlay, spec 017)
  - `agent_type`, `spec_id`, `run_id` (COMMANDER-injected base keys)
- **Relationships:** Populated from context_pack → read by ProductionRule match → enriched by Operator application → discarded after dispatch (no persistence between calls)
- **Lifecycle:** Created fresh at each `enrich_context` call → not persisted (stateless working memory model)
- **Sources:** mental-model.md (SCOUT), boundaries.md (SCOUT), assumptions.md (SCOUT)
- **Gaps:** Key stability across runs is unvalidated (A-003 status: unvalidated). The `actr_buffers` nested dict requires special handling (U-007, should-resolve-before-HOW).

---

### SOAR Operator (fully qualified — see Overloaded Terms in glossary.md)
- **Description:** A named enrichment action proposed by a matching ProductionRule. Carries the semantic intent of what to add to context_pack. The operator does not execute code — the apply phase merges its payload.
- **Key attributes:**
  - `name` (str — e.g., `"enrich-with-soar-state"`, `"enrich-goal-active"`, `"default-no-match"`)
  - `payload` (dict — fields to inject into context_pack under `context_pack["soar_state"]`)
  - `source_rule_id` (str)
  - `confidence` (float — inherited from the proposing ProductionRule)
- **Relationships:**
  - Proposed by ProductionRule (one-to-one: each rule proposes one operator)
  - Evaluated by DecisionProcedure (many-to-one: all proposals → one winner)
  - Applied by ApplyPhase (merge payload into context_pack)
  - Triggers ImpasseEvent if no operator is proposed
- **Lifecycle:** Proposed → DecisionProcedure selects (argmax confidence) or rejects → applied to enrich context_pack → discarded after application
- **Sources:** mental-model.md (SCOUT), glossary.md (SCOUT)

---

### DecisionProcedure
- **Description:** Selects a single operator from the proposed set. In full SOAR, a preference calculus with 8 preference types. In Echelon's overlay, argmax on confidence with first-match tie-breaking.
- **Key attributes:**
  - `strategy`: always `"argmax-confidence"` in v1
  - `tie_break`: `"first-match"` when confidence values are equal
- **Deviation from canonical SOAR:** Full SOAR fires an impasse on a tie; this overlay picks first-match. This is flagged in contradictions-and-gaps.md §Tie-Behavior-Deviation.
- **Relationships:** Receives all proposed operators from match phase → emits one selected operator OR fires ImpasseEvent (no-operator case only; tie case picks first-match)
- **Lifecycle:** Invoked once per elaboration cycle; stateless between calls
- **Sources:** mental-model.md (SCOUT), glossary.md (SCOUT)

---

### ImpasseEvent
- **Description:** Created when no production rule's conditions match the current working memory (no-operator impasse) or when two rules tie on confidence (tie impasse, but see deviation above). Logged to the impasse log. Triggers DefaultOperator.
- **Key attributes:**
  - `type` (str — `"no-operator"` or `"tie"`)
  - `wme_snapshot` (dict — WME state at impasse time for debugging)
  - `run_id` (str)
  - `cycle` (int)
- **First-class status:** ImpasseEvent must be logged — impasse must not be silently swallowed. This is an architectural invariant confirmed across all reference architectures (RJ-008).
- **Relationships:** Created by DecisionProcedure → appended to `soar-impasse-{run_id}.json` → triggers DefaultOperator application
- **Sources:** mental-model.md (SCOUT), glossary.md (SCOUT), reference-architectures.md (SCOUT)
- **Typo corrected:** DISCOVER source had "ImpasseCvent" (mental-model.md line 24) — correct form is "ImpasseEvent."

---

### ChunkRecord (SOAR chunk — fully qualified — see Overloaded Terms in glossary.md)
- **Description:** A newly-learned production rule created by the SOAR-inspired chunking mechanism after a successful dispatch. Approximates SOAR's chunking without dependency tracing.
- **Key attributes:**
  - `rule_id` (str — prefixed `"chunk-"`)
  - `conditions` (inferred from WME snapshot — generalization strategy TBD per U-003)
  - `actions` (the enrichment payload that succeeded)
  - `confidence` (float — starts at 0.6, increases with repeated successful application — specific increment not yet defined)
  - `learned` (bool — always True)
  - `episode_id` (str — `run_id + ":" + str(cycle)`)
- **Relationships:** Produced by ChunkingEngine → appended to ProceduralMemoryStore → matched in subsequent dispatch cycles within the same run
- **Sources:** mental-model.md (SCOUT), unknowns.md (SCOUT)
- **Gaps:** Confidence increment formula not defined. Generalization strategy (U-003) is a must-resolve-before-HOW blocker.

---

### ProceduralMemoryStore
- **Description:** File-backed list of production rules. Persistent within a run; not persisted across runs (v1 scope, A-008).
- **Key attributes:**
  - `rules` (list of ProductionRule dicts)
  - `run_id` (str)
  - `last_updated` (ISO timestamp)
- **File path:** `.specify/squad/soar-procedural-{run_id}.json`
- **Access pattern:** Read at each `enrich_context` call; appended to by `update_soar_memory` post-dispatch. Single-writer (SOAR overlay); read-accessible for diagnostics.
- **Sources:** mental-model.md (SCOUT), boundaries.md (SCOUT)

---

### ChunkingEngine
- **Description:** The post-dispatch component that reads the EpisodicIndex and constructs ChunkRecords from successful episodes. Called by `update_soar_memory(outcome, run_id)`.
- **Trigger condition:** outcome marks dispatch as successful — specific success criterion is open question U-006.
- **Dependencies:** Reads EpisodicIndex (`episodic-index-{run_id}.json`) — soft dependency; if absent, chunking is skipped.
- **Sources:** mental-model.md (SCOUT), boundaries.md (SCOUT)
- **Gaps:** Success criterion (U-006) not defined.

---

## Entity Relationship Table

| Entity A | Relationship | Entity B | Cardinality | Confirmed By |
|----------|-------------|----------|-------------|-------------|
| ProductionRule | matches against | WorkingMemory | many-to-many | SCOUT mental-model + reference-architectures |
| ProductionRule | proposes | SOAR Operator | one-to-one | SCOUT mental-model |
| WorkingMemory | is extracted from | context_pack | one-to-one | SCOUT mental-model + boundaries |
| DecisionProcedure | selects from | SOAR Operator (set) | many-to-one | SCOUT mental-model |
| DecisionProcedure | fires | ImpasseEvent | conditional (no-operator case) | SCOUT mental-model + reference-architectures |
| ImpasseEvent | is logged to | `soar-impasse-{run_id}.json` | one-to-many (append-only) | SCOUT mental-model + boundaries |
| ChunkRecord | extends | ProceduralMemoryStore | one-to-many | SCOUT mental-model |
| ChunkingEngine | reads | EpisodicIndex | one-to-one per run | SCOUT mental-model + boundaries |
| ProceduralMemoryStore | is consumed by | `enrich_context()` | one-to-one per call | SCOUT boundaries |
| SOAR overlay | is called by | COMMANDER | one-to-many (once per dispatch) | SCOUT boundaries |
| `soar_state` key | is injected into | context_pack | one-to-one per dispatch | SCOUT boundaries (confirmed: no key collision) |

---

## Concept Map

```
DISPATCH CYCLE (per agent, pre-dispatch — position 6)
│
├── 1. WME EXTRACTION
│     context_pack dict → list of WMEs
│     {id: "state-<run_id>", attr: <key>, value: str(<value>)[:200]}
│     Known stable attrs: active_goal, actr_buffers, lida_broadcast,
│       gwt_workspace, episodic_prior_artifact, agent_type, spec_id, run_id
│
├── 2. MATCH PHASE (Elaboration — single pass)
│     Load ProceduralMemoryStore (soar-procedural-{run_id}.json)
│     For each ProductionRule: check if ALL conditions match current WMEs
│     Result: set of {operator_name, payload, confidence} proposals
│     [OPEN: WME pattern schema — U-002; actr_buffers handling — U-007]
│
├── 3. SELECT PHASE (Decision Procedure)
│     If proposals empty:
│       → ImpasseEvent(type="no-operator") → log → DefaultOperator
│     If proposals non-empty:
│       → argmax(confidence) → selected SOAR Operator
│       → On tie: first-match (DEVIATION: full SOAR would fire impasse)
│
├── 4. APPLY PHASE
│     Merge selected Operator.payload into context_pack["soar_state"]
│     soar_state = {operator_applied, confidence, cycle, wme_count, impasse: false}
│     [FR-CAO-006: ONLY context_pack["soar_state"] is written — no COMMANDER state touched]
│
└── RETURN enriched context_pack

POST-DISPATCH (per agent, after result received)
│
└── 5. SOAR CHUNKING (SOAR-inspired procedural compilation)
      Called by: update_soar_memory(outcome, run_id)
      Trigger: outcome["success"] == True (specific criterion: U-006)
      Read EpisodicIndex (episodic-index-{run_id}.json) — soft dependency
      Construct ChunkRecord from WME snapshot + applied payload
      Generalization strategy: U-003 (OPEN — must resolve before HOW)
      Append ChunkRecord to ProceduralMemoryStore
      Result: chunk available for matching in next dispatch cycle
```

---

## Behavioral Patterns

### Pattern 1: Successful Production Rule Match (happy path)
1. `enrich_context` called with context_pack (6 overlays worth of keys present) and run_id
2. WMEs extracted — ~8-15 WMEs expected from stable keys
3. ProceduralMemoryStore loaded — seed rules scanned (5-10 expected, A-004)
4. One or more rules match; highest-confidence operator selected
5. Operator payload merged into `context_pack["soar_state"]`
6. Enriched context_pack returned; COMMANDER proceeds with dispatch

### Pattern 2: Impasse (no rules match)
1. WME extraction produces a state not covered by any production rule
2. DecisionProcedure receives empty proposals → creates ImpasseEvent(type="no-operator")
3. ImpasseEvent appended to `soar-impasse-{run_id}.json`
4. DefaultOperator fires: `soar_state = {"operator_applied": "default-no-match", "impasse": true}`
5. Whether `soar_impasse: true` surfaces to the dispatched agent is open question U-004

### Pattern 3: Chunking (learning a new SOAR rule)
1. Post-dispatch: COMMANDER calls `update_soar_memory(outcome, run_id)`
2. outcome["success"] check (criterion: U-006)
3. ChunkingEngine reads WME snapshot from dispatch cycle
4. Generalization applied (strategy: U-003)
5. ChunkRecord appended to ProceduralMemoryStore
6. New rule available for matching in subsequent dispatch cycles within this run

### Pattern 4: Overlay Failure (FR-CAO-006 resilience)
1. `enrich_context` raises an unhandled exception
2. COMMANDER must catch and continue dispatch with unenriched context_pack
3. Overlay failure must NOT block dispatch — this is the FR-CAO-006 read-only constraint's failure mode implication

---

## FR-CAO-006 Compliance Verification

FR-CAO-006 states the overlay must be read-only on COMMANDER state. The Match-Select-Apply cycle maps cleanly without violation:

| Write operation | Target | FR-CAO-006 compliant? |
|----------------|--------|----------------------|
| Apply phase: merge payload | `context_pack["soar_state"]` — the overlay's own output key | YES — context_pack is the overlay's output, not COMMANDER state |
| Impasse logging | `soar-impasse-{run_id}.json` — owned by SOAR overlay | YES — not COMMANDER state |
| Chunking write | `soar-procedural-{run_id}.json` — owned by SOAR overlay | YES — not COMMANDER state |
| COMMANDER state.json | NOT touched | YES — no access |
| goal-stack-*.json | NOT touched (read as WME input only) | YES — read-only |
| gwt-workspace-*.json | NOT touched (read as WME input only) | YES — read-only |
| episodic-index-*.json | NOT touched (read by ChunkingEngine only) | YES — read-only |

**Conclusion:** The Match-Select-Apply cycle maps cleanly to `enrich_context()` without violating FR-CAO-006. All writes are to SOAR-overlay-owned files or to the overlay's own output key in context_pack.
