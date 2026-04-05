# Assumptions — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — unified and deduplicated from DISCOVER outputs  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources merged**: assumptions.md (SCOUT), boundaries.md (SCOUT), mental-model.md (SCOUT), reference-architectures.md (SCOUT), reasoning-journal.json (SCOUT)  
**Deduplication:** 3 near-duplicate assumptions merged (see notes below). No contradictory assumptions found across sources.

---

## Critical Assumptions
<!-- If wrong, these invalidate significant portions of the design -->

### A-001: ADR-005 uniform interface applies to the SOAR overlay
- **Statement:** The SOAR overlay must expose `enrich_context(context_pack: dict, run_id: str) -> dict` as its primary interface. It may additionally expose `update_soar_memory(outcome: dict, run_id: str) -> None` for post-dispatch chunking, following the goal_stack `update_goal_stack` pattern.
- **Basis:** Confirmed pattern from COMMANDER.md, all five existing overlay implementations, and ADR-005. The interface is a hard contract.
- **Risk if wrong:** Cannot wire into the COMMANDER pre/post-dispatch sequence without changing COMMANDER.md.
- **Validation method:** Read COMMANDER.md pre-dispatch and post-dispatch sequences; confirm overlay slot 6 follows the same pattern as slots 1-5.
- **Status:** VALIDATED (COMMANDER.md and all 5 overlay files confirm the pattern)
- **Sources:** SCOUT assumptions.md (A-001), RJ-004 (SCOUT)

---

### A-002: Python stdlib only — no C extensions, no external SOAR packages
- **Statement:** The SOAR overlay must be implemented using Python 3 standard library only. Explicitly excluded: `scipy`, `numpy`, `sklearn`, `soar-sml`, `pysoarlib`, any C-extension or SOAR-kernel-dependent package.
- **Basis:** ADR-005 OQ-005 resolution in spec 017 research.md. `scripts/requirements.txt` confirms no C-extension packages. soar-sml requires C++ SOAR kernel — incompatible with ADR-003 self-contained constraint.
- **Risk if wrong:** Entire implementation approach changes (could use Rete network, full preference calculus, canonical SOAR chunking).
- **Validation method:** Check `scripts/requirements.txt`; confirm no soar-sml or C-extension entries.
- **Status:** VALIDATED (requirements.txt contains no C-extension packages)
- **Sources:** SCOUT assumptions.md (A-002), SCOUT reference-architectures.md (Divergence Points), RJ-005 (SCOUT)

---

### A-003: context_pack keys are stable enough to serve as WME attribute names
- **Statement:** Top-level context_pack keys (`active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`, `agent_type`, `spec_id`, `run_id`) appear reliably across dispatch calls and can be used as WME attribute names for production rule conditions.
- **Basis:** All five existing overlays inject named keys in a deterministic COMMANDER sequence. SOAR overlay runs last (position 6) and can assume prior enrichments are present.
- **Risk if wrong:** Production rules cannot reliably match; all dispatches degrade to impasse → DefaultOperator. Overlay enrichment value is zero.
- **Validation method:** Instrument overlay to log observed context_pack keys per run; compare across 5+ runs.
- **Status:** UNVALIDATED (no cross-run key-stability test run)
- **Sources:** SCOUT assumptions.md (A-003), RJ-010 (SCOUT)

---

### A-004: 5-10 hand-coded seed rules sufficient to cover common dispatch contexts
- **Statement:** Hand-coded seed rules initialized at module load are sufficient to avoid impasse in the majority of dispatch calls. An impasse rate above 50% in the first dispatch cycle indicates the seed rule set is insufficient.
- **Basis:** Five existing CA overlays each inject one well-defined key. Context_pack structure is predictable enough that rules covering key combinations should achieve majority coverage. Analogy: ACT-R overlay seeds with 4 buffer classifications.
- **Risk if wrong:** Overlay delivers `{"operator_applied": "default-no-match"}` on most dispatches. No enrichment value.
- **Validation method:** Instrument impasse log. After 10 test dispatches, compute impasse rate. If > 50%, expand seed rule set.
- **Status:** UNVALIDATED
- **Sources:** SCOUT assumptions.md (A-004)

---

## Standard Assumptions

### A-005: COMMANDER dispatches agents sequentially — no concurrent writes to ProceduralMemoryStore
- **Statement:** COMMANDER dispatches agents serially within a run. Concurrent writes to `soar-procedural-{run_id}.json` do not occur.
- **Basis:** COMMANDER.md shows serial pre/post-dispatch sequences. No parallel dispatch mechanism exists. Episodic Memory overlay uses the same single-writer, append-only pattern.
- **Risk if wrong:** If COMMANDER adds parallel dispatch in future, concurrent writes could corrupt the rule store. File locking would be required.
- **Validation method:** Confirm in COMMANDER.md that dispatch is always sequential within a run.
- **Status:** VALIDATED (COMMANDER.md shows serial sequences; no parallel dispatch mechanism)
- **Sources:** SCOUT assumptions.md (A-005)

---

