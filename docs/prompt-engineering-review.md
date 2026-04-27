# Echelon Prompt Engineering Review

## Executive Summary

The echelon framework contains 41 agent files and 25 command files representing a sophisticated multi-agent software engineering system. Overall prompt quality is high in structural clarity and output specification, but suffers from four cross-cutting problems: excessive credential stacking in every Role section, widespread negative/fear-based framing through overuse of NEVER Rules, missing XML tag structure for separating content types, and inconsistent tool-use guidance that relies on inference rather than explicit instruction. The agents that handle the most complex reasoning tasks (COMMANDER, SAGE, IMPLEMENTER) are the most verbose but also the most prone to overloaded role sections. Command files are generally well-structured procedurally but lack role-setting and context-motivation for the Claude that executes them.

---

## Cross-Cutting Violations

### 1. Credential Stacking in Every Role Section

**Best practice violated:** BP-25 — Avoid excessive credential stacking; numbers like "500+", "200+", "1000+" are not grounded and do not meaningfully focus the model.

**Affected files:** All 41 agent files. Every single Role section opens with a pattern like "You are AGENT — a [title] who has [number]+ [things]. Your [superlative]."

**Issue:** Every agent announces an astronomical track record. Examples:
- change-controller.md: "you have processed 200+ mid-build scope changes without breaking a single release"
- code-reviewer.md: "you have reviewed 5,000+ pull requests"
- verification.md: "a backpropagation specialist who has traced 10,000+ requirements"
- veteran.md: "has evaluated 500+ patterns"
- consolidator.md: "transforms raw episodic experience into generalized schemas" (no track record, but inconsistently omitted)

Every agent has a different inflated number, none are grounded in reality, and they add nothing the model can act on. The pattern also creates length pressure that crowds out actually useful framing.

**Recommendation:** Replace the credential boilerplate with a single sentence stating the agent's purpose and the key behavioral constraint it must maintain. For example, change-controller.md's opening should be:

> You are CHANGE CONTROLLER. Your job is to assess the impact of specification changes that arrive during the build phase and produce a propagation plan before any rework begins.

The role section should then optionally name the most important single constraint ("You assess blast radius before anyone writes a line of code" is good — keep that). Everything else is noise.

---

### 2. Negative/Fear-Based Framing via NEVER Rules

**Best practice violated:** BP-26 — Don't use negative/fear-based framing; "you MUST NEVER" repeated excessively creates anxiety-driven prompting rather than clear guidance.

**Affected files:** All agent files that include a "## NEVER Rules" section (approximately 30 of 41 agents).

**Issue:** The framework uses a dedicated NEVER Rules section in nearly every agent. Some agents have only one rule (change-controller.md: "NEVER skip impact analysis"), which is fine, but others accumulate 5–7 NEVER rules stacked before the Prime Directive. The repetitive negative structure creates friction without adding clarity. Examples:

- implementer.md lists 5 NEVER rules, each bolded, before any positive guidance
- debugger.md lists 5 NEVER rules: "NEVER guess", "NEVER fix symptoms", "NEVER skip verification", "NEVER change architecture", "NEVER change spec"
- sage.md's Rule 6 reads: "Heuristic fallback mode is forbidden. Understanding (via Skill tool) is mandatory for WHY2/WHY3. If you reach this point without Understanding scores, you have violated the mandatory gate at Step 1 — STOP and go back to Step 1."

The debugger rules 2–5 are better written as positive: "Fix root causes, not symptoms. Verify all tests pass after fixing. Escalate to COMMANDER if fix requires architecture change." This communicates the same information without the anxious framing.

**Recommendation:** Keep NEVER rules only for truly irreversible or high-risk actions where negative framing is warranted (e.g., "NEVER write to reasoning-journal.jsonl directly" is a legitimate sole-writer contract). For behavioral guidance, convert to positive framing:

Instead of: "NEVER guess at the fix. Find the root cause first."
Write: "Diagnose root cause before writing any fix. Proceed to Step 4 (Fix) only after documenting the root cause in debug-report.md."

---

### 3. Role Section Double-Writing (Duplicated Identity)

**Best practice violated:** BP-5 — Give the model a role with a single clear sentence; BP-24 — Role should be in the system prompt itself.

**Affected files:** All 41 agent files.

**Issue:** Every agent's Role section contains the agent's identity written twice: first as a credential-stacked headline, then as a functional description. Example from code-reviewer.md:

> "You are CODE REVIEWER — a senior code quality engineer who has reviewed 5,000+ pull requests across distributed systems. You catch the subtle bugs that tests miss: race conditions, security holes, and maintainability traps. **You are the CODE REVIEWER** — you review code for quality, patterns, bugs, security, and adherence to the project's architectural decisions."

The bold re-introduction is redundant and wastes tokens on every dispatch. This pattern appears in all agents.

**Recommendation:** Merge into a single role sentence, then move directly to what the agent produces:

> You are CODE REVIEWER. You inspect each task's implementation for correctness, security vulnerabilities, constitution compliance, and ADR adherence, and return a verdict of APPROVED, CHANGES_REQUESTED, or BLOCKED.

---

### 4. Missing XML Tag Structure for Separating Content Types

**Best practice violated:** BP-4 — Use XML tags (`<instructions>`, `<context>`, `<input>`) to separate content types unambiguously.

**Affected files:** All command files and the agent dispatch prompts embedded in echelon.build.md, echelon.run.md, and echelon.verify.md.

**Issue:** The command files embed agent dispatch prompts as freeform prose inside bullet points. Example from echelon.build.md section 2.3:

> **prompt:** Read the file `agents/build/implementer.md` for your complete instructions. You are the IMPLEMENTER. Build task {task_id}: {task_description}. Here is your context pack: [include files]. Write code and tests. Append entries to `reasoning-journal.json`.

The context pack is not delimited. The instructions blend with the input data. When the model receives a large context pack with this structure, it cannot reliably distinguish "the task definition" from "the referenced spec requirements" from "the constitution."

**Recommendation:** All agent dispatch prompts in command files should wrap distinct content types in XML tags:

```
<instructions>
Read agents/build/implementer.md for your complete instructions. You are the IMPLEMENTER.
</instructions>
<task>
Task ID: {task_id}
Description: {task_description}
Acceptance criteria: ...
</task>
<context>
<spec_requirements>{FR-* entries}</spec_requirements>
<constitution>{constitution.md content}</constitution>
<adrs>{relevant ADRs}</adrs>
</context>
```

---

### 5. No Context/Motivation for Key Instructions

**Best practice violated:** BP-2 — Add context/motivation; explain WHY behind instructions so the model generalizes.

**Affected files:** Primarily the rule/constraint sections across agents. Significant examples: implementer.md Rules section, code-reviewer.md Rules section, spec-guard.md NEVER Rules, orchestrator.md NEVER Rules.

**Issue:** Many rules are stated without motivation. The IMPLEMENTER's Rule 3 says "File paths must match tasks.md — If the task says the code goes in `src/components/shell.ts`, that is where it goes. Do not reorganize." This gives no reason why, so when the model encounters an ambiguous case (task file path looks like a typo), it has no principle to fall back on.

Similarly, the ORCHESTRATOR has a "Spec-Kit Integration" section duplicated verbatim twice in a row (lines 28–52 and 39–52 of orchestrator.md) with no differentiation.

**Recommendation:** Add brief "because" clauses to critical rules. For the file path rule:

> File paths must match tasks.md exactly. If the task says `src/components/shell.ts`, that is where the code goes — because INTEGRATOR validates integration by looking at those specific paths, and any deviation produces a false integration failure.

---

### 6. Inconsistent Tool Use Guidance in Agent Prompts

**Best practice violated:** BP-12 — Explicit tool use guidance; tell the agent WHEN and HOW to use tools; don't rely on inference.

**Affected files:** sage.md, cartographer.md, golddigger.md, investigator.md, architect.md.

**Issue:** Several agents have tool-use instructions embedded in numbered process steps rather than surfaced as explicit pre-conditions. The sage.md NEVER rule "NEVER produce quality gate scores without invoking Understanding via the Skill tool" is critical, but the positive instruction for HOW to invoke it is buried in a mid-process step. The cartographer.md "Preflight: speckit.specify Availability (MANDATORY GATE)" section is well-written but is placed after 50+ lines of Spec-Kit Integration context, meaning the gate instructions arrive late.

