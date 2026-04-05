# Unknowns — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: SYNTHESIZER (FUSE) | **Date**: 2026-04-03 | **Supersedes**: SCOUT unknowns.md

---

## Synthesis Note

SCOUT identified 8 known unknowns and 3 potential unknown unknowns. SYNTHESIZER re-prioritizes based on cross-system dependency analysis. The priority order is revised from SCOUT's ordering:

**Priority revision:**
- U-009 (write-time interception hook) is elevated to **highest priority** — it blocks the entire NS-003 architecture before any other design can proceed.
- U-001 (FPCR threshold) was already highest priority; confirmed as must-resolve-before-WHAT.
- U-007 (known-good samples) is elevated because it blocks Phase 1 schema calibration — everything else in NS-003 Phase 1 depends on it.
- U-003 (dependency management) is elevated because experiment reproducibility gate — both sub-systems require it.

---

## Priority 1: Must-Resolve-Before-WHAT

### U-001: Which FPCR threshold is authoritative — 0.70 (brief) or 0.80 (pre-registered)?
- **Why it matters:** The entire NS-003-A experiment PASS/FAIL verdict depends on this threshold. Achieving FPCR = 0.70 is INCONCLUSIVE under the pre-registered design but is success under the spec 017 brief.
- **Who can answer:** [user] — spec 017 brief author must confirm whether 0.70 is a minimum viable exploration target or an amendment to the pre-registered PASS criterion.
- **Sub-system:** NS-003
- **Related:** A-004 (conflicted assumption), contradictions-and-gaps.md CRIT-001
- **Blocking:** All NS-003 implementation targets, schema calibration goals, success criteria for WHY1 challenge

### U-009: What is the write-time interception hook mechanism in COMMANDER for NS-003? (NEW — synthesized from SCOUT RJ-009)
- **Why it matters:** NS-003 requires intercepting agent output AFTER the LLM call but BEFORE the artifact file is written. The COMMANDER dispatch protocol (commander.md) currently describes only Pre-Dispatch steps — there is NO documented post-dispatch, pre-commit hook pattern anywhere in the codebase. If agents write their own outputs directly via tool calls within their LLM context, there may be no interception point at the COMMANDER level. If COMMANDER pipes output, there is a natural hook.
- **Who can answer:** [domain-expert] — must audit `commands/squad.run.md`, `commands/squad.build.md`, and the full COMMANDER dispatch sequence to determine where artifact writes occur.
- **Sub-system:** NS-003 (blocks NS-003-A Critic integration and NS-003-B BeliefGraph commit interception)
- **Related:** boundaries.md — NS-003 Generator-Critic integration point; SCOUT RJ-009
- **Blocking:** NS-003 architecture design. All other NS-003 design choices depend on knowing the interception mechanism.
- **Priority escalation reason:** SCOUT flagged this in potential unknown unknowns. SYNTHESIZER elevates to must-resolve because without the interception point, NS-003 cannot be pre-commit — and post-commit would remove the entire novelty claim.

### U-007: What are the known-good sample artifacts from spec runs 008-014?
- **Why it matters:** Phase 1 completion criterion requires zero false rejections on known-good samples from prior runs 008-014. The `.specify/specs/` directory currently shows only specs 015 and 016. Runs 008-014 may be in a separate location or not archived.
- **Who can answer:** [user] — locate prior spec run artifacts for schema calibration.
- **Sub-system:** NS-003 (Phase 1 schema formalization)
- **Blocking:** Phase 1 schema calibration — cannot begin without known-good samples.

### U-003: Does a Python requirements.txt exist for the scripts/ directory?
- **Why it matters:** NS-003 requires jsonschema; U-CA-004 requires scipy. Neither is in any requirements file. The ns003-experiment-design.md Section 8 reproducibility requirement demands explicit dependency management so the experiment can be run by a third party.
- **Who can answer:** [domain-expert] — inspect CI configuration; create scripts/requirements.txt as part of spec 017 implementation.
- **Sub-system:** Shared (NS-003 + U-CA-004)
- **Blocking:** Experiment reproducibility gate for both sub-systems.
- **SYNTHESIZER note:** SCOUT reasoning-journal.json RJ-007 identifies this as a "necessary deliverable for spec 017." Minimum contents: jsonschema, scipy, pyyaml, anthropic (if SDK used).