### A-006: WME value truncation at 200 characters does not lose semantically critical information
- **Statement:** Truncating WME values to 200 characters is sufficient. Production rule conditions match on key presence and partial value content, not on full value text.
- **Basis:** ACT-R overlay truncates at 500 chars. SOAR overlay's WME values are used for structural pattern matching (key presence, type), not deep content analysis.
- **Risk if wrong:** Production rules needing to match content beyond 200 chars will fail. Impasse rate increases.
- **Validation method:** Review seed rule conditions for any value-content matching requirements.
- **Status:** UNVALIDATED
- **Sources:** SCOUT assumptions.md (A-006)

---

### A-007: Confidence scalar is a sufficient simplification of SOAR's preference calculus
- **Statement:** Replacing SOAR's 8 preference types with a single `confidence` float and argmax selection is adequate for context enrichment. Full preference calculus is not needed for single-step enrichment with 5-10 rules.
- **Basis:** Echelon overlays are enrichment tools, not multi-step problem-solving agents. Argmax on confidence achieves the same practical outcome for the use case.
- **Risk if wrong:** Tie cases are handled differently from canonical SOAR (first-match vs. impasse). Tie frequency above 10% of dispatches would warrant adding a secondary preference signal.
- **Validation method:** Monitor tie frequency in production. If > 10%, reconsider.
- **Status:** UNVALIDATED
- **Sources:** SCOUT assumptions.md (A-007)
- **Cross-reference:** This assumption implies a behavioral deviation from canonical SOAR — flagged in contradictions-and-gaps.md §Tie-Behavior-Deviation.

---

### A-008: Cross-run ProceduralMemoryStore persistence is out of scope for v1
- **Statement:** SOAR chunks do not persist across runs. Each run starts fresh from hand-coded seed rules.
- **Basis:** Consistent with spec 017 Episodic Memory overlay ("no cross-run persistence"). Cross-run persistence requires canonical rule identifiers and conflict resolution — significant additional complexity.
- **Risk if wrong:** If cross-run learning is expected, the overlay delivers no cumulative improvement across spec runs.
- **Validation method:** Confirm with user whether cross-run chunking persistence is a requirement for spec 018.
- **Status:** UNVALIDATED (user intent not confirmed on this dimension)
- **Sources:** SCOUT assumptions.md (A-008)

---

## Low-Risk Assumptions

### A-009: The SOAR overlay runs at position 6 in the COMMANDER pre-dispatch sequence
- **Statement:** The SOAR overlay is appended after the five existing overlays, running last so it can read all prior enrichments as WMEs.
- **Basis:** COMMANDER.md lists overlays 1-5 explicitly. Position 6 is the natural extension.
- **Risk if wrong:** Minimal — but if another overlay is inserted at position 5 post-spec-017, the sequence may differ.
- **Validation method:** Read current COMMANDER.md to confirm position 6 is available.
- **Status:** UNVALIDATED (requires COMMANDER.md review)
- **Sources:** SCOUT assumptions.md (A-009)

---

### A-010: The `soar_state` key does not conflict with any existing overlay output key
- **Statement:** `context_pack["soar_state"]` does not conflict with the five existing overlay keys (`active_goal`, `actr_buffers`, `lida_broadcast`, `gwt_workspace`, `episodic_prior_artifact`).
- **Basis:** COMMANDER.md lists the five injected keys explicitly. `soar_state` does not appear.
- **Risk if wrong:** Negligible — a key collision would overwrite prior value and be immediately visible in testing.
- **Validation method:** Grep all existing overlay files for `soar_state`.
- **Status:** VALIDATED (grep confirms no existing overlay uses `soar_state`)
- **Sources:** SCOUT assumptions.md (A-010)

---

## Synthesizer-Added Assumptions

### A-011: The 200-char WME value truncation applies after JSON serialization of nested dicts
- **Statement:** When a context_pack value is a nested dict (e.g., `actr_buffers`), it is first JSON-serialized to a string, then truncated at 200 characters. This means nested dicts may be truncated mid-JSON, producing syntactically invalid JSON strings in WME values — which is acceptable since WME values are matched as strings, not parsed as JSON.
- **Basis:** Inferred from WME Extraction Layer definition in SCOUT boundaries.md: "Nested dicts are serialized to JSON string before coercion." The order (serialize → truncate) is the only sensible interpretation.
- **Risk if wrong:** If truncation happens before serialization (impossible given the description), the behavior is undefined.
- **Status:** INFERRED (not explicitly stated in source; derived by SYNTHESIZER — flag for WHY1 validation)
- **Sources:** SCOUT boundaries.md (WME Extraction Layer)

### A-012: The SOAR overlay's position-6 enrichment adds value beyond what the five existing overlays provide
- **Statement:** The SOAR overlay's structural pattern-matching enrichment (which SOAR operator matches the combined WME state) provides unique signal not already present in the five prior overlay outputs. If this assumption is false, the overlay is redundant.
- **Basis:** Not validated in DISCOVER sources. This is an implicit rationale assumption — the spec was requested, implying the user believes value exists.
- **Risk if wrong:** The overlay adds token cost (U-CA-004 token budget concern) with no enrichment benefit.
- **Status:** UNVALIDATED — this is the fundamental value proposition assumption of the entire spec.
- **Sources:** SYNTHESIZER-derived from U-CA-004 concern in SCOUT unknowns.md