More critically, the investigator.md Step 5 (EXPERIMENT) says "Use Bash to run `setup-worktree.sh` to create an isolated git worktree" but does not specify what to do if that script is unavailable, creating an ambiguity about whether to block or continue.

**Recommendation:** Move all mandatory tool invocations to a "Required Tool Calls" section at the very top of each agent prompt (after the Role but before the Process), clearly stating: (1) which tools must be called, (2) in what order, and (3) what to do on failure.

---

### 7. Data at the Bottom, Queries at the Bottom (Long Context Order)

**Best practice violated:** BP-6 — In long contexts, put data at the top; queries/instructions at the end improve performance up to 30%.

**Affected files:** echelon.run.md, echelon.build.md (dispatch prompt patterns throughout).

**Issue:** The dispatch prompts in command files consistently place the instruction first, then the context pack. For example, echelon.run.md section 2 dispatch: "Read the file `agents/exploration/scout.md` for your complete instructions... Here is your context pack: [include context pack files listed above]." The context pack is appended after the instruction. For large context packs (full spec.md, constitution, reasoning journal), this ordering degrades retrieval performance.

**Recommendation:** In dispatch prompts, put the data first and the instruction last:

```
<context>
{spec.md content}
{constitution.md content}
{research.md content}
</context>

<instruction>
You are IMPLEMENTER. Read agents/build/implementer.md for your full protocol.
Build task {task_id} as specified above.
</instruction>
```

---

### 8. Missing Self-Correction Instructions in Quality-Critical Agents

**Best practice violated:** BP-20 — Ask the model to verify its work against criteria before finishing.

**Affected files:** Most build agents. Exceptions: implementer.md (has a "Self-Check Protocol"), code-reviewer.md (lacks explicit self-verification step), spec-guard.md (lacks explicit self-verification step), test-guardian.md (lacks explicit self-verification step).

**Issue:** The IMPLEMENTER has an elaborate Inter-Step Self-Check Protocol (well-designed). However, CODE REVIEWER, SPEC GUARD, and TEST GUARDIAN — which are pure evaluation agents — have no equivalent self-check. They can issue findings that are internally inconsistent or miss their own criteria without any structured self-verification.

**Recommendation:** Add a brief Quality Check section to each evaluator agent. For code-reviewer.md:

> Before finalizing your verdict: verify that (1) every CRITICAL finding has a `file_line` reference, (2) every CHANGES_REQUESTED verdict has at least one HIGH finding, and (3) no finding has a severity above what the evidence supports.

---

## Per-Agent Analysis

### agents/build/change-controller.md

#### Issues
- Role section has double identity ("you are CHANGE CONTROLLER" written twice) and credential stacking ("200+ mid-build scope changes without breaking a single release").
- Step 5 and Step 5b are both numbered "Step 5" — a sequencing error that could cause the model to skip Step 5b or conflate them.
- The output section says "COMMANDER writes to the reasoning journal. Return journal entries in the `echelon_result` block." This instruction appears in almost every agent and is better served by a global contract stated once in COMMANDER, not repeated verbatim per-agent.
- The "Recommend, do not decide" rule (Rule 5) and the "NEVER accept a change that violates the constitution" (Rule 6) contradict each other slightly — Rule 5 says to present and let the MANAGER decide, but Rule 6 says to reject immediately. This ambiguity is unresolved.

#### Strengths
- The process steps are well-ordered and numbered sequentially.
- The output template is detailed, specific, and includes a structured finding-to-rework traceability section (Step 5b) that directly serves downstream VERIFICATION needs.
- The `echelon_result` block is well-specified with concrete field names.

---

### agents/build/code-reviewer.md

#### Issues
- Role section has double identity and credential stacking ("reviewed 5,000+ pull requests").
- The Engagement Gate / Bypass condition references `quality_score` but the inline note says "(Field name: `quality_score` — the actual field in agent-scores.yaml. Do NOT use `scorekeeper_accuracy`.)" — this kind of inline correction comment signals the spec was wrong at least once and the fix was patched in rather than cleaned up. It creates noise.
- The comment `# B4-INVISIBLE: verified against b4/agents/*.py at 2026-04-05` appears inline in the prompt. Internal system metadata comments embedded in agent prompts is a code smell — the model will read and potentially echo this.
- The TypeScript Quality section (section 6) is always included even for non-TypeScript reviews, with no stack-detection gate.
- Section 7 (Performance) and Section 8 (Accessibility) should be conditional on code type.

#### Strengths
- Confidence-based filtering is a strong design: suppressing findings below the threshold prevents noise reports.
- Consolidation rules (group similar findings) demonstrate awareness of output quality over quantity.
- The Severity-Based Verdicts table is clean and machine-parseable.
- Finding format is exhaustively specified with all required fields.

---

### agents/build/debugger.md

#### Issues
- NEVER Rules 1–5 are all phrased negatively. Converting to positive framing would improve clarity (e.g., "Step 4 (Fix) requires completing Step 3 (Root Cause) with a documented root cause. An empty or 'unknown' Root Cause section means you are not yet ready to fix.").
- "Based on: systematic-debugging skill (reproduce → isolate → root cause → fix → verify)" — referencing an internal skill name in an agent prompt is an implementation detail that could confuse the model if the skill is ever renamed.
- The Process section says Step 2 uses "binary search: comment out half the code" — this describes a manual approach that may be impractical for an LLM executing via file reads. The guidance should describe the actual tool-available approach (grep, read, trace call graph).

#### Strengths
- The Step 4 pre-condition rule ("You may only enter this step after completing Step 3") is an excellent hard gate that prevents premature fixing.
- The Completion Signal format is clean and machine-parseable.
- The Integration with Build Flow section gives excellent context for when and why DEBUGGER is dispatched.

---

### agents/build/engineering-manager.md

#### Issues
- Role section has double identity ("You are ENGINEERING MANAGER" written twice with different emphases). The credential ("shipped 30+ projects through multi-stage quality gates") adds noise.
- The Execution Continuity section is well-intentioned but its language is anxiety-driven: "Agent and Skill tool completions are never stopping points... Stop only when the build is declared DONE or a BLOCKED condition is set." This reads as a command to never stop — adding instruction about positive continuation criteria would be clearer.
- The BUILD_COMPLETE Eligibility Policy section references a specific feature ID `002-build-qa-phase-split` as though it is a permanent state, which is confusing context-leakage from a development artifact into a production prompt.
- The Rework Routing Policy contains a reference to `affected_scope_confidence` but this field is not defined anywhere in this agent's inputs section.

#### Strengths
- The Pre-Verification Sanity Check list is excellent — it validates workflow execution rather than just artifact presence.
- The Build Completion Criteria table is comprehensive and machine-checkable.
- The "Three strikes rule" with the Risk Acceptance Protocol fallback is well-designed autonomous decision-making.

---

### agents/build/implementer.md

#### Issues
- Role section has double identity and extreme credential stacking ("delivered 1,000+ tasks with a 90% first-pass approval rate").
- The Belief Register section at the bottom is unusual — embedding a belief register with expiry dates and confidence scores directly in the agent prompt means the model is primed with potentially stale calibration data on every dispatch. This should be externalized to a config file.
- The E2E bootstrap check (Step 5d) is extremely long and contains implementation logic (detecting package managers, installing Playwright, creating config files) that belongs in a tool/script, not in the agent's reasoning. When the agent reads a 400-line section on bootstrapping E2E infrastructure, it burns context on infrastructure setup that should already be done.
- The Eval-Driven Development section adds eval concepts (pass@1, pass@3) that may conflict with TDD guidance earlier. The model must balance "write failing tests first" (TDD) with "run the implementation once per eval" — the relationship between these is not clarified.

#### Strengths
- The Inter-Step Self-Check Protocol (with JSON schema and escalation paths) is the best-designed self-verification mechanism in the entire codebase.
- NEVER Rule 4 ("NEVER review your own code") is exactly the right positive-boundary rule for a multi-agent system.
- The Process steps are sequenced precisely with TDD discipline.
- The status report format (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED) is a clean contract.

---

### agents/build/integrator.md

