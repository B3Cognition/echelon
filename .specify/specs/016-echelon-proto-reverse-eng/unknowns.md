# Unknowns — Echelon Proto

## Known Unknowns

### U-001: What Is the Optimal Agent Count Per Tier?
- **Why it matters:** 42 agents across 7 tiers may be under- or over-specialization. Too many agents = coordination overhead (COMMANDER route complexity, context pack size). Too few agents = role confusion.
- **Who can answer:** Experimentation (ablation study); potentially AUDITOR post-run analysis
- **Priority:** Should-resolve-before-PLAN (affects BUILD phase coordination cost)
- **Related assumptions:** A-002 (42 agents is optimal)
- **Validation approach:** Remove agents from one tier (e.g., 3 specialists instead of 6); measure output quality. If no degradation, agent count can be reduced.

### U-002: What Is the True Token Cost of the Full Pipeline?
- **Why it matters:** BANZAI mode claims unlimited budget, but actual cost per run is unknown. Matters for production cost modeling, cloud infrastructure budgeting.
- **Who can answer:** Measurement on representative codebases (N=10+ diverse domains)
- **Priority:** Should-resolve-before-BUILD (affects service cost model)
- **Related assumptions:** A-004 (unlimited budget improves quality)
- **Validation approach:** Instrument full run with token-logger.py. Track total tokens per phase, per agent. Establish baseline costs (small codebase, medium, large).

### U-003: How Effective Is SAGE's Understanding Metrics Validation?
- **Why it matters:** SAGE gates spec quality using 7-dimension Understanding metrics. But is this gate valid? Do high-Understanding specs produce high-quality implementations?
- **Who can answer:** Benchmark study: specs with high Understanding scores → implementations with fewer bugs, better architecture compliance. Specs with low scores → more rework.
- **Priority:** Must-resolve-before-WHAT (quality gate validation)
- **Related assumptions:** A-009 (Understanding metrics accurately measure quality)
- **Validation approach:** Run N=20 specs: N=10 high Understanding (pass SAGE), N=10 low (fail SAGE but implement anyway). Measure implementation quality. Success = high-Understanding specs have ≥ 30% fewer bugs.

### U-004: What Is the Calibration Data Convergence Rate for New Domains?
- **Why it matters:** calibration-profile.yaml is domain/tech-stack specific. How many runs (N) are needed before GATEKEEPER estimates stabilize and become reliable for a new domain?
- **Who can answer:** AUDITOR via calibration analysis on historical runs (need N=20+ runs on same domain/tech combo)
- **Priority:** Should-resolve-before-ASSESS (affects GATEKEEPER confidence in estimates)
- **Related assumptions:** A-013 (knowledge base is maintained and current)
- **Validation approach:** Cluster runs by domain (e.g., "Python REST API," "Rust embedded system"). For each cluster, plot estimation error vs run number. Identify convergence point (where error stabilizes).

### U-005: Does the Endocrine System Measurably Improve Quality?
- **Why it matters:** Hormones are a novelty mechanism, but is their effect real or marginal? 5% improvement in quality? 20%? Or undetectable noise?
- **Who can answer:** Controlled experiment: BANZAI with hormones active vs baseline (hormones frozen at 0.5 or removed)
- **Priority:** Must-resolve-before-BUILD (affects core system design; if hormones have no effect, can remove complexity)
- **Related assumptions:** A-005 (hormones improve quality)
- **Validation approach:** Run N=10 same spec, BANZAI-with-hormones vs baseline. Measure: Understanding metrics (spec quality), output consistency (variance across runs), token efficiency. Hypothesis: BANZAI ≥ baseline on all metrics.

### U-006: What Is the Precision/Recall of the Contradiction Scanner?
- **Why it matters:** Scanner detects 3 heuristic types. But what % of real contradictions does it miss (false negatives)? What % of detected contradictions are false positives?
- **Who can answer:** Benchmark on labeled contradiction test set (N=20+ pairs with known ground truth)
- **Priority:** Should-resolve-before-SYNTHESIZER (affects reliability of early contradiction detection)
- **Related assumptions:** A-006 (scanner heuristics detect ≥ 60% of real contradictions)
- **Validation approach:** Create labeled dataset: N=20 spec pairs with known contradictions, N=20 without. Run scanner. Compute precision and recall. Success = precision ≥ 0.70, recall ≥ 0.60.

