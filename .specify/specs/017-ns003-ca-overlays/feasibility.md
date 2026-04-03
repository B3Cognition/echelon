# Feasibility Assessment — Spec 017 (NS-003 + U-CA-004)

**Produced by**: GATEKEEPER (ASSESS agent)
**Date**: 2026-04-03
**Mode**: BANZAI — no human in loop for routine decisions
**Constitution version**: 1.1.0 (P-020, P-021, P-022 in effect)
**Input artifacts reviewed**: spec.md, issues.md, risks.md, constitution.md, contradiction-scanner.py, belief-parser.py, endocrine.sh, commander.md (echelon extension), echelon.run.md, echelon.build.md, extension.yml

---

## 1. Technical Feasibility — Per Component

### 1.1 NS-003-A: Schema Validator (`scripts/ns003_critic.py`)

**Verdict: FEASIBLE with one design caveat.**

The two-component design (deterministic jsonschema + Claude API prose assessment) is well-precedented and straightforwardly implementable:

- `jsonschema` is installed and importable in the current environment (confirmed by environment check). Required-field and type validation against 6 artifact category schemas is standard jsonschema usage.
- The Claude API (anthropic SDK) is installed and importable (confirmed). The prose-assessment component is a single API call per artifact — no novel SDK usage required.
- The Markdown-to-dict parsing step (A-009) has an established pattern in `contradiction-scanner.py` (regex-based extraction). That code is reusable as a parsing reference for the new validator.

**Design caveat — structured-to-prose ratio (RSK-010 / IS-007)**: Echelon DISCOVER and WHY artifacts are predominantly prose-reasoning documents. If prose represents >40% of artifact content (likely for DISCOVER-class and ASSESS-class artifacts), FPCR measures only the structured-field portion. IS-007 correctly reclassifies RSK-010 as CRITICAL for the patent claim, but this does not block implementation — it requires a coverage limitation section in the experiment report and, ideally, a supplementary section-header presence check. HOW must add these requirements as explicit tasks.

**No major technical blocker identified for NS-003-A.** Schema calibration risk (RSK-004) is manageable through Phase 1 pilot testing (FR-NS3A-005 already specifies this). The 30-second per-artifact latency limit (FR-NS3A-004) is conservative and achievable with standard timeout handling.

---

### 1.2 NS-003-B: AGM Belief Revision Engine (`scripts/ns003_agm.py`)

**Verdict: FEASIBLE for post-hoc mode; pre-commit mode is CONDITIONALLY FEASIBLE with significant HOW-phase risk.**

**Post-hoc mode (mode=post-hoc)**: Fully feasible. Reading completed artifact files, parsing assertions by field_identifier, detecting conflicts, and maintaining a run-scoped BeliefNode graph in a JSON file are standard Python file I/O and dict operations. The four AGM postulates as operationalized in FR-NS3B-003 are implementable in Python without external libraries — the field_identifier uniqueness constraint is a simple dict key check, minimality reduces to "remove only the node whose key matches the incoming assertion," and the SUPERSEDED chain is an append to a list. The test oracle in FR-NS3B-003 is concrete and unambiguous.

**FR-NS3B-003 sufficiency**: The operational definition is sufficient for implementation. The spec explicitly places K*3 (Inclusion) and K*5 (Extensionality) out of scope, which is appropriate for v1. The consistency predicate (at most one ACTIVE BeliefNode per field_identifier) is deterministic and testable. The minimality definition (remove only the matching field_identifier) avoids the combinatorial complexity of full AGM contraction. This is a pragmatic but legitimate simplification that is faithfully labeled as minimal revision (K*2).

**Pre-commit mode (mode=pre-commit)**: This is where IS-003 creates real risk. The speckit dispatch pattern uses the Agent tool to run subagents, which are standard Claude subagent invocations. In the Claude subagent execution model, agents produce artifacts by calling Write tool calls within their own LLM context — COMMANDER does not receive agent output as a synchronous return value before it is written to disk. This is Model B (write-wrapper required), not Model A (COMMANDER-controlled write).

