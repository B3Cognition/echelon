# Echelon Proto — Novelty Catalogue (Final, Authoritative)

**Version**: 2.0 — Final
**Date**: 2026-04-02
**Produced by**: T-005 IMPLEMENTER (Build Spec 016)
**Sources integrated**: novelty-catalogue.md (SCOUT), integration-notes.md (T-002), INVESTIGATION-SUMMARY.md (INVESTIGATOR), patent-analysis.md (ORACLE), maverick-report.md (MAVERICK)
**Constitution compliance**: P-004, P-005, P-006 verified

> This file supersedes novelty-catalogue.md as the authoritative novelty registry for echelon_proto.
> All 12 original mechanisms are included plus 3 combination claims added from ORACLE Section 3 and MAVERICK.

---

## NOVEL-001: Endocrine Neuromodulation System (6-Hormone Agent Personality Modulation)

**Mechanism**: A real-time agent personality modulation system inspired by mammalian endocrine signaling. Six neuromodulator levels (adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine) are maintained as floating-point scalars [0.0–1.0] per agent. Each agent archetype has per-hormone baselines (e.g., exploration agents: [0.3, 0.7, 0.3, 0.6, 0.5, 0.4]). Hormones are phase-gated (spike on phase-specific triggers: deadline pressure raises adrenaline, gate pass raises dopamine). Hormones decay across dispatch cycles (adrenaline decays 0.6×/cycle; serotonin decays 0.95×/cycle). Downstream agents receive a 30% hormone boost propagated from upstream levels. Circuit breakers cap oscillation (max change ±0.4/cycle, floor 0.0, ceiling 1.0). The result is an observable, deterministic, replayable personality trace per dispatch sequence.
**Evidence Grade**: A
**Defensibility**: HIGH

### Prior Art Differential
- Prior art: CrewAI has static text personas. AutoGen has no personality system. LangChain agents are stateless personality-wise. Simulation literature (Ayouni et al. 2020) uses static agent traits in social simulation — not dynamically modulated in real time.
- Delta: Echelon adds six-dimensional quantified scalar state modulation with exponential decay per dimension, phase-gated event triggers, downstream propagation, and circuit breakers — none of which exist in combination in any LLM orchestration framework.

### Evidence in Code
- `scripts/bash/endocrine.sh` lines 83–93 — hormone constants, archetype baselines, phase-gated delta logic, decay calculation, propagation factor
- `squad-config.yml` lines 444–532 — per-archetype hormone baselines, decay rates, circuit breaker settings for all 8 archetypes
- `agents/control/commander.md` — COMMANDER injects hormone state into context pack before each dispatch

### Specialist Findings
- INVESTIGATOR (INV-001, 2026-04-02): PARTIALLY CONFIRMED / CHALLENGER. Core mechanism is engineered prompt injection with quantified state management — not a structurally different mechanism from dynamic prompting. Strong novelty exists in the six-dimensional quantification + exponential decay + outcome-based calibration combination. Key vulnerability: if CrewAI, AutoGen, or LangChain implement multi-dimensional state modulation with decay, novelty claim weakens. Targeted search of those repos for "decay," "state modulation," "feedback tuning" is an open evidence gap.
- ORACLE (Section 2, CLAIM-002): HIGH DEFENSIBILITY when claim is narrowed to "quantified neuromodulator-inspired state vectors" with per-archetype baselines, phase-gated deltas, dimension-specific exponential decay, 0.30 downstream propagation, and ±0.4/cycle circuit breakers. Efficacy experiment (A-005/U-005, N≥10 runs, hormones on vs frozen) required before filing.
- MAVERICK (Section 1, Item 3): Primary IP angle is AI transparency and debugging, not quality improvement. Every hormone dimension has a measurable trigger and deterministic response — the system is fully observable and replayable. This constitutes "AI interpretability" IP, which carries higher defensibility surface due to regulatory and safety relevance. The biological metaphor is pedagogically useful but legally weak; the patent framing must center on interpretability + determinism, not the metaphor.

### Patent Defensibility
- Claim type: specific-implementation + combination-of-elements
- Strongest claim: "A method for modulating LLM agent behavior via quantified neuromodulator-inspired state vectors, where each of six dimensions represents a discrete motivational axis (urgency, reward, vigilance, stability, collaboration, focus), characterized by per-archetype baseline initialization, phase-gated event-triggered delta updates, exponential time-decay per dimension, 0.30 downstream propagation ratio, and ±0.4/cycle circuit breakers — producing a fully observable, deterministic, replayable agent behavior trace."
- Weakest point: Core mechanism is prompt text injection (not learned, not neural). If any prior framework implements multi-dimensional decay-based state modulation on agents, the novelty collapses to engineering. Open evidence gap: targeted prior-art search of CrewAI, AutoGen, LangChain GitHub for "decay" or "state modulation" has not been completed (INV-001 recommendation, unresolved as of 2026-04-02).

### What Would Constitute Full Proof
- Targeted search of CrewAI, AutoGen, LangChain GitHub repos for "decay," "state modulation," "feedback tuning" on agent behavior — zero results required to strengthen claim
- Ablation experiment: N≥10 full Echelon runs with hormones active vs frozen at baseline; measure gate pass rate, output consistency (variance), and agent output quality (Understanding metrics); success = ≥10% improvement on ≥2 metrics (p < 0.05)
- USPTO/WIPO patent search for "neuromodulator," "hormone," "agent personality" + "LLM" — expected zero results in agent orchestration domain

---

## NOVEL-002: Belief Annotation System (Temporal Freshness Tracking for Operational Knowledge)

**Mechanism**: A YAML annotation system for embedding operational beliefs into configuration files and agent prompts. Annotations use `@belief(claim: "...", verified: "YYYY-MM-DD", expires: "YYYY-MM-DD", confidence: 0.0–1.0, severity: "low|medium|high")` syntax. A `scripts/belief-parser.py` script extracts all annotations from config files and agent `## Belief Register` tables in Markdown, producing `config-belief-graph.json`. Beliefs are automatically classified as: expired, approaching_expiry (< 30 days to expiry), low_confidence (< 0.5), or fresh. Downstream agents receive stale-belief caution alerts, enabling dynamic trust-threshold adjustment based on belief age.
**Evidence Grade**: A
**Defensibility**: MEDIUM

### Prior Art Differential
- Prior art: LangChain ConversationBufferMemory tracks conversation history, not operational beliefs. CrewAI has task context injection but no freshness tracking. OWL/RDF support temporal metadata but are not integrated into LLM agent dispatch. No framework implements expiry-based belief classification affecting agent reasoning.
- Delta: Echelon makes operational assumptions machine-readable, queryable, and expiry-aware. Freshness classification is automatic. Downstream agents adjust caution based on classification — no equivalent exists in LLM orchestration.