#### Issues
- Credential stacking: "verified 100+ phase checkpoints across microservice architectures."
- The process steps mix command execution with interpretation logic in a way that buries the important inference rules. Steps 1–3 are well-structured, but Step 4 (Integration Checks) has four sub-sections without clear PASS/FAIL criteria per sub-check — the overall verdict table at the end implies binary pass/fail but the individual checks don't specify what constitutes a failure.
- Step 5 (Bundle Analysis) includes tree-shaking verification, which requires running a build tool. The step doesn't specify how to verify tree shaking without running the build command again.

#### Strengths
- The classification of test failures (KNOWN, REGRESSION, NEW_FAILURE) is a strong tracing mechanism.
- Rule 1 ("Run real commands") is clear positive guidance.
- The integration report output template is detailed and covers all critical dimensions.

---

### agents/build/progress-tracker.md

#### Issues
- The agent has no Role credential stacking, which is refreshing — but the role description is very thin and could benefit from one sentence clarifying its relationship to ENGINEERING MANAGER.
- The Engagement Gate / Bypass condition references `task_complexity` from "ORCHESTRATOR task output" but the inputs section does not list ORCHESTRATOR output as an input, creating a gap.
- The Token Tracking Aggregation section is very long for a progress-tracking agent and includes complex formulas. This could be a separate specialist or a script.
- `# B4-INVISIBLE` comment appears inline again.

#### Strengths
- The drift detection thresholds table is clear and actionable.
- The EVM metrics (CPI, SPI, EAC, ETC) are well-defined with formulas.
- The distinction between "bypass fires → drift-threshold check only" vs "full recalculation" is clean adaptive behavior.

---

### agents/build/spec-guard.md

#### Issues
- Double identity in Role ("You are SPEC GUARD" appears twice) and credential stacking.
- The Batch Contract section (v0.4.0 QA) introduces a different mode of operation (batch QA review) that's described in the middle of the prompt without a clear trigger condition. The model must infer when it is in "batch mode" vs "per-task mode."
- `# B4-INVISIBLE` comment inline.
- The NEVER rules are all phrased negatively. Rule 3 ("NEVER approve your own previous FAIL") is actually important and should be stated as a positive constraint: "When re-validating a previously FAILed task, treat it as a fresh review — read the code from scratch rather than checking a diff."

#### Strengths
- The four-field requirement parsing (ACTOR / ACTION / OBJECT / OUTCOME / CONSTRAINTS) is an excellent structured approach to verification.
- The NEGATIVE SPACE check ("what MUST NOT happen") addresses a common gap in spec validation.
- The Orphan Code Detection section with three-tier classification (infrastructure orphan / feature orphan / dead code) is precise.

---

### agents/build/test-guardian.md

#### Issues
- Double identity and credential stacking ("reviewed 2,000+ test suites").
- The Engagement Gate has two separate bypass conditions (Bypass A and Bypass B) without a clear priority order if both apply simultaneously.
- `# B4-INVISIBLE` inline.
- The process steps are labeled 1–5 but Step 5 ("Update Coverage Map") has no explicit instruction to read existing coverage-map.md before appending, which could produce duplicates.

#### Strengths
- The Behavior vs Implementation quality check examples (BAD/GOOD pairs) are the clearest few-shot guidance in any agent in the codebase.
- The minimum test counts table is specific and immediately actionable.
- The edge case coverage table by category (Strings / Numbers / Arrays / Objects / Async / State / Error) is comprehensive.

---

### agents/build/verification.md

#### Issues
- Credential stacking ("traced 10,000+ requirements to code across enterprise systems") is the most extreme example in the codebase.
- The Deterministic Coverage Tuple section introduces a formula (`qa_coverage = 0.60*R + 0.25*L + 0.15*B`) but `L` (line coverage ratio) and `B` (branch coverage ratio) are never defined in terms of how to compute them without a coverage tool. The agent would need to either run tests with coverage instrumentation or approximate these values, but neither path is specified.
- Step 1b (Load Behavioral Diagram) uses a Bash command embedded inline in a process step. This is fine for COMMANDER-level agents but creates confusion about tool availability for VERIFICATION as a subagent.
- Rule 8 ("Both Step 2 and Step 2b are mandatory") is stated as a rule at the bottom but the steps themselves don't cross-reference each other. A reader could follow Steps 1–5 linearly and miss the interdependency.

#### Strengths
- The five-classification system (IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / PARTIALLY_IMPLEMENTED / NOT_IMPLEMENTED / INCORRECT) is precise and exhaustive.
- The UNVERIFIED_WORKFLOW_GAP category is an important concept — differentiating "code was probably written" from "we have evidence the workflow ran" is subtle and well-specified.
- The Backpropagation Loop diagram at the bottom is a clear mental model of the feedback cycle.

---

### agents/build/visual-validator.md

#### Issues
- The "Why This Exists" section is the most compelling motivation text in any agent — it describes a real first-run failure concretely. However, this section is agent-internal context, not model-behavioral guidance. It could be shortened to two sentences.
- No NEVER Rules or structured constraints section — the "Rules" section at the bottom uses numbered items but they are all positively framed, which is the right approach. However, there is no instruction about what to do when the Playwright tools are unavailable.
- The agent does not specify verbosity — it should clarify whether to screenshot every component or only those that render incorrectly.

#### Strengths
- The "Why This Exists" motivation is excellent and genuinely unique — it makes clear what this agent catches that unit tests miss.
- The visual check table (6 checks with Method and Pass Criteria) is immediately actionable.
- Including the Spec Behavioral Diagram in the visual report is a smart cross-validation step.

---

### agents/control/checkpoint.md

#### Issues
- Double identity in Role section.
- The 4-Phase Model Context is a large ASCII diagram that takes up significant space to convey information already inferable from the agent's role.
- Step 2 embeds a large template internalization prompt inline. This prompt should be a separate file reference or XML-wrapped block, not inline prose.
- The "Why This Matters" section at the bottom (cost comparison without vs with internalization) is useful motivation but is placed after all the process steps, where it has the least influence on model behavior. It should be in the Role section.

#### Strengths
- The Scoring criteria table (6 criteria with Pass/Fail definitions) is precise.
- The Structured Doubt Format requirement (category + resolution_type) is good schema discipline.
- Step 4's instruction to "re-dispatch the agent with the internalization prompt and re-verify" after resolving a doubt prevents rubber-stamping.

---

### agents/control/commander.md

#### Issues
- This is by far the longest agent (800+ lines) and contains significant complexity that exceeds a single agent's cognitive scope. Sections like the Endocrine System (hormone-modulated motivation) and FEP-RLIF Routing Augmentation are specialized enough to belong in separate specialist sub-agents that COMMANDER dispatches.
- The Bootstrap Contract (Steps 1–8) is a good procedure, but Step 4 (Read relevant journal entries) requires COMMANDER to perform query-by-dimension logic on the journal index — this is implementation-level detail that should be a tool call, not a reasoning step.
- NEVER Rule 5 ("NEVER proceed after a dispatch without executing the Post-Dispatch Protocol") is the most critical rule but is buried as item 5 of 6. It should be item 1 or a standalone mandatory section.
- The Belief Register at the bottom has 12 entries with structured fields (Claim, Verified, Expires, Anchor, Confidence, Severity). Embedding a 12-row table of beliefs with expiry dates inside an agent prompt is unconventional and may cause the model to over-index on specific belief values as hard rules when they are soft estimates.

#### Strengths
- The Evidence Hierarchy table (5 ranks, with examples) is one of the best-designed decision frameworks in the codebase.
- The Post-Dispatch Protocol (Steps A–D) is explicit, ordered, and machine-checkable.
- The Meta-Cognition Checklist (5 questions before every routing decision) is excellent — this is the right application of explicit self-reflection prompting.
- The Human Escalation vs Autonomous Resolution decision tree is well-designed: check GUARDIAN → INVESTIGATOR → MAVERICK before escalating.

---

### agents/control/scorekeeper.md

#### Issues
- The SDT Compliance section is conceptually interesting but its guidance ("DO: 'Here's what happened and why it matters'" / "DON'T: 'You scored 4/6, badge awarded'") is meta-commentary about how SCOREKEEPER should behave when feeding scores back — but this does not translate into specific output format constraints. The model cannot follow "don't show scores as 'your score'" unless the output template explicitly separates score storage from score display.
- The gamification machinery (badges, leaderboard, peer appreciation) is elaborate and conceptually coherent, but the Process section ("After each agent action, SCOREKEEPER awards/deducts points") implies SCOREKEEPER runs continuously in real time. The actual dispatch mechanism is post-run only. This creates a gap between the described behavior and the executable behavior.
- The Belief Register has 12 entries with low-confidence design choices (0.65–0.70) presented as authoritative guidance. The model may treat these as fixed rules rather than calibrated estimates.

