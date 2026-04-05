# Domain Glossary — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — unified from DISCOVER outputs  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources merged**: glossary.md (SCOUT), mental-model.md (SCOUT), boundaries.md (SCOUT), assumptions.md (SCOUT), unknowns.md (SCOUT), reference-architectures.md (SCOUT), reasoning-journal.json (SCOUT)

---

## Overloaded Term Resolutions

The following five terms collide between SOAR's formal vocabulary and existing Echelon terminology. All uses of these terms in spec 018 and downstream artifacts MUST apply the qualification rule specified here. Failure to qualify is a spec defect.

| Term | SOAR Meaning | Echelon Existing Meaning | Qualification Rule |
|------|-------------|--------------------------|-------------------|
| **State** | The symbolic WME graph rooted at the current state identifier in working memory. A state in SOAR is not a status field — it is the entire knowledge structure of the agent at a point in time. | `state.json` — the squad-run metadata file managed by COMMANDER. It contains run_id, phase, status, and all squad bookkeeping fields. | Always write "SOAR working memory state" or "WM state" for SOAR; always write "squad state.json" or "state.json" for Echelon squad bookkeeping. Never use bare "state" in spec 018 artifacts. |
| **Chunk** | A compiled production rule created automatically by SOAR's chunking learning mechanism from a substate problem-solving episode. A chunk is a procedural memory item — an IF-THEN rule, not a data grouping. | Cognitive psychology (Miller 1956): a grouped unit of short-term memory items (chunking as compression/grouping). Also used colloquially for token chunks in LLM contexts. | Always write "SOAR chunk" or "chunked production rule" for spec 018's learning mechanism. Never use bare "chunk" without qualification. Explicitly prohibit the Miller 1956 meaning in spec 018 contexts. |
| **Operator** | A declarative WME structure proposed by production rules and selected by the SOAR decision procedure. An operator is a symbolic label with preference attributes — it is not code that runs; it is selected and then applied by other production rules. | Python operator: a built-in or overloaded syntactic operation (`+`, `*`, `@`). Also used as a general CS term for "an entity that operates on something." | Always write "SOAR operator" in spec 018 contexts. When referring to the Python language construct, write "Python operator." Never use bare "operator" in spec 018 without qualification. |
| **Memory** | SOAR defines four memory subsystems: working memory (WMEs), procedural memory (production rules), episodic memory (temporal experience), semantic memory (declarative long-term). Each is a distinct architectural subsystem with separate access semantics. | `episodic_memory.py` — the Episodic Memory CA overlay (spec 017). In Echelon context, "memory overlay" or "memory module" typically refers to this module. | Qualify as: "SOAR working memory," "SOAR procedural memory," "SOAR episodic memory," "SOAR semantic memory." Refer to the spec 017 module as "Echelon Episodic Memory overlay" or "episodic_memory.py." Never use bare "memory" in spec 018. |
| **Goal** | A SOAR goal state: a working memory state created automatically to resolve an impasse. A SOAR goal state is ephemeral — it exists only while the impasse it was created to resolve is active, and is retracted when the impasse resolves. | Echelon Goal Stack overlay: an active task objective recorded in `goal-stack-{run_id}.json`. These are explicitly managed, persistent-within-run objectives, not ephemeral impasse-resolution constructs. | Always write "SOAR goal state" for the SOAR architectural construct. Write "Echelon goal stack entry" or "goal-stack entry" for the Goal Stack overlay's objectives. Never use bare "goal" in spec 018 artifacts without qualification. |

---

## Core Terms

### WME (Working Memory Element)
- **Definition:** The atomic unit of information in SOAR's working memory. A WME is a triple: `(identifier, attribute, value)`. The identifier is a symbol referencing an object in the symbolic graph; the attribute names a property of that object; the value is either another identifier (making the graph relational) or a constant (integer, float, string). The entire SOAR working memory state at any moment is the set of all WMEs currently active.
- **Echelon representation:** Python dict `{"id": str, "attr": str, "value": str|int|float}`. Values are string-coerced and truncated to 200 characters (see A-006). Nested dict values are JSON-serialized before coercion.
- **WME extraction rule:** Each top-level key of context_pack becomes one WME: `{id: "state-<run_id>", attr: <key>, value: str(<value>)[:200]}`.
- **Source:** glossary.md (SCOUT), mental-model.md (SCOUT), reference-architectures.md (SCOUT)
- **Confidence:** 0.95 (A — multiple concordant references)
- **Cross-reference flags:** None — all sources agree on this definition.