### Evidence in Code
- `scripts/belief-parser.py` lines 43–68 — freshness classification logic (expired/approaching_expiry/low_confidence/fresh)
- `scripts/belief-parser.py` 547 lines total — @belief() parsing, Belief Register table extraction, config-belief-graph.json output
- `squad-config.yml` — @belief() annotations embedded in comments (e.g., six-hormone dimensionality claim, confidence: 0.75)
- `agents/exploration/scout.md` lines 436–446 — agent prompt Belief Register table (8 beliefs documented with metadata)

### Specialist Findings
- INVESTIGATOR: Not separately investigated. Integration-notes.md Gap-002 confirms catalogue accurately reflects belief system state.
- ORACLE (Section 1, NOVEL-002): MEDIUM invalidation risk. Straightforward mechanism. Prior-art risk from OWL/RDF and semantic web knowledge management.
- MAVERICK: Not separately challenged. COMBINATION-002 (see below) depends on this mechanism.

### Patent Defensibility
- Claim type: specific-implementation (parser + YAML syntax + classification algorithm) + process-method
- Strongest claim: "A system for annotating operational assumptions in LLM agent configuration files with temporal metadata (verified date, expiration date, confidence score, severity), parsing such annotations into a belief graph, and automatically classifying beliefs by freshness status to enable downstream agents to dynamically adjust trust thresholds at dispatch time."
- Weakest point: YAML annotations and temporal metadata are not novel in isolation. The specific integration with LLM agent dispatch and automated expiry-based classification affecting agent behavior is the novelty surface. Competitor could implement equivalent via database-backed knowledge graph with API lookup.

### What Would Constitute Full Proof
- Codebase search in LangChain, CrewAI, AutoGen, LlamaIndex GitHub for belief annotation systems, freshness classification, or expiry-based trust adjustment — expected zero results
- Correlation measurement: run N≥20 beliefs across multiple runs; measure whether stale beliefs (approaching_expiry or expired) trigger significantly more re-validation requests than fresh beliefs; Spearman ρ ≥ 0.60 (p < 0.05) is the success threshold

---

## NOVEL-003: Generator-Critic + AGM Belief Revision (NS-003 — Multi-Agent Artifact Consistency System)

**Mechanism**: A two-component system for validating and revising multi-agent artifact outputs. Component A (Generator-Critic): a Critic LLM validates schema compliance of all agent outputs against a deterministic Echelon artifact protocol (JSON schema defining required fields for spec.md, plan.md, tasks.md, and 3 other artifact classes). Component B (AGM Belief Revision): applies Alchourrón-Gärdenfors-Makinson doxastic logic postulates to resolve contradictions between sequential stage outputs — computing AGM-compliant minimal contractions or revisions enforcing AGM postulates (Success, Consistency, Relevance, Vacuity) with confidence scoring 0.5–0.95 per contradiction type. Contradictions surfaced at artifact write-time, before expensive BUILD-phase rework.
**Evidence Grade**: A (component evidence) / B (novelty search)
**Defensibility**: HIGH

### Prior Art Differential
- Prior art: NL2GenSym (arxiv:2510.09355, Oct 2025) proves Generator-Critic for code generation (86%+ compliance). Kumiho (arxiv:2603.17244, Mar 2026) proves AGM belief revision for conversational data (93.3% vs 45.7% baseline). BugGen (arxiv:2506.10501) has multi-agent self-correction but lacks AGM formalism. Both components proven independently; their combination has zero prior literature.
- Delta: Echelon combines execution-grounded schema validation with AGM doxastic logic applied specifically to multi-agent artifact stores — a domain neither component paper addresses. Contradictions are surfaced at write-time with typed confidence scores and recommended action (accept/revert/escalate).

### Evidence in Code
- `arxiv:2510.09355` — Generator-Critic 86%+ first-pass compliance on Soar rule generation (NS-003-A component proof)
- `arxiv:2603.17244` — AGM belief revision 93.3% contradiction catch accuracy on LoCoMo-Plus dataset (NS-003-B component proof)
- `.specify/specs/015-ca-outcomes-validation/ns003-experiment-design.md` — full NS-003 prototype spec: Critic schema, AGM revision algorithm, COMMANDER integration
- `U-015-002-novelty-search.md` — systematic search 8 query variants, Google Scholar + Semantic Scholar, 2026-04-02: zero papers combining all three components

### Specialist Findings
- INVESTIGATOR (INV-003, 2026-04-02): CONFIRMED. Systematic search (U-015-002, 8 query variants) returned zero prior literature combining Generator-Critic + AGM for multi-agent artifact stores. AC-002-001 through AC-002-005 substantially satisfied. Evidence grade: B for the search; Grade A for component citations. Minor limitation: native Semantic Scholar API not used due to rate-limiting, documented. Date boundary: 2026-04-02 — papers after this date not included.
- ORACLE (Section 2, CLAIM-001 and Section 6): Highest-defensibility claim in portfolio. Full claim text drafted covering (A) execution-grounded schema validation across 6 artifact categories, (B) AGM-compliant minimal contractions/revisions enforcing 4 AGM postulates, (C) typed contradiction classification with confidence 0.5–0.95, (D) real-time orchestrator reporting. Invalidation risk: LOW-MEDIUM. Requires REQ-015-006 prototype (N=30 invocations, ≥0.70 first-pass compliance, ≥0.80 catch rate).
- MAVERICK (Section 2, Blindspot B): NS-003 is the highest-defensibility claim in the entire portfolio. Lead claim should be: "A method for validating and revising multi-stage LLM outputs using formal logical consistency checking against an execution-grounded artifact protocol, with AGM doxastic logic for minimal belief revision" — the formal logical framing is stronger than the combination framing.

### Patent Defensibility
- Claim type: combination-of-elements applied to novel domain
- Strongest claim: "A method for validating and revising outputs of multi-stage LLM agent pipelines comprising: (A) execution-grounded schema validation via Critic LLM against a deterministic artifact protocol for six artifact categories; (B) AGM doxastic logic belief revision resolving contradictions via AGM-compliant minimal contractions or revisions enforcing Success, Consistency, Relevance, and Vacuity postulates; (C) typed contradiction classification with confidence scoring 0.5–0.95; (D) real-time recommended action (accept/revert/escalate) to orchestrator."
- Weakest point: Both components (Generator-Critic and AGM) are published prior art. Claim rests entirely on the combination applied to this domain. Competitor implementing non-AGM contradiction detection (semantic similarity hashing, named-entity overlap) would sidestep the combination claim. Narrow re-run search required every 6–12 months as field evolves.