The audit of echelon.run.md and echelon.build.md confirms: COMMANDER dispatches subagents and receives a completion signal, not the artifact content stream. Subagents self-write via Write tool. A synchronous pre-write interception hook does not exist at the COMMANDER dispatch layer.

**Consequence for pre-commit mode**: Pre-commit mode as described in FR-NS3B-004 requires either (a) modifying every agent prompt to call a write-wrapper utility before its own Write tool call, or (b) a file-system level hook (inotify/fsevents watcher) that intercepts writes in real time. Option (a) is a systemic agent-prompt change; option (b) is platform-dependent and fragile. FR-NS3B-004 correctly includes the downgrade path: if pre-commit is infeasible, remove it from scope, amend the novelty claim, and document in an ADR.

**Assessment**: HOW must treat the pre-commit feasibility investigation (IS-003 resolution) as Task Zero — before any NS-003-B implementation begins. The post-hoc mode path is safe to build immediately and should not be blocked.

---

### 1.3 NS-003 Experiment Runner (`scripts/ns003_experiment.py`)

**Verdict: FEASIBLE.**

N=30 live Echelon invocations is achievable. Each invocation is a subagent dispatch producing one artifact, validated by ns003_critic.py. The 10-minute total runtime limit (NFR-PERF-002) is tight but manageable: at 30 seconds max per artifact API call, the worst case is 15 minutes if all calls hit the timeout ceiling. In practice, artifact validation calls should average well under 30 seconds (prose-assessment prompts are short). The historical_artifacts fallback (FR-NS3E-001) provides a graceful degradation path if API quota is exhausted mid-run.

The commit hash lock requirement (IS-006) is straightforward — `git rev-parse HEAD` before the experiment begins. HOW must make this an explicit task.

The calibration set availability (IS-010, A-003, RSK-012) is the most operationally uncertain element. Spec runs 008-014 are not visible in `.specify/specs/` of echelon_proto and appear not to be archived there. The fallback to runs 015-016 is pre-registered as a DEVIATION in FR-NS3E-001 and is acceptable, but HOW must treat this as a concrete task (locate/generate calibration set before Phase 1) rather than a soft assumption.

**Cost estimate**: At approximately 30 tokens per validation call (context: one artifact + prompt + response), N=30 live invocations plus calibration calls total approximately 50-60 API calls. At current claude-sonnet-4-6 pricing, this is well within a single experiment budget — not a cost risk.

---

### 1.4 U-CA-004 Runner (`scripts/uca004_runner.py`)

**Verdict: FEASIBLE — IS-004 is RESOLVED by P-021; scipy is available.**

The critical blocker from IS-004 (AQS requires human evaluators, incompatible with BANZAI) is formally resolved by P-021, which explicitly authorizes an automated LLM judge proxy. The proxy design (FR-UCA-002) — fixed scoring prompt template, five dimensions, integer 0-5 per dimension, full audit trail — is implementable with the anthropic SDK already confirmed available.

N=20 invocations per condition (40 total agent invocations + 40 AQS scoring calls = approximately 80 API calls total) is feasible within a single experiment run. Mann-Whitney U via `scipy.stats.mannwhitneyu` is confirmed available and is a one-line call. Cohen's d requires a manual formula (mean difference / pooled SD) — also trivial.

**AQS proxy validity concern (IS-007-adjacent)**: The automated LLM judge evaluating its own outputs introduces evaluator-model circularity — the same model family (claude-sonnet-4-6) produces the artifacts and scores them. This is a known limitation that must be documented in the experiment report. It does not block execution, but it will require explicit disclosure in any patent or external validation context. HOW must add this as an explicit note in the results template.

**VOID threshold (FR-UCA-ERR-002)**: The N<16 VOID rule is well-specified and correctly implemented in the spec. With N=20 target and 4 allowed failures before VOID, the margin is reasonable. At N=20, Mann-Whitney has limited statistical power for detecting small effect sizes. The Cohen's d ≥ 0.5 requirement (medium effect) is appropriate compensation — a positive result at N=20 with d ≥ 0.5 is meaningful; a negative result at N=20 is genuinely inconclusive by statistical norms (insufficient power to rule out small effects). The spec's binary POSITIVE/NEGATIVE framing without INCONCLUSIVE is a constitutionally mandated simplification (P-020); HOW must document the power limitation in the negative report template.

