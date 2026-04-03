# System Boundaries — Spec 018 (SOAR Cognitive Architecture Overlay)

**Produced by**: SYNTHESIZER (FUSE) — unified from DISCOVER outputs  
**Date**: 2026-04-03 | **Spec**: 018-soar-overlay  
**Sources merged**: boundaries.md (SCOUT), mental-model.md (SCOUT), assumptions.md (SCOUT), reference-architectures.md (SCOUT)

---

## Internal Boundaries

### SOAR Overlay Module (`scripts/ca/soar_overlay.py`)
- **Classification:** Internal — Python module in the same `scripts/ca/` package as all other CA overlays
- **Primary interface:** `enrich_context(context_pack: dict, run_id: str) -> dict` — ADR-005 uniform interface, position 6 in COMMANDER's pre-dispatch sequence
- **Secondary interface:** `update_soar_memory(outcome: dict, run_id: str) -> None` — called post-dispatch by COMMANDER for SOAR-inspired chunking
- **Communication method:** Direct Python import (same process). Confirmed by: SCOUT boundaries.md; consistent with all five existing overlays.
- **Data written (complete enumeration):**
  - `context_pack["soar_state"]` — the overlay's enrichment output key
  - `.specify/squad/soar-procedural-{run_id}.json` — ProceduralMemoryStore (SOAR chunks + seed rules)
  - `.specify/squad/soar-impasse-{run_id}.json` — ImpasseEvent log (append-only)
- **Data NOT written (FR-CAO-006 compliance):**
  - `state.json` — COMMANDER-owned; never touched
  - `goal-stack-{run_id}.json` — Goal Stack overlay-owned; read as WME input only
  - `gwt-workspace-{run_id}.json` — GWT overlay-owned; read as WME input only
  - `episodic-index-{run_id}.json` — Episodic Memory overlay-owned; read by ChunkingEngine only
  - Any other COMMANDER-managed file
- **Out-of-scope (hard boundaries):**
  - Full SOAR interpreter (no Rete network, no SML, no C extension)
  - Multi-cycle elaboration quiescence
  - Full SOAR preference calculus
  - Cross-run ProceduralMemoryStore persistence (v1 scope)
  - COMMANDER routing, quality gate, or endocrine trigger modification
  - `state.json` reads or writes
- **Trust level:** Trusted (COMMANDER is the sole caller; context_pack comes from COMMANDER, not external input)
- **Failure mode:** If `enrich_context` raises an exception, COMMANDER catches and continues dispatch with unenriched context_pack. Overlay failure must NOT block dispatch.
- **Sources:** SCOUT boundaries.md (confirmed); SCOUT assumptions.md (A-001, A-002); RJ-004 (SCOUT)

---

### ProceduralMemoryStore (`.specify/squad/soar-procedural-{run_id}.json`)
- **Classification:** Internal — SOAR overlay-owned runtime artifact
- **Responsibility:** Persists production rules for the duration of a run
- **Communication method:** File I/O (JSON). No cross-process access. Single-writer: SOAR overlay module.
- **Access pattern:** Read at each `enrich_context` call (load fresh); appended to by `update_soar_memory` post-dispatch
- **Lifecycle:** Created on first `enrich_context` call → grows as SOAR chunks are learned → discarded at run end
- **Gitignored:** Yes (runtime artifact, consistent with all other CA overlay state files)
- **Concurrency:** Single-writer safe (COMMANDER dispatches agents sequentially — A-005 validated). If COMMANDER adds parallel dispatch in future, file locking will be required.
- **Trust level:** Trusted derivation (hand-coded seed rules are developer-authored; SOAR chunks derive from COMMANDER-orchestrated outcomes)
- **Sources:** SCOUT boundaries.md, SCOUT mental-model.md

---

### ImpasseLog (`.specify/squad/soar-impasse-{run_id}.json`)
- **Classification:** Internal — SOAR overlay-owned runtime artifact
- **Responsibility:** Append-only log of ImpasseEvents for observability and post-run analysis
- **Communication method:** File I/O (JSON, append-only)
- **Lifecycle:** Created when first impasse occurs; append-only thereafter
- **Gitignored:** Yes
- **Trust level:** Diagnostic (not used for control flow, only for observability)
- **Sources:** SCOUT boundaries.md, SCOUT mental-model.md

---

### WME Extraction Layer (internal to `soar_overlay.py`)
- **Classification:** Internal — stateless transform
- **Responsibility:** Converts flat context_pack dict to list of WME triples
- **Rule:** `{id: "state-<run_id>", attr: <key>, value: str(value)[:200]}`; nested dict values JSON-serialized before coercion
- **Constraint:** 200-char value truncation (size constraint, not security boundary — A-006 unvalidated)
- **Open question:** How to handle `actr_buffers` nested dict (U-007 — should-resolve-before-HOW)
- **Sources:** SCOUT boundaries.md

---

## External Boundaries

