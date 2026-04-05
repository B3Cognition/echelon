# SOAR Cognitive Architecture Overlay — Specification

> The SOAR Overlay is the sixth cognitive architecture overlay in the Echelon cognitive agent squad. It adds a Match-Select-Apply decision cycle to the pre-dispatch context enrichment pipeline. Before each agent dispatch, the overlay extracts the current context state into Working Memory Elements (WMEs), matches those WMEs against a set of production rules stored in a run-scoped procedural memory store, selects the highest-confidence matching rule as the active SOAR operator, and merges that operator's enrichment payload into the context pack. When no rule matches, the overlay logs an impasse event and applies a default operator. After each successful dispatch, the overlay records a SOAR-inspired chunk — a new production rule derived from the successful episode — so that subsequent dispatches within the same run benefit from accumulated procedural experience. The overlay follows the ADR-005 uniform interface (`enrich_context` / `update_soar_memory`) and uses no external dependencies beyond the standard library.

---

## User Scenarios & Testing

### Scenario 1: Context Enrichment via Production Rule Match

**As a** dispatched Echelon agent,
**I want to** receive a context pack that includes a SOAR operator selection derived from the current working memory state,
**So that** my reasoning is informed by a structured assessment of which procedural rule best fits my current task context.

#### Acceptance Criteria

- **AC-1.1:** Given a context pack containing at least one Tier 1 WME (`active_goal`), when `enrich_context` is called, then the returned context pack contains a `soar_state` key whose serialized length does not exceed 200 characters.
- **AC-1.2:** Given at least one production rule whose conditions are fully satisfied by the current WMEs, when `enrich_context` is called, then `soar_state["operator_applied"]` contains the name of the selected SOAR operator and `soar_state["impasse"]` is `false`.
- **AC-1.3:** Given two production rules that both fully match the current WMEs and share the same confidence score, when `enrich_context` is called, then the rule that appears first in the ProceduralMemoryStore is selected and no ImpasseEvent is created.
- **AC-1.4:** Given `enrich_context` is called with a valid context pack and run_id, when the call completes, then it returns within 100 milliseconds without invoking any subprocess or external process.
- **AC-1.5:** Given a context pack containing all five prior overlay output keys (`active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`), when `enrich_context` is called, then the returned context pack retains all five prior overlay keys unchanged.
- **AC-1.6:** Given a context_pack containing keys `active_goal`, `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`, `lida_broadcast`, and `extra_key`, when `enrich_context` is called, then the working memory WME set contains exactly 5 WMEs (one per Tier 1 + Tier 2 key plus `lida_broadcast`), does NOT include a WME for `extra_key`, and the WME for each key has `attr` equal to the key name and `value` equal to the string-coerced key value (truncated to 200 chars).
- **AC-1.7:** Given a production rule whose operator enrichment payload, when combined with mandatory fields, would produce a `soar_state` where `len(json.dumps(soar_state)) > 200`, when `enrich_context` returns, then the returned `soar_state` contains only the four mandatory keys (`operator_applied`, `impasse`, `cycle`, `wme_count`), `operator_applied` is truncated to a maximum of 64 characters, and `len(json.dumps(soar_state)) <= 200`.

---

### Scenario 2: Impasse Handling — No Matching Production Rule

**As a** COMMANDER orchestrating a dispatch,
**I want to** receive a valid enriched context pack even when no production rule matches the current WME state,
**So that** agent dispatch is never blocked by an absence of matching SOAR rules.

#### Acceptance Criteria

- **AC-2.1:** Given a context pack whose WME state matches no production rule in the ProceduralMemoryStore, when `enrich_context` is called, then `soar_state["operator_applied"]` equals `"default-no-match"` and `soar_state["impasse"]` is `true`.
- **AC-2.2:** Given an impasse occurs, when `enrich_context` completes, then an ImpasseEvent record is appended to `soar-impasse-{run_id}.json` containing at minimum: `type`, `run_id`, `cycle`, and a `wme_snapshot` of the WME state at impasse time.
- **AC-2.3:** Given an impasse occurs and `soar-impasse-{run_id}.json` does not yet exist, when `enrich_context` completes, then the file is created and the ImpasseEvent is written as the first entry.
- **AC-2.4:** Given any impasse condition, when `enrich_context` is called, then the returned context pack is a valid dict (not null, not an exception propagated to the caller) so that COMMANDER can proceed with dispatch.

---