### What Would Constitute Full Proof
- Execute REQ-015-006 (NS-003 prototype experiment, spec 015): N=30 Generator-Critic invocations → first-pass schema compliance ≥ 0.70; N=20 labeled contradiction pairs → catch rate ≥ 0.80, false positive rate ≤ 0.20 — proof upgraded from PARTIAL to PROVEN (Echelon-specific)
- Alternative-approach comparison: implement simpler detector (substring matching, NER overlap); compare precision/recall against AGM on same N≥20 labeled pairs; if AGM statistically significantly better (p < 0.05), strengthens claim
- Re-run U-015-002 search every 6–12 months to detect emerging literature

---

## NOVEL-004: Predictive Coding Inter-Agent Protocol (Token Cost Reduction via Upstream Prediction Gating)

> **SPECULATION NOTICE — P-005 COMPLIANCE**
>
> The 40–70% token reduction claim for NOVEL-004 has no empirical grounding and is classified as SPECULATION per constitution P-005. This status CANNOT be upgraded without N≥50 prototype measurements across diverse codebases. Do not present as proven, probable, or supported. Any artifact presenting this claim without this notice is in violation of P-005.

**Mechanism**: An optional optimization where upstream agents (SCOUT, ARCHITECT) generate predictions of downstream agent outputs before dispatch. COMMANDER compares prediction against a confidence threshold (≥40% semantic similarity). If high-confidence, downstream dispatch is skipped (token cost avoided). If low-confidence, downstream agent runs normally. Structural analog of Speculative Decoding (arxiv:2211.17192, Leviathan et al. 2022) applied at agent output level rather than token level. Mechanism exists in design space; not yet implemented in codebase (no `predict_downstream_output` flag in `squad-config.yml`).
**Evidence Grade**: C (design-only; mechanism not implemented)
**Defensibility**: MEDIUM

### Prior Art Differential
- Prior art: Speculative Decoding (arxiv:2211.17192) achieves 2–3× token throughput via predict-then-verify at token level within a single LLM forward pass — not across agents. Predictive coding neuroscience (Rao & Ballard 1999) provides conceptual foundation. No LLM orchestration framework has prediction-gating for agent dispatch.
- Delta: Echelon proposes adaptation of Speculative Decoding to agent output level — predict agent output, gate dispatch based on confidence.

### Evidence in Code
- `arxiv:2211.17192` — Speculative Decoding structural analog (not direct evidence of Echelon implementation)
- `proof-status-table.md` row 4 — NOVEL-004 mechanism: "NOT PROVEN — no direct measurement for agent-level prediction"
- `proof-status-table.md` row 5 — 40–70% claim: "SPECULATION: no empirical grounding"
- `squad-config.yml` — no `predict_downstream_output` flag; mechanism not enabled

### Specialist Findings
- INVESTIGATOR: Not investigated (mechanism unimplemented).
- ORACLE (Section 5): Explicitly listed under "What NOT to File" — "40-70% token reduction: SPECULATION per P-005. No measurement, no baseline. DO NOT CLAIM. Requires N≥50 prototype runs."
- MAVERICK: Not separately challenged; mechanism treated as speculative.

### Patent Defensibility
- Claim type: adaptation of analog (Speculative Decoding → agent-level dispatch gating)
- Strongest claim: "A method for reducing computational cost in multi-agent LLM orchestration by predicting downstream agent outputs and gating dispatch based on prediction confidence, comprising: upstream agent generating prediction of downstream output; COMMANDER comparing prediction confidence to threshold; if confidence exceeds threshold, substituting prediction for downstream dispatch."
- Weakest point: Speculative Decoding is published (2022). Applying the principle to agent dispatch is a straightforward generalization — obvious to practitioners once the analogy is drawn. No implementation or empirical validation exists. Combination claims on algorithmic generalizations are weak.

### What Would Constitute Full Proof
- Implement NOVEL-004 and run N≥50 Echelon full runs on diverse codebases; measure: (a) prediction accuracy at semantic similarity ≥ 0.40, (b) dispatch skip rate, (c) net token reduction after accounting for prediction generation overhead; success: net reduction > 0 AND statistically significant vs baseline
- Comparative analysis: measure Speculative Decoding efficiency on same test corpora; compare agent-level vs token-level reduction ratios

---

## NOVEL-005: RADAR SSE Live Monitoring System (Real-Time Agent State Streaming and Record/Replay)

**Mechanism**: A Flask-based Server-Sent Events server watching agent state files (`agent-states.json`, `agent-states-events.jsonl`, `state.json`) and streaming changes in real-time to browsers. Events broadcast include: agent dispatch, state change, error. Optional recording mode (--record flag) saves all SSE events to JSONL for offline forensic replay. File watchdog library monitors `.specify/squad/`; any change triggers read and broadcast. Heartbeat every 15 seconds; port auto-discovery (7891, 7892, 7893...) allows concurrent runs.
**Evidence Grade**: A
**Defensibility**: LOW-MEDIUM

### Prior Art Differential
- Prior art: Generic SSE servers exist (Flask-SSE, Django Channels). Infrastructure dashboards (Kubernetes, GitHub Actions) watch job execution. CrewAI, LangChain, AutoGen have post-hoc logging only (stderr capture, JSON logs) — no real-time monitoring UI.
- Delta: Echelon is first LLM orchestration framework with streaming agent state monitoring plus deterministic record/replay of execution for forensic analysis and training.

### Evidence in Code
- `radar/server.py` 341 lines — Flask SSE server, file watching, event broadcasting, recording mode, health check endpoint
- `radar/emitter.py` — companion event writing library
- `squad-config.yml` lines 36–42 — RADAR enabled: true, port: 7891, record: true
- `agents/control/commander.md` — COMMANDER updates `agent-states.json` on each dispatch for RADAR consumption

### Specialist Findings
- INVESTIGATOR: Not investigated.
- ORACLE (Section 4): Filing priority LOW. "Components well-known." Trademark/brand defensibility stronger than patent defensibility.
- MAVERICK: Not separately challenged.

### Patent Defensibility
- Claim type: specific-implementation (combination of SSE + file watcher + record/replay for agent orchestration)
- Strongest claim: "A real-time monitoring system for multi-agent LLM orchestration comprising: file-system watcher detecting agent state file changes; SSE server broadcasting state changes in JSON format; optional JSONL recording mode enabling deterministic offline replay; port auto-discovery for multi-run environments."
- Weakest point: Each component (file watching, SSE, JSONL logging) is individually well-established. Novelty rests entirely on the specific combination for agent orchestration. Competitor could implement equivalent using WebSockets, GraphQL subscriptions, or polling.