### U-002: How does the Anthropic API get invoked by NS-003 — SDK or CLI subprocess?
- **Why it matters:** No existing Python script calls the anthropic SDK (confirmed via grep). If NS-003 must use CLI subprocess pattern, token count capture requires parsing CLI output (fragile). If SDK, token counts available from response object.
- **Who can answer:** [user] or [domain-expert] — inspect extension.yml for invocation pattern.
- **Sub-system:** NS-003 (Generator invocations) + U-CA-004 (experiment runs)
- **Blocking:** NS-003 Generator implementation, token logging fidelity (REQ-015-003).

---

## Priority 2: Should-Resolve-Before-HOW

### U-004: What is the Markdown → dict parsing strategy for the NS-003 Critic?
- **Why it matters:** The Critic validates Markdown output against JSON Schema. A parsing layer must extract structured fields into a Python dict. `extract_assertions_from_file` in contradiction-scanner.py provides a similar extraction, but its output (list of Assertion objects) is not directly schema-validatable.
- **Who can answer:** [SCIENTIST] — investigate whether existing Markdown parsing libraries (python-markdown, mistletoe) produce schema-validatable structures, or whether a custom parser extending contradiction-scanner.py logic is required.
- **Sub-system:** NS-003
- **Blocking:** NS-003 Phase 1 (schema formalization) and Phase 2 (Critic implementation).

### U-005: What is the BeliefGraph persistence format and scope?
- **Why it matters:** NS-003-B requires persistent belief graph within a single run. Two options: (a) in-memory Python dict serialized to belief-graph.json at run end [lowest complexity]; (b) networkx or similar graph library. The Kumiho paper uses Redis + Neo4j, but external services are inappropriate for the prototype.
- **Who can answer:** [SCIENTIST] — evaluate in-memory vs networkx vs external backend.
- **Sub-system:** NS-003-B
- **SYNTHESIZER note:** Cross-run persistence (needed for CA overlay 4 Episodic Memory) is explicitly OUT of NS-003 v1 scope. v1 = run-scoped only.

### U-006: Can endocrine event hooks be called from Python without going through bash?
- **Why it matters:** If NS-003 is implemented in Python, it must trigger endocrine events. Options: (1) Python calls endocrine.sh via subprocess; (2) COMMANDER handles event wiring based on NS-003 return codes. Option 2 is architecturally cleaner and avoids Python→bash dependency.
- **Who can answer:** [domain-expert] — architecture decision for COMMANDER integration.
- **Sub-system:** Shared (NS-003 endocrine wiring)

### U-008: How is the ACT-R buffer activation formula's cosine_similarity computed?
- **Why it matters:** The ACT-R Typed Buffer uses `activation = recency_weight × cosine_similarity(embed(chunk), embed(goal_buffer))`. This requires embedding both chunks and the goal buffer. If embeddings API calls are needed, buffer preprocessing adds latency and cost. If TF-IDF/BM25 approximation is sufficient, it stays within the API-only constraint (ADR-003 prohibits model changes, not local computation).
- **Who can answer:** [SCIENTIST] — investigate whether TF-IDF cosine or BM25 produces sufficient ranking for the experiment.
- **Sub-system:** U-CA-004 (Condition C ACT-R preprocessor)

---

## Priority 3: Can Defer (Post-HOW)

None identified — all 8 known unknowns are blocking or should-resolve at this scope.

---

## Priority 1 Additions — SAGE (WHY1) 2026-04-03

### U-010: Can AQS scoring be automated for BANZAI mode execution of U-CA-004? (NEW — IS-004)
- **Why it matters:** U-CA-004's primary dependent variable (AQS) is defined as a human evaluation rubric. In BANZAI mode (no human in loop), there are zero human evaluators. The experiment as specified cannot be executed fully autonomously. Either an automated AQS proxy must be defined and pre-registered, or the human must confirm a split-execution approach (autonomous runs, human scoring), or the experiment design must be revised.
- **Who can answer:** [user] — fundamental scope and evaluation approach decision.
- **Sub-system:** U-CA-004 (blocks experiment runner design)
- **Blocking:** U-CA-004 experiment infrastructure design. HOW phase cannot design the runner without knowing the evaluation approach.
- **Related:** IS-004, u-ca-004-experiment-spec.md Section 6, user-intent.md BANZAI mode

