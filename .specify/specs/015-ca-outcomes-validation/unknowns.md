# Unknowns — Spec 015 (CA Outcomes Validation)
**Agent**: SCOUT | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Purpose**: What remains unknown after spec 014 that blocks proof of the claimed outcomes. Each unknown is classified by blocking status and by what would resolve it.

---

## Unknown Classification

| Status | Meaning |
|--------|---------|
| BLOCKS-PROOF | This unknown must be resolved before the claim can be evaluated |
| DEGRADES-CONFIDENCE | The unknown weakens confidence in the claim; does not fully block |
| OPEN-MEASUREMENT | A measurement that has not been taken; can be taken with current codebase |
| OPEN-EXPERIMENT | Requires a prototype experiment to resolve |
| OPEN-LITERATURE | Requires additional literature search to resolve |

---

## Critical Unknowns

### U-015-001: U-CA-004 — Gate Experiment Not Run [BLOCKS-PROOF for 5 CA overlays]

**What it is**: The three-condition experiment comparing (A) naive baseline, (B) expert-engineered prompt, and (C) CA-structured overlay on the same Echelon task class, same LLM (Claude Opus 4.x), with the same evaluation metric.

**Current status**: INCONCLUSIVE from spec 014 investigation. The MAP paper (Nature Communications 2025) provides the closest Grade A evidence — CA-structured pipeline outperforms GPT-4 CoT on planning tasks — but the task class (graph traversal, Tower of Hanoi) differs from Echelon's code analysis pipeline, and GPT-4 (2023) is not Claude Opus 4.x.

**Why it blocks**: Every CA overlay claim (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) is conditioned on this gate resolving positively. If the experiment shows no advantage for CA-structured pipelines over expert prompting on Echelon tasks, the implementation case for all 5 overlays collapses.

**What would resolve it**: Run the gate experiment as designed in spec 014 unknowns.md. Three conditions, N=10 runs each (minimum), Claude Opus 4.x as the LLM, a fixed test codebase (one well-understood repository), a predefined quality rubric for artifact evaluation. Estimated timeline: 4-6 weeks including experiment design, implementation, and measurement.

**Risk if unresolved**: Engineering resources committed to overlay implementation before the gate experiment may be entirely wasted if the gate returns negative results. The U-CA-004 INCONCLUSIVE verdict from spec 014 already identified this as ISS-002 (CRITICAL).

---

### U-015-002: U-CA-009 — CA Overhead Cost Not Measured [BLOCKS-PROOF for net efficiency claims]

**What it is**: The token overhead cost of CA mechanism infrastructure (Generator-Critic validation loop, belief graph writes, constraint propagation, prediction generation) vs the token savings those mechanisms produce.

**Current status**: No measurement exists. Spec 014 plan.md explicitly marks all `estimated_net_delta` fields as null, pending U-CA-009.

**Why it blocks**: Even if a CA mechanism improves output quality, it may add more token cost than it saves. Net efficiency requires both sides of the ledger. Without baseline and overhead measurements, "efficiency improvement" cannot be stated.

**What would resolve it**:
1. Instrument a baseline Echelon run: log total tokens consumed (prompt + completion) per agent invocation, per pipeline run.
2. Instrument an NS-003 prototype run: log the additional tokens consumed by Critic validation calls, belief graph write operations, and retry prompts.
3. Compute net delta: (tokens saved by early termination, context reduction, or avoided retries) − (tokens added by mechanism overhead).
4. Compare to ACON's 22-54% compression ceiling (the algorithmic maximum for context compression).

**Estimated resolution effort**: 1-2 days of instrumentation code + 5-10 prototype runs on a fixed test codebase.

---

### U-015-003: Token Efficiency Baseline — Echelon Runs Not Instrumented [OPEN-MEASUREMENT]

**What it is**: The current per-run token consumption of Echelon pipelines is unknown. No historical measurement exists across the 9 completed spec runs (specs 008-014).

**Why it matters**: Every token efficiency claim (40-70% reduction for NOVEL-004, 20%+ reduction for ACT-R typed buffer, ACON ceiling comparison) requires a baseline to compute improvement against. Without a baseline, "reduction" is undefined.

**What would resolve it**: Post-hoc token estimation from spec run logs (if Echelon writes token counts to reasoning-journal.json — current journal schema does not include token counts). Forward-looking: instrument the next 3-5 spec runs with token logging per agent invocation.

**Note**: squad-config.yml sets `token_budget_k: 999999` — effectively unlimited. This means the pipeline has never been constrained to measure token efficiency. The system has no cost-pressure signal that would have triggered efficiency measurement.

---

### U-015-004: Scope Violation Rate Baseline — No Historical Measurement [OPEN-MEASUREMENT]

**What it is**: The frequency with which Echelon agents produce outputs that fall outside their declared scope across historical runs is unknown.

**Why it matters**: Three mechanisms (NS-003 Critic consistency check, AC-3 constraint certificate, NOVEL-002 Phi-proxy) claim to reduce scope violations. Without a baseline rate, "reduction" cannot be measured, and the severity of the problem cannot be assessed.

**What would resolve it**: Manual review of 3-5 prior spec runs. For each run, review each agent's output against its scope definition (in the agent prompt) and classify each output section as in-scope, out-of-scope, or borderline. Aggregate into a violation rate per agent type and per run. This is a 1-2 day manual annotation effort for an experienced Echelon operator.

**Evidence from spec 014**: ISS-001 notes that ASSESS reproducing DISCOVER findings is a known scope violation mode. This is qualitative; it does not quantify frequency.

---

### U-015-005: Contradiction Detection Rate in Current Runs — No Baseline [OPEN-MEASUREMENT]

**What it is**: The frequency with which contradictions between artifacts from different pipeline stages occur in completed Echelon runs, undetected.

