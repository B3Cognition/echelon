# Assumptions — Spec 015 (CA Outcomes Validation)
**Agent**: SCOUT | **Run**: squad-1775154996 | **Date**: 2026-04-02
**Purpose**: Expose the tacit assumptions embedded in each claimed outcome. For each assumption: state it precisely, classify it, and identify whether spec 014 research validated it.

---

## Assumption Classification

| Class | Meaning |
|-------|---------|
| VALIDATED | Spec 014 research directly confirms the assumption |
| PARTIALLY VALIDATED | Spec 014 research provides partial or indirect support |
| OPEN | The assumption has not been examined; it is tacit |
| FALSIFIED | The assumption has been shown to be incorrect or requires significant qualification |

---

## NS-003: Self-Correcting Artifact Store

### A-NS-001: Echelon's artifact protocol has a parseable schema

**Tacit assumption**: The Generator-Critic mechanism requires a formal schema to validate agent outputs. For the Critic to function deterministically, the schema must be parseable by code (not by an LLM).

**Is the schema defined?**: Partially. The Echelon artifact protocol uses structured markdown with defined section headers per agent type (e.g., DISCOVER outputs a "Findings" section, a "Components" section). This structure exists in the agent prompt definitions (e.g., commander.md references artifact sections, architect.md references plan.md structure). However, no machine-parseable JSON Schema or typed interface exists in the current codebase. The schema is implicit in the agent prompts, not exported as a formal artifact.

**Status**: PARTIALLY VALIDATED. The structure exists; the formalization does not. Creating a JSON Schema for each agent's output type is a prerequisite for NS-003 deployment that requires 1-2 days of engineering effort per agent type.

**Source**: Echelon agent prompts (commander.md context pack references, architect.md plan.md structure); spec 014 plan.md Component 1 (Critic operations: "schema for this agent's output type" — implies the schema must be authored).

**Implication**: NS-003 cannot deploy without this prerequisite. The assumption is achievable but not yet satisfied.

---

### A-NS-002: The belief graph can represent Echelon's artifact assertions as triples

**Tacit assumption**: AGM belief revision requires facts to be representable as discrete, comparable propositions (triples: subject-predicate-object or equivalent). Echelon agents produce prose mixed with structured sections. Extracting propositions from prose requires either a structured output format or an additional LLM parsing call.

**Status**: OPEN. Spec 014 plan.md describes BeliefNode entities (content, source agent, version, confidence, contradiction flag) but does not specify how prose agent output is decomposed into BeliefNode facts. The Kumiho architecture (Redis + Neo4j) assumes structured input. The plan.md proposes a networkx graph for prototype — same structural requirement.

**Source**: Spec 014 plan.md, Component 2 (Belief Revision); Kumiho paper architecture description.

**Implication**: Two possible resolution paths: (a) mandate structured output from agents (JSON-formatted assertions alongside prose findings), or (b) add an LLM extraction call that parses prose into triples before belief graph ingestion. Path (b) adds token cost and a new failure surface. Path (a) requires agent prompt redesign. Neither path is free.

---

### A-NS-003: The NL2GenSym 86% compliance result transfers to Echelon's task class

**Tacit assumption**: The Generator-Critic mechanism that achieves 86%+ schema compliance on Soar rule generation will achieve comparable compliance rates on Echelon's artifact sections.

**Status**: PARTIALLY VALIDATED. The mechanism is general (any formally defined schema + execution-grounded feedback). However, Soar rules have a precise BNF grammar — the Critic can use a parser for exact binary validation. Echelon artifact sections are structured markdown: richer, more open-ended, with soft constraints (a "Findings" section should contain findings, not code). The Critic's precision degrades as the schema becomes softer. The 86% result is a ceiling for the mechanism on a well-constrained task; Echelon's less constrained task is likely to yield lower first-pass rates.

**Source**: NL2GenSym paper (SRC-A1); spec 014 plan.md (Component 1, note on schema types).

**Implication**: The 86% number should not be cited as the expected Echelon compliance rate. The correct claim is: "NL2GenSym demonstrates the mechanism works at 86% on a tightly constrained schema; Echelon's prototype measurement will establish the actual compliance rate for its task."

---

## NOVEL-004: Predictive Coding Broadcast

### A-NV-001: Upstream agents can generate structured prediction packets without additional LLM calls