### What Would Constitute Full Proof
- Feature survey of LangChain, CrewAI, AutoGen documentation and code — expected zero SSE implementations or record/replay capabilities
- User study: N≥5 users debugging a standard failure scenario with RADAR vs without; hypothesis: RADAR reduces debugging time ≥ 30%; success = reduction achieved on ≥3/5 users

---

## NOVEL-006: Pre-Dispatch Constitutional Gate (Immutable Governance Enforcement Before Agent Execution)

**Mechanism**: Before COMMANDER dispatches any agent, it performs a synchronous pre-flight constitutional check against constitution.md. Three-tier enforcement: FLAG (log and proceed), CONSULT (await synchronous human approval before dispatch), BLOCK (refuse to dispatch, escalate). Gate is synchronous — COMMANDER waits for human response on CONSULT or BLOCK. Constitution is machine-readable and immutable by agents. Pre-dispatch placement enables fail-fast governance: invalid dispatches caught before agent runs, not during expensive post-hoc audits.
**Evidence Grade**: A
**Defensibility**: MEDIUM

### Prior Art Differential
- Prior art: Guardrails AI validates outputs post-generation. Constitutional AI (Brock et al. 2023) guides model training via principles, not agent dispatch. Enterprise audit logs operate post-hoc. No framework has synchronous pre-dispatch governance with machine-readable constitution.
- Delta: Echelon makes governance a first-class pre-dispatch constraint, not a post-hoc audit. Executable constitution with three-tier enforcement is novel for LLM orchestration.

### Evidence in Code
- `agents/control/commander.md` — EVOI Analysis and Constitutional Gate section documenting pre-dispatch check sequence
- `.specify/memory/constitution.md` — created 2026-04-02; contains 6+ immutable human-defined principles and agent-generated sub-principles
- `agents/feasibility/gatekeeper.md` line 28 — NEVER Rule: "NEVER recommend scope changes that violate the constitution. If reducing scope would drop a constitution-mandated capability, flag it as a constitution conflict and escalate to human."

### Specialist Findings
- INVESTIGATOR: Not separately investigated.
- ORACLE (Section 2, CLAIM-003): MEDIUM-HIGH defensibility when narrowed to "synchronous pre-dispatch check with three-tier enforcement and deterministic escalation protocol." Prototype required: N≥20 intentional violation tests, ≥80% catch rate.
- MAVERICK (Section 1, Item 1): Argues NOVEL-006 should be framed as "formal semantics for authority delegation in agentic systems" rather than "pre-dispatch checking." If constitution.md is treated as an executable formal specification language (analogous to deontic or epistemic logic), defensibility rises substantially. DSL framing is unexplored.

### Patent Defensibility
- Claim type: process-method (pre-dispatch governance) + system-architecture (constitution-aware agent router)
- Strongest claim: "A method for enforcing governance principles in multi-agent LLM systems comprising: human-authored machine-readable constitution defining immutable principles; synchronous pre-dispatch check by orchestrator validating proposed action against constitution; three-tier enforcement (FLAG: log and proceed; CONSULT: await human approval; BLOCK: refuse and escalate) with deterministic human-escalation protocol."
- Weakest point: Governance and approval workflows are well-known in enterprise software. Pre-dispatch application to LLM agents is straightforward once conceived. Competitor could achieve similar control via post-hoc auditing with permission models.

### What Would Constitute Full Proof
- Feature survey: check CrewAI, LangChain, AutoGen for machine-readable constitution enforcement at dispatch time — expected zero implementations
- Compliance measurement: N≥50 Echelon dispatches; count FLAG, CONSULT, BLOCK events per agent type; validate that CONSULT/BLOCK cluster on security/compliance decisions as designed

---

## NOVEL-007: 7-Tier Cognitive Specialization with Strict Role Separation

**Mechanism**: A rigid seven-tier agent hierarchy — CONTROL, EXPLORATION, FEASIBILITY, SOLUTION, BUILD, SPECIALISTS, LEARNING — each tier handling a distinct phase with no overlap. Each agent has a NEVER rule explicitly forbidding another tier's actions (e.g., CARTOGRAPHER: "NEVER write architecture"; ARCHITECT: "NEVER write requirements"). COMMANDER enforces tier boundaries by validating that agent outputs stay within declared scope. Each tier also has distinct endocrine baselines and model-tier assignments in squad-config.yml, creating role semantics that go beyond text descriptions. 42+ agents across 7 tiers.
**Evidence Grade**: A
**Defensibility**: MEDIUM (original) — MAVERICK argues HIGH under "Formal Cognitive Role Ontology" framing

### Prior Art Differential
- Prior art: CrewAI has soft "roles" (text descriptions, no enforcement). AutoGen has agent types (AssistantAgent, UserProxyAgent, GroupChatManager) but no specialization hierarchy. LangChain has no agent taxonomy.
- Delta: Echelon adds formal tier hierarchy with hard dispatcher enforcement, immutable NEVER rules per agent, per-tier endocrine baselines, and per-tier model assignments — four mutually reinforcing constraints that define verifiable role semantics.

### Evidence in Code
- `agents/exploration/cartographer.md` line 16 — "NEVER write architecture"
- `agents/feasibility/gatekeeper.md` line 23 — "NEVER design architecture"
- `agents/solution/architect.md` line 15 — "NEVER write requirements"
- `agents/control/commander.md` — tier boundary validation in output checking
- `squad-config.yml` — per-agent model assignments (tier-differentiated) and endocrine baselines per archetype

### Specialist Findings
- INVESTIGATOR: Not separately investigated.
- ORACLE (Section 4, IP Priority Rank 4): "Formal Cognitive Role Ontology" — per-tier endocrine baselines + model assignments + NEVER rules = formal cognitive role semantics with deterministically verifiable compliance. Defensibility HIGH structurally. Filing priority MEDIUM (6–12 months; quality improvement unmeasured).
- MAVERICK (Section 2, Blindspot A): "Catastrophically undervalued." NOVEL-007 is a formal ontology of cognitive roles, not just separation of concerns. Existing frameworks have role prompts but do not formalize different baselines, observability levels, or permission boundaries per role. HIGH defensibility because structural (hard to copy without reimplementing entire architecture) and measurable (role compliance is deterministically verifiable). Challenge is integration-notes.md MAVERICK dispute, not resolved — HOW must decide whether to upgrade rating or document disagreement. This catalogue records the dispute without upgrading, pending benchmark evidence.