**Why it matters**: NS-003's belief revision claims to catch contradictions at write-time. Without knowing the baseline contradiction rate in current runs, the severity of the problem (and thus the value of NS-003) is unknown.

**What would resolve it**: Automated scan of prior spec run artifacts with a contradiction detection heuristic: extract key factual assertions from each agent's output (using structured sections where available), compare assertions across stages, flag pairs that assert contradictory facts about the same entity. A lightweight GPT-3.5-class classifier could perform this at low cost across the 9 available spec runs.

---

### U-015-006: Prediction Accuracy Model for NOVEL-004 — No Calibration Data [BLOCKS-PROOF for NOVEL-004]

**What it is**: The forward model (the prediction generator for NOVEL-004) has no calibration data. Its expected accuracy, break-even threshold, and failure modes are entirely theoretical. No historical Echelon data exists to estimate how often an upstream agent's findings would correctly predict the downstream agent's findings.

**Why it blocks**: NOVEL-004's token reduction claim is entirely dependent on prediction accuracy. If prediction accuracy is < 20%, the mechanism adds overhead with negligible savings. The break-even estimate (40-50%, extrapolated from Speculative Decoding) is unvalidated for agent-level prediction.

**What would resolve it**:
- Retrospective calibration: examine pairs of adjacent agent outputs from prior spec runs (e.g., DISCOVER → ASSESS pairs across 9 specs). For each pair, have a human or LLM evaluate: "Given DISCOVER's output, how much of ASSESS's output could have been predicted?" Score each pair 0-100%.
- Average prediction accuracy estimate.
- This gives a rough calibration point before any prototype is built.

**Estimated resolution effort**: 1-2 days manual analysis of available spec run artifacts.

---

### U-015-007: Echelon Target System Architecture — 7 Stages vs 42 Agents (ISS-001, OPEN) [DEGRADES-CONFIDENCE]

**What it is**: ISS-001 in spec 014 issues.md is CRITICAL and OPEN: Echelon is described as both a "7-stage pipeline" (in most spec 014 files) and a "42-agent architecture" (confirmed from squad-config.yml internalization tier list). The relationship between stages and agents is not formally defined.

**Current partial resolution**: From the agent directory listing, Echelon has: control, exploration, feasibility, learning, solution, specialists, build tiers — 7 functional tiers with multiple agents per tier. The "7-stage pipeline" likely refers to the 7 functional tiers; the 42 agents are distributed across those tiers. The COMMANDER dispatches specific agents within a tier based on EVOI.

**Why it matters for validation**: The Goal Stack overlay assumes a goal tree structure where "operators" correspond to pipeline stages. If the stages are tiers (not individual agents), the goal stack design changes significantly. The ACT-R typed buffer token budget per tier vs per agent call also changes the efficiency calculation.

**What would resolve it**: A definitive count and mapping: tier → agents within tier → invocation pattern (all always invoked? subset selected by COMMANDER?). This is a 30-minute code review task on the commander.md dispatch protocol.

---

### U-015-008: Prior Literature Exhaustiveness for Novelty Claim [OPEN-LITERATURE]

**What it is**: The NS-003 novelty claim ("this combination has no prior literature") is based on a 13-source literature review in spec 014. This review may not be exhaustive.

**Why it matters**: A single contradicting paper would invalidate the novelty claim. The novelty claim is one of the highest-value outputs from spec 014 (it motivates NS-003 as a research contribution, not just an engineering improvement).

**What would resolve it**: A systematic literature search on Semantic Scholar using the specific conjunction: ("execution-grounded" OR "schema validation") AND ("belief revision" OR "AGM") AND ("multi-agent" OR "pipeline"). Record the date, query, and zero-result confirmation. This search takes < 30 minutes and provides a defensible provenance for the novelty claim.

---

## Summary: Blocking vs Non-Blocking Unknowns

| Unknown | Claim Blocked | Blocking Status | Resolution Effort |
|---------|--------------|----------------|-------------------|
| U-015-001: U-CA-004 gate not run | 5 CA overlays + their use cases | BLOCKS-PROOF | 4-6 weeks experiment |
| U-015-002: CA overhead cost not measured | Net efficiency claims | BLOCKS-PROOF | 1-2 days instrumentation + 5-10 prototype runs |
| U-015-003: Token baseline missing | All token efficiency claims | OPEN-MEASUREMENT | 1-2 days instrumentation |
| U-015-004: Scope violation baseline missing | AC-3, NS-003, NOVEL-002 improvement claims | OPEN-MEASUREMENT | 1-2 days annotation |
| U-015-005: Contradiction rate baseline missing | NS-003 severity assessment | OPEN-MEASUREMENT | 1-2 days automated scan |
| U-015-006: Prediction accuracy not calibrated | NOVEL-004 token reduction | BLOCKS-PROOF | 1-2 days retrospective analysis |
| U-015-007: 7-stage vs 42-agent architecture | Goal Stack, ACT-R buffer sizing | DEGRADES-CONFIDENCE | 30 minutes code review |
| U-015-008: Novelty search not exhaustive | NS-003 novelty claim | OPEN-LITERATURE | 30 minutes systematic search |

**Immediate unblocking actions** (resolvable without a prototype experiment):
- U-015-003, U-015-004, U-015-005: instrumentation and annotation of existing spec runs — 3-4 days total.
- U-015-007: 30-minute commander.md inspection.
- U-015-008: 30-minute Semantic Scholar search.

**Long-lead blockers** (require experiment design and prototype implementation):
- U-015-001: U-CA-004 gate experiment — 4-6 weeks.
- U-015-002 + U-015-006: NS-003 and NOVEL-004 prototypes — 2-4 weeks each.
