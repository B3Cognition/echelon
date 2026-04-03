# Mental Model — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03 | **Supersedes**: SCOUT mental-model.md

---

## Synthesis Note

SCOUT identified two independent sub-systems sharing three integration points. SYNTHESIZER confirms this structure and adds the cross-system dependency analysis.

**Two independent sub-systems:**
1. **NS-003 prototype** — Generator-Critic (NS-003-A) + AGM Belief Graph (NS-003-B): write-time artifact quality enforcement
2. **U-CA-004 + CA overlays** — ACT-R buffer experiment infrastructure + conditional overlay implementations

**Three shared integration points:**
1. **endocrine.sh** — both sub-systems fire endocrine events through COMMANDER
2. **COMMANDER dispatch protocol** — both sub-systems require COMMANDER.md modifications (different hooks)
3. **Artifact store** — both sub-systems operate on the same Markdown artifact directory

---

## Core Entities (Unified)

### Artifact Store
- **Description:** The persistence layer for all pipeline outputs within one Echelon spec run. Organized as a directory of Markdown files grouped by pipeline stage. Currently written by agents and read by subsequent agents with no consistency enforcement at write-time.
- **Key attributes:** spec run ID, artifact files by stage, no write-time validation currently
- **Relationships:** Written by all pipeline agents; read by subsequent agents; scanned post-hoc by contradiction-scanner.py; target for NS-003 write-time Critic + belief graph; context source for U-CA-004 AQS evaluation
- **Sources confirmed by:** [NS-003] `ns003-experiment-design.md`; [U-CA-004] `u-ca-004-experiment-spec.md`; [code] `contradiction-scanner.py` ARTIFACT_STAGE_MAP
- **Lifecycle:** Created at run start → populated incrementally by each pipeline stage → persisted at `.specify/specs/<spec-id>/`
- **Gaps:** No write-time validation exists today (NS-003 is the addition). No cross-artifact consistency enforcement (NS-003-B is the addition). Episodic Memory (CA overlay 4) would add cross-RUN persistence — not in v1 scope.

### Assertion (contradiction-scanner.py — existing)
- **Description:** An ephemeral factual claim extracted from a spec artifact during a scan. Has: file path, line number, text (≤300 chars), entity (normalized key), numbers (extracted numeric tokens), statuses (PASS/FAIL/YES/NO etc.), negated (boolean), stage (pipeline stage).
- **Key attributes:** entity (normalized key for matching), stage, numbers, statuses, negated
- **Relationships:** Compared against Assertions from adjacent pipeline stages using `_entities_match()`; Contradiction objects produced on mismatch; stop-key list (_GENERIC_STOP_KEYS, 25 keys) prevents false positives from generic field names
- **Lifecycle:** Created per scan invocation → compared → discarded (NOT persisted)
- **Relationship to BeliefNode:** Assertion is the ephemeral precursor form. NS-003-B's BeliefNode uses the same entity normalization logic (`_normalise_entity()`) but persists the result across the run.

### BeliefNode (to be built — NS-003-B)
- **Description:** A persistent node in the NS-003-B belief graph representing one factual assertion tied to a specific schema field. Unlike the ephemeral Assertion, BeliefNode is written to the graph at artifact commit time and persists across the run.
- **Key attributes:** content, source_agent, version_counter, confidence_score (0.5-0.95), field_identifier, status (ACTIVE | SUPERSEDED), superseded_by edge
- **Relationships:** Created when an artifact section is committed; ConflictSignal triggered if a new node contradicts existing node for same field_identifier; AGM revision creates SUPERSEDED relationship; ConflictSignal outcome wired to endocrine events
- **Lifecycle:** Created at artifact write → ACTIVE → SUPERSEDED (if contradicted by higher-evidence assertion, retained with provenance chain)
- **Persistence format:** Unresolved — candidate options: (a) in-memory Python dict + belief-graph.json at run end [lowest complexity], (b) networkx graph object + serialized to JSON. See unknowns.md U-005.