**Tacit assumption**: The forward model (the prediction of downstream agent findings) is cheap — template-based or rule-based — and does not require invoking a large LLM. The mechanism's efficiency claim depends on this: if generating the prediction costs as many tokens as the full downstream call, there is no net saving.

**Status**: OPEN. No specification of the prediction format or generation method exists beyond the high-level description in alternatives.md (NOVEL-004). The phrase "template-based forward model" appears in alternatives.md, but no template is defined. The prediction complexity scales with the downstream agent's task complexity: predicting what ASSESS will find given DISCOVER's output requires either a rule (IF DISCOVER finds "no rate limiting" THEN ASSESS will classify as "availability risk") or a small LLM call.

**Source**: Spec 014 alternatives.md NOVEL-004; Speculative Decoding (SRC-A5, which uses a small model, not zero-cost prediction).

**Implication**: The "template-based" assumption requires validation that a rule-set of manageable size can cover a sufficient proportion of the DISCOVER→ASSESS prediction space. If the rule set is large and brittle, a small LLM prediction call is more robust but partially undercuts the efficiency gain.

---

### A-NV-002: The prediction accuracy break-even at 40-50% is correct for this context

**Tacit assumption**: The break-even prediction accuracy for NOVEL-004 (the proportion of correct predictions needed to offset prediction-generation overhead) is analogous to Speculative Decoding's break-even. Speculative Decoding achieves break-even when the small model's acceptance rate ≥ 40-50%.

**Status**: OPEN. The analogy is structural (predict-then-verify at different abstraction levels) but the cost structure differs. In Speculative Decoding, the small model is much cheaper than the large model, and the verification step is near-zero (large model processes the same context). In NOVEL-004, the prediction check requires parsing and comparing agent outputs (non-zero cost), and the downstream agent invocation is cheaper relative to the prediction overhead than in Speculative Decoding. The break-even may be higher (requiring 60-70% accuracy, not 40-50%).

**Source**: Speculative Decoding (SRC-A5); spec 014 alternatives.md NOVEL-004 (risk section mentions 40-50% estimate).

**Implication**: The 40-50% break-even should be treated as a lower bound estimate, not a validated threshold. The actual break-even requires prototype measurement.

---

## ACT-R Typed Buffer

### A-AR-001: Relevance and recency of context items are quantifiable without an LLM call

**Tacit assumption**: The activation formula `activation(chunk) = recency_weight × relevance_score` can be computed without invoking a large LLM. Relevance is computed as cosine similarity between chunk embedding and goal buffer embedding (requires an embedding model). Recency is computed from stage timestamps (deterministic).

**Status**: VALIDATED (in principle). Embedding-based relevance scoring is standard practice (sentence-transformers, OpenAI ada-002, etc.). The computation is cheap relative to LLM generation. The formula is explicitly labeled Grade C (approximation to spreading activation) in spec 014 plan.md — the assumption is validated but the equivalence to ACT-R activation is not.

**Source**: Spec 014 plan.md REQ-CA-006; "Lost in the Middle" (SRC-A4, validates that context ordering affects LLM output quality).

**Caveat**: The embedding similarity relevance score assumes the goal buffer embedding captures the full scope of what the agent needs from the artifact store. If the goal buffer is too high-level (a one-line description), the cosine similarity will miss relevant chunks that use different vocabulary. Goal buffer quality is a prerequisite for relevance scoring quality.

---

### A-AR-002: Context token reduction will not degrade output quality

**Tacit assumption**: Injecting only the top-K activation-scored chunks (instead of the full artifact store) will not cause the agent to miss critical information that would have been in the truncated context.

**Status**: OPEN. This is the core risk of the ACT-R buffer approach. The "Lost in the Middle" result (SRC-A4) shows that information in the middle of context is underweighted — but this argues for better ordering, not necessarily truncation. Truncation removes content entirely. The assumption that the top-K retrieved chunks contain all necessary content is not validated; it is an application of information retrieval assumptions to a generative context.

**Source**: Spec 014 plan.md (estimated_net_delta: null — explicitly unresolved); ACON (SRC for compression ceiling); U-CA-002 (token reduction measurement — OPEN).

**Implication**: The ACT-R typed buffer prototype must include a quality degradation test: compare agent output quality (human-rated or evaluated against a ground truth) with full context vs typed buffer. Token reduction is only valuable if quality is maintained.

---

## LIDA Broadcast

### A-LB-001: All 42 agents have a defined "scope" that can be matched to findings