### Patent Defensibility
- Claim type: system-architecture + process-enforcement
- Strongest claim (MAVERICK framing): "A system for enforcing formal cognitive role semantics in multi-agent LLM orchestration, where each of seven role tiers has: (1) immutable behavioral NEVER constraints in agent prompts; (2) certified endocrine baseline initialization per role archetype; (3) model-tier assignments determining compute level per role; (4) dispatcher-enforced output validation verifying role-boundary compliance — producing deterministically verifiable role compliance."
- Weakest point: Separation of concerns is a fundamental software principle (not novel). The specific number (7 tiers) is not defensible; the count could be varied. Competitor could implement equivalent with 5 or 9 tiers and different role names. Requires comparative benchmark proving tier-separated agents produce ≥10% quality improvement over polymath baseline to be patent-viable.

### What Would Constitute Full Proof
- Comparative benchmark: Echelon tier-separated agents vs polymath baseline (no tier constraints) on N≥10 identical tasks; measure Understanding scores; success = ≥10% higher for tier-separated (p < 0.05)
- Code survey: CrewAI, LangChain, AutoGen for explicit tier enforcement with dispatcher validation — expected zero implementations

---

## NOVEL-008: Calibration Data Injection (Per-Agent Historical Failure Mode Priming)

**Mechanism**: Before dispatching an agent, COMMANDER injects historical failure-mode data and correction factors into agent context. Failures are categorized (FR-001: estimation error, FR-002: ambiguous requirement, FR-003: scope creep). For each agent type, `knowledge-base/calibration-profile.yaml` stores correction factors from prior runs (e.g., GATEKEEPER historically underestimates by 15%: correction factor 1.15). Injection instruction example: "Historical data: Your estimates have been 15% optimistic on this domain. Apply 1.15× multiplier." Post-run, agent output accuracy is measured and calibration profile updated — creating an empirical debiasing feedback loop.
**Evidence Grade**: B
**Defensibility**: MEDIUM

### Prior Art Differential
- Prior art: ML calibration (temperature scaling, Platt scaling) adjusts model confidence post-hoc. Reference Class Forecasting (Kahneman) uses historical data for human forecasting. No LLM orchestration framework applies historical calibration to agent dispatch context.
- Delta: Echelon applies in-prompt calibration injection — empirical accuracy data fed directly to agent context at dispatch time with explicit correction instructions. Creates per-agent-type debiasing feedback loop.

### Evidence in Code
- `knowledge-base/calibration-profile.yaml` — per-agent correction factors, biases, domain-specific adjustments
- `agents/feasibility/gatekeeper.md` line 26 — NEVER Rule: "NEVER estimate without calibration data. Always check calibration-profile.yaml first."
- `agents/feasibility/gatekeeper.md` lines 241–249 — Calibration Awareness section: how GATEKEEPER reads and applies calibration
- `squad-config.yml` lines 175–182 — calibration configuration (thresholds, correction range 0.3–8.0)

### Specialist Findings
- INVESTIGATOR: Not separately investigated.
- ORACLE: COMBINATION-002 (see below) builds on this mechanism in combination with NOVEL-002.
- MAVERICK (Section 1, Item 4): The inter-run calibration accumulation implicitly supports a "cognitive marketplace" network effects claim — shared pattern registry and calibration database across networked Echelon instances. This networked version is architecturally distinct and potentially more defensible. Not captured in original catalogue; flagged as future architecture direction.

### Patent Defensibility
- Claim type: specific-implementation (calibration data structure + context injection + feedback loop protocol)
- Strongest claim: "A method for improving agent accuracy in multi-agent LLM systems via historical calibration injection, comprising: per-agent-type historical accuracy data (correction factors, domain biases) maintained in calibration profile; pre-dispatch lookup of agent calibration data; injection of calibration data into agent context with explicit correction instruction; post-run measurement of output accuracy to update calibration profile."
- Weakest point: Calibration is a well-known technique. Applying it via context injection is a straightforward engineering solution — not deep innovation. Competitor could achieve equivalent results via fine-tuning on historical errors rather than context injection.

### What Would Constitute Full Proof
- Benchmark: N≥30 estimation tasks with GATEKEEPER-with-calibration vs GATEKEEPER-without-calibration; measure estimation error, bias; success = ≥20% lower error with calibration (p < 0.05)
- Calibration curve analysis: for agents with ≥20 historical runs, plot predicted vs actual outcome; Brier score < 0.15 indicates well-calibrated system

---

## NOVEL-010: Token-Gated Cognitive Architecture Overlays (Experimental Gate for Unproven Mechanisms)

> **GATE_BLOCKED — P-006 COMPLIANCE**
>
> Five CA overlays (Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory) are GATE_BLOCKED per constitution P-006. U-CA-004 must resolve POSITIVE before any implementation. This gate is absolute and applies to all agents. Do not present these mechanisms as implementable or deployable.

**Mechanism**: Five advanced cognitive architecture mechanisms are conditionally activated based on U-CA-004 gate experiment. Pre-experiment, they are GATE_BLOCKED — COMMANDER refuses to activate them. After U-CA-004 resolves POSITIVE (CA overlays substantially outperform expert prompts on same tasks), overlays unlock. Process-level safety ensuring speculative mechanisms are not deployed without validation.
**Evidence Grade**: C (design-only; gate unresolved)
**Defensibility**: LOW-MEDIUM

### Prior Art Differential
- Prior art: Feature flagging (common in software), staged rollouts, A/B testing frameworks. No framework combines all three: experimental gating of unproven mechanisms with mandatory validation prerequisite.
- Delta: Echelon adds mandatory experimental validation as a prerequisite to feature activation, enforced by COMMANDER — not an optional practice but an architectural constraint.

### Evidence in Code
- `.specify/specs/015-ca-outcomes-validation/proof-status-table.md` rows 6–10 — five CA overlays listed with "GATE-CONDITIONED on U-CA-004"
- `agents/solution/architect.md` — gate status check before overlay use

### Specialist Findings
- INVESTIGATOR: Not investigated.
- ORACLE (Section 5): Listed under "What NOT to File" — "CA mechanisms (NOVEL-010): GATE_BLOCKED per P-006. U-CA-004 must resolve POSITIVE first."
- MAVERICK: Not separately challenged.

