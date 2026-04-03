# Risks — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03

---

## Risk Register

| ID | Risk | Category | Probability | Impact | Severity | Mitigation |
|----|------|----------|-------------|--------|----------|------------|
| RSK-001 | FPCR threshold ambiguity corrupts experiment verdict | Scientific validity | HIGH | CRITICAL | CRITICAL | Resolve CRIT-001 before WHAT phase |
| RSK-002 | Write-time interception hook is architecturally infeasible | Architecture | MEDIUM | CRITICAL | CRITICAL | Audit COMMANDER dispatch before designing NS-003 |
| RSK-003 | Cortisol contagion cascade from NS-003 ESCALATED events | System behavior | LOW-MEDIUM | HIGH | HIGH | Run NS-003 experiment in isolated mode |
| RSK-004 | Schema over-specification causes false rejections on valid outputs | Experiment quality | MEDIUM | HIGH | HIGH | Phase 1 pilot: test schemas on 5 known-good samples before full N=30 |
| RSK-005 | Echelon extension codebase changes between NS-003 and U-CA-004 experiments | Experiment comparability | LOW-MEDIUM | HIGH | HIGH | Lock codebase to commit hash before either experiment |
| RSK-006 | No dependency management → experiment not reproducible | Reproducibility | MEDIUM | HIGH | HIGH | Create scripts/requirements.txt as first implementation task |
| RSK-007 | Token logging degrades to word-count heuristic if SDK unavailable | Measurement fidelity | MEDIUM | MEDIUM | MEDIUM | Confirm SDK vs CLI decision before implementation |
| RSK-008 | Evaluator bias in U-CA-004 if blinding is infeasible | Experiment validity | MEDIUM | MEDIUM | MEDIUM | Design pre-calibration rubric exercise; consider order randomization |
| RSK-009 | ACT-R buffer cosine_similarity computation adds latency/cost via embeddings API | Implementation complexity | LOW-MEDIUM | MEDIUM | MEDIUM | Evaluate TF-IDF/BM25 approximation first |
| RSK-010 | NS-003 FPCR measures schema coverage not artifact quality | Metric validity | MEDIUM | MEDIUM | MEDIUM | Measure structured-to-prose ratio before schema design |
| RSK-011 | BeliefGraph run-scoped only — no cross-run episodic memory in v1 | Feature scope | LOW | LOW | LOW | Document as known v1 limitation; CA overlay 4 (Episodic Memory) addresses this |
| RSK-012 | Prior spec runs 008-014 not archived or accessible | Phase 1 gate | MEDIUM | HIGH | HIGH | Locate or recreate known-good samples before Phase 1 |

---

## CRITICAL Risks (Require Immediate Action)

### RSK-001: FPCR Threshold Ambiguity Corrupts Experiment Verdict
- **Description:** Two authoritative sources define different FPCR PASS thresholds (0.70 vs 0.80). Any FPCR result in [0.70, 0.80) produces contradictory verdicts depending on which source is used.
- **Root cause:** Spec 017 brief was written with a different threshold than the pre-registered experiment design (spec 015).
- **Consequence if unresolved:** The experiment produces an unresolvable verdict. Post-hoc threshold choice violates reproducibility requirement. The scientific validity of NS-003 is compromised.
- **SYNTHESIZER recommendation:** Default to pre-registered 0.80 (per scientific norms). Treat 0.70 as minimum viable start threshold. Document in user-intent.md.
- **Owner:** WHY1 must challenge this; human must confirm.
- **Timeline:** Must resolve before WHAT phase.

### RSK-002: Write-Time Interception Hook May Be Architecturally Infeasible
- **Description:** NS-003 requires intercepting agent output between LLM call and artifact file write. No such hook exists in the codebase. If agents write their own outputs via tool calls within their LLM context, COMMANDER may have no opportunity to intercept.
- **Root cause:** NS-003 architectural requirement was designed against an assumed COMMANDER capability that may not exist.
- **Consequence if infeasible:** NS-003 degrades to post-hoc detection (like contradiction-scanner.py), eliminating its core novelty claim (pre-commit ConflictSignal). The entire NS-003-B architecture collapses.
- **Mitigation:** Audit COMMANDER dispatch sequence before designing NS-003 integration. If pre-commit interception is infeasible at the COMMANDER level, consider a write-wrapper utility that all agents invoke, which calls the Critic before the actual file write.
- **Owner:** Architecture design in HOW phase.
- **Timeline:** Must resolve as part of WHAT phase architecture decisions.

---

## HIGH Risks

### RSK-003: Cortisol Contagion Cascade from NS-003 ESCALATED Events
- **Description:** Each NS-003 ESCALATED outcome triggers `on_gate_fail` → cortisol +0.10. After 3 consecutive ESCALATED events: cortisol reaches 0.80 → contagion threshold → `propagate_cortisol_contagion` to downstream agents.
- **Root cause:** Endocrine system's cortisol contagion mechanism is sensitive to repeated gate failures. NS-003 experiment runs 5 invocations per agent type — if schema underspecification causes many FAIL results during calibration, the squad enters high-stress state.
- **Mitigation:** Run NS-003 experiment in an isolated mode (separate from production squad runs) with endocrine state initialization reset before each experiment batch. Do NOT run NS-003 calibration runs against production state.json.
- **Detection:** Monitor cortisol levels after each experiment batch; reset if > 0.70 before resuming production work.

