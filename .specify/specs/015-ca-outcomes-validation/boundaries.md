# Boundaries — Spec 015 (CA Outcomes Validation)
**Agent**: SCOUT | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Purpose**: Define what is in-scope for proof with current evidence and Echelon codebase, what is out-of-scope, and what "proof" means in each context.

---

## In-Scope: Claims Testable With Current Evidence and Codebase

### 1. NS-003-A — Generator-Critic schema compliance (IN SCOPE)

**Why in scope**: NL2GenSym provides Grade A evidence that the Generator-Critic mechanism achieves 86%+ first-pass compliance on a structured symbolic task. The Echelon artifact protocol uses structured markdown with defined section schemas. The mechanism is directly implementable via black-box API access. No gate experiment is needed.

**What can be tested now**:
- Define JSON Schema or structured markdown schema for each Echelon agent's output type.
- Run 20-30 agent invocations against a fixed test codebase (single run, reproducible input).
- Measure first-pass compliance rate.
- Measure retry success rate (does the Critic feedback loop converge within 2 retries?).

**Scope qualification**: The NL2GenSym paper measures compliance on Soar rule generation — a narrower, more formally defined task than Echelon artifact sections. The transfer to Echelon's more open-ended prose-plus-structure artifact format is not guaranteed. The schema must be defined at a level of specificity that enables automated validation without LLM evaluation.