### COMMANDER (`agents/control/commander.md`)
- **Classification:** External — orchestrator (prompt-level agent, not a Python process)
- **Dependency strength:** Hard (COMMANDER is the sole caller)
- **Communication method:** Direct Python import → function call; COMMANDER passes context_pack and run_id in; receives enriched context_pack out
- **Trust level:** Full trust (COMMANDER is the system's root orchestrator)
- **Failure impact:** COMMANDER must catch overlay exceptions and continue dispatch with unenriched context_pack
- **Confirmation status:** Validated — COMMANDER.md and all 5 existing overlay implementations confirm the call pattern (A-001 validated)
- **Sources:** SCOUT boundaries.md, SCOUT assumptions.md (A-001)

---

### Existing CA Overlays (specs 017 and overlays 1-5)
- **Classification:** External — peer Python modules in same package
- **Overlays and their context_pack keys:**
  - Goal Stack overlay → `context_pack["active_goal"]`
  - ACT-R overlay → `context_pack["actr_buffers"]` (nested dict — see U-007)
  - LIDA overlay → `context_pack["lida_broadcast"]`
  - GWT overlay → `context_pack["gwt_workspace"]`
  - Episodic Memory overlay (spec 017) → `context_pack["episodic_prior_artifact"]`
- **Dependency strength:** Soft (SOAR overlay reads their outputs as WMEs; if a prior overlay fails to inject its key, WME set is smaller but SOAR overlay still runs — impasse rate increases)
- **Communication method:** SOAR overlay reads the keys they inject into context_pack (read-only)
- **SOAR overlay's position:** Position 6 — runs after all five prior overlays, so all five enrichment keys should be present (A-009 unvalidated — requires COMMANDER.md amendment confirmation)
- **Sources:** SCOUT boundaries.md

---

### Episodic Memory Overlay (spec 017) — ChunkingEngine dependency
- **Classification:** External — peer Python module; soft dependency for chunking only
- **Dependency strength:** Soft (ChunkingEngine reads episodic-index-{run_id}.json; if absent, chunking is skipped; `enrich_context` is unaffected)
- **Communication method:** File read (episodic-index-{run_id}.json) — read-only from SOAR overlay's perspective
- **Failure impact:** If episodic index absent, chunking skipped for that dispatch; enrich_context runs normally
- **Sources:** SCOUT boundaries.md

---

### Official SOAR Interpreter (SoarGroup/Soar C++ kernel, soar-sml PyPI, pysoarlib)
- **Classification:** External — HARD EXCLUSION
- **Dependency strength:** None — explicitly excluded
- **Reason:** Violates ADR-005 (stdlib-only), ADR-003 (API-only, self-contained), and deployment constraints (platform-specific wheels, kernel binary)
- **Impact:** Echelon's overlay reimplements SOAR concepts in Python dicts and a JSON rule store. No SML, no SWIG bindings, no C extensions.
- **This boundary is non-negotiable** — confirmed by A-002 (validated), RJ-005, RJ-009 (SCOUT)
- **Sources:** SCOUT boundaries.md, SCOUT assumptions.md (A-002), SCOUT reference-architectures.md

---

### squad-config.yml
- **Classification:** External — configuration file
- **Dependency strength:** Soft (overlay falls back to hardcoded defaults if section absent)
- **Communication method:** File read (YAML) — read-only from overlay's perspective
- **Expected keys:**
  - `ca_overlays.soar.max_wmes` (int, default 50)
  - `ca_overlays.soar.chunking_enabled` (bool, default true)
  - `ca_overlays.soar.min_chunk_confidence` (float, default 0.6)
- **Failure impact:** Missing soar section → hardcoded defaults → no dispatch interruption
- **Sources:** SCOUT boundaries.md

---

## Trust Boundaries

| Boundary | Trust Level | Rationale |
|----------|-------------|-----------|
| context_pack contents | Full trust | Comes from COMMANDER, not external input. No input sanitization beyond size control. |
| Hand-coded seed rules | Full trust | Developer-authored. Schema validation (required fields) sufficient. |
| SOAR chunks (ChunkRecords) | Derived trust | Derived from COMMANDER-orchestrated successful outcomes. Schema validation sufficient. |
| soar-procedural-*.json | Derived trust | Written only by SOAR overlay; local filesystem, gitignored. Same trust model as all other CA overlay state files. |
| soar-impasse-*.json | Diagnostic | Append-only; used only for observability, not control flow. |
| EpisodicIndex (read-only) | External trust | Written by Episodic Memory overlay. SOAR overlay reads but never writes. Schema assumed valid. |

---

## Boundary Contradictions (none found — sources consistent)

All boundary definitions are internally consistent across the DISCOVER sources. The one noteworthy alignment is that:

- SCOUT glossary.md describes the overlay as "Python-native approximation using stdlib only" (ADR-005)
- SCOUT boundaries.md confirms "explicitly excluded: Official SOAR Interpreter"
- SCOUT assumptions.md confirms A-002 as validated
- SCOUT reference-architectures.md confirms the Divergence Points table shows Rete/SML as excluded

No contradiction between these descriptions. The boundary is clearly and consistently defined across all four sources.

---

## Boundary Gaps

### Gap: squad-config.yml soar section not yet written
- **Impact:** Until squad-config.yml is updated with `ca_overlays.soar.*` keys, the overlay will always use hardcoded defaults. Low priority — defaults are reasonable.
- **Who resolves:** HOW spec / BUILD agent

### Gap: COMMANDER.md position-6 amendment not confirmed
- **Impact:** The SOAR overlay's position-6 slot in the pre-dispatch sequence is assumed (A-009) but not validated against COMMANDER.md. If another overlay was inserted at position 5 after spec 017, the sequence may differ.
- **Who resolves:** SCIENTIST should read COMMANDER.md pre-dispatch sequence and confirm position 6 is available.