### Contradiction (contradiction-scanner.py — existing)
- **Description:** A detected mismatch between two Assertions from adjacent pipeline stages. Three heuristic types: count_mismatch (confidence=0.7), status_mismatch (confidence=0.85), boolean_mismatch (confidence=0.5). Important: upper-bound detector — over-detects hard contradictions, misses soft prose contradictions.
- **Key attributes:** id (C-NNN), ctype, assertion_a, assertion_b, entity, confidence
- **Lifecycle:** Created per scan → written to contradiction-report.json → verified=null (awaiting manual review)
- **Role in spec 017:** This is the NS-003-B BASELINE. CCR metric for NS-003-B must be measured against this baseline's detection rate.

### ConflictSignal (to be built — NS-003-B)
- **Description:** A write-time event emitted when a new BeliefNode would violate consistency with an existing BeliefNode for the same field_identifier.
- **Key attributes:** field_identifier, new_assertion, existing_node, recommended_action (accept|revert|escalate), confidence_score
- **Lifecycle:** Fired pre-commit → AGM revision applied → resolution recorded → run continues or ESCALATED to human
- **Endocrine wiring required:** ESCALATED → COMMANDER calls `endocrine.sh on_gate_fail <agent>`; resolved → COMMANDER calls `endocrine.sh on_gate_pass <agent>`
- **Emergent risk:** If ≥3 consecutive ConflictSignals reach ESCALATED in build phase, cortisol crosses 0.8 threshold and triggers contagion cascade. See risks.md RSK-003.

### Endocrine State (existing, Phase 3 active — shared integration point)
- **Description:** A 6-dimensional hormone vector maintained in state.json under `endocrine_state.agents.<AGENT_NAME>.hormones`. Values in [0.0, 1.0] per hormone. Initialized from per-archetype baselines in squad-config.yml.
- **Current state:** Phase 3 active (all 6 hormones). No hooks for NS-003 or CA overlay events — these are NEW event sources.
- **NS-003 wiring:** COMMANDER calls existing endocrine.sh commands (on_gate_fail, on_gate_pass, on_quality_improvement, on_quality_regression) based on NS-003 outcomes. No structural changes to endocrine.sh needed.
- **CA overlay wiring:** ACT-R buffer build quality outcomes trigger on_quality_improvement or on_quality_regression system-wide.
- **Integration mechanism:** COMMANDER.md Post-Dispatch Protocol section requires new additions. Current Pre-Dispatch Protocol (lines 210-232) covers only pre-dispatch steps; post-dispatch, pre-commit hook pattern is NOT documented anywhere. See unknowns.md U-009.
- **Sources:** [code] `scripts/bash/endocrine.sh`; `squad-config.yml`; `agents/control/commander.md`

### AQS Evaluation (U-CA-004 — to be built)
- **Description:** A scoring event applied to one agent output within one experiment condition. Human evaluator scores four dimensions on 0-3 integer scales.
- **Key constraint:** Evaluator requires access to ALL prior stage artifacts from the same run to score Internal Consistency dimension. Experiment runner must package (run output + all prior stage artifacts) as evaluator context bundle.
- **Key attributes:** condition (A/B/C), run_id, agent_type, dimension_scores [0-3 each], AQS [0.0-1.0], evaluator_id
- **Relationships:** N=20 invocations per condition (60 total); fed into Mann-Whitney U test comparing Condition B vs C; compared against SVR measurements
- **Sources:** [U-CA-004] `u-ca-004-experiment-spec.md` Section 6

---

## Relationships (Unified)