**Tacit assumption**: For LIDA broadcast to work — sending critical findings to all relevant agents simultaneously — there must be a machine-readable scope declaration per agent that allows the router to determine which agents are relevant for a given finding.

**Status**: OPEN. Echelon's 42-agent architecture (confirmed in spec 014 ISS-001, which also noted the 7-stage vs 42-agent discrepancy that is OPEN). Each agent prompt defines its role in natural language (e.g., "You are ARCHITECT — you make technology decisions"). No machine-parseable scope tag or scope schema exists in the current agent definitions. The commander.md routes based on pipeline stage, not on agent-scope matching.

**Source**: Agent prompt files (commander.md, architect.md, etc.); spec 014 ISS-001 (CRITICAL: target system architecture unresolved).

**Implication**: LIDA broadcast requires a scope formalization step that does not exist. This is a substantial prerequisite — one scope declaration per agent (42 agents), agreed upon by the squad maintainers, and parseable by the routing layer.

---

## Episodic Memory

### A-EM-001: Prior run artifacts are content-addressable by a meaningful key

**Tacit assumption**: The episodic memory overlay requires that prior run artifacts can be retrieved by content similarity — not by run ID or timestamp alone. This requires an embedding index over prior artifact content.

**Status**: OPEN. The current Echelon storage is file-based (per spec 014 plan.md: "The artifact store is file-based"). Files are named by spec ID and agent type (e.g., `014-cognitive-architecture-llm-framing/research.md`). There is no embedding index. Retrieval by content similarity requires an offline indexing job that runs after each spec completes.

**Source**: Squad config (knowledge_base stale_threshold_months: 12, max_entries: 500 — a knowledge base config exists but is not the same as an embedding index over spec artifacts); spec 014 plan.md; MemGPT (SRC for episodic memory in LLM agents).

**Proof of prior run corpus**: 9 spec runs are available (specs 008-015, minus 015 itself which is current). This is a thin corpus for episodic memory — meaningful retrieval probably requires 20+ runs minimum to cover the codebase patterns that would constitute "reuse opportunities."

**Implication**: The episodic memory claim requires two prerequisites: (a) an embedding index built over the available spec run corpus, and (b) a demonstration that the retrieved artifacts actually improve agent output quality for similar codebases. Neither exists. Both are 1-2 week engineering efforts.

---

## AC-3 Constraint Propagation

### A-AC-001: A constraint ontology exists or can be built from available sources

**Tacit assumption**: AC-3 requires a constraint network: variables, domains, and binary constraints between them. For Echelon, the constraints encode the logical dependencies between pipeline stages (DISCOVER facts constrain ASSESS assertions, etc.). This constraint ontology must be authored and maintained.

**Status**: OPEN. No constraint ontology exists for Echelon. The logical dependencies between stages are implicit in the agent prompts and the pipeline sequence, not formalized as a machine-readable constraint graph. Authoring this ontology requires domain knowledge of the pipeline's intended logical invariants.

**Source**: Spec 014 alternatives.md NOVEL-003 (constraint schema: "designed once per pipeline stage type and is static"); AC-3 literature (Mackworth 1977).

**Feasibility note**: The constraints for two adjacent stages (DISCOVER → ASSESS) are the most tractable starting point. A minimal constraint ontology covering three DISCOVER finding types (architecture pattern, authentication mechanism, data flow) and their ASSESS implications could be authored in 2-3 days. This is the minimum viable constraint network for a feasibility test.

---

### A-AC-002: The LLM will respect constraint certificates injected into context

**Tacit assumption**: Injecting a constraint certificate ("The following outputs are inconsistent with the established artifact state: [list]") will cause the LLM to avoid generating those outputs. The LLM is "prompted to respect constraints" but not "formally forced to."

**Status**: PARTIALLY VALIDATED (by analogy). Instruction-following capabilities of Claude Opus 4.x on explicit negative constraints ("do NOT include X") are documented qualitatively but not measured in an Echelon-specific context. The mechanism is acknowledged as "soft guidance" in spec 014 alternatives.md (NOVEL-003 risk section).

**Source**: Spec 014 alternatives.md NOVEL-003 (risk: "The LLM is not logically forced to respect the constraints, only prompted to"); Anthropic documentation on instruction following.

**Implication**: The constraint certificate provides probabilistic, not deterministic, pruning. The measurable outcome is "violation rate reduction," not "zero violations." The useful question is: by how much does the constraint certificate reduce the violation rate compared to no certificate? This is measurable in a prototype.