### U-011: Does ANTHROPIC_API_KEY propagate into the subagent environment when speckit dispatches via `claude -p`? (NEW — IS-009)
- **Why it matters:** NS-003 Generator invocations require the Anthropic Python SDK. The SDK requires ANTHROPIC_API_KEY to be available in the subprocess environment. The speckit framework dispatches agents via `claude -p`. If the subagent environment does not inherit ANTHROPIC_API_KEY from the parent shell (varies by OS and shell configuration), all SDK calls will fail with authentication errors regardless of whether the SDK is installed.
- **Who can answer:** [domain-expert] — inspect extension.yml and speckit invocation pattern for environment variable inheritance.
- **Sub-system:** NS-003 (Generator invocations) + U-CA-004 (experiment runs)
- **Blocking:** NS-003 Generator implementation. Unresolvable via grep — requires execution-level inspection.
- **Related:** A-002, U-002, IS-009

### U-012: Do current Echelon agents write artifact files themselves (via Write tool calls in LLM context) or does COMMANDER control the write step? (NEW — IS-003)
- **Why it matters:** This determines whether NS-003's pre-commit architecture (Model A: COMMANDER controls write) is feasible or requires a write-wrapper utility pattern (Model B: agents call a shared utility). Model A is a COMMANDER-level change. Model B requires modifying every agent's prompt instructions. The patent novelty claim ("pre-commit, not post-hoc") depends on one of these models being feasible.
- **Who can answer:** [domain-expert] — audit `commands/squad.run.md` and `commands/squad.build.md` for the artifact write mechanism.
- **Sub-system:** NS-003 (blocks all architecture design)
- **Blocking:** NS-003 architecture design. Identified by SAGE as the single most important unresolved architectural question for NS-003.
- **Related:** GAP-001, U-009, IS-003, RJ-009

---

## Potential Unknown Unknowns (Inherited from SCOUT, Confirmed by SYNTHESIZER)

### Area 1: Markdown Schema Specificity vs LLM Output Variability
- **Why suspicious:** contradiction-scanner.py documentation warns: "Assertion extraction from bold-key patterns, KV lines, and table rows — misses contradictions in unstructured prose." LLM agents produce substantial prose in reasoning sections. A JSON Schema validating only structured fields may pass stylistically invalid outputs and reject stylistically unusual but semantically correct outputs.
- **SYNTHESIZER cross-reference:** This directly affects A-003 (schema feasibility assumption). If prose content cannot be schema-validated, the Critic's coverage is inherently partial. The FPCR measurement may reflect schema coverage gaps rather than actual agent compliance.
- **Recommended investigation:** SCIENTIST should analyze 10-15 prior Echelon run artifacts to measure what fraction of content is structured (KV lines, tables, bold-key) vs unstructured prose.

### Area 2: COMMANDER Integration Complexity for Write-Time Interception
- **Why suspicious:** (Elevated from potential unknown unknown to Priority 1 known unknown as U-009 above.) This was the most significant gap identified across all SCOUT sources combined.

### Area 3: U-CA-004 Evaluator Inter-Rater Reliability on AQS
- **Why suspicious:** With a single evaluator across 60 invocations (20 per condition), evaluator drift could confound the Condition B vs C comparison. Experiment design does not specify evaluation order randomization or blinding.
- **SYNTHESIZER cross-reference:** SCOUT reasoning-journal.json RJ-008 notes that AQS Internal Consistency dimension requires evaluators to have all prior stage artifacts — making blind evaluation difficult (artifacts would reveal the pipeline stage and potentially the condition). Blinding may be structurally infeasible.
- **Recommended investigation:** SCIENTIST should determine if evaluator blinding is feasible and design a pre-calibration rubric exercise (5 reference outputs before main batch) to reduce within-evaluator drift.