---

### 1.5 CA Overlay Implementations (5 overlays — CONDITIONAL on POSITIVE)

**Assessment is prospective — gate is not yet cleared.**

| Overlay | Script | Complexity | Notes |
|---------|--------|------------|-------|
| Goal Stack | `scripts/ca/goal_stack.py` | LOW | Persistent JSON goal hierarchy, initialized at dispatch, injected into context pack. No external dependencies. Standard Python. |
| ACT-R Typed Buffer | `scripts/ca/actr_buffer.py` | MEDIUM | Four-buffer context restructuring. Token counting is the main complexity — requires either SDK token counting or a word-count heuristic. The retrieval_buffer ranking (OQ-005) must be resolved: TF-IDF is the low-complexity path (stdlib-friendly with sklearn or manual implementation); embeddings API adds a dependency and cost. |
| LIDA Broadcast | `scripts/bash/lida_broadcast.sh` | LOW | File-based payload broadcast (write to shared temp file). Replace-not-append semantics and run-end cleanup are straightforward bash. COMMANDER dispatch wiring (FR-CAO-003 consume step) adds one line to COMMANDER protocol. |
| GWT Bounded Workspace | `scripts/ca/gwt_workspace.py` | MEDIUM | Token-bounded workspace with priority eviction. Requires reliable token counting. Eviction by recency (lowest priority = oldest) is implementable as a sorted list pop. |
| Episodic Memory | `scripts/ca/episodic_memory.py` | LOW-MEDIUM | Temporal artifact index (append-only JSON with timestamp sort). Query by agent type returns most-recent entry. No cross-run persistence in v1. Straightforward. |

All 5 overlays are individually implementable in Python/bash without external dependencies beyond what NS-003 already requires. The COMMANDER integration constraint (FR-CAO-006: no modification of routing/quality gates/endocrine triggers) is enforceable — overlays are read-only on COMMANDER decisions, write-only to context pack. The gate-check service (FR-CAO-000, `scripts/ca/verify_gate.sh`) is a bash script checking uca004-results.json — two lines of logic.

---

## 2. Risk Assessment

### 2.1 IS-003 (Write-Time Hook) — Risk to NS-003-B Pre-Commit Mode

**Rating: HIGH risk to the pre-commit novelty claim; MANAGEABLE risk to the overall spec.**

The subagent dispatch pattern in the Echelon extension (echelon.run.md, echelon.build.md) confirms agents self-write via Write tool within their LLM context. COMMANDER receives a completion event, not the artifact stream. This makes Model A (COMMANDER-intercept) architecturally infeasible for pre-commit mode without modification.

**How the HOW phase must design around this**: The HOW ARCHITECT must explicitly choose between:

1. **Post-hoc-only scope** (FR-NS3B-004 downgrade path): Remove pre-commit from NS-003-B scope, amend Section 1 novelty claim to state "post-hoc detection" rather than "pre-commit," and document in an ADR. This is the lower-effort, lower-risk path. The patent novelty claim shifts from "pre-commit interception" to "AGM belief revision applied to multi-agent artifact stores" — still novel per U-015-008, as the systematic search confirmed zero prior literature for the Generator-Critic + AGM combination regardless of timing mode.

2. **Write-wrapper utility** (Model B): Add a shared `scripts/write_artifact.py` utility that all agent prompts are instructed to call before their Write tool call, which invokes the Critic synchronously. This preserves the pre-commit claim but requires modifying every agent's system prompt — a systemic change out of scope for spec 017 and potentially touching the echelon extension's agent definitions. High implementation cost, high prompt-injection risk.

**Recommendation for HOW**: Treat post-hoc as the default implementation. Reserve pre-commit as a stretch goal with an explicit ADR documenting the feasibility verdict. Do NOT defer the decision — the HOW ARCHITECT must decide before any NS-003-B code is written, per the FR-NS3B-004 gate.

---

### 2.2 API Quota / Cost Risk for N=50+ Claude Calls

