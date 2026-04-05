# Assumptions — Echelon Proto

## Critical Assumptions

### A-001: Claude Opus Model Executes All Agents (BANZAI Mode)
- **Statement:** All 42 agents run on Claude 3.5 Opus (BANZAI config); learning tier falls back to Sonnet for cost-savings. Opus provides sufficient reasoning capability for each agent's task.
- **Basis:** BANZAI design choice; squad-config.yml hardcodes all tiers to opus model
- **Risk if wrong:** Sonnet-class models may lack nuance for complex reasoning (ARCHITECT design, GATEKEEPER feasibility analysis, SAGE challenge). Quality degradation unpredictable.
- **Validation method:** Run same spec with Sonnet on all tiers vs Opus baseline; measure Understanding metric differences on quality dimensions (cognitive, semantic, depth)
- **Status:** Unvalidated (design assumption, not empirically tested)

### A-002: 42 Agents is Optimal Tier-Specialization Depth
- **Statement:** Seven tiers with 3–11 agents per tier provides right balance between specialization (deep expertise per agent) and coordination overhead (managing N agents is O(N²) complexity). Moving to 5 tiers or 10 tiers would degrade quality or increase token cost.
- **Basis:** Design experience; no formal optimization
- **Risk if wrong:** Over-specialization (too many tiers) causes coordination bottlenecks. Under-specialization (fewer agents) causes role confusion. Unknown where optimum is.
- **Validation method:** Ablation study: remove agents from one tier (e.g., 3 specialists instead of 6), measure quality metrics. Hypothesis: quality drops. If quality stays same, agent count can be reduced.
- **Status:** Unvalidated

### A-003: Phase Sequencing (DISCOVER → WHY → WHAT → ASSESS → HOW → PLAN → BUILD → LEARN) is Optimal
- **Statement:** The 8-phase sequence cannot be reordered. DISCOVER must precede WHAT (can't write spec before understanding domain). WHAT must precede HOW (can't design before knowing requirements). No phase skipping.
- **Basis:** Logical dependencies (requirements before architecture) + empirical heuristic from software engineering
- **Risk if wrong:** Alternative orderings (e.g., ASSESS before HOW, exploratory prototyping before requirements) might improve time-to-delivery or quality in some domains
- **Validation method:** Run same spec using alternate phase sequences (e.g., WHAT→DISCOVER, HOW→ASSESS); measure quality and time. If alternate outperforms, sequence assumption is violated.
- **Status:** Unvalidated (logical foundation strong, empirical test pending)

### A-004: Unlimited Token Budget (BANZAI Mode) Improves Quality Without Degrading Latency
- **Statement:** token_budget_k: 999999 allows agents to produce thorough, detailed outputs without trimming. Downstream agents receive fuller context (glossary, mental models, reasoning journals). Quality improves monotonically with token budget (up to diminishing returns). Latency is acceptable even with unlimited budget (< 30 min per spec run end-to-end).
- **Basis:** Design choice; assumes LLM inference speed is not the bottleneck (human reading/review is)
- **Risk if wrong:** Unlimited budget may cause information overload: downstream agents process 10k tokens context, become unfocused. Token cost unsustainable (e.g., $500/run instead of $50).
- **Validation method:** Measure quality vs token budget on same task. Hypothesis: quality plateaus around 50-100k tokens (diminishing returns). Plot: token_spent vs Understanding metrics (structure, testability, semantic, etc.)
- **Status:** Unvalidated (assumption drives config; measurement not done)

### A-005: Endocrine Hormones Improve Output Quality (Monotonic Improvement)
- **Statement:** Hormone modulation (adrenaline, dopamine, cortisol, serotonin, oxytocin, norepinephrine) improves agent outputs on average. Hormones are not a novelty but a quality lever.
- **Basis:** Neuroscience analogy (mammalian hormones improve decision-making under stress/reward) + design intuition
- **Risk if wrong:** Hormones may add noise without signal. Quality of frozen-hormone baseline may be indistinguishable from or better than dynamic hormones.
- **Validation method:** Run same task with BANZAI (hormones active) vs baseline (hormones fixed at 0.5). Measure: Understanding metrics, output consistency (variance in repeated runs), token efficiency. Hypothesis: BANZAI ≥ baseline on all metrics. Success = ≥ 5% improvement on ≥ 2 metrics.
- **Status:** Unvalidated