### Scenario 3: Post-Dispatch Procedural Learning (SOAR-Inspired Chunking)

**As a** COMMANDER that has received a successful dispatch outcome,
**I want to** record a new production rule derived from the successful episode,
**So that** subsequent dispatches within the same run benefit from accumulated procedural knowledge without re-deriving context from scratch.

#### Acceptance Criteria

- **AC-3.1:** Given a dispatch outcome where `outcome['status']` is not in `['BLOCKED', 'ESCALATED']`, when `update_soar_memory(outcome, run_id)` is called, then a new ChunkRecord is appended to `soar-procedural-{run_id}.json` with `learned` set to `true` and `rule_id` prefixed with `"chunk-"`.
- **AC-3.2:** Given a dispatch outcome where `outcome['status']` is in `['BLOCKED', 'ESCALATED']`, when `update_soar_memory` is called, then no new ChunkRecord is written and the ProceduralMemoryStore is unchanged.
- **AC-3.3:** Given `update_soar_memory` is called and the Episodic Memory index file (`episodic-index-{run_id}.json`) is absent, when chunking would otherwise run, then chunking is skipped silently and no error is raised.
- **AC-3.4:** Given chunking is disabled via configuration (`ca_overlays.soar.chunking_enabled: false`), when `update_soar_memory` is called regardless of outcome, then no ChunkRecord is written.
- **AC-3.5:** Given a ChunkRecord is successfully written, when `enrich_context` is called for a subsequent dispatch within the same run, then the newly written ChunkRecord is available for matching.

---

### Scenario 4: ProceduralMemoryStore Initialization with Seed Rules

**As a** COMMANDER starting a new run,
**I want to** know that the SOAR overlay begins each run with a baseline set of production rules covering common dispatch contexts,
**So that** early dispatches are not dominated by impasses while the overlay accumulates learned rules.

#### Acceptance Criteria

- **AC-4.1:** Given a new run_id for which no `soar-procedural-{run_id}.json` exists, when `enrich_context` is called for the first time, then the file is created containing exactly the hand-coded seed rules and no ChunkRecords.
- **AC-4.2:** Given the ProceduralMemoryStore is initialized, when inspected, then it contains at least 5 seed rules, each covering at least one Tier 1 or Tier 2 WME attribute.
- **AC-4.3:** Given an existing `soar-procedural-{run_id}.json` from a prior call within the same run, when `enrich_context` is called again, then the existing file is loaded (not overwritten) and seed rules remain intact.

---

### Scenario 5: ACT-R Buffer Key De-duplication Fix (ISS-004)

**As a** COMMANDER consuming the enriched context pack,
**I want to** receive a context pack where `actr_buffer.py`'s output keys are present exactly once,
**So that** downstream agents do not receive duplicated or shadowed ACT-R buffer data.

#### Acceptance Criteria

- **AC-5.1:** Given the ACT-R overlay (`actr_buffer.py`) has injected `actr_buffers` into context_pack, when any overlay subsequently processes the context pack, then `actr_buffers` appears exactly once as a top-level key in the returned context pack; the returned dict has no top-level key that was present in the input context_pack alongside `actr_buffers`.
- **AC-5.2:** Given the fix is applied to `actr_buffer.py`, when `enrich_context` is called by the ACT-R overlay, then the returned context pack does NOT contain as top-level keys any of the keys that were present in the input context_pack (`role`, `task`, `spec_text`, `prior_artifacts`, `constitution`, `active_goal`, and any other key present at call time); it contains only `actr_buffers` as the top-level key representing overlay output.
- **AC-5.3:** Given the de-duplication fix is in place, when the six-overlay stack runs end-to-end, then the total token overhead of all six overlays combined does not exceed 25% net-new tokens relative to the pre-overlay context pack size.

---

### Scenario 6: Overlay Failure Resilience

**As a** COMMANDER orchestrating a dispatch,
**I want to** proceed with agent dispatch even if the SOAR overlay raises an unhandled exception,
**So that** a SOAR overlay defect never blocks agent execution.

#### Acceptance Criteria

- **AC-6.1:** Given `enrich_context` raises any unhandled exception, when COMMANDER's dispatch sequence catches it, then dispatch proceeds with the unenriched context pack (without `soar_state`) and the exception is logged.
- **AC-6.2:** Given `update_soar_memory` raises any unhandled exception, when COMMANDER's post-dispatch sequence catches it, then the dispatch outcome record is preserved and no run state is corrupted.