#### Strengths
- The Failure Mode Recording requirement (FR-003) with concrete `failure_modes[]` schema is the most valuable data structure in the learning loop.
- The Self-Healing Mechanism (prompt refinement triggers → automatic adjustments vs human escalation) is well-designed.
- Token Efficiency Scoring is a clear extension of the base scoring system with well-defined thresholds.

---

### agents/control/strategist.md

#### Issues
- The agent is concise compared to others (good), but the Temporal Reasoning / Consequence Tracer table (T+1 month, T+3 months, T+6 months, T+12 months) asks the model to reason about specific time horizons without any grounding data. The model cannot predict "T+3 months: Are we hitting scaling issues?" without usage data.
- The Output Block agent codename is "OVERVIEW" but the file uses "STRATEGIST" as the primary name — inconsistency between internal and external codename.
- No self-verification step before producing the strategic overview.

#### Strengths
- The NEVER Rules are appropriate, few, and correctly scope the agent to advisory-only.
- The Effort Allocation decision logic (UNDER-INVESTED / OVER-INVESTED threshold rules) is clear.
- The Decision Blast Radius concept is a useful framing for prioritizing INVESTIGATOR time.

---

### agents/control/tracker.md

#### Issues
- The Predictive Social Cognition Protocol (FR-PSC-001 through FR-PSC-005) is an elaborate subsystem embedded in a tracker agent. It references prediction model JSON, semantic similarity scoring (0.0–1.0), and a learning-mode threshold. This belongs in a specialized subagent, not in the core tracker.
- Security note W-003 ("prediction_statement must always be agent-generated prose... Never include verbatim user input") appears twice in different subsections — redundant.
- The NEVER Rule ("NEVER override user statements with agent reasoning") is correctly framed but the "Why This Exists" section that follows it is more impactful than the rule. Swapping their order (motivation first, rule second) would be more effective.

#### Strengths
- The user-intent.md example in the role section is excellent — it concretely shows the format and the problem (ASSESS scoped to MVP when user wanted full parity).
- The Stakeholder Model section is a valuable addition that makes stakeholder conflicts explicit.
- The "Intent corrections are the HIGHEST priority change (even above constitution)" rule is an important and correct hierarchy statement.

---

### agents/exploration/cartographer.md

#### Issues
- NEVER Rule 6 ("NEVER create spec.md manually") is the most critical rule but receives no special prominence in the layout.
- The Marketplace Search section appears before the Inputs section — content ordering should follow information dependency (inputs first, then the process that uses them).
- The GOLDDIGGER Mode 2 Deep Dive Requests section contains inline Python code using `-c` one-liners. The embedded comment "WARNING: Do NOT add print() statements" appears multiple times and is the kind of implementation-specific footgun that should be in a script, not in the agent prompt.
- The Belief Register has 8 entries with expiry dates. Same issue as COMMANDER — embedding expiring calibration data in the agent prompt.
- The Per-Requirement Failure Consumption section (Amendment Mode) is well-designed but its placement mid-document interrupts the linear process flow.

#### Strengths
- The speckit.specify Preflight gate is the best-structured mandatory gate in any agent — it covers success, branch verification, and error with explicit output signals for COMMANDER.
- The Quality Checklist at the end is clean and comprehensive.
- The GOLDDIGGER Mode 2 criteria ("Appropriate when" / "Not appropriate for") set a high bar that prevents unnecessary deep dives.

---

### agents/exploration/golddigger.md

#### Issues
- NEVER Rule 5 is stated three times across the document (once in the NEVER list, and embedded in Steps 2b and 3.2 as inline reminders). The repetition signals a design smell: if a rule needs to be stated three times, the prompt structure has failed to make it unambiguous.
- The adaptive polyrepo depth promotion logic (Step 1b, Python script) is complex infrastructure code embedded in an agent prompt. This logic belongs in a script.
- The failure handling section has the unusual condition "NEVER use this tool to run `cat`..." appearing in a different system message context. The inline code examples include the `print()` warning multiple times.

#### Strengths
- The Cache HIT / MISS logic (with SHA-256 hash of 7 components) is precisely defined.
- The Mode 1 vs Mode 2 configuration profiles are concrete and separated.
- The explicit state.json fields that GOLDDIGGER writes vs the fields COMMANDER writes is clear division of responsibility.

---

### agents/exploration/modeler.md

#### Issues
- Extremely short for the complexity of the task — the invariant checking section gives one example but does not enumerate the types of invariants to check in other architectures.
- No inputs section — the agent assumes it knows what files to read without being told.
- No `echelon_result` schema showing `invariants_checked` or specific findings format.
- No NEVER rules, which means no explicit scope constraints (unlike every other agent).

#### Strengths
- The "Why This Exists" section with the moduleB ID mismatch example is concrete and motivating.
- The four-part model structure (Entity Graph / Contract Map / Data Flow / Invariants) is well-organized.
- The invariant checking pseudocode example is clear.

---

### agents/exploration/sage.md

#### Issues
- This is the most complex agent in the exploration group at 800+ lines. The two operating modes (assumption-challenge and spec-validation) are sufficiently different that they could be separate agents.
- The Self-Calibration section (reading sage-decisions.yaml to check false-positive rate) is an excellent design but is buried deep in the document where it has low influence on model behavior at the start of a response.
- The Internalization-Weighted Scrutiny section reads agent-scores.yaml to decide how deeply to scrutinize each agent's output — this is a sophisticated personalization mechanism but it is described in the middle of an already long prompt, well after the review process steps.
- The contradiction detection section (Step 8) is correctly identified as mandatory but the five contradiction types are presented as a flat list. A matrix view (which artifact pairs to compare for each type) would be clearer.

#### Strengths
- NEVER Rule 4 ("NEVER produce quality gate scores without invoking Understanding via the Skill tool") has the correct absolute framing for a blocking dependency.
- The Per-Requirement Failure Consumption feeding back to CARTOGRAPHER is an excellent closed-loop design.
- The WHY3 Automation Coverage Check is a concrete, unambiguous gate condition.
- The Blocking Rules (5 rules) are clearly stated with the false-positive rate self-calibration being particularly sophisticated.

---

### agents/exploration/scout.md

#### Issues
- The Mode Detection section is good but the brownfield detection heuristic (`if source code files exist`) could produce false positives on projects with compiled artifacts in the repo root.
- The Step 4 (Git History) uses specific Bash commands inline. These are fine for the Bash tool but the indented code blocks mix git commands with narrative, creating density that could be clearer as a numbered substep list.
- The Belief Register has 7 entries with expiry dates and confidence scores — same embedding issue as other agents.
- The Quality Checklist at the bottom ("at least 2-3 potential unknown unknowns") is a minimum that could be gamed (write 2 trivial unknowns). A threshold on quality, not just quantity, would be better.

#### Strengths
- The brownfield vs greenfield bifurcation is clean and well-structured.
- The GOLDDIGGER cache hit handling (read cached result instead of re-requesting) is efficient.
- The Mode 2 request criteria ("Unresolvable entry points" / "Integration opacity") are specific and limit over-requesting.
- The Completion Signal format is clean.

---

### agents/exploration/synthesizer.md

#### Issues
- The agent's NEVER rules include two that are really data quality rules embedded in the rule section: NEVER 6 (LOC claims) and NEVER 7 (resolution claims). These are domain-specific anti-patterns that belong in the process steps as checks, not as NEVER rules.
- The "Why This Matters" comparison table is good motivation but its placement at the end means it has no influence on the model's behavior during execution.
- No explicit verbosity guidance — synthesizer outputs can range from 2 pages to 20 pages depending on contradictions found. Expected output size guidance would help.

#### Strengths
- The Inventory → Cross-Reference → Contradictions → Patterns sequence is logically ordered.
- The GOLDDIGGER Mode 2 trigger conditions (step 3b) are specific and correctly gate the request.
- The `contradictions-and-gaps.md` output format with source attribution per item is excellent.

---

### agents/feasibility/gatekeeper.md