### Production Rule
- **Definition:** An IF-THEN rule in procedural memory. The LHS (left-hand side) is a conjunction of WME patterns that must all match current working memory. The RHS (right-hand side) is a list of actions — in full SOAR, add/remove WMEs or propose/accept/reject operators. In Echelon's overlay, the RHS is the operator name and enrichment payload to inject into context_pack.
- **Echelon schema (open question — U-002):** `{rule_id: str, conditions: [WME-pattern], actions: [{operator_name, payload}], confidence: float[0,1], learned: bool}`. The WME-pattern schema is unresolved (U-002).
- **Key distinction from other rule systems:** In SOAR, ALL matching production rules fire simultaneously in each elaboration cycle (parallel firing). The decision point is operator selection, not rule selection. This is architecturally distinct from classic expert systems (one rule fires per cycle).
- **Source:** glossary.md (SCOUT), mental-model.md (SCOUT)
- **Confidence:** 0.93

### SOAR Operator (fully qualified term — see Overloaded Terms above)
- **Definition:** A declarative WME structure proposed in working memory by production rules. An operator carries a name and attributes representing a potential action. The SOAR decision procedure selects one operator per decision cycle. The selected operator is then applied by production rules that match its structure.
- **Echelon representation:** `{name: str, payload: dict, source_rule_id: str, confidence: float}`. The operator does not execute code directly — the apply phase merges its payload into context_pack.
- **Source:** glossary.md (SCOUT), mental-model.md (SCOUT)
- **Confidence:** 0.90
- **SYNTHESIZER note:** The mental-model.md contains a typo — "ImpasseCvent" (line 24) — should be "ImpasseEvent." Logged in contradictions-and-gaps.md.

### Match-Select-Apply Cycle
- **Definition:** SOAR's core decision cycle. **Match phase (Elaboration):** All production rules whose LHS patterns are satisfied by current WMEs fire simultaneously. Multiple elaboration sub-cycles iterate until quiescence (no new WMEs added or removed). **Select phase (Decision):** The decision procedure applies operator preferences to choose a single operator. **Apply phase:** Production rules whose conditions match the selected operator's WMEs fire to modify working memory.
- **Echelon mapping:**

  | SOAR Phase | Echelon Equivalent | Deviation |
  |------------|-------------------|-----------|
  | Elaboration (all matching rules fire) | Scan all ProductionRules in ProceduralMemoryStore against context_pack WMEs | Single-pass only — no quiescence iteration |
  | Decision (operator selection via preferences) | Argmax confidence among proposed operators | Full preference calculus replaced by scalar confidence |
  | Application (apply operator to WMEs) | Merge selected operator payload into context_pack | WMEs not truly added/removed; context_pack dict mutated |
  | Impasse → substate creation | ImpasseEvent → DefaultOperator + impasse log | No true substate; impasse is an event, not a state |
  | Chunking (learn new rule from substate) | `update_soar_memory` post-dispatch → append ChunkRecord | No dependency tracing; generalization is heuristic |

