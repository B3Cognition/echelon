# SOAR Cognitive Architecture Overlay — Domain Overview

## Summary

The SOAR Cognitive Architecture Overlay (spec 018) adds a structured, rule-based context enrichment mechanism to the Echelon cognitive agent squad as the sixth overlay in the pre-dispatch enrichment pipeline. Its purpose is to give each agent dispatch a SOAR-inspired assessment of which procedural rule best fits the current cognitive state — expressed as a SOAR operator selection and injected into the context pack before the agent receives it.

The overlay operates by extracting the current context pack's contents into Working Memory Elements (WMEs), evaluating a set of production rules against those WMEs in a single-pass Match-Select-Apply cycle, selecting the highest-confidence matching operator, and merging that operator's payload into `context_pack["soar_state"]`. When no rule matches, an impasse is logged and a DefaultOperator fires. After each successful dispatch, SOAR-inspired chunking records a new production rule derived from the episode, so that the rule base grows within a run. The overlay is implemented using only the Python standard library, follows the ADR-005 uniform interface contract, and writes only to its own run-scoped files — never to COMMANDER-owned state.

This spec also bundles a bug fix for `actr_buffer.py` (ISS-004): the ACT-R overlay was found to duplicate original context pack keys when injecting `actr_buffers`, creating a structural FR-CAO-002 violation. FR-SOAR-011 requires that the de-duplication be corrected as part of the spec 018 delivery.

---

## Dependency Graph

```
COMMANDER pre-dispatch sequence (positions 1-6)
│
├── [1] Goal Stack overlay       → context_pack["active_goal"]
├── [2] ACT-R overlay (+ ISS-004 fix) → context_pack["actr_buffers"]
├── [3] LIDA overlay             → context_pack["lida_broadcast"]
├── [4] GWT overlay              → context_pack["gwt_workspace"]
├── [5] Episodic Memory overlay  → context_pack["episodic_prior_artifact"]
└── [6] SOAR overlay             → context_pack["soar_state"]
         │
         ├── reads: squad-config.yml (ca_overlays.soar.*)
         ├── reads/writes: soar-procedural-{run_id}.json (ProceduralMemoryStore)
         └── writes: soar-impasse-{run_id}.json (ImpasseLog)

COMMANDER post-dispatch
└── SOAR overlay update_soar_memory(outcome, run_id)
         │
         └── reads: episodic-index-{run_id}.json (soft dependency — from spec 017)
             writes: soar-procedural-{run_id}.json (ChunkRecord append)
```

---

## Stakeholders

| Role | Interests | Key Scenarios |
|------|-----------|---------------|
| User / System Owner | Deliver a fully functional SOAR overlay as the sixth CA overlay; chunking must ship as implemented code (even if disabled by default) | All scenarios |
| Dispatched Agents (42 Echelon agents) | Receive richer context pack including SOAR operator assessment; impasse flag may inform reasoning adaptation | Scenario 1, 2 |
| COMMANDER | Wire position-6 pre-dispatch call and post-dispatch `update_soar_memory`; never blocked by SOAR overlay failures | Scenario 6 |
| BUILD Agent | Implement all FR-SOAR-001 through FR-SOAR-013 with no external dependencies | All scenarios |
| VERIFY Agent | Confirm acceptance criteria for all six scenarios; validate ISS-004 fix; validate COMMANDER.md amendment | All scenarios |

---

## Domain Areas

| Area | Description | Complexity | MVP? |
|------|-------------|------------|------|
| Match-Select-Apply Cycle | WME extraction, production rule matching, DecisionProcedure, Apply phase | Medium | Yes |
| ProceduralMemoryStore | JSON file I/O, seed rule initialization, ChunkRecord append, load-order preservation | Low | Yes |
| Impasse Handling | DefaultOperator, ImpasseEvent creation and logging | Low | Yes |
| SOAR-Inspired Chunking | Post-dispatch ChunkRecord construction, generalization strategy, success criterion evaluation | High | Yes (code must exist; default-disabled) |
| ISS-004 Fix (actr_buffer.py) | Remove duplicate keys from ACT-R overlay return value | Low | Yes |
| COMMANDER Integration | COMMANDER.md amendment for position-6 pre-dispatch and post-dispatch hooks | Low | Yes |
| Configuration | `ca_overlays.soar.*` keys in squad-config.yml; fallback to hardcoded defaults | Low | Yes |

---

## Key Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| WME condition schema (OQ-001) is not resolved before HOW — HOW cannot write testable acceptance criteria for rule matching | High | High | SCIENTIST must resolve U-001 and U-002 before HOW begins; CARTOGRAPHER has flagged these as OQ-001 |
| Seed rule set insufficient — impasse rate > 50% on early dispatches, delivering no enrichment value | Medium | High | Instrument impasse log; expand seed rules if impasse rate > 50% after 10 test dispatches |
| Six-overlay token overhead exceeds 25% FR-CAO-002 reinterpretation — SOAR `soar_state` key pushes combined stack over budget | Medium | High | Measure token delta before BUILD finalizes payload; keep `soar_state` minimal (mandatory fields only at cap) |
| Chunking generalization strategy (OQ-005) deferred to HOW — if not resolved, ChunkRecords may over- or under-generalize and provide no learning value | Medium | Medium | Accept Option D (disable by default in v1; enable in v2 after seed rule validation) |
| COMMANDER.md position-6 slot not confirmed (A-009 UNVALIDATED) — slot may be occupied or amendment approach may differ | Low | High | SCIENTIST must read COMMANDER.md and confirm position 6 before HOW drafts the amendment section |
| ISS-004 fix (actr_buffer.py) breaks existing ACT-R overlay consumers if their code expects duplicate keys | Low | Medium | Verify no existing agent code depends on duplicate key structure before applying fix |