### A-006: Contradiction Scanner Heuristics (Count, Status, Boolean Mismatches) Detect Most Real Contradictions
- **Statement:** Three heuristics (count_mismatch, status_mismatch, boolean_mismatch) capture ≥ 60% of real contradictions between pipeline stages. Remaining contradictions are soft/prose-level and require human review or NLP semantic analysis.
- **Basis:** Design of scanner; upper-bound detection assumption
- **Risk if wrong:** Heuristics may miss critical contradictions (false negatives). Scanner's utility as a screening tool would be limited if recall < 50%.
- **Validation method:** Precision/recall benchmark on labeled contradiction set (N=20 pairs with known contradictions, N=20 without). Success = recall ≥ 60%, precision ≥ 70%.
- **Status:** Unvalidated (scanner deployed, but precision/recall unknown)

---

## Standard Assumptions

### A-007: Agents Read and Follow NEVER Rules
- **Statement:** Each agent's prompt includes NEVER rules (e.g., "NEVER write requirements" for ARCHITECT). Agents parse and comply with these rules; they do not violate them.
- **Basis:** LLM instruction-following capability
- **Risk if wrong:** Agents may ignore NEVER rules or interpret them flexibly, causing role bleedthrough
- **Validation method:** Automated check: scan agent outputs for role violations (e.g., ARCHITECT recommends a specific technology → violates "NEVER implementation details" rule). Count violations. Success = < 5% violation rate.
- **Status:** Partially validated (empirical test pending; instruction-following known to be imperfect)

### A-008: state.json Persistence is Reliable
- **Statement:** state.json is correctly serialized and deserialized across all agent dispatches. No data loss, no corruption from JSON parsing errors.
- **Basis:** Standard JSON library reliability + careful file handling in COMMANDER
- **Risk if wrong:** State loss mid-run would cause cascade failure (agents read stale state)
- **Validation method:** Automated: after each dispatch, verify state.json is valid JSON and contains all prior dispatch history (no entries deleted)
- **Status:** Assumed reliable (standard practice; not tested in this codebase)

### A-009: SAGE's Understanding Metrics Accurately Measure Spec Quality
- **Statement:** Seven Understanding dimensions (structure, testability, semantic, cognitive, readability, behavioral, depth) correctly measure whether a spec is high-quality (non-ambiguous, testable, well-reasoned).
- **Basis:** IEEE 830-1998 (Software Requirements Specification standard); empirical calibration (if available)
- **Risk if wrong:** Metrics may be noisy (high false positive rate: reject good specs, accept bad specs). Threshold tuning becomes arbitrary.
- **Validation method:** Validate metrics against human expert judgment. Give N=20 specs to domain experts; ask "is this high quality?". Compare expert judgment vs Understanding metrics. Success = Cohen's kappa ≥ 0.60 (moderate agreement).
- **Status:** Unvalidated (metrics design documented; human calibration unknown)

### A-010: GOLDDIGGER Reverse-Engineering is Sound
- **Statement:** GOLDDIGGER's function signature extraction, call graph tracing, and dependency detection are accurate (low false positive/negative rates).
- **Basis:** Code analysis best practices (Abstract Syntax Trees, static analysis)
- **Risk if wrong:** GOLDDIGGER produces incorrect analysis → downstream agents (SYNTHESIZER, SCOUT) build mental models on corrupted data
- **Validation method:** GOLDDIGGER output validated manually on test codebase (N=5 codebases, diverse tech stacks). Spot-check: 100 extracted function signatures, verify accuracy. Success = ≥ 95% accuracy.
- **Status:** Assumed sound (standard reverse-eng techniques; not validated in this codebase)

---

## Low-Risk Assumptions