### RSK-004: Schema Over-Specification Causes False Rejections on Valid Outputs
- **Description:** If JSON Schema schemas for Echelon artifact types are too specific, the Critic will reject valid but stylistically variant agent outputs. False rejection rate would inflate FAIL counts, driving FPCR into INCONCLUSIVE zone even when actual agent compliance is high.
- **Root cause:** JSON Schema specificity calibration is inherently difficult for free-form Markdown with variable structure.
- **Mitigation:** Phase 1 pilot — build schemas for 2-3 artifact types, test against 5 known-good samples each, measure false rejection rate before committing to full schema suite. If false rejection rate > 5% on known-good samples, revise schema before Phase 2.

### RSK-005: Codebase Changes Compromise Cross-Experiment Comparability
- **Description:** NS-003 and U-CA-004 both use the Echelon extension codebase as the test target. If the codebase is updated between experiments, the test environment differs, invalidating cross-experiment comparison.
- **Mitigation:** Lock codebase to a specific commit hash before running either experiment. Record hash in experiment metadata. Both experiments must use the same hash.

### RSK-006: No Dependency Management Prevents Reproducibility
- **Description:** NS-003 requires jsonschema; U-CA-004 requires scipy. Neither is tracked. A fresh environment cannot reproduce the experiments.
- **Mitigation:** Create `scripts/requirements.txt` as the first implementation task, with pinned versions. Minimum: `jsonschema>=4.0.0`, `scipy>=1.10.0`, `pyyaml>=6.0`, `anthropic>=0.20.0` (if SDK used).

### RSK-012: Prior Spec Runs 008-014 Not Accessible for Phase 1 Calibration
- **Description:** Phase 1 requires zero false rejections on prior spec runs 008-014. These are not visible in `.specify/specs/`.
- **Mitigation:** Human must locate or provide access to runs 008-014 before Phase 1 begins. Alternative: use runs 015-016 as calibration samples (smaller set, but confirmed accessible). If neither is available, design synthetic known-good samples from the artifact type definitions.

---

## MEDIUM Risks

### RSK-007: Token Logging Degrades to Word-Count Heuristic if SDK Unavailable
- **Description:** If NS-003 must use CLI subprocess for LLM invocations, token counts come from the CLI output (if available) or fall back to token-logger.py's word_count × 1.3 heuristic. This undermines REQ-015-003 token baseline fidelity.
- **Mitigation:** Confirm SDK vs CLI architecture decision (U-002) before implementing token logging. If CLI-only: parse CLI output for token counts where available; document heuristic fallback as a measurement limitation in the experiment report.

### RSK-008: Evaluator Bias in U-CA-004 (Single Evaluator, Condition-Distinguishable Outputs)
- **Description:** A single evaluator scoring 60 invocations across 3 conditions may drift over time or unconsciously favor Condition C (ACT-R) if outputs are condition-distinguishable.
- **Mitigation:** Pre-calibration rubric exercise (5 reference outputs before main batch). Randomize evaluation order across conditions. Document evaluator blinding limitations in experiment report.

### RSK-009: ACT-R Buffer Cosine Similarity Requires Embeddings API
- **Description:** The ACT-R activation formula requires cosine similarity between artifact chunks and goal buffer. If embeddings API calls are needed, buffer preprocessing adds API calls per invocation, increasing cost and latency.
- **Mitigation:** Evaluate TF-IDF cosine approximation first (local, zero-cost). If TF-IDF ranking quality is insufficient (evaluate on 5 sample retrievals), escalate to lightweight sentence-transformer (local model) before using embeddings API.

### RSK-010: NS-003 FPCR Measures Schema Coverage Not Artifact Quality
- **Description:** If structured fields represent < 60% of artifact content, FPCR measures compliance only on the structured portion. Prose sections (reasoning, analysis, narrative) are invisible to the schema validator. FPCR would be a partial quality signal.
- **Mitigation:** Measure structured-to-prose ratio in 10-15 prior Echelon run artifacts before schema design. Document coverage fraction in experiment report. Consider augmenting NS-003-A with a lightweight prose structure check (e.g., required section headers present).

---

## LOW Risks

### RSK-011: BeliefGraph v1 Has No Cross-Run Episodic Memory
- **Description:** NS-003-B belief graph is run-scoped only. Cross-run consistency (detecting that an assertion in spec 017 contradicts one in spec 016) is not addressed.
- **Context:** This is a deliberate v1 scope decision, not a gap. CA overlay 4 (Episodic Memory) addresses cross-run persistence if U-CA-004 resolves POSITIVE.
- **Mitigation:** Document as known v1 limitation in experiment report. No action required for spec 017.