### U-007: How Well Does U-CA-004 Resolve the CA Overlay Question?
- **Why it matters:** Five CA overlays (Goal Stack, ACT-R Buffer, LIDA Broadcast, GWT Workspace, Episodic Memory) are gate-blocked pending U-CA-004 experiment. Will U-CA-004 resolve conclusively, or inconclusive (CA ≈ baseline)?
- **Who can answer:** U-CA-004 experiment execution (spec 015 requirement)
- **Priority:** Must-resolve-before-ARCHITECT (blocks architecture decisions)
- **Related assumptions:** A-014 (U-CA-004 gate experiment is valid and decisive)
- **Validation approach:** Design U-CA-004 with sufficient statistical power (N ≥ 20 codebases). Measure: AQS (Accumulated Quality Score). If AQS(CA) > AQS(baseline) + 10 pp, gate resolves POSITIVE. Otherwise NEGATIVE/INCONCLUSIVE.

### U-008: Do NS-003 Component Proofs (NL2GenSym, Kumiho) Transfer to Echelon?
- **Why it matters:** NS-003 relies on Generator-Critic (86%+ compliance, NL2GenSym) and AGM belief revision (93.3% accuracy, Kumiho) transferring to Echelon artifact store. If tasks are sufficiently different, transfer may fail.
- **Who can answer:** NS-003 prototype experiment (spec 015 REQ-015-006)
- **Priority:** Must-resolve-before-HOW (NS-003 is primary architecture; transfer failure invalidates design)
- **Related assumptions:** A-015 (NS-003 components transfer to Echelon)
- **Validation approach:** Deploy NS-003 prototype on Echelon: measure first-pass schema compliance ≥ 0.70 (vs NL2GenSym 0.86), contradiction catch rate ≥ 0.80 (vs Kumiho 0.933). If below targets, investigate task differences and fine-tune.

### U-009: What Is the Acceptable False Positive Rate for Constitutional Gates?
- **Why it matters:** Constitutional pre-dispatch gates (FLAG/CONSULT/BLOCK) may be too aggressive (over-blocking agents) or too lenient (allowing violations). What false positive rate is tolerable?
- **Who can answer:** User feedback; COMMANDER logs of gate decisions
- **Priority:** Should-resolve-before-BUILD (affects developer experience with governance)
- **Related assumptions:** A-014 (constitution is non-negotiable)
- **Validation approach:** Track constitutional gate events (FLAG, CONSULT, BLOCK) over N=10 runs. Measure: how many BLOCK decisions were justified (prevented real violation) vs unjustified (false alarm)? Target: ≥ 80% justified.

### U-010: What Is the Memory Footprint of the Reasoning Journal?
- **Why it matters:** reasoning-journal.json is append-only. For long runs (N=100+ dispatches), journal size can grow to MB levels. Does this impact load time, serialization cost, agent context pack size?
- **Who can answer:** Measurement on full runs; potentially PROGRESS-TRACKER monitoring
- **Priority:** Can-defer (not blocking, but important for production)
- **Related assumptions:** A-008 (state.json persistence is reliable)
- **Validation approach:** Instrument reasoning journal: record entry count, file size, load/save latency per phase. Set budget: reasoning journal ≤ 10 MB for 200+ entries (2–5 KB per entry target).

---

## Potential Unknown Unknowns

### Area 1: Agent Reasoning Drift Over Long Runs
- **Why suspicious:** BANZAI mode runs can execute 100+ dispatches in single session. Agents are stateless (fresh prompt each dispatch), but context pack (shared across all agents) accumulates knowledge. Does the context pack eventually become too large or self-contradictory, degrading agent reasoning?
- **Recommended investigation:** Monitor Understanding metric quality over course of long run. Plot Understanding scores vs dispatch number. Hypothesis: scores remain stable (no drift). If drift observed, investigate root cause (context pack bloat, accumulated errors, etc.).

### Area 2: Emergent Behavior from Tier Interactions
- **Why suspicious:** 7 tiers with 42 agents create complex multi-agent system. Emergent behaviors (oscillation, deadlock, unexpected synergies) may appear that are not predicted by individual agent behavior.
- **Recommended investigation:** Apply chaos engineering to Echelon: inject failures (agent timeouts, specification contradictions, resource constraints); observe system behavior. Do teams of agents recover gracefully, or cascade into failure?