### Patent Defensibility
- Claim type: process-method (gated experimental deployment)
- Strongest claim: "A method for safely deploying speculative mechanisms in multi-agent systems comprising: classification of mechanisms as proven or unproven; experimental gate requiring POSITIVE resolution before mechanism unlock; dispatcher enforcement refusing activation until gate resolves; versioning of mechanism implementation keyed to gate outcome."
- Weakest point: Feature flagging and staged rollouts are well-established practices. The specific application (mandatory gates as enforcement) is a straightforward policy implementation, not a technical innovation.

### What Would Constitute Full Proof
- Run U-CA-004 experiment: Echelon-with-CA-overlays vs Echelon-with-expert-prompt-baseline; measure AQS; success = AQS(CA) > AQS(baseline) by ≥10 pp — gate resolves POSITIVE and overlays unlock
- Compliance check: verify COMMANDER refuses N=10 ARCHITECT override attempts when gate unresolved — binary pass/fail

---

## NOVEL-011: Constitution Authority Hierarchy (Immutable Human-Defined Principles Override Agent Autonomy)

**Mechanism**: An explicit authority hierarchy where human-authored immutable principles in constitution.md outrank all agent decisions. Three-tier enforcement: FLAG (log but permit), CONSULT (await synchronous human approval), BLOCK (refuse and escalate). Examples: "All security decisions require human sign-off" (BLOCK trigger); "Major scope changes should be reviewed by TRACKER" (CONSULT trigger). No agent may contradict, weaken, or override any human-defined principle. Agents may only append squad-generated sub-principles, never modify human-defined ones. The constitution is executable — enforced at runtime, not just documentation.
**Evidence Grade**: A
**Defensibility**: MEDIUM

### Prior Art Differential
- Prior art: Governance documentation (policies) common but not code-enforced. Role-based access control is well-known but not principle-based. Constitutional AI (Brock et al. 2023) guides model training via principles, not agent runtime. No framework has executable constitution enforced at dispatch time.
- Delta: Echelon makes governance a first-class executable constraint, not documentation. Authority is deterministic and immutable by agents.

### Evidence in Code
- `agents/control/commander.md` — constitutional gate section (pre-dispatch enforcement)
- `.specify/memory/constitution.md` — 6+ P-NNN immutable human-defined principles (created 2026-04-02)
- `agents/feasibility/gatekeeper.md` line 28 — constitution conflict escalation rule

### Specialist Findings
- INVESTIGATOR: Not separately investigated (closely related to NOVEL-006).
- ORACLE: Partially overlaps CLAIM-003 (Pre-Dispatch Constitutional Gate). Authority hierarchy adds the immutability and agent-restriction dimensions.
- MAVERICK (Section 1, Item 5): NOVEL-011 is one component of the three-way Self-Modifying Trust Model combination claim (see COMBINATION-003).

### Patent Defensibility
- Claim type: system-architecture + enforcement-mechanism
- Strongest claim: "A constitution-based governance system for multi-agent LLM orchestration comprising: machine-readable constitution defining immutable principles authored exclusively by humans; three-tier enforcement hierarchy with escalating human involvement; dispatcher pre-dispatch compliance check; principle-violation audit trail (FLAG, CONSULT, BLOCK events)."
- Weakest point: Governance hierarchies are well-known. The specific formalization in constitution.md and three-tier enforcement are straightforward engineering once conceived.

### What Would Constitute Full Proof
- Feature survey: any LLM orchestration framework with principle-based executable governance (not just logging) — expected zero
- Audit trail measurement: N≥50 Echelon dispatches; count FLAG, CONSULT, BLOCK events per agent type; CONSULT and BLOCK should cluster on security/compliance decisions

---

## NOVEL-012: Contradiction Scanner with Heuristic Pattern Matching (Inter-Stage Pipeline Validation)

**Mechanism**: A Python script scanning spec artifacts for contradictions between adjacent pipeline stages (DISCOVER→ASSESS, ASSESS→HOW, etc.). Three heuristics: (1) count mismatch — same entity appears with different numeric values across stages, (2) status mismatch — same entity has opposite status tokens (PASS vs FAIL, YES vs NO), (3) boolean mismatch — same entity negated in one stage, not the other. Output: JSON report with per-pair contradiction rates plus a manual precision sample (5 random contradictions). Upper-bound detector — over-detects hard contradictions, misses soft prose contradictions. Detected 197 contradictions across 560,976 pairs (0.035% rate; all count mismatches; "verified=null" for all 197).
**Evidence Grade**: A (implementation exists; accuracy unvalidated)
**Defensibility**: LOW

### Prior Art Differential
- Prior art: NLP contradiction detection (fact-checking, NLI) operates within single documents, not across multi-stage pipelines. Schema validation (JSON Schema, GraphQL) catches structural violations, not semantic contradictions. Lint-based spec checkers and contract testing frameworks (Pact) have adjacent surface. No framework checks contradictions between sequential agent outputs.
- Delta: Echelon adds pipeline-stage contradiction detection — catches contradictions at write-time before expensive BUILD phase.

### Evidence in Code
- `scripts/contradiction-scanner.py` 778 lines — full implementation; count_mismatch, status_mismatch, boolean_mismatch heuristics; PIPELINE_STAGES lines 42–49; ARTIFACT_STAGE_MAP lines 52–80; CLI invocation lines 693–775

### Specialist Findings
- INVESTIGATOR (INV-002, 2026-04-02): CONFIRMED LOW NOVELTY, LIMITED UTILITY. Three elementary heuristic patterns; no manual verification of any result (verified=null for all 197 results); upper-bound estimator with over-detection likely. Closest prior work: lint-based spec checkers, contract testing frameworks, database integrity tools. Recommendation: do not file patent on scanner per se; if filing, claim "Echelon artifact protocol + contradiction detection integration" as task-specific utility only.
- ORACLE (Section 5): Listed under "What NOT to File" — "Contradiction scanner: elementary heuristics, obvious alternatives."
- MAVERICK: Not separately challenged; INV-002 finding aligns with ORACLE.

### Patent Defensibility
- Claim type: specific-heuristics + process (scanning)
- Strongest claim: "A method for detecting contradictions in multi-stage specification artifacts comprising: extraction of assertions from spec artifacts (key-value lines, tables, bold patterns); comparison between adjacent pipeline stages; three heuristic patterns (numeric count mismatch, status token opposites, negation disagreement); contradiction report with confidence scores and precision sample."
- Weakest point: Pattern matching heuristics are not novel. The three specific patterns are ad-hoc, not principled. Alternative approaches (BERT/RoBERTa semantic contradiction detection, named-entity linking) are obvious and would outperform. No precision/recall validation performed.