#### Issues
- The "killed 40% of proposals" credential stacking is extreme — it may prime the model toward rejection bias.
- The 6-point Implementability Check section (Mode 2) is excellent but its placement after Mode 1 means a reader must scroll through the entire feasibility assessment to reach it. A table of contents or modes summary at the top would help.
- NEVER Rule 3 ("NEVER override user intent") references INTENT TRACKER as the check mechanism but does not specify HOW to check — does the agent read `user-intent.md`? Call TRACKER? The path is ambiguous.
- The Cone of Uncertainty mention ("A point estimate is not sufficient...") correctly warns against point estimates but the output format in estimates.md asks for an "optimistic / most likely / pessimistic" triple without specifying how wide the cone should be at this stage.

#### Strengths
- The RICE scoring scales are specific and immediately applicable.
- The DEFER loop limit (2 iterations before kill/escalate) is a clean convergence rule.
- The 6-point Implementability Check is well-structured with actionable READY/NEEDS_CLARIFICATION/BLOCKED classification.

---

### agents/feasibility/validator.md

#### Issues
- The Session Cache Protocol (SHA-256 hash of 7 inputs) is a sophisticated caching mechanism, but the cache key computation requires the model to hash 7 file contents and concatenate them — this is a multi-step operation that will likely be done incorrectly or inconsistently. This should be offloaded to a script.
- The NEVER rule amendment ("NEVER accept partial coverage — AMENDED: NEVER accept partial coverage unless a valid session cache verdict exists...") creates a confusing base-rule-plus-exception structure. Stating the full rule with its conditions would be cleaner.
- `# B4-INVISIBLE` comment inline.
- The Triadic Cognitive Model diagram is identical to the one in checkpoint.md — two agents describing the same diagram is redundant.

#### Strengths
- The 6-criteria internalization check table (with Pass/Fail definitions per criterion) is clean and precise.
- The scoring thresholds (6/6 → INTERNALIZED, 4-5/6 → PARTIAL, <4/6 → FAILED) are clear.
- The doubt resolution protocol (check artifact → flag gap → escalate ambiguity) is well-ordered.

---

### agents/learning/adaptive.md

#### Issues
- The Stagnation Detection threshold ("quality scores improved < 0.02 across 2 consecutive runs") is a raw number without context. Is 0.02 a meaningful delta on a 0-1 scale? The agent should explain what this means in practical terms.
- Step 6 (Prompt Recommendations) is gated on `evolution.enabled` config but the gate check is mentioned in the middle of the step, not at the top. A reader following the numbered steps could execute the first part of Step 6 before discovering the gate.
- The Constraints section says "Do NOT suppress bad news" — this is a positive framing principle but stated negatively ("do not").

#### Strengths
- The four trajectory classifications (improving / flat / regressing / oscillating) are clean and differentiated.
- The Confirmation Bias Check (patterns applied 3+ times without validation) is a valuable quality gate.
- The Prompt Recommendations section with evidence chain requirements (correlation threshold + downstream evidence requirement) is rigorous.

---

### agents/learning/auditor.md

#### Issues
- The Tier 1 KB Bootstrap Protocol (10 steps with specific script calls) is the most infrastructure-heavy section in any agent. An agent prompt should not contain what is essentially a database transaction protocol — this belongs in the scripts themselves.
- The ECC Protocol (5-channel confidence computation) is sophisticated but its integration into the FINALIZE flow is described separately from the main Mode 1 process steps, creating a parallel instruction track that is easy to miss.
- The NEVER rules are important (especially "NEVER compute internalization metrics" — INTERNALIZER does that) but are placed after the Configuration section rather than near the top.
- Mode 4 (Post-Build Self-Assessment) and Mode 5 (Post-Feedback Confidence Threshold Refresh) are not clearly labeled as modes in the process description — they appear as numbered sections.

#### Strengths
- The four modes are well-differentiated and each has a clear trigger and output.
- The Calibration Dashboard Generation section is a clean addition with a concrete health score formula.
- The signal-disagreement hallucination detection logic (Pattern A and Pattern B) is well-specified with precise thresholds and exception handling.

---

### agents/learning/consolidator.md

#### Issues
- The three operating modes (Online Replay / Offline Consolidation / Mental Simulation) are each triggered by different COMMANDER dispatches but the mode-detection logic requires COMMANDER to pass `mode: "online_replay"` etc. explicitly. The agent has no fallback for mode detection from context.
- The "Cognitive layer: L3" and "Synthesis: S3" technical metadata in the Role section is jargon that the model cannot act on.
- NEVER Rule 1 ("NEVER overwrite a VETERAN entry without creating a backup tag") is underspecified — what constitutes a "backup tag"?

#### Strengths
- The three modes are well-separated and independently specifiable.
- The salience weighting formula (`salience = recency_weight × outcome_signal`) is explicit.
- The NEVER rules appropriately prioritize non-blocking behavior (Rule 2: "NEVER block agent execution").

---

### agents/learning/internalizer.md

#### Issues
- This is one of the most technically complex agents in the codebase, defining 16 metrics (I-01 through I-16) with deterministic formulas. The complexity is appropriate for the task but the formula density makes the prompt very long.
- Step 0 (General Rules for All Metric Computations) introduces critical rules (null vs zero, empty denominator) but they appear before the metrics, so the model must hold them in mind while reading the metrics section. A reminder at the start of each metric would help ("If denominator = 0, return null per Step 0 Rule 3").
- The cold-start phase system (Phase 1: runs 1-4, Phase 2: runs 5-9, Phase 3: runs 10+, Phase 4: runs 20+) is well-designed but the Phase 4 "promotion candidate" concept adds complexity that could be deferred to a simpler spec.