### Area 3: Transferability of Calibration Data Across Domains
- **Why suspicious:** calibration-profile.yaml is domain/tech-stack specific. But Echelon's philosophy is domain-agnostic. Can a GATEKEEPER calibration learned on Python projects transfer to Rust projects? Or does each domain need separate calibration?
- **Recommended investigation:** Run N=20 projects: 10 Python, 10 Rust. Train GATEKEEPER on Python subset (runs 1–5). Apply calibration to Rust projects (runs 6–10). Measure: does Python calibration help Rust estimates, or hurt them? Success = transfer accuracy within 10 pp of domain-specific accuracy.

### Area 4: Role of Human Intent Alignment (TRACKER)
- **Why suspicious:** TRACKER verifies user intent vs scope. But if user intent is itself ambiguous or contradictory, can TRACKER detect it? Or does TRACKER accept the contradiction, leading to confused downstream agents?
- **Recommended investigation:** Provide TRACKER with intentionally ambiguous user descriptions (e.g., "build a fast, flexible system that's simple but feature-rich"). Measure: does TRACKER flag ambiguity? Can it surface contradictions for user to resolve?

### Area 5: Specification Explosion (Requirements Proliferation)
- **Why suspicious:** CARTOGRAPHER writes requirements based on DISCOVER output. But as codebases grow, requirements can multiply (1000+ requirements for 100k LOC). Does GATEKEEPER estimation accuracy degrade with requirement count? Does SAGE quality gate slow down?
- **Recommended investigation:** Measure quality gate throughput vs requirement count. Plot: phase execution time vs number of requirements. Hypothesis: linear relationship (1000 requirements = 10× time for 100 requirements). If superlinear, investigate bottleneck.

### Area 6: Specification-to-Code Fidelity (Verification Completeness)
- **Why suspicious:** VERIFICATION agent checks implementation against spec via backpropagation. But can any agent fully verify that code satisfies all requirements? Or are there inherently unverifiable aspects (e.g., user experience, subjective quality)?
- **Recommended investigation:** Run VERIFICATION on N=10 projects. Measure: what % of spec requirements have testable verification criteria? What % are subjective or require human judgment? Set target: ≥ 80% testable.

---

## Related Unknowns Across Specs

### From Spec 015 (CA Outcomes Validation)
- **U-CA-004**: Does cognitive architecture outperform expert prompts on Echelon tasks? (BLOCKING GATE for 5 overlays)
- **U-015-002**: Systematic search confirmed NS-003 novelty (no prior literature found). But is search exhaustive? Any non-indexed papers combining Generator-Critic + AGM?
- **NS-003 Prototype** (U-015-006): Can NS-003 achieve ≥ 70% compliance and ≥ 80% contradiction catch on Echelon artifacts? (Design-level proof pending)

---

## Summary: How Unknowns Affect Pipeline

| Unknown | Blocking? | Current Workaround | Impact if Unresolved |
|---------|-----------|-------------------|----------------------|
| U-001 (optimal agent count) | No | Default 42 agents | Suboptimal efficiency; possible overcomplexity |
| U-002 (true token cost) | No | BANZAI unlimited (overestimate) | Cannot budget cloud infrastructure |
| U-003 (SAGE validation) | No | Assume SAGE gates are valid | Possible low-quality specs pass gate |
| U-004 (calibration convergence) | No | Assume N=5 runs is sufficient | GATEKEEPER estimates noisy on new domains |
| U-005 (hormones efficacy) | No | Assume hormones help | Possible wasted complexity |
| U-006 (scanner precision/recall) | No | Assume heuristics catch 60%+ contradictions | Undetected contradictions cascade to BUILD |
| U-007 (U-CA-004 resolution) | **YES** | Gate blocks all 5 CA overlays | CA mechanisms cannot be deployed |
| U-008 (NS-003 transfer) | **YES** | Assume transfer succeeds | NS-003 implementation may fail on Echelon artifacts |
| U-009 (constitutional gate FP rate) | No | Assume gates are well-calibrated | Possible over-blocking (developer friction) or under-blocking (compliance violations) |
| U-010 (journal memory footprint) | No | Append-only (unbounded growth) | Long runs may slow down due to large context packs |

**Blocking Unknowns:** U-007 and U-008 must be resolved before Echelon can be considered production-ready. Both are addressed by experiments in spec 015 (U-CA-004, NS-003 prototype).