- **FR-CAO-006 compliance:** The apply phase merges operator payload into context_pack (the overlay's own output dict). It does NOT write to state.json, goal-stack-*.json, gwt-workspace-*.json, or any COMMANDER-owned state. This preserves the read-only-on-COMMANDER-state constraint. See contradictions-and-gaps.md §MSA-Compliance for the verification trace.
- **Source:** glossary.md (SCOUT), mental-model.md (SCOUT), reference-architectures.md (SCOUT), RJ-003 (SCOUT)
- **Confidence:** 0.88

### Chunking (SOAR chunking — fully qualified term — see Overloaded Terms above)
- **Definition:** SOAR's built-in procedural learning mechanism. When a problem-solving episode in a substate produces a result that resolves an impasse, SOAR automatically compiles the reasoning trace into a new production rule via dependency tracing. The new rule (chunk) fires in future situations with matching conditions, converting deliberate reasoning into reactive processing.
- **Echelon approximation:** When a dispatch is marked successful post-dispatch, `update_soar_memory` constructs a ChunkRecord from the WME snapshot. No dependency tracing is performed — generalization strategy is an open question (U-003). The approximation is labeled "SOAR-inspired procedural compilation" to distinguish it from canonical SOAR chunking.
- **Critical deviation:** Canonical SOAR chunking requires dependency tracing to identify which WMEs were causally relevant. Echelon's overlay lacks this — see U-003 for the three generalization strategy options under investigation.
- **Source:** glossary.md (SCOUT), unknowns.md (SCOUT), RJ-002 (SCOUT), RJ-006 (SCOUT)
- **Confidence:** 0.85

### Impasse
- **Definition:** A condition arising when the SOAR decision procedure cannot select a single operator. Canonical SOAR impasse types: (a) no-operator (no rules proposed any operator), (b) tie (multiple operators proposed with insufficient preferences to distinguish), (c) operator no-change (selected operator cannot be applied). An impasse triggers automatic substate creation.
- **Echelon mapping:** In Echelon's overlay, impasse occurs when no production rule's conditions match the current context_pack WMEs. The overlay models `"no-operator"` and `"tie"` impasse types (ImpasseEvent). Substate creation is not implemented — instead, a DefaultOperator fires and the event is logged to `soar-impasse-{run_id}.json`.
- **First-class status:** Impasse is an architectural event, not an error. The overlay must not swallow impasses silently. Logging to the impasse log is mandatory.
- **Source:** glossary.md (SCOUT), boundaries.md (SCOUT), RJ-008 (SCOUT)
- **Confidence:** 0.92

### Elaboration Cycle
- **Definition:** A single firing of all production rules whose conditions are currently satisfied. Multiple elaboration cycles execute within a single decision cycle until quiescence.
- **Echelon scope:** Single-pass only — one elaboration cycle per `enrich_context` call. Quiescence iteration is not implemented. This is a deliberate performance optimization, not an oversight.
- **Source:** glossary.md (SCOUT), boundaries.md (SCOUT)
- **Confidence:** 0.95

### ProceduralMemoryStore
- **Definition:** The persistent JSON file holding all production rules (hand-coded seed rules + SOAR chunks) for a given run. Analogous to SOAR's procedural memory.
- **File path:** `.specify/squad/soar-procedural-{run_id}.json`
- **Lifecycle:** Created on first `enrich_context` call → grows as SOAR chunks are learned → discarded at run end (no cross-run persistence in v1).
- **Source:** mental-model.md (SCOUT), boundaries.md (SCOUT)
- **Confidence:** 0.93

### Preference
- **Definition:** In full SOAR, categorical structures encoding operator evaluation (acceptable, best, better, worse, reject, require, prohibit). The decision procedure uses preferences to select an operator; conflicting or insufficient preferences trigger an impasse.
- **Echelon simplification:** Replaced by a single numeric `confidence` float in [0.0, 1.0]. Argmax selects the winner; ties go to first-match. The full preference calculus is not implemented (v1 scope, context-enrichment use case).
- **Source:** glossary.md (SCOUT)
- **Confidence:** 0.90

### Substate
- **Definition:** In full SOAR, a new working memory state created automatically in response to an impasse. The substate inherits a link to the superstate and carries a SOAR goal state to resolve the impasse. Substates enable hierarchical task decomposition without explicit stack management.
- **Echelon scope:** Substates are NOT implemented. When an impasse occurs, the overlay fires a DefaultOperator (not a substate) and logs an ImpasseEvent. This is the most significant deviation from canonical SOAR semantics.
- **Source:** glossary.md (SCOUT), boundaries.md (SCOUT)
- **Confidence:** 0.95

### ImpasseEvent
- **Definition:** An event object created by the overlay's DecisionProcedure when no operator can be selected. Carries `type` (`"no-operator"` or `"tie"`), `wme_snapshot`, `run_id`, `cycle`.
- **Persistence:** Appended to `soar-impasse-{run_id}.json` (append-only log).
- **Source:** mental-model.md (SCOUT)
- **Confidence:** 0.90

### SML (Soar Markup Language)
- **Definition:** The communication protocol used by the official SoarGroup C++ implementation to interface with external languages. SML is NOT used in Echelon's SOAR overlay.
- **Negative definition:** The overlay does NOT use SML, SWIG bindings, pysoarlib, or soar-sml. This term is defined here specifically to prevent future developer confusion.
- **Source:** glossary.md (SCOUT), RJ-011 (SCOUT)
- **Confidence:** 0.99

---

## Terms from Reference Architectures (synthesis-only — not in DISCOVER glossary)

### Rete Network
- **Definition:** The efficient pattern-matching algorithm used by the official SOAR C++ kernel to match production rules against WMEs. Rete achieves near-constant time per rule-match incremental update. Without Rete, the overlay uses a naive O(rules × WMEs) linear scan.
- **Echelon scope:** NOT implemented. Linear scan is used. Acceptable for ≤50 rules × ≤50 WMEs (see U-001 for performance concern at scale).
- **Source:** reference-architectures.md (SCOUT)
- **Confidence:** 0.90

### AgentConnector pattern (from pysoarlib)
- **Definition:** The pattern where a Python object manages a SOAR agent's input-link (data in) and output-link (operator proposals out). Structurally equivalent to Echelon's `enrich_context(context_pack) -> enriched_context_pack` interface.
- **Validation:** This equivalence validates the overlay's interface design as architecturally analogous to a SOAR I/O cycle.
- **Source:** reference-architectures.md (SCOUT)
- **Confidence:** 0.85