**Rating: LOW.**

Total API calls across both experiments: approximately 30 (NS-003 critic validation, live invocations component) + 30 (NS-003 live Echelon invocations) + 40 (U-CA-004 invocations) + 40 (U-CA-004 AQS scoring) = approximately 140 calls. Each NS-003 critic call is a short prompt (one artifact + schema assessment instruction). Each AQS scoring call is a structured rubric evaluation — moderate length. No single call is a long-context operation.

The primary quota risk is a sustained rate-limit under parallel execution. FR-NS3A-004 and FR-UCA-ERR-003 include per-call timeout handling. As long as the experiment runners execute sequentially (not in parallel batch), rate-limit exposure is minimal. HOW must confirm sequential execution as the default run mode.

The ANTHROPIC_API_KEY propagation concern (IS-009) is a real operational risk. The echelon extension.yml does not specify any explicit environment variable passthrough mechanism. Claude Code subagent invocations inherit the shell environment by default, so ANTHROPIC_API_KEY set in the parent shell will propagate. However, this has not been formally verified for the speckit dispatch pattern. FR-DEP-003 requires startup checks in all scripts — this is the correct mitigation and is already in scope.

---

### 2.3 Non-Determinism Risk (NFR-REPRO-001)

**Rating: MITIGATED — confirmed by IS-013 resolution.**

IS-013 (NFR-REPRO-001 infeasibility with non-deterministic Claude API) was resolved by CARTOGRAPHER: NFR-REPRO-001 is downgraded to SHOULD, temperature=0 is documented, and the ±0.05 bound is labeled best-effort for the prose component. The deterministic jsonschema component produces identical verdicts across runs (zero variance). The Claude API component at temperature=0 produces high but not absolute determinism — variance from system non-determinism and network jitter exists but is bounded.

This mitigation is sound. The reproducibility claim in the spec is now appropriately scoped and will not be a patent review blocker if the report accurately documents the deterministic vs. non-deterministic components and their respective variance bounds.

---

## 3. Effort Estimates

### 3.1 NS-003-A: Schema Validator

Estimated tasks:
1. Define JSON schemas for 6 artifact categories (DISCOVER, ASSESS, HOW, PLAN, BUILD, LEARN)
2. Implement Markdown-to-dict parser (reuse contradiction-scanner.py extraction pattern)
3. Implement deterministic jsonschema validation component
4. Implement Claude API prose-structure assessment component with 30-second timeout
5. Implement FPCR computation and dual-threshold classification (P-022)
6. Implement error handlers: missing schema (exit 2), API auth failure mid-batch (PARTIAL_RESULTS), empty artifact (SKIP)
7. Implement calibration set false-rejection-rate measurement (Phase 1 gate)

**Task count estimate: 7 tasks** (schema authoring is the largest variable — depends on artifact type diversity)

---

### 3.2 NS-003-B: AGM Belief Revision Engine

Estimated tasks:
1. **IS-003 HOW-phase investigation**: Audit write mechanism, document pre-commit vs. post-hoc decision in ADR (Task Zero — must precede all others)
2. Implement BeliefNode data model (field_identifier, value, stage, confidence, status, superseded_chain)
3. Implement BeliefGraph persistence (run-scoped JSON with atomic write/rollback per FR-NS3B-ERR-002)
4. Implement three contradiction type detectors (assertion_conflict, scope_conflict, architecture_conflict) with confidence scoring
5. Implement K*2 minimal revision (four postulates: Success, Consistency, Relevance, Vacuity)
6. Implement post-hoc mode: read artifact files, extract assertions, run revision, produce contradiction report
7. (Conditional) Implement pre-commit mode: ConflictSignal emission, synchronous evaluation — only if IS-003 resolves in favor of write-wrapper
8. Implement error handlers: malformed assertion (MalformedAssertionError), BeliefGraph write failure (rollback)

**Task count estimate: 7-8 tasks** (IS-003 resolution determines whether task 7 is in scope)

---

### 3.3 Experiment Runners

Estimated tasks:

**NS-003 runner** (`scripts/ns003_experiment.py`):
1. Commit hash capture and metadata recording
2. Live invocation loop (N=30, calls Echelon subagent per invocation, pipes output to ns003_critic.py)
3. Historical_artifacts fallback with DEVIATION labeling
4. Results JSON generation (FR-NS3E-002 fields)
5. Dual-threshold report generation (ns003-report.md, FR-NS3E-003/004)

**U-CA-004 runner** (`scripts/uca004_runner.py`):
1. Condition loop (BASELINE, CA-ACTIVE, N=20 per condition)
2. AQS proxy scorer (fixed prompt template, 5 dimensions, 0-5 integer, per-call audit trail)
3. Out-of-range score handling (discard + retry once, then SCORING_FAILED)
4. VOID rule enforcement (N<16 VOID, no Mann-Whitney)
5. Mann-Whitney U (scipy.stats.mannwhitneyu, two-tailed, p<0.05) + Cohen's d computation
6. POSITIVE/NEGATIVE verdict determination (p<0.05 AND d≥0.5)
7. Results JSON (FR-UCA-006 fields) + positive authorization list (FR-UCA-007 if NEGATIVE: negative report)

**Dependency management** (shared):
1. `scripts/requirements.txt` with pinned versions (jsonschema, scipy, anthropic, pyyaml minimum)
2. `scripts/setup.sh` with pip install + help-invocation smoke test

**Runner task count estimate: 14 tasks** (split roughly 5 NS-003 + 7 U-CA-004 + 2 dependency management)

---

### 3.4 CA Overlays (Conditional — if U-CA-004 POSITIVE)

Estimated tasks (per overlay):
1. `scripts/ca/verify_gate.sh` — gate-check service (1 task, prerequisite for all)
2. Goal Stack (`goal_stack.py`) — 2 tasks (data model + context-pack injection)
3. ACT-R Typed Buffer (`actr_buffer.py`) — 3 tasks (4-buffer structuring + retrieval ranking + token count verification)
4. LIDA Broadcast (`lida_broadcast.sh`) — 2 tasks (payload file write/replace + run-end cleanup)
5. GWT Workspace (`gwt_workspace.py`) — 2 tasks (bounded workspace + priority eviction)
6. Episodic Memory (`episodic_memory.py`) — 2 tasks (temporal index + query-by-agent-type)
7. COMMANDER integration verification for each overlay (FR-CAO-006 compliance check) — 1 task per overlay = 5 tasks

**CA overlay task count estimate: 17 tasks** (conditional block)

---

### 3.5 COMMANDER Endocrine Wiring (IS-005 — Phase 3 Hooks)

The Phase 3 commands (`on_gate_pass`, `on_gate_fail`, `on_quality_improvement`) exist in `endocrine.sh` (lines 654-696) but are NOT called from COMMANDER's post-dispatch protocol. COMMANDER currently calls only `decay_hormones` in post-dispatch.

Wiring effort estimate:
1. Add `on_gate_pass`/`on_gate_fail` calls to COMMANDER post-dispatch protocol (modify `agents/control/commander.md` or the echelon COMMANDER)
2. Add `on_quality_improvement` trigger logic (determine what constitutes a quality improvement event — requires a criterion definition)
3. Activate Phase 3 in `squad-config.yml` (`endocrine.phase: 3`)
4. Verify circuit breaker behavior with Phase 3 active (RSK-003 cortisol cascade risk is relevant here)

**IS-005 wiring task count estimate: 4 tasks** — but this has RSK-003 interaction (cortisol cascade if NS-003 triggers many `on_gate_fail` events during calibration). HOW must sequence endocrine wiring AFTER NS-003 experiment completes, or isolate experiment runs from production endocrine state.

---

## 4. Issue Status Summary for HOW Phase

The following issues from issues.md affect HOW-phase feasibility directly:

| Issue | Status | HOW Phase Impact |
|-------|--------|-----------------|
| IS-001 | RESOLVED (P-022 — both thresholds in effect) | None — spec is unambiguous |
| IS-002 | PARTIALLY OPEN — P-006 bypass via state.json only | HOW must confirm work scope does not require formal constitutional amendment; NS-003 + experiment infra is safe; CA overlay implementation code requires P-006 amendment or POSITIVE verdict |
| IS-003 | OPEN — write mechanism not audited | Task Zero in HOW; blocks pre-commit NS-003-B design |
| IS-004 | RESOLVED (P-021 authorizes LLM judge proxy) | None |
| IS-005 | OPEN — Phase 3 hooks exist but not wired | HOW must add COMMANDER wiring tasks; sequence after NS-003 experiment |
| IS-006 | OPEN — commit hash lock not specified as deliverable | HOW must add explicit task |
| IS-007 | OPEN — RSK-010 underclassified | HOW must add structured-to-prose ratio measurement task and coverage limitation to report template |
| IS-008 | RESOLVED (BANZAI Mode added to glossary) | None |
| IS-009 | OPEN — API key propagation not confirmed | HOW must add propagation verification task |
| IS-010 | OPEN — calibration set circular dependency | HOW must add explicit calibration-set-location task with fallback |
| IS-011 through IS-022 | RESOLVED by CARTOGRAPHER | None |

---

## 5. Kill Gate Decision

### Summary of Blockers vs. Caveats

**No fundamental technical blocker exists** for the core MVP scope (NS-003-A, NS-003-B post-hoc mode, both experiment runners, dependency management). All required libraries are present in the environment. The spec's quality gates passed post-CARTOGRAPHER amendments. P-020, P-021, P-022 are in constitution and resolve the three previously-CRITICAL issues (FPCR threshold ambiguity, AQS human evaluator incompatibility, CA gate authorization).

**The open issues are manageable design constraints**, not architectural impossibilities. IS-003 limits pre-commit scope but explicitly provides a downgrade path (FR-NS3B-004) that preserves post-hoc mode — the portion that is both immediately feasible and sufficient for the CCR metric. IS-005 (Phase 3 wiring) is sequencing-manageable. IS-007 (prose ratio measurement) is an additional task, not a blocker.

**The CA overlay conditional gate is appropriately enforced**. FR-CAO-000 (verify_gate.sh) prevents premature implementation. P-006 remains technically in force for production overlay code until U-CA-004 resolves POSITIVE — the HOW phase must not authorize CA overlay implementation files before that verdict.

### Specific Caveats Requiring HOW-Phase Mitigation

1. **IS-003 resolution is Task Zero** for NS-003-B. HOW ARCHITECT must issue an ADR on the pre-commit/post-hoc decision before any NS-003-B implementation. The ADR must document which model was selected (Model A, Model B, or post-hoc-only) and why.

2. **Structured-to-prose ratio measurement (IS-007 / RSK-010)** must be added as an explicit pre-Phase-2 task. If prose fraction exceeds 40% in DISCOVER/ASSESS artifacts, the NS-003-A schemas must include lightweight section-header presence checks as supplementary signals, and the experiment report must include a coverage limitation statement.

3. **Calibration set location (IS-010 / RSK-012)** must be resolved before Phase 1 schema calibration begins. HOW must designate runs 015-016 as the fallback calibration set and label this as a pre-registered deviation if runs 008-014 are inaccessible.

4. **API key propagation (IS-009)** must be verified before either experiment runner executes its first live invocation. The FR-DEP-003 startup check is necessary but not sufficient — the subagent invocation pattern must be confirmed to inherit ANTHROPIC_API_KEY.

5. **Phase 3 endocrine wiring (IS-005)** must be sequenced AFTER NS-003 experiment completes to prevent RSK-003 cortisol cascade from experiment FAIL events contaminating production endocrine state.

6. **AQS proxy circularity** (same model produces artifacts and scores them) must appear as an explicit limitation statement in the U-CA-004 results and negative-report templates.

---

`ASSESS_VERDICT: PROCEED_WITH_CAVEATS — all MVP components are technically feasible with available libraries and existing codebase patterns, but six specific HOW-phase mitigations are required: IS-003 ADR as Task Zero, prose-ratio measurement pre-Phase-2, calibration set designation, API key propagation verification, Phase 3 endocrine wiring sequenced post-experiment, and AQS proxy circularity disclosure in report templates.`