| Entity A | Relationship | Entity B | Cardinality | Source | Notes |
|----------|-------------|----------|-------------|--------|-------|
| Artifact Store | scanned by | Assertion extractor | 1:N | existing code | Post-hoc, upper-bound heuristic |
| Assertion | compared against | Assertion (adjacent stage) | N:M | existing code | `_entities_match()` + 3 heuristics |
| Assertion | produces | Contradiction | N:1 | existing code | When heuristic match found |
| Artifact Store | written to | BeliefNode | 1:N | NS-003-B target | At write-time (pre-commit), not post-hoc |
| BeliefNode | emits on conflict | ConflictSignal | 1:1 | NS-003-B target | One signal per field_identifier conflict |
| ConflictSignal | triggers | AGM Revision | 1:1 | NS-003-B target | Minimal contraction/revision per AGM postulates |
| AGM Revision | supersedes | BeliefNode | 1:1 | NS-003-B target | Lower-evidence node gets SUPERSEDED flag |
| COMMANDER | reads | Endocrine State | 1:1 per dispatch | existing code | Pre-dispatch protocol |
| COMMANDER | writes | Endocrine State | 1:N per run | existing code | Event triggers after each agent output |
| ConflictSignal (ESCALATED) | triggers | on_gate_fail | 1:1 | **to be wired** | New event source — not yet in COMMANDER |
| ConflictSignal (resolved) | triggers | on_gate_pass | 1:1 | **to be wired** | New event source — not yet in COMMANDER |
| CA Overlay (ACT-R Buffer) | preprocesses | Artifact Store context | 1:N per invocation | U-CA-004 conditional | 4-buffer scoring replaces full concatenation |
| AQS Evaluation | measures | Agent output | 1:1 | U-CA-004 | Per invocation, per condition |
| Mann-Whitney U | compares | AQS (Cond B) vs AQS (Cond C) | N:N | U-CA-004 | N=20 per condition |
| Contradiction (heuristic) | is BASELINE for | ConflictSignal (NS-003-B) | 1:system | synthesis insight | CCR must exceed heuristic detection rate |

---

## Architecture: Two Sub-Systems with Three Shared Integration Points

```
════════════════════════════════════════════════════════════════════════════
SUB-SYSTEM 1: NS-003 (Generator-Critic + AGM Belief Graph)
════════════════════════════════════════════════════════════════════════════

NS-003-A (Schema Compliance):
  COMMANDER dispatches agent
    → LLM generates raw Markdown output
    → critic.validate(output, schema, artifact_store) [deterministic Python, no LLM]
        ↓ PASS                      ↓ FAIL
    commit to artifact store    CriticReport
    on_gate_pass(agent) [1]     → retry_prompt (max 2)
                                    ↓ FAIL after 2
                                ESCALATED → on_gate_fail(agent) [1]

NS-003-B (Belief Consistency, parallel to NS-003-A):
  At artifact commit time:
    new_assertion for field F
      → BeliefGraph.lookup(field_identifier=F)
          ↓ no node         ↓ existing node
      create BeliefNode   check consistency
      commit              ↓ consistent      ↓ conflict
                      update metadata   ConflictSignal
                                          → AGM K*2 revision
                                          → supersede existing node
                                          → recommended_action
                                          → on_gate_fail/pass(agent) [1]

[1] = Shared integration point with endocrine.sh

════════════════════════════════════════════════════════════════════════════
SUB-SYSTEM 2: U-CA-004 (CA Overlay Gate Experiment)
════════════════════════════════════════════════════════════════════════════

Condition A (naive baseline) ──┐
Condition B (expert prompts)   ├── N=20 runs each on Echelon extension codebase
Condition C (ACT-R Typed Buf) ──┘    [2]
                                ↓
                   AQS scoring (4 dims × 0-3) per artifact
                   SVR scoring (out-of-scope sections / total)
                        ↓
                   Mann-Whitney U (Cond B vs Cond C)
                        ↓ p<0.05 AND ΔAQS≥0.10 AND ΔSVR≥15%
                   POSITIVE → unlock ACT-R [3], proceed to Goal Stack test
                   NEGATIVE → terminate overlay program

[2] = ACT-R buffer preprocesses Artifact Store context (Shared integration point)
[3] = Conditional: only if POSITIVE; P-006 authorized but experiment gate still applies

════════════════════════════════════════════════════════════════════════════
SHARED INTEGRATION POINTS
════════════════════════════════════════════════════════════════════════════

  [1] endocrine.sh:
      - NS-003 ESCALATED → on_gate_fail(agent)
      - NS-003 resolved → on_gate_pass(agent)
      - CA overlay quality result → on_quality_improvement / on_quality_regression
      *** NO hooks exist yet — all three require new COMMANDER.md additions ***

  [2] Artifact Store context (CA overlay):
      - ACT-R buffer replaces full artifact concatenation in COMMANDER context pack
      - Uses same .specify/specs/<run>/ directory structure as NS-003

  [3] COMMANDER dispatch protocol:
      - NS-003 requires post-LLM, pre-commit hook (write-time interception)
      - CA overlay requires pre-dispatch context preprocessing
      - BOTH are COMMANDER.md modifications — must be designed to coexist
      *** Interception hook mechanism is UNKNOWN (U-009) ***

════════════════════════════════════════════════════════════════════════════
EXISTING BASELINE (heuristic)
════════════════════════════════════════════════════════════════════════════

Echelon Pipeline run
  → agents produce Artifact Store (Markdown files)
  → COMMANDER dispatches: reads endocrine state → injects prompt modifier → agent runs
  → contradiction-scanner.py: POST-HOC scan of Markdown
      extracts Assertions → compares adjacent stage pairs
      → Contradiction (count/status/boolean mismatch heuristics)
      → contradiction-report.json (manual_precision_sample for review)
```