#### Strengths
- The null vs zero distinction (Step 0, Rule 1) is excellent data quality design — explicitly differentiating "not computed" from "scored zero" prevents a common aggregation error.
- The Cross-Validation section (Goodhart's Law Defense) with three specific CV rules and advisory-only flag semantics is sophisticated and correctly designed.
- The 8-step downstream outcome backfill process closes the loop between internalization metrics and actual build outcomes.

---

### agents/learning/mirror.md

#### Issues
- The agent has no credential stacking (good) but the Role description is weak: "You are MIRROR — a post-mortem facilitator who has extracted actionable patterns from 100+ project retrospectives." One number is still one number too many.
- The "Maximum 5 new patterns and 5 new pitfalls per run" constraint is correctly placed in the Constraints section but no guidance is given on how to prioritize which 5 to select when more qualify.
- Step 0 (Compute Project Fingerprint using SHA-256) involves a Bash command that the model must execute. There is no fallback if git remote is not set.

#### Strengths
- The Evidence Grading (A-E) for patterns is correctly connected to the same scale used by INVESTIGATOR, maintaining cross-agent consistency.
- The Knowledge Transfer Validation section is thoughtful — it asks the right questions about institutional knowledge risk.
- The deduplication check before adding entries prevents knowledge base bloat.

---

### agents/learning/monitor.md

#### Issues
- The "Why This Exists" section describes a specific historical failure ("In our first run, I (Claude) built 55 components without running the Echelon on the expanded scope") — writing "I (Claude)" breaks persona consistency and embeds first-person historical narrative in an agent prompt.
- The five metacognition checks are conceptually well-designed but most of them ("Is the MANAGER's context getting too large?") ask questions the model cannot objectively measure. Adding specific thresholds (e.g., "if reasoning-journal.jsonl has >100 entries") would make the checks actionable.
- The verdict criteria (ON_TRACK / DRIFT_DETECTED / ESCALATE) are defined but the mapping from the five checks to the verdict is not explicit.

#### Strengths
- The trigger conditions (every 5 tasks, after drift warning, after 3 consecutive FAILs, phase gates) are specific and actionable.
- Rule 5 ("When in doubt, use ESCALATE") is the correct default for a metacognition watchdog.
- The framing "Are we building the right thing? trumps Are we building it right?" is an excellent prioritization principle.

---

### agents/learning/realist.md

#### Issues
- Credential stacking: "compared 200+ project plans against actual production outcomes."
- The Engagement Gate bypass condition (confidence_brier > 0.85 AND benchmarked within 30 days) references `confidence_brier` which is a specific field from calibration-profile.yaml. If this field is missing, the gate defaults to full analysis — but the agent doesn't state this default explicitly.
- Step 2 mandates WebSearch with "at least 2 different query strategies" — this is explicit tool use guidance, which is correct, but it doesn't specify what to do if internet access is unavailable.

#### Strengths
- The "All three methods below are mandatory" statement for estimate grounding is clear and correctly rejects implicit skipping.
- The severity rating system (INFO / WARNING / CRITICAL) is well-applied.
- The "Do NOT modify other agents' artifacts. You annotate and report" constraint is correctly scoped.

---

### agents/learning/veteran.md

#### Issues
- The promotion threshold (3 distinct project fingerprints) is correctly justified in the "Promotion Threshold" section — this is good motivational context placed at the right level.
- The Marketplace Candidacy Evaluation section adds a second output pathway that isn't in the main Process steps. An agent reading the Process section could complete all 6 steps without ever reaching marketplace candidacy evaluation.
- CONSOLIDATOR Integration section refers to a schema registry but doesn't specify what format it uses or where it lives.

#### Strengths
- The fingerprint-based deduplication across projects is a sophisticated design that prevents project-specific noise from polluting the global KB.
- The 3-step promotion validation (evidence threshold + no contradictions + semantic alignment) is appropriately rigorous.
- The demotion check (flag for human, not automatic) correctly prevents regression.

---

### agents/solution/architect.md

#### Issues
- The NEVER Rule 7 ("NEVER assign a CRITICAL-risk engine as PRIMARY at any layer") is very domain-specific and appears to reference a specific prior incident ("trealla-js has CRITICAL cyclic loop risk (R-C-001)"). This is project-specific context embedded as a universal rule — it should either be externalized to a config or be more generically stated.
- The ADR Self-Check Protocol uses the exact phrase "CONCERN resolution constraint: When `verdict: 'CONCERN'`, the identified inconsistency or NEVER-rule violation MUST be resolved and the self-check re-run with `verdict: 'PASS'` BEFORE emitting the ADR to the reasoning journal." This is excellent — the self-correction requirement is precisely specified.
- The Context7 Integration section instructs the architect to use an MCP tool (`mcp__plugin_context7_context7__resolve-library-id`). If this tool is unavailable, the agent has no fallback guidance — it would silently fall back to training data (Grade E evidence), which the section explicitly forbids.
- The Belief Register has 8 entries.

#### Strengths
- The Deferral Classification (deferred-safe vs deferred-risky) with explicit escalation path for deferred-risky is a strong design.
- The ADR format template with mandatory "Alternatives Rejected" section prevents undocumented decisions.
- The quality checklist before completion is well-organized.

---

### agents/solution/orchestrator.md

#### Issues
- The "Spec-Kit Integration" section is **duplicated verbatim** in the same file (lines 28–52 and 39–52 appear to be two separate but identical sections). This is a copy-paste error that wastes tokens and could confuse the model about which version to follow.
- The required `complexity` field (trivial / standard / complex) for every task is a good contract, but the description says it affects PROGRESS TRACKER's bypass behavior (FR-ENG-007) and SPEC GUARD's engagement mode. The cross-agent effects are described here but not in those agents' inputs sections, creating a one-way dependency.
- The quality checklist is thorough but has no exit condition — if a check fails, what action should the model take?

#### Strengths
- The dependency graph read from quality-gates.md (Step 0) — using requirement dependency data to order tasks — is a sophisticated and correct optimization.
- The `[P]` parallel marker and the parallelism integrity check criteria are well-defined.
- The Risk Assessment (probability × impact on a 1-9 scale) is actionable.

---

### agents/solution/sentinel.md

#### Issues
- The Step 6 Automation Coverage Gate section is very long and contains both policy (never assign manual) and process (what to do when automation is hard). These should be separated.
- The flakiness management section (Steps 8.1–8.5) is detailed and well-designed but also contains a specific tech-stack reference (`test.fixme(true, 'Flaky - Issue #NNN')`) that assumes Playwright/Vitest. A stack-agnostic pattern should be shown alongside.
- The Belief Register has 9 entries with mostly 0.65–0.75 confidence for design choices. Same embedding issue.

#### Strengths
- Stack Detection (Step 0) is placed first in the process, which is the correct ordering — all subsequent decisions depend on knowing the stack.
- The coverage-map.md rule ("zero rows with `coverage_type: manual`") is a clean, checkable gate condition.
- The E2E setup detection logic is specific and covers multiple package managers.

---

### agents/specialists/advocate.md

#### Issues
- No credential stacking — consistent with other short specialist agents.
- No NEVER rules or process constraints — what does the agent do if it finds WCAG CRITICAL violations? The Key Rules mention "Flag WCAG CRITICAL violations as blocking issues" but the output format and echelon_result block don't have a corresponding `verdict: BLOCKED` path.
- The Nielsen's 10 Heuristics section (Step 2) uses "PASS / CONCERN / FAIL" ratings without mapping these to an overall verdict.

#### Strengths
- The WCAG 2.1/2.2 four-principles structure is correctly organized.
- The three output artifacts (accessibility-requirements.md, user-flow.md, UX Amendments) are well-specified.
- Trigger conditions are specific and correctly scoped.

---

### agents/specialists/benchmark.md

#### Issues
- "Your load predictions have prevented 50+ production outages" — credential stacking with impossibly specific claims.
- Step 1 instructs the agent to produce estimates "with assumptions clearly stated and confidence marked as LOW" when no load data exists — this is correct. But the note ("Flag the missing load model as a spec gap") is placed as a third-priority option when it should be a first-priority action.
- The Universal Scalability Law (USL) is mentioned but not defined in the prompt — a reader unfamiliar with USL would not know what to do with that step.

#### Strengths
- The "Numbers, not adjectives" Key Rule is the clearest statement of a prompt engineering best practice in any specialist agent.
- Little's Law and Amdahl's Law are stated with formulas and application guidance — actionable.
- The capacity planning structure (compute + database + cache + queue + network) covers the full infrastructure stack.

---

### agents/specialists/guardian.md

#### Issues
- "conducted 200+ threat models using STRIDE and OWASP Top 10. Your minimum security checklist has caught critical vulnerabilities in 80% of projects" — the 80% claim is particularly unfounded and may create overconfidence.
- The Minimum Security Checklist and the full Process are both included in every dispatch for always_on mode. The gate condition ("If dispatched in always_on mode for a non-security domain, run ONLY this checklist and skip the full Process") is clear, but the full Process instructions still occupy space in the prompt for every dispatch.
- The Risk Acceptance Protocol's decision matrix (table) defines ESCALATE only when residual risk is HIGH in compliance domains — but the boundary between "security-relevant domain" and "compliance domain" is not explicitly defined.

#### Strengths
- The Minimum Security Checklist (5 items with pass criteria) is an excellent lightweight security gate.
- The Risk Acceptance Protocol with structured RAR entries separates risk quantification from escalation decision, which reduces unnecessary human interruption.
- The always_on vs on_demand mode dispatch guidance is clean.

---

### agents/specialists/investigator.md

#### Issues
- "followed the full scientific method because hunches are not evidence" — this is the correct approach but phrased as a justification for the agent's behavior rather than an instruction.
- Step 5 (EXPERIMENT) says to use Bash to run `setup-worktree.sh`. If this script doesn't exist, the step fails silently. There should be an explicit check.
- The 8-step method is numbered in the prompt but the steps are presented as nested sections rather than a flat ordered list, which creates visual ambiguity about the nesting structure.

#### Strengths
- The 5-grade evidence quality scale (A-E with weights) is the clearest tool-use grading framework in any agent.
- The "time-box research" rule (10 minutes, then document gap) is an excellent anti-perfectionism constraint.
- The CONSOLIDATOR delegation mechanism for counterfactual queries is a clean subagent dispatch design.
- The Belief Register here is relevant — INV-001 and INV-002 directly affect the agent's core behavior (evidence grading) and are worth keeping.

---

### agents/specialists/maverick.md

#### Issues
- The three-phase innovation method (Design Thinking → AutoTRIZ → Lateral Thinking) has a Phase 3 labeled as "Evidence Grade: C" — using the same evidence grading scale for the innovation method itself as for the research findings is an interesting meta-use, but the 0.60 weight for "Phase 3 evidence" is presented without context for how it affects the agent's confidence in its own outputs.
- The TRIZ contradiction matrix and 40-principles template are referenced but the agent is told to "read `templates/triz-contradiction-matrix.md`" — if this file doesn't exist, the step fails. There's an embedded fallback (the 16-parameter table inline), which is good, but it's presented after the file reference, creating a read-first-fallback-second structure.
- The Belief Register has 8 entries. MAV-004 ("LLMs can reliably apply TRIZ inventive principles") has confidence 0.60 — the lowest in the register — and yet this is the core claim of Phase 2. Presenting this as a belief with 0.60 confidence might correctly calibrate the model but could also undermine confidence in the approach.

#### Strengths
- The "method selection is not arbitrary" instruction and the requirement to document attempted methods and rejection reasons is excellent process discipline.
- All three toolkit methods have structured output formats — this transforms vague innovation into machine-parseable structured output.
- The Antifragility Check as a post-generation evaluation is a well-timed quality gate.

---

### agents/specialists/oracle.md

#### Issues
- The agent is purely data-driven (8 domain knowledge sections) with almost no process guidance. The Process section (Steps 1–5) is very thin for a specialist agent.
- No NEVER Rules — the agent can theoretically add domain requirements for domains it doesn't know, with no guardrail.
- Step 3 (Anti-pattern Detection) uses "review `spec.md` and `plan.md`" — but this assumes both exist. For pre-HOW dispatches, `plan.md` doesn't exist yet.

#### Strengths
- The domain knowledge sections (Fintech, Healthcare, E-commerce, etc.) are correctly structured as pattern + compliance + pitfalls + data triads.
- "COMPLIANCE_GAP violations are blocking issues" is the right severity assignment.
- The Key Rules emphasize specificity over generality, which is correct for a domain expert.

---

## Per-Command Analysis

### commands/echelon.bugfix.md

#### Issues
- The "Professional Conduct — ABSOLUTE RULE" and "Execution Continuity — ABSOLUTE RULE" headers are capitalized and labeled ABSOLUTE RULE, but their content is behavioral guidance, not absolute rules. The ALL-CAPS label is an anxiety-framing pattern.
- Step 0 contains a Bash block that finds the default branch and switches to it. This is procedural orchestration code in a prompt — it would be cleaner as a script call.
- The command has no role-setting sentence. The Claude executing this command has no identity statement.

#### Strengths
- The separation between echelon.bugfix (diagnose) and harness-run (implement) is clean and well-documented.
- The Handoff block at Step 6 is a well-formatted terminal output template.
- The prerequisite validation (Step 1) is explicit about what happens when spec_id is missing.

---

### commands/echelon.build.md

#### Issues
- No role-setting sentence. The prompt says "You are the COMMANDER" but this relies on the agent loading commander.md first — the identity is conditional and deferred.
- The `echelon_result` block format is not described for the command itself — only for subagents. The command has no structured completion signal.
- Section 6.3 (Update Task Result — COMMANDER action) is explicitly labeled "This is a COMMANDER action, not a PROGRESS TRACKER action" and repeats this in capital letters. The redundant emphasis suggests this boundary was violated previously and the fix was bolted on.
- The "Inline execution mode" paragraph in section 2.4 ("If COMMANDER executes task work directly in the main conversation without dispatching IMPLEMENTER as a subagent") normalizes a mode that should be prohibited — it creates a loophole that bypasses quality gates.

#### Strengths
- The v0.4.0 operator flow (5 phases with clear gates between BUILD and QA) is well-structured.
- The Quick Reference flow (section 11) is an excellent mental model summary.
- The verify.sh Smoke Test Requirement (8.1b.1) is explicit, justified, and includes multiple stack-specific patterns.
- Section 8.5 (Auto-Feedback & Post-Build Validation) closes the learning loop automatically.

---

### commands/echelon.change.md

#### Issues
- Very short command (80 lines visible, likely complete) — the Prerequisites section is well-structured.
- No role-setting for the executing Claude.
- "If not in build phase, inform the user: If in Phase A (understanding): Changes are free" — this guidance is correct but phrased informally. A structured signal format (like bugfix's handoff block) would be more consistent.

#### Strengths
- Three-outcome decision (ACCEPT / DEFER / REJECT) with explicit propagation steps for ACCEPT is clear.
- Prerequisite validation is appropriate and complete.

---

### commands/echelon.codegen.md

#### Issues
- The Architectural Invariants section (INV-001 through INV-010) is the strongest invariant declaration in any command file. The framing ("CANNOT be overridden by any phase, LLM advisory, or commercial pressure") is exactly the right level of authority.
- Phase 0 (Pre-Flight) has excellent dependency validation (fail fast on missing SOAR binary) but the write_state helper function is embedded as a Bash heredoc in the prompt. This is a code-in-prompt anti-pattern that should be externalized to a script.
- Resume Mode is placed at the very end of the document after all phases — but it's triggered by `$ARGUMENTS = "--resume"` which is checked first. The jump-to-end structure will cause sequential readers to miss the resume logic.

#### Strengths
- The SOAR gate-based phase transition (exit 0 = ADVANCE, exit 1 = RETRY, exit 2 = ESCALATE) is a clean state machine contract.
- INV-008 ("Conflict impasse = correct behaviour, NOT a failure") correctly frames the escalation.
- The Terminal Summary block format is comprehensive and machine-parseable.
- Harness integration (HARNESS_BUILD_STATUS_FILE) is correctly gated on env var presence.

---

### commands/echelon.run.md

#### Issues
- This is the longest command file (1,900+ lines) — it functions as both a command and a state machine specification. The Role section is the weakest part: "You are the MANAGER — the orchestrator of 19 cognitive functions" — a one-sentence role this late in a 1900-line document has almost no behavioral influence.
- The Scope Boundary and Professional Conduct ABSOLUTE RULES are important but their length (10+ lines each) dilutes the message. "ABSOLUTE RULE" bolded headers appear 3 times.
- The GOLDDIGGER Mode 2 Queue (Phase 1.8) describes backward-compatibility handling for old string format queue entries inline in the dispatch protocol. This is an implementation detail that should be in a migration note, not in the main command prompt.
- Section 20 (Quick Reference: Phase Transitions) should be moved to Section 1 — a reader who understands the state machine can navigate the document much more efficiently.

#### Strengths
- The Role Separation table (Agent / PRODUCES / NEVER does) is one of the best cross-agent contract summaries in the framework. It is crisp, scannable, and actionable.
- The Pre-Dispatch Enforcement Protocol (pre-dispatch-gate.sh + Calibration Injection) is a sophisticated quality gate with a clear fallback behavior.
- The State Transition Checkpoints (BUILD_IN_PROGRESS → QA_IN_PROGRESS → QA_COMPLETE → CHANGE_PENDING) are well-defined with entry preconditions.
- Section 15 (Error Handling) covers all critical external tool failures with explicit hard-stop vs degraded-mode decisions.

---

### commands/echelon.review.md

#### Issues
- Machine-only invocation is stated ("Users do not call it directly") but there is no guard that enforces this — a user could invoke it directly. A "caller check" at Step 0 verifying the ARGUMENTS format matches ReviewLoopController output would add resilience.
- Same ABSOLUTE RULE headers.
- No role-setting sentence.

#### Strengths
- The table of commands (echelon.review vs harness-run Phase 3) is a clean architectural split description.
- The agent table (DEBUGGER → SENTINEL → SPEC GUARD per group) matches the bugfix pattern, maintaining consistency.

---

### commands/echelon.verify.md

#### Issues
- Very short. The QA Phase Entry Gate (Step 0) is well-structured.
- No role-setting sentence.
- "Execution Continuity — MANDATORY" at the top is the same boilerplate as build.md. Consider a shared preamble rather than per-command repetition.

#### Strengths
- The QA batch dispatch order (SPEC_GUARD → CODE_REVIEWER → TEST_GUARDIAN → INTEGRATOR → VISUAL_VALIDATOR → VERIFICATION) is explicit and correctly ordered.
- The engineering manager dispatch before gap review is a good quality gate.

---

### Remaining Command Files (echelon.deploy.md, echelon.ground.md, echelon.harness-*.md, echelon.health.md, echelon.init.md, echelon.innovate.md, echelon.investigate.md, echelon.resume.md, echelon.run.md, echelon.status.md, echelon.understanding-*.md)

These follow the same structural patterns as the analyzed commands. Common issues: no role-setting, ABSOLUTE RULE headers, Bash code embedded in prompt steps, missing XML tag structure for context separation. Common strengths: specific agent dispatch sequences, structured handoff signals, clear prerequisites. The understanding-* commands (echelon.understanding-batch.md, echelon.understanding-diagram.md, echelon.understanding-energy.md, echelon.understanding-scan.md, echelon.understanding-validate.md) are the most tightly scoped commands in the framework and have the cleanest structure as a result.

---

## Priority Improvement List

Ordered by impact — highest impact improvements first with concrete rewrite suggestions.

### Priority 1: Eliminate Credential Stacking Across All 41 Agent Files

**Impact:** Every agent dispatch is affected. The opening role section sets the model's frame for the entire response. Stacking inflated credentials creates no behavioral benefit and wastes tokens.

**Concrete rewrite pattern:** For every agent, replace the credential-stacked opening with:

Format: `You are [CODENAME]. [One sentence: what you produce]. [One sentence: the key constraint you must maintain].`

Example for IMPLEMENTER (current: "a senior developer who has delivered 1,000+ tasks with a 90% first-pass approval rate"):
> You are IMPLEMENTER. You write production code and tests for a single task from tasks.md. You implement exactly what the spec requires — no more, no less — and you never review your own code.

---

### Priority 2: Add XML Tag Structure to All Agent Dispatch Prompts in Command Files

**Impact:** Every agent receives a context pack from COMMANDER. Without XML separation, the model cannot reliably distinguish instructions from data, degrading retrieval for large context packs.

**Concrete rewrite pattern:** In echelon.build.md Section 2.3, change:

Current:
```
prompt: Read the file agents/build/implementer.md for your complete instructions. You are the IMPLEMENTER. Build task {task_id}: {task_description}. Here is your context pack: [include files].
```

Rewrite:
```
<instructions>
You are IMPLEMENTER. Read agents/build/implementer.md for your complete protocol.
</instructions>
<task id="{task_id}">
{task_description}
{acceptance_criteria}
</task>
<requirements>
{FR-* entries from spec.md}
</requirements>
<constraints>
<constitution>{constitution.md}</constitution>
<adrs>{relevant ADRs}</adrs>
</constraints>
<context>
{existing code from prior tasks}
{relevant test-strategy.md section}
</context>
```

Apply this pattern to all 20+ dispatch prompts in echelon.build.md, echelon.run.md, and echelon.codegen.md.

---

### Priority 3: Convert NEVER Rules to Positive Framing Across All Agents

**Impact:** Approximately 30 agents have NEVER Rules sections. Converting key rules to positive framing removes anxiety-driven prompting without losing the constraint.

**Concrete conversions:**

DEBUGGER NEVER Rules (current):
> 1. NEVER guess at the fix. Find the root cause first.
> 2. NEVER fix symptoms. Fix causes.
> 3. NEVER skip verification. After fixing, prove the fix works AND didn't break anything else.

Rewrite as Steps 4 pre-conditions:
> **Step 4 Pre-condition:** Enter this step only after Step 3 (Root Cause) is documented with a specific root cause, not "unknown." Implement the root cause fix — not a workaround for the symptom. Complete Step 5 (Verify) before reporting RESOLVED.

IMPLEMENTER NEVER Rules (current):
> 3. NEVER skip tests. Every task must have tests. TDD: test first, then code.

Rewrite:
> Every task produces failing tests before any implementation code. Step 5a (Write Failing Tests First) must complete before Step 5b (Write Code).

Keep NEVER framing only for irreversible actions: "NEVER write to reasoning-journal.jsonl directly" (sole-writer contract), "NEVER create spec.md manually" (workflow integrity), "NEVER implement alternatives" (MAVERICK scope boundary).

---

### Priority 4: Add Role-Setting to All 25 Command Files

**Impact:** Command files have no identity statement. The Claude executing a command file is purely instruction-following with no role frame, which degrades behavior compared to having an explicit role.

**Concrete addition:** Add a one-sentence role section at the top of every command file (after the frontmatter):

For echelon.build.md:
> You are the COMMANDER executing the build phase. Load commander.md first, then execute the state machine below.

For echelon.bugfix.md:
> You are the COMMANDER executing a diagnostic triage. Your job is to produce a bugfix analysis artifact and task list — not to implement fixes.

For echelon.verify.md:
> You are the COMMANDER running a verification check. Dispatch the required agents in order and route their outputs as specified.

---

### Priority 5: Externalize Belief Registers from Agent Prompts

**Impact:** Approximately 12 agents contain Belief Register tables with expiry dates and confidence scores. These are calibration artifacts, not behavioral instructions. Including them in prompts causes the model to treat confidence scores as hard rules.

**Recommendation:** Move all Belief Register tables to a separate `knowledge-base/belief-registers/` directory (one YAML file per agent). COMMANDER reads the relevant file during dispatch and injects only the beliefs relevant to the current decision into the context pack. This keeps prompt length down and makes belief expiry/confidence updates maintainable without modifying agent prompts.

---

### Priority 6: Add Self-Verification Steps to Evaluator Agents

**Impact:** CODE REVIEWER, SPEC GUARD, and TEST GUARDIAN produce verdicts that gate the build. Adding a self-check before final verdict reduces false positives and false negatives.

**Concrete addition to code-reviewer.md:**

Add before the Verdict section:
```markdown
## Pre-Verdict Self-Check

Before issuing your verdict, verify:
- [ ] Every CRITICAL finding has a `file_line` reference pointing to actual code.
- [ ] Every CHANGES_REQUESTED verdict has at least one HIGH or CRITICAL finding.
- [ ] No MEDIUM-only findings have been escalated to HIGH without justification.
- [ ] At least one check from each relevant Review Checklist section was applied.
- [ ] The Commendations section has at least one entry (if the code has any quality).

If a check fails, revise the findings before proceeding.
```

Apply analogous checks to SPEC GUARD (every FAIL has a specific FR-* ID and code location) and TEST GUARDIAN (every MISSING finding has a specific acceptance criterion and test file location).

---

### Priority 7: Fix the Duplicated Spec-Kit Integration Section in orchestrator.md

**Impact:** The duplicated section (lines 28–52 and 39–52 of orchestrator.md) wastes tokens and creates ambiguity. The second instance is a slightly different version of the first, creating a version conflict.

**Concrete fix:** Remove the first instance (lines 28–38) and keep the second instance (lines 39–52) which includes the speckit.analyze call. Verify that the content is consistent and merge any non-duplicated content.

---

### Priority 8: Move the "Why This Matters" / "Why This Exists" Motivational Sections to the Role

**Impact:** Most agents put their motivational context (the failure mode they prevent, the value they add) at the bottom after 200+ lines of process. Motivation placed before process steps improves instruction-following by giving the model a purpose frame before it encounters specific rules.

**Concrete change for visual-validator.md:** Move the "Why This Exists" section (the first-run failure story) to immediately after the one-sentence role. The process section should start after the model understands WHY it is being asked to look at screenshots.

Same pattern for debugger.md (move "Root cause analysis feeds back to IMPLEMENTER. Misdiagnosis means the same bug comes back" to the role section), spec-guard.md (move "Gaps you miss are visible in the gap-report" to role), and test-guardian.md (move "VERIFICATION cross-checks your coverage claims" to role).

---

### Priority 9: Remove Inline B4-INVISIBLE Comments from Agent Prompts

**Impact:** The `# B4-INVISIBLE: verified against b4/agents/*.py at 2026-04-05` comment appears in at least 5 agent files (code-reviewer.md, progress-tracker.md, spec-guard.md, test-guardian.md, realist.md). These are internal system metadata comments that the model will read and may reference in outputs.

**Concrete fix:** Move B4 audit metadata to a separate `b4-audit-log.md` file or to the agent YAML frontmatter if supported. Remove all `# B4-INVISIBLE` comments from agent prose.

---

### Priority 10: Clarify the Step 5 / Step 5b Numbering Error in change-controller.md

**Impact:** Two adjacent sections are both labeled "Step 5" (the Propagation Plan and Finding-to-Rework Traceability). This is a sequencing error that could cause the model to skip Step 5b.

**Concrete fix:** Renumber Finding-to-Rework Traceability as Step 5b consistently with the numbering used in the heading, and add an explicit transition: "Proceed to Step 5b before marking any finding as complete."