---

## Functional Requirements

### SOAR Overlay Core (Match-Select-Apply Cycle)

- **FR-SOAR-001**: The overlay's `enrich_context` function runs a single Match-Select-Apply cycle against the current context pack's WMEs each time it is called. *(User Story: Scenario 1 | Priority: MVP)*
- **FR-SOAR-002**: Production rules are stored in a run-scoped JSON file at `.specify/squad/soar-procedural-{run_id}.json` (the ProceduralMemoryStore). *(User Story: Scenario 1, 4 | Priority: MVP)*
- **FR-SOAR-003**: Working memory for each call is constructed as the subset of current context pack keys belonging to WME Stability Tier 1 (`active_goal`) and Tier 2 (`actr_buffers`, `gwt_workspace`, `episodic_prior_artifact`); Tier 3 keys (`lida_broadcast`) are treated as opportunistic and may be absent without causing an impasse. When `lida_broadcast` IS present in context_pack, it IS included in the working memory WME set. *(User Story: Scenario 1 | Priority: MVP)*
- **FR-SOAR-004**: The selected SOAR operator is the production rule with the highest condition-match confidence score among all fully matching rules; when no rule fully matches, the overlay proceeds to impasse handling (FR-SOAR-005). *(User Story: Scenario 1, 2 | Priority: MVP)*
- **FR-SOAR-005**: When no production rule's conditions match the current WME state, the overlay sets `soar_state["impasse"]` to `true`, sets `soar_state["operator_applied"]` to `"default-no-match"`, and logs an ImpasseEvent to `soar-impasse-{run_id}.json`. *(User Story: Scenario 2 | Priority: MVP)*
- **FR-SOAR-006**: When two or more production rules match with equal confidence scores, the overlay selects the rule that appears first in ProceduralMemoryStore load order; no ImpasseEvent is created for this tie condition. This is an intentional deviation from canonical SOAR behavior, which would fire a tie impasse. *(User Story: Scenario 1 | Priority: MVP)*
- **FR-SOAR-007**: SOAR-inspired chunking (procedural compilation) is controlled by a configuration flag (`ca_overlays.soar.chunking_enabled`). The default value of this flag in v1 is `false`. The chunking code must be fully implemented and functional when the flag is set to `true`. If the `ca_overlays.soar` section or the `chunking_enabled` key is absent from `squad-config.yml`, the overlay defaults to `chunking_enabled: false` (chunking disabled). The key is optional. No warning or error is raised when the key is absent. *(User Story: Scenario 3 | Priority: MVP)*
- **FR-SOAR-008**: The `soar_state` payload injected into context_pack must satisfy `len(json.dumps(soar_state)) <= 200` at all times; if the payload would exceed this limit, it is truncated to the mandatory fields only (`operator_applied`, `impasse`, `cycle`, `wme_count`). The mandatory-fields-only payload is: `{"operator_applied": <name truncated to 64 chars>, "impasse": <bool>, "cycle": <int>, "wme_count": <int>}`. The size check is performed after constructing the full soar_state dict, before returning. *(User Story: Scenario 1 | Priority: MVP)*
- **FR-SOAR-009**: On the first call to `enrich_context` for a given run_id, the overlay initializes the ProceduralMemoryStore with at least 5 hand-coded seed rules hard-coded in the overlay module (`soar.py`) by the developer covering the common WME combinations for Tier 1 and Tier 2 attributes. *(User Story: Scenario 4 | Priority: MVP)*
- **FR-SOAR-010**: The `update_soar_memory(outcome, run_id)` function is called by COMMANDER after each agent dispatch; it evaluates the outcome against the configured success criterion and, when the criterion is met and chunking is enabled, appends a new ChunkRecord to the ProceduralMemoryStore. The success criterion is: `outcome['status'] not in ['BLOCKED', 'ESCALATED']` *(User Story: Scenario 3 | Priority: MVP)*

---

### ACT-R Buffer Key De-duplication Fix (ISS-004 / FR-CAO-002 Violation)

- **FR-SOAR-011**: The `actr_buffer.py` overlay's `enrich_context` function must return a context pack in which the original pre-overlay keys that are subsumed by the `actr_buffers` key are removed before returning; the returned context pack must not contain both the original keys and the `actr_buffers` key simultaneously. Specifically, the returned context pack contains exactly one key added by this overlay (`actr_buffers`) plus any keys that were NOT present in the input context_pack at call time. All keys that were present in the input context_pack at call time are removed from the returned dict. *(User Story: Scenario 5 | Priority: MVP)*