**Proof threshold**: First-pass compliance ≥ 70% (below NL2GenSym's 86% but accounting for the less constrained output type) would constitute supporting evidence. First-pass compliance < 50% would indicate the mechanism requires redesign for this task class.

---

### 2. NS-003-B — Belief Revision contradiction catching (IN SCOPE)

**Why in scope**: Kumiho provides Grade A evidence that AGM-compliant belief revision achieves 93.3% accuracy on a multi-turn consistency tracking task. The Echelon artifact protocol creates facts that can contradict across stages (DISCOVER asserts X, ASSESS contradicts X). The mechanism is implementable as a deterministic Python property graph with no LLM calls in the revision step.

**What can be tested now**:
- Construct a labeled test set: take N Echelon run artifacts from prior specs (9 specs available), inject known contradictions, measure whether the Critic fires ConflictSignal correctly.
- Measure false-negative rate (contradictions not caught) and false-positive rate (conflicts flagged that are not actual contradictions).

**Scope qualification**: Kumiho operates on a conversational fact-tracking dataset (LoCoMo-Plus). Echelon's artifacts are multi-domain technical analysis outputs. The contradiction patterns differ: Kumiho handles factual inconsistencies ("the meeting was on Tuesday" vs "the meeting was on Wednesday"); Echelon handles logical inconsistencies across technical domains ("the system uses REST" vs "the system is event-driven").

**Proof threshold**: Contradiction catch rate ≥ 75% on a manually labeled test set of 20+ artificially contradicted artifact pairs.

---

### 3. NS-003-C — Novelty of the combination (IN SCOPE for literature claim)

**Why in scope**: Spec 014's research pass reviewed 13+ sources across the CA-LLM literature. No source combining execution-grounded Generator-Critic with AGM belief revision applied to multi-agent artifact stores was found. This is a repeatable literature search.

**What can be tested now**:
- Run a systematic search on Semantic Scholar and Google Scholar with query: ("Generator-Critic" OR "generation-validation loop") AND ("belief revision" OR "AGM postulates") AND ("multi-agent" OR "artifact store").
- A zero-result search on this conjunction is the proof.

**Scope qualification**: "No prior literature" claims are inherently falsifiable — a single contradicting paper invalidates them. The spec 014 search was extensive but not exhaustive. The novelty claim should be stated as "no prior literature found in the reviewed corpus" not "no prior literature exists."

---

### 4. AC-3 Constraint Propagation — feasibility in principle (IN SCOPE for design review)

**Why in scope**: AC-3 is a well-established CS algorithm (Mackworth 1977, Bessiere 2006). Its application to prune the semantic output space of LLM agents is novel, but the constraint propagation step itself is deterministic and requires no empirical validation of the algorithm. What requires empirical validation is whether the LLM respects the injected constraint certificate (soft guidance, not hard enforcement).

**What can be tested now**:
- Design the constraint schema for two adjacent pipeline stages (DISCOVER → ASSESS).
- Inject the constraint certificate into ASSESS's context.
- Measure whether ASSESS's output contains assertions that contradict the constraint certificate (violation rate).
- Compare with a baseline run that omits the constraint certificate.

**Scope limitation**: The constraint certificate provides soft guidance only. The LLM is not formally forced to respect it. Full proof would require constrained decoding (not available via black-box API). The measurable outcome is "violation rate reduction," not "zero violations."

---

## Out-of-Scope: Claims That Cannot Be Proven With Current Evidence

### 5. NOVEL-004 token reduction (40-70%) — OUT OF SCOPE (SPECULATION)

**Why out of scope**: The original spec 014 answer explicitly labeled this "SPECULATION: needs measurement." The claim is not derived from any measured evidence. The Speculative Decoding analogy (SRC-A5) achieves 2-3x token throughput at the token level — this cannot be directly extrapolated to semantic-level agent prediction without a prototype. The 40-70% range has no empirical grounding.

**What would bring it in scope**: A prototype implementation of NOVEL-004 with instrumented token counters across N=50+ Echelon pipeline runs. The prototype must include:
- A forward model for at least two adjacent agent pairs (e.g., DISCOVER → ASSESS).
- A prediction check mechanism.
- Token logging for LLM calls (prediction check pass vs full generation).
- Baseline measurement (all agents fully invoked, no prediction protocol).

This is a 4-8 week engineering effort minimum. Not achievable within a research validation run.

---

### 6. 5 CA Overlays — OUT OF SCOPE without U-CA-004 gate experiment

**Why out of scope**: Every CA overlay claim (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) is conditioned on U-CA-004 resolving positively. U-CA-004 asks: "Does a CA-structured pipeline outperform an expert-prompt-engineered pipeline on the same task?" This gate experiment has not been run.

The U-CA-004 investigation result from spec 014 is INCONCLUSIVE (verdict: weak positive signals; no direct controlled comparison on identical tasks; MAP paper is the closest evidence but uses a different task class).

**What U-CA-004 resolution requires**:
- Three-condition experiment: (A) naive baseline, (B) expert-engineered prompt, (C) CA-structured overlay.
- Same LLM (Claude Opus 4.x) across all conditions.
- Same task class (Echelon-style code analysis pipeline).
- Identical evaluation metric (task success rate or artifact quality score).
- Minimum N=10 runs per condition for statistical validity.

Until U-CA-004 resolves, all 5 overlay claims remain in Category P4 (gate-conditioned). Implementing any overlay before the gate experiment runs risks engineering resources on mechanisms that may not outperform a well-crafted expert prompt.

**Implication**: The use cases attributed to individual overlays ("WHY rejects spec 3x → COMMANDER knows in advance" for Goal Stack; "Critical findings missed → LIDA Broadcast" for LIDA) are similarly out of scope. They inherit the P4 blocking condition.

---

### 7. Cross-run token efficiency improvements — OUT OF SCOPE (baseline missing)

**Why out of scope**: No baseline measurement of token consumption per Echelon run exists. The squad-config.yml sets `token_budget_k: 999999` (effectively unlimited). Without a measured baseline, no improvement claim can be validated.

**What would bring it in scope**: Instrument 5-10 prior Echelon runs to extract:
- Total tokens consumed (prompt + completion) per pipeline run.
- Tokens per agent invocation.
- Redundancy rate (tokens in output that duplicate prior artifact store content).

This instrumentation is achievable within the current Echelon framework (post-call token count introspection is available per the plan.md Access Model table).

---

## U-CA-004 Conditionality: Precise Statement

The 5 CA overlays CANNOT be proven without U-CA-004 because:

1. **The baseline is not established**: Without knowing what a well-engineered expert prompt achieves on Echelon's task class, there is no reference against which the overlay can demonstrate superiority.

2. **The MAP paper (closest Grade A evidence) uses a different task class**: MAP compares CA modularization vs GPT-4 CoT on graph traversal, Tower of Hanoi, and PlanBench. Echelon's task is multi-stage codebase analysis. The generalization cannot be assumed.

3. **The CA overhead cost is unknown**: U-CA-009 (CA overhead cost analysis) has not been measured. Even if an overlay improves output quality, it may add token cost that negates the efficiency benefit. Net value requires both quality improvement AND overhead measurement.

4. **Frontier LLM risk**: As noted in U-CA-004 synthesis, Claude Opus 4.x may have internalized CoT-equivalent reasoning through alignment training. The MAP study used GPT-4 (2023 vintage). The advantage CA provides over CoT may be smaller or zero for the latest models. This risk is unquantified.

---

## What "Proof" Means: Research Context vs Production Context

**In research context** (spec 015 validation scope):
- Proof = Grade A empirical evidence on a comparable task, with explicit qualification of the task class difference.
- The Generator-Critic mechanism is "proven" in research terms: NL2GenSym provides Grade A evidence. The qualification is that the task (Soar rule generation) is narrower than Echelon's task.
- "Proven in research context" does NOT mean safe to deploy to production Echelon runs without a prototype validation step.

**In production context** (not this spec's scope):
- Proof = prototype measurement on Echelon's actual task class (code analysis pipeline), with baseline comparison, across multiple runs.
- No claim in spec 014's outcomes is fully proven in production context. NS-003 is the closest — it has Grade A component evidence and is implementable via API, but has not been measured in the Echelon pipeline specifically.

**The honest summary**: Spec 014's outcomes establish a research design backed by Grade A component-level evidence for NS-003, Grade C/analogy evidence for NOVEL-004, and an explicit gate condition for the 5 overlays. The outcomes are not production proofs; they are research claims with varying degrees of evidential support and defined experiment designs for validation.