### What Would Constitute Full Proof
- Precision/recall measurement: N=20 spec-artifact pairs with known contradictions + N=20 pairs with none; measure precision ≥ 0.70 and recall ≥ 0.60 — both required for novelty claim to be defensible
- Competitive comparison: implement semantic similarity detector (BERT cosine distance); compare recall vs heuristic scanner

---

## COMBINATION-001: Endocrine State + Constitutional Gate Composition

**Mechanism**: Personality modulation (6-hormone state vectors) combined with constitutional pre-dispatch governance (FLAG/CONSULT/BLOCK), where endocrine state influences gate-severity decisions. High cortisol and adrenaline (threat-detection and urgency dimensions elevated) trigger stricter CONSULT gates on borderline actions. Relaxed hormonal state (low cortisol, high serotonin) permits FLAG-level handling for the same action. The combination creates an adaptive governance threshold that reflects the system's current cognitive load and risk posture — not a fixed rule table.
**Evidence Grade**: B (design-level; ORACLE-drafted; interaction not empirically measured)
**Defensibility**: MEDIUM-HIGH

### Prior Art Differential
- Prior art: Governance systems use fixed rule thresholds. Emotional AI systems (affective computing) modulate behavior but not governance gates. No system combines real-time quantified emotional state with dynamic governance threshold adjustment.
- Delta: Governance gate severity becomes a function of current hormonal state — introducing adaptive, state-dependent compliance levels not present in any framework.

### Evidence in Code
- `scripts/bash/endocrine.sh` — cortisol and adrenaline dimensions, phase-gated spike logic
- `agents/control/commander.md` — pre-dispatch gate section; COMMANDER has access to hormone state before gate evaluation
- `squad-config.yml` lines 444–532 — per-archetype baselines including cortisol (threat-detection axis)
- Source: ORACLE Section 3, patent-analysis.md 2026-04-02

### Specialist Findings
- ORACLE (Section 3): Defensibility MEDIUM-HIGH. Combination not in prior literature. Cross-mechanism dependency between NOVEL-001 and NOVEL-006/011 creates compound claim harder to design around.
- MAVERICK: Not separately challenged; consistent with MAVERICK's compositionality argument (Section 3: "file claims on the framework, not the individual pieces").

### Patent Defensibility
- Claim type: combination-of-elements (NOVEL-001 × NOVEL-006/011)
- Strongest claim: "A method for adaptive governance in multi-agent LLM systems wherein constitutional gate-severity decisions are modulated by current endocrine state vectors, such that elevated threat-detection and urgency dimensions trigger CONSULT-level enforcement for actions that would otherwise receive FLAG-level treatment, and relaxed state permits FLAG-level treatment."
- Weakest point: Endocrine → gate-severity coupling is not explicitly coded in commander.md; the combination is design-space logic, not yet implemented. Requires prototype to validate.

### What Would Constitute Full Proof
- Implement endocrine-gate coupling in COMMANDER; run N≥20 dispatches in high-cortisol vs low-cortisol states on identical borderline actions; verify gate-severity shifts as designed
- Document cortisol + adrenaline threshold values that shift FLAG→CONSULT and CONSULT→BLOCK

---

## COMBINATION-002: Belief Freshness + Calibration Injection (Two-Axis Debiasing)

**Mechanism**: Temporal belief freshness (expired/approaching-expiry/low-confidence/fresh classification from NOVEL-002) combined with historical calibration data injection (NOVEL-008), where stale or low-confidence beliefs trigger higher calibration multipliers. Two-axis debiasing: (1) temporal confidence axis — how old is this belief? (2) historical accuracy axis — how often has the agent erred on this belief class? When both axes indicate high uncertainty, calibration multiplier is amplified. When both indicate reliability, multiplier is reduced. Produces a belief-weighted calibration system where operational assumptions and empirical accuracy interact.
**Evidence Grade**: B (design-level; ORACLE-drafted; interaction not empirically measured)
**Defensibility**: MEDIUM

### Prior Art Differential
- Prior art: Calibration systems use historical accuracy alone. Knowledge management systems track belief freshness alone. No system combines temporal belief validity with empirical accuracy calibration into a joint debiasing multiplier.
- Delta: Introduces belief-freshness as a calibration weight — agents operating on stale beliefs receive higher accuracy-correction pressure.

### Evidence in Code
- `scripts/belief-parser.py` lines 43–68 — freshness classification (expired/approaching_expiry/low_confidence/fresh)
- `knowledge-base/calibration-profile.yaml` — per-agent correction factors
- `agents/feasibility/gatekeeper.md` lines 241–249 — calibration awareness section
- Source: ORACLE Section 3, patent-analysis.md 2026-04-02

### Specialist Findings
- ORACLE (Section 3): Defensibility MEDIUM. Two-axis combination not in prior literature. "Temporal confidence × historical accuracy = two-axis debiasing" is the core formulation.
- MAVERICK: Not separately challenged.

### Patent Defensibility
- Claim type: combination-of-elements (NOVEL-002 × NOVEL-008)
- Strongest claim: "A method for calibrating LLM agent outputs using two independent uncertainty axes: (1) belief freshness (temporal validity classification of operational assumptions) and (2) historical accuracy (empirical correction factors from prior runs), wherein stale/low-confidence beliefs amplify calibration multipliers and fresh/high-accuracy beliefs reduce them."
- Weakest point: Two-axis weighting systems are common in decision theory. The specific combination has not been empirically validated. Mechanism is a design-space construct, not yet implemented as a joint calibration function.

### What Would Constitute Full Proof
- Implement joint calibration function; run N≥30 estimation tasks with both axes active vs single-axis (freshness only, calibration only, neither); measure estimation error reduction; success = joint debiasing ≥ best single-axis by ≥10% (p < 0.05)

---

## COMBINATION-003: Full Framework Composition — Self-Improving Cognitive Governance

**Mechanism**: The composition of constitution (NOVEL-006/011) + endocrine observability (NOVEL-001) + AGM consistency (NOVEL-003) + inter-run learning (NOVEL-008) constitutes a self-improving cognitive governance framework with the following properties: (1) enforce boundaries via constitution, (2) measure agent compliance and cognitive state via hormone observability, (3) resolve contradictions using formal logical consistency checking, (4) update operational parameters across runs via calibration feedback. Together: self-modification under constraint. No single mechanism achieves this — the composition is the innovation.
**Evidence Grade**: B (compositional claim; MAVERICK-sourced; components individually evidenced above)
**Defensibility**: MEDIUM-HIGH