---

### COMMANDER Integration

- **FR-SOAR-012**: `COMMANDER.md` must be amended to document `soar.enrich_context(context_pack, run_id)` as position 6 in the pre-dispatch enrichment sequence, called after the Episodic Memory overlay (position 5) and before agent dispatch. *(User Story: Scenario 1 | Priority: MVP)*
- **FR-SOAR-013**: `COMMANDER.md` must be amended to document `soar.update_soar_memory(outcome, run_id)` as a mandatory post-dispatch call, executed after the agent's artifact is received and before the next dispatch cycle. *(User Story: Scenario 3 | Priority: MVP)*

---

## Non-Functional Requirements

- **NFR-SOAR-001**: The overlay uses only standard library modules; no external packages, C extensions, or SOAR-specific packages may be imported. Measurable target: Zero non-stdlib imports; verified by static analysis of the module's import statements. *(Category: Dependencies)*
- **NFR-SOAR-002**: The `soar-procedural-{run_id}.json` and `soar-impasse-{run_id}.json` files must be excluded from version control via the `.specify/squad/` gitignore exclusion. Measurable target: Confirmed by `git check-ignore -v .specify/squad/soar-procedural-*.json` returning a match. *(Category: Security / Confidentiality)*
- **NFR-SOAR-003**: `enrich_context` must complete its full Match-Select-Apply cycle without invoking any subprocess, external process, or network call. Measurable target: Measured wall time < 100ms on a rule store of ≤ 50 rules and a WME set of ≤ 50 elements. *(Category: Performance)*
- **NFR-SOAR-004**: An unhandled exception in `enrich_context` or `update_soar_memory` must not propagate to the caller in a way that blocks dispatch; the overlay must be designed so that COMMANDER can wrap calls in exception handling. Measurable target: Zero blocked dispatches attributable to SOAR overlay exceptions in test runs. *(Category: Reliability)*
- **NFR-SOAR-005**: The combined six-overlay context pack must not exceed 25% net-new token overhead relative to the pre-overlay baseline, counted across all overlay enrichment keys. Measurable target: Measured token delta of six-overlay stack ≤ 125% of pre-overlay context pack size. *(Category: Token Budget)*
- **NFR-SOAR-006**: Every impasse event must be logged with sufficient detail for post-run diagnosis: at minimum `type`, `run_id`, `cycle`, and `wme_snapshot`. Measurable target: `soar-impasse-{run_id}.json` entries each contain all four mandatory fields; verified by log schema check. *(Category: Observability)*

---

## Key Entities

### ProductionRule
- **Attributes:** `rule_id` (unique, prefixed `"seed-"` or `"chunk-"`), `conditions` (list of WME condition dicts, each `{attr: str, value?: str}`; a rule is satisfied when all conditions match the WME set by presence + optional substring sentinel), `actions` (enrichment payload), `confidence` (float 0.0–1.0), `learned` (boolean)
- **Relationships:** Many-to-many match against WorkingMemory; one-to-one proposal of a SOAR operator; produced by ChunkingEngine (for learned rules) or initialized from seed set (for hand-coded rules)
- **Lifecycle:** Created once → stored in ProceduralMemoryStore → matched on every `enrich_context` call → never modified after creation; new SOAR chunks do not replace existing rules
- **Constraints:** `rule_id` must be unique within a ProceduralMemoryStore; `confidence` must be in [0.0, 1.0]; `learned` is immutable after creation

### WorkingMemory
- **Attributes:** `wmes` (list of `{id, attr, value}` triples), `state_id` (string, `"state-{run_id}"`), `cycle_count` (integer)
- **Relationships:** Populated from context_pack (one-to-one per call); consumed by production rule match phase; discarded after each call
- **Lifecycle:** Created fresh on each `enrich_context` call; not persisted between calls
- **Constraints:** Each top-level context_pack key produces exactly one WME; WME values are string-coerced and truncated at 200 characters; nested dict values are serialized before coercion