### A-011: Agents Can Read and Parse Markdown Artifacts
- **Statement:** Agent context includes glossary.md, mental-model.md, plan.md, etc. Agents can reliably extract information from Markdown formatted files.
- **Basis:** LLM capability to parse common text formats
- **Risk if wrong:** Agents might misread Markdown tables, nested lists, or code blocks
- **Validation method:** Simple: agent extracts N=10 facts from Markdown artifact; verify extraction accuracy. Success = 100% correct (low bar).
- **Status:** Low risk (empirically known LLM capability)

### A-012: Constitution.md Exists and is Machine-Readable
- **Statement:** constitution.md is created by human before run and is formatted as YAML or JSON with parseable principle definitions.
- **Basis:** User responsibility to provide governance artifact
- **Risk if wrong:** Constitution enforcement cannot run if file is missing or malformed
- **Validation method:** Pre-flight check: COMMANDER loads constitution.md, validates syntax. Fail fast if invalid.
- **Status:** Low risk (procedural; enforced via check before run starts)

### A-013: Knowledge Base Artifacts (calibration-profile.yaml, marketplace-index.yaml) are Maintained and Current
- **Statement:** Knowledge base files are updated after each run and reflect current accuracy data, patterns, and calibration factors. Stale knowledge base degrades quality.
- **Basis:** Learning loop maintenance responsibility
- **Risk if wrong:** Old calibration factors lead to poor estimates in next run; old patterns are reused incorrectly
- **Validation method:** Post-run audit: check timestamps on knowledge base files. If > 30 days old, flag for refresh. Alert user if stale data might impact next run.
- **Status:** Low risk (procedural; requires human discipline)

---

## Spec 015 Proof Topology Assumptions

### A-014: U-CA-004 Gate Experiment is Valid and Decisive
- **Statement:** U-CA-004 (comparing CA-structured pipeline vs expert-prompt baseline) is a valid experiment that will definitively resolve whether CA overlays should be activated. If U-CA-004 resolves POSITIVE (CA ≥ baseline + 10 pp), overlays unlock; if NEGATIVE, overlays remain blocked.
- **Basis:** Proof topology from spec 015; gate-conditioned assumption
- **Risk if wrong:** Experiment might be inconclusive (CA ≈ baseline, no statistical significance). U-CA-004 resolves INCONCLUSIVE → gate remains unresolved indefinitely.
- **Validation method:** Design U-CA-004 with sufficient sample size (N ≥ 20 codebases) and effect size to detect ≥ 10 pp difference. Power analysis: target 0.80 (80% power to detect effect if it exists).
- **Status:** Unvalidated (experiment not yet run)

### A-015: NS-003 Component Proofs (NL2GenSym 86%+, Kumiho 93.3%) Transfer to Echelon
- **Statement:** NL2GenSym's 86%+ schema compliance on Soar rule generation will transfer to Echelon artifact protocol schema. Kumiho's 93.3% contradiction detection accuracy on LoCoMo-Plus will transfer to Echelon multi-artifact store.
- **Basis:** Task similarity (both involve schema validation, contradiction detection); paper claims high accuracy
- **Risk if wrong:** Echelon-specific artifact complexity may degrade accuracy. Components achieve 60%+ (not 86%+) in Echelon context.
- **Validation method:** NS-003 prototype experiment (spec 015 REQ-015-006): run Generator-Critic + AGM on N=30 agent invocations. Measure: first-pass compliance ≥ 70%, contradiction catch rate ≥ 80%. If actual < target, re-calibrate or investigate transferability issues.
- **Status:** Unvalidated; transfer not yet measured

---

## Assumption Dependency Graph

```
A-003 (phase sequence)
  ├── A-001 (Opus capability needed for each phase)
  └── A-009 (SAGE metrics validate each phase output)

A-004 (unlimited budget improves quality)
  └── A-002 (42 agents can use unlimited budget efficiently)

A-005 (hormones improve quality)
  └── A-002 (agent specialization enables hormone effectiveness)

A-006 (contradiction scanner efficacy)
  └── A-008 (state.json reliability required for scanner coordination)

A-014 (U-CA-004 validity)
  └── A-015 (NS-003 components transfer to Echelon)

A-015 (component transferability)
  └── A-001 (Opus capability required for component integration)
```