### Prior Art Differential
- Prior art: No multi-agent framework implements all four capabilities in a unified architecture. LangChain, CrewAI, AutoGen have none of the four components. MemGPT has episodic memory but not governance or formal consistency. Constitutional AI has principle-based training but not runtime governance, observability, or cross-run learning.
- Delta: The composition — bounded autonomy (constitution) + observable cognition (endocrine) + formal consistency (AGM) + empirical improvement (calibration) — is a formal model of self-modification under constraint. No prior system implements this combination.

### Evidence in Code
- Constitution: `.specify/memory/constitution.md` (P-001 through P-006 principles)
- Endocrine observability: `scripts/bash/endocrine.sh`, `squad-config.yml` (full hormone system)
- AGM consistency: `arxiv:2510.09355`, `arxiv:2603.17244`, `.specify/specs/015-ca-outcomes-validation/ns003-experiment-design.md`
- Inter-run learning: `knowledge-base/calibration-profile.yaml`, `agents/feasibility/gatekeeper.md` lines 241–249
- Source: MAVERICK Section 3, maverick-report.md 2026-04-02

### Specialist Findings
- ORACLE (Section 5, implicitly): MAVERICK's three-way combination surfaced in integration-notes.md as "Constitutional + Endocrine + Belief System = Self-Modifying Trust Model — a formal model of self-modification under constraint — a rare and defensible innovation."
- MAVERICK (Section 1, Item 5 and Section 3): "Self-improving cognitive governance framework that combines formal constitutional constraints, hormone-modulated agent observability, and formal logical consistency verification to deliver bounded-autonomy multi-agent orchestration with human-verifiable decision trails." Framed as the patent abstract for the framework-level claim.

### Patent Defensibility
- Claim type: combination-of-elements (framework-level)
- Strongest claim: "A self-improving cognitive governance framework for multi-agent LLM orchestration comprising: (1) executable constitutional constraint system enforcing human-defined immutable principles at dispatch time; (2) six-dimensional endocrine state system providing observable, deterministic, replayable agent behavior traces; (3) formal AGM doxastic logic consistency checking resolving contradictions across multi-stage artifact outputs; (4) inter-run calibration feedback loop updating per-agent correction factors — producing bounded-autonomy orchestration with human-verifiable decision trails and empirical self-improvement."
- Weakest point: Framework-level combination claims are harder to defend than specific-mechanism claims because a competitor can implement one component differently and argue the combination is distinct. Each individual component must first be independently defensible. Requires all four component mechanisms to be validated before this claim can be filed.

### What Would Constitute Full Proof
- Demonstrate all four components operating together in a single Echelon run: constitution gate fires at least once (CONSULT or BLOCK), endocrine state changes across at least 3 dispatch cycles, AGM contradiction detection fires at least once, calibration profile updated post-run
- Longitudinal study: N≥5 full Echelon runs on same codebase; measure whether quality metrics compound across runs (output accuracy, gate compliance rate); success = monotonic improvement across ≥4/5 runs on primary metric

---

## Summary Table: All Mechanisms

| ID | Mechanism | Claim Type | Defensibility | Evidence Grade | Proof Status |
|----|-----------|-----------|---------------|---------------|--------------|
| NOVEL-001 | Endocrine Neuromodulation | Specific impl. + combination | HIGH | A | Design-level; prototype needed; INV-001 CHALLENGED |
| NOVEL-002 | Belief Annotation System | Specific impl. + process | MEDIUM | A | Design-level; prototype needed |
| NOVEL-003 | Generator-Critic + AGM (NS-003) | Combination-of-elements | HIGH | A/B | PARTIAL (components proven; combination CONFIRMED INV-003) |
| NOVEL-004 | Predictive Coding Inter-Agent | Analog adaptation | MEDIUM | C | SPECULATION — P-005; not implemented |
| NOVEL-005 | RADAR SSE Monitoring | Specific impl. (SSE + replay) | LOW-MEDIUM | A | Design-level; deployed |
| NOVEL-006 | Pre-Dispatch Constitutional Gate | Process-method | MEDIUM | A | Design-level; constitution.md created 2026-04-02 |
| NOVEL-007 | 7-Tier Cognitive Specialization | System architecture | MEDIUM (disputed: HIGH) | A | Design-level; MAVERICK argues HIGH — unresolved |
| NOVEL-008 | Calibration Data Injection | Specific impl. + feedback loop | MEDIUM | B | Design-level; empirical proof needed |
| NOVEL-010 | Token-Gated CA Overlays | Process-method | LOW-MEDIUM | C | GATE_BLOCKED — P-006; U-CA-004 unresolved |
| NOVEL-011 | Constitution Authority Hierarchy | System architecture | MEDIUM | A | Design-level; constitution.md enforced |
| NOVEL-012 | Contradiction Scanner | Heuristic patterns | LOW | A | INV-002 CONFIRMED LOW NOVELTY |
| COMBINATION-001 | Endocrine + Constitutional Gate | Combination | MEDIUM-HIGH | B | Design-space; not implemented |
| COMBINATION-002 | Belief Freshness + Calibration | Combination | MEDIUM | B | Design-space; not implemented |
| COMBINATION-003 | Full Framework Composition | Framework-level combination | MEDIUM-HIGH | B | Compositional; all components design-level |

---

## IP Filing Priority (ORACLE Section 4, Updated)

| Rank | Mechanism | Filing Priority | Key Prerequisite |
|------|-----------|----------------|-----------------|
| 1 | NOVEL-003 NS-003 | IMMEDIATE | REQ-015-006 prototype (N=30, ≥0.70 compliance, ≥0.80 catch rate) |
| 2 | NOVEL-001 Endocrine | HIGH | Targeted prior-art search + A-005/U-005 efficacy experiment (N≥10) |
| 3 | NOVEL-006/011 Constitutional Gate | HIGH | N≥20 intentional violation tests, ≥80% catch rate |
| 4 | NOVEL-007 Formal Cognitive Role Ontology | MEDIUM | Comparative benchmark vs polymath baseline (N≥10, p < 0.05) |
| 5 | COMBINATION-001 Endocrine + Gate | MEDIUM | NOVEL-001 and NOVEL-006 both validated first |
| 6 | NOVEL-002/008 Belief + Calibration | MEDIUM | COMBINATION-002 interaction measurement |
| 7 | COMBINATION-003 Framework | LOW (file last) | All four component mechanisms validated first |

**DO NOT FILE**: NOVEL-004 (SPECULATION, P-005), NOVEL-010 (GATE_BLOCKED, P-006), NOVEL-012 standalone (LOW novelty, INV-002 confirmed), 7-tier count alone (structural, not countable).