---

## Behavioral Patterns

### Pattern 1: NS-003-A Retry Loop (to be built)
1. COMMANDER dispatches agent with standard prompt + context pack
2. Agent (LLM) produces raw Markdown output
3. `critic.validate(output, schema)` runs Python jsonschema validator
4. PASS: output committed to artifact store, `endocrine.sh on_gate_pass <agent>`
5. FAIL: CriticReport constructed; retry prompt assembled; max 2 retries
6. After 2 failures: ESCALATED, `endocrine.sh on_gate_fail <agent>`, logged

### Pattern 2: NS-003-B Write-Time Belief Check (to be built)
1. At artifact commit time, for each key-value assertion:
2. Normalize field_identifier (stage + field key)
3. Lookup BeliefGraph for existing node
4. No node: create BeliefNode, commit
5. Existing node: apply field-type consistency rule
6. Consistent: update BeliefNode metadata, commit
7. Inconsistent: emit ConflictSignal, apply AGM K*2 revision, retain SUPERSEDED node, return recommended_action

### Pattern 3: U-CA-004 ACT-R Buffer Preprocessing (to be built, conditional on POSITIVE)
1. Pre-dispatch, Python function constructs 4-buffer context:
   - goal_buffer: current pipeline goal + agent scope declaration (~200 tokens)
   - retrieval_buffer: top-K artifact chunks ranked by `recency_weight × cosine_similarity` (≤4,000 tokens)
   - imaginal_buffer: in-progress artifact section (variable)
   - stable_buffer: compressed invariant context summary (~500 tokens)
2. Replaces full artifact concatenation in standard COMMANDER context pack
3. Operates outside LLM call — cosine_similarity computation method TBD (U-008)

### Pattern 4: Endocrine Propagation (existing, Phase 3 active)
- on_gate_pass(agent): dopamine +0.15 to that agent
- on_quality_improvement(): serotonin +0.10 system-wide
- propagate_downstream(from, to): `to.dopamine += (from.dopamine - 0.5) × 0.3`
- propagate_cortisol_contagion(from, to): if from.cortisol > 0.8, to.cortisol += 0.05
- **NS-003 risk:** 3 consecutive ESCALATED → cortisol crosses 0.8 → contagion cascade