### SOAR Operator
- **Attributes:** `name` (string), `payload` (dict), `source_rule_id` (string), `confidence` (float)
- **Relationships:** Proposed by exactly one ProductionRule; selected by DecisionProcedure; applied to context_pack
- **Lifecycle:** Proposed during match phase; selected (or rejected) during select phase; applied during apply phase; discarded after application
- **Constraints:** Exactly one operator is applied per `enrich_context` call (either the winning rule's operator or the DefaultOperator); `payload` serialized length must contribute to keeping `soar_state` ≤ 200 characters

### ImpasseEvent
- **Attributes:** `type` (one of `"no-operator"`), `wme_snapshot` (dict), `run_id` (string), `cycle` (integer)
- **Relationships:** Created by DecisionProcedure when no rule matches; appended to `soar-impasse-{run_id}.json`; triggers DefaultOperator application
- **Lifecycle:** Created at impasse detection; appended to impasse log; not referenced again within the same call
- **Constraints:** `type` is `"no-operator"` for the no-match case; tie case resolves to first-match and does NOT produce an ImpasseEvent (see FR-SOAR-006)

### ProceduralMemoryStore
- **Attributes:** `rules` (ordered list of ProductionRules), `run_id` (string), `last_updated` (ISO 8601 timestamp)
- **Relationships:** Loaded by `enrich_context`; appended to by `update_soar_memory` (ChunkRecords); read-accessible for diagnostic purposes
- **Lifecycle:** Created on first `enrich_context` call for a run_id; grows within the run as ChunkRecords are added; not persisted across runs
- **Constraints:** Single-writer (only the SOAR overlay writes to this file); load order is preserved for tie-breaking; file is gitignored

### ChunkRecord
- **Attributes:** `rule_id` (prefixed `"chunk-"`), `conditions` (inferred from WME snapshot per configured generalization strategy), `actions` (the enrichment payload from the successful dispatch), `confidence` (initial value per configuration), `learned` (always `true`), `episode_id` (`"{run_id}:{cycle}"`)
- **Relationships:** Produced by ChunkingEngine after a successful dispatch; appended to ProceduralMemoryStore; participates in subsequent match cycles
- **Lifecycle:** Created post-dispatch by `update_soar_memory`; available for matching in subsequent calls within the same run
- **Constraints:** `learned` is always `true`; `episode_id` is unique within a run; `confidence` must be in [0.0, 1.0]

---

## Success Criteria

### MVP Success
- [ ] `enrich_context` returns a context pack with a valid `soar_state` key on every call, regardless of whether a production rule matches or an impasse occurs
- [ ] At least 5 seed rules are seeded on first call and at least one matches per FR-SOAR-004's confidence-based selection criteria (impasse rate < 100%) across a 10-dispatch test run
- [ ] ImpasseEvents are logged to `soar-impasse-{run_id}.json` whenever the no-operator case occurs; no impasse is silently swallowed
- [ ] `enrich_context` returns in under 100ms for a 50-rule ProceduralMemoryStore across 10 consecutive test calls
- [ ] `actr_buffer.py` de-duplication fix is verified: the returned context pack contains `actr_buffers` exactly once and no duplicate original keys
- [ ] The SOAR overlay does not block any dispatch in the test run; all COMMANDER exception-handling paths work correctly
- [ ] `soar_state` serialized length ≤ 200 characters in all test dispatches
- [ ] `soar-procedural-{run_id}.json` and `soar-impasse-{run_id}.json` are gitignored and absent from `git status` after a test run

### Full Product Success
- [ ] SOAR-inspired chunking (when enabled) produces at least one ChunkRecord per 5-dispatch window when the success criterion is met
- [ ] Chunked rules demonstrably reduce impasse frequency within a single run: impasse rate in dispatches 11–20 is lower than in dispatches 1–10 when chunking is enabled
- [ ] Six-overlay stack cumulative token overhead ≤ 25% of pre-overlay baseline, verified across 5 spec runs
- [ ] COMMANDER.md is amended and documents position-6 `enrich_context` and post-dispatch `update_soar_memory` hook-points
- [ ] No external dependency introduced: `pip install` of the overlay raises no new packages beyond the pre-existing requirements

---

## Scope

### In Scope (MVP)
- Match-Select-Apply single-pass decision cycle (`enrich_context`)
- WME extraction from context pack (Tier 1, Tier 2, Tier 3 stability classification)
- Production rule matching: condition evaluation against WME set
- DecisionProcedure: argmax-confidence operator selection, first-match tie resolution
- DefaultOperator: applied on no-match impasse
- ImpasseEvent: created and logged on no-match impasse
- ProceduralMemoryStore: initialized with seed rules, persisted per run_id
- Seed rules: 5 minimum hand-coded rules covering Tier 1 and Tier 2 WME attributes
- `update_soar_memory`: post-dispatch call; ChunkRecord creation and ProceduralMemoryStore append
- Chunking implementation (code complete); disabled by default (`chunking_enabled: false`)
- `soar_state` payload hard cap at 200 characters serialized
- `actr_buffer.py` ISS-004 de-duplication fix
- COMMANDER.md amendment: position-6 pre-dispatch hook, post-dispatch `update_soar_memory` hook
- Runtime artifact gitignore: `soar-procedural-{run_id}.json`, `soar-impasse-{run_id}.json`
- stdlib-only implementation (no external dependencies)

### In Scope (Post-MVP)
- Chunking enabled by default after seed rule set is validated across 10+ spec runs
- Confidence increment formula for ChunkRecords (fixed increment, multiplicative, or Bayesian)
- One-level WME flattening for nested dict values (`actr_buffers.goal`, etc.)
- Endocrine system wiring for impasse events (cortisol signal) and successful chunking (dopamine signal)
- Cross-run ProceduralMemoryStore persistence (requires canonical rule identifiers and conflict resolution)
- `max_rules` cap and pruning policy for ProceduralMemoryStore

### Explicitly Out of Scope
- Official SOAR C++ kernel, SML, soar-sml, pysoarlib — violates ADR-005 (stdlib-only) and ADR-003 (self-contained); non-negotiable exclusion
- Rete network pattern matching — excluded by stdlib-only constraint; linear scan is sufficient for ≤ 50 rules
- Multi-cycle elaboration quiescence — single-pass is sufficient for context enrichment; multi-cycle adds latency without proportionate benefit
- Full SOAR preference calculus (8 preference types) — replaced by scalar confidence; adequate for the enrichment use case
- Substate creation on impasse — the most significant deviation from canonical SOAR; excluded by scope (enrichment tool, not general problem-solver)
- COMMANDER state.json reads or writes — prohibited by FR-CAO-006 (read-only on COMMANDER state)
- AQS measurement experiment (U-CA-004 controlled test for 6-overlay stack) — noted as a recommended follow-on action, not a blocking requirement

---

## Open Questions

| ID | Question | Impact | Source |
|----|----------|--------|--------|
| OQ-001 [RESOLVED] | WME condition schema is **presence-only + value-sentinel**: each condition is a dict `{"attr": "<context_pack_key_name>", "value": "<optional_sentinel_string>"}`. Match criteria: (1) the WME set contains a WME with `attr` equal to the condition's `attr` value; AND (2) if `value` is specified, the WME's string-coerced value contains the sentinel string as a substring. A production rule's conditions are "fully satisfied" if ALL conditions in its `conditions` list match the current WME set. Tier 3 WMEs (`lida_broadcast`): included in working memory WHEN PRESENT. A condition on `lida_broadcast` is unsatisfied (not matched) when `lida_broadcast` is absent from context_pack. No impasse is triggered merely because a Tier 3 WME is absent. | FR-SOAR-001, FR-SOAR-004, FR-SOAR-009; affects what acceptance criteria are testable for rule matching | unknowns.md U-001, U-002 |
| OQ-002 | What keys does COMMANDER inject into context_pack before the overlay chain runs, per agent type (SCOUT, WHAT, GUARDIAN, BUILD)? Are agent-specific keys stable within an agent type? | FR-SOAR-003, FR-SOAR-009; affects which WME attributes seed rules can reliably target | unknowns.md U-NEW-001 |
| OQ-003 | How frequently does COMMANDER trigger a LIDA broadcast per spec run? If < 20% of dispatches, should `lida_broadcast`-conditional seed rules be excluded from the initial seed set? | FR-SOAR-009; affects seed rule set composition | unknowns.md U-NEW-002 |
| OQ-004 [RESOLVED] | The success criterion for triggering SOAR-inspired chunking is: `outcome['status'] not in ['BLOCKED', 'ESCALATED']`. Rationale: deterministic, no AQS instrumentation needed, conservative learning approach for v1. | FR-SOAR-010, AC-3.1; the criterion definition directly determines what gets learned | unknowns.md U-006 |
| OQ-005 | What is the generalization strategy for ChunkRecord condition construction? (All WMEs at dispatch; triggering rule's conditions only; minimal set of active_goal + agent_type) | FR-SOAR-010, AC-3.1; determines whether chunks are useful or over-/under-fitted | unknowns.md U-003 |
| OQ-006 | Should impasse events surface to the dispatched agent via `soar_state["impasse"] = true`, or remain internal to the overlay (agent never sees the impasse flag)? | FR-SOAR-005; affects whether dispatched agents can adapt behavior based on SOAR impasse state | unknowns.md U-004 |
| OQ-007 | What is the EpisodicIndex JSON schema (from spec 017 Episodic Memory overlay) that ChunkingEngine must read? | FR-SOAR-010, AC-3.3; ChunkingEngine cannot be implemented without this schema | contradictions-and-gaps.md G-005 |

---

## Assumptions in Effect

| ID | Assumption | Status | Requirements Affected |
|----|-----------|--------|----------------------|
| A-001 | The ADR-005 uniform interface (`enrich_context(context_pack, run_id) -> dict`) applies to the SOAR overlay exactly as to overlays 1–5 | VALIDATED | FR-SOAR-001, FR-SOAR-012 |
| A-002 | Python standard library only — no C extensions, no soar-sml, no pysoarlib | VALIDATED | NFR-SOAR-001, all FR-SOAR |
| A-003 | Context pack keys from prior overlays (`active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`) appear reliably across dispatch calls | UNVALIDATED | FR-SOAR-003, FR-SOAR-009 |
| A-004 | 5–10 hand-coded seed rules are sufficient to avoid impasse in the majority of dispatches within a run | UNVALIDATED | FR-SOAR-009 |
| A-005 | COMMANDER dispatches agents sequentially within a run; no concurrent writes to ProceduralMemoryStore | VALIDATED | FR-SOAR-002, FR-SOAR-010 |
| A-006 | Truncating WME values at 200 characters does not lose semantically critical information for production rule matching | UNVALIDATED | FR-SOAR-003 |
| A-007 | Scalar confidence (argmax) is a sufficient simplification of SOAR's preference calculus for context enrichment | UNVALIDATED | FR-SOAR-004, FR-SOAR-006 |
| A-008 | Cross-run ProceduralMemoryStore persistence is out of scope for v1 | UNVALIDATED (intent-consistent) | FR-SOAR-002 |
| A-009 | Position 6 in the COMMANDER pre-dispatch sequence is available for the SOAR overlay | UNVALIDATED | FR-SOAR-012 |
| A-010 | The `soar_state` key does not conflict with any existing overlay output key | VALIDATED | FR-SOAR-001, FR-SOAR-008 |
| A-011 | Nested dict WME values are JSON-serialized before truncation at 200 characters | INFERRED (flag for WHY1) | FR-SOAR-003 |
| A-012 | The SOAR overlay's structural pattern-matching enrichment provides unique signal not already present in the five prior overlay outputs | UNVALIDATED | All FR-SOAR (fundamental value proposition) |

---

## Glossary Additions

The following terms are introduced or qualified by this specification and were not present in the DISCOVER glossary in this form:

| Term | Definition |
|------|------------|
| WME Stability Tier | A classification of context pack keys by reliability of presence. Tier 1 (safe anchor): `active_goal` — always present. Tier 2 (guard required): `actr_buffers`, `gwt_workspace`, `episodic_prior_artifact` — present when their producing overlay succeeds. Tier 3 (opportunistic): `lida_broadcast` — present only when COMMANDER triggers a LIDA broadcast. |
| DefaultOperator | The fallback operator applied when no production rule matches the current WME state. Injects `soar_state["operator_applied"] = "default-no-match"` and `soar_state["impasse"] = true`. Not a rule in the ProceduralMemoryStore — it is a hard-coded fallback. |
| ChunkRecord | A learned production rule created by SOAR-inspired procedural compilation after a successful dispatch. Distinguished from seed rules by `learned: true` and `rule_id` prefixed `"chunk-"`. |
| ImpasseEvent | An event record created when no production rule matches the current WME state (no-operator impasse). Logged to `soar-impasse-{run_id}.json`. Tie conditions are resolved by first-match and do NOT create ImpasseEvents. |
| ProceduralMemoryStore | The run-scoped JSON file (`soar-procedural-{run_id}.json`) that persists production rules (seed rules + ChunkRecords) for the duration of a run. |
| ISS-004 | The identified structural violation in `actr_buffer.py` where the returned context pack duplicates original keys alongside the merged `actr_buffers` key. Resolved by FR-SOAR-011. |
