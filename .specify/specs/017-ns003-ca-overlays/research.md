# Architecture Research — Spec 017 (NS-003 Prototype + U-CA-004 Experiment)

**Produced by**: ARCHITECT (HOW agent)
**Date**: 2026-04-03
**Spec**: 017-ns003-ca-overlays
**Constitution version**: 1.1.0 (P-006/P-020 in effect; CA overlays conditional)
**GATEKEEPER verdict consumed**: PROCEED_WITH_CAVEATS
**Technology stack**: Python 3.11+, `anthropic` SDK, `jsonschema`, `scipy`, `pyyaml`, standard library only

---

## Technology Stack Decision

All scripts in this spec use the following fixed dependency set (no exceptions without a new ADR):

| Package | Role | Version constraint |
|---------|------|--------------------|
| `anthropic` | Claude API client for NS-003 prose assessment and AQS proxy scoring | `>=0.25.0,<1.0.0` |
| `jsonschema` | Deterministic JSON Schema field validation (NS-003-A Critic component) | `>=4.21.0,<5.0.0` |
| `scipy` | Mann-Whitney U and Cohen's d (U-CA-004 experiment) | `>=1.13.0,<2.0.0` |
| `pyyaml` | Squad config and state file parsing | `>=6.0.1,<7.0.0` |

Standard library modules used: `argparse`, `json`, `hashlib`, `pathlib`, `re`, `datetime`, `subprocess`, `sys`, `os`, `dataclasses`, `typing`. No other third-party package is permitted without a new ADR entry.

---

## ADR-001: IS-003 Resolution — NS-003-B Pre-Commit Mode Formally Descoped

**Status**: DECIDED (Task Zero — supersedes all NS-003-B pre-commit design work)
**Issue resolved**: IS-003 (OPEN in issues.md)
**FR affected**: FR-NS3B-004 downgrade path activated

### Context

IS-003 required an audit of the artifact write mechanism in COMMANDER's dispatch pattern before any NS-003-B architecture could be designed. GATEKEEPER confirmed (feasibility.md §1.2) that Echelon agents self-write artifact files via the Claude Write tool within their own LLM context. COMMANDER receives a completion signal after the write occurs — not a pre-write content stream. This is Model B (write-wrapper required), not Model A (COMMANDER-controlled write).

The evidence chain:
- `echelon.run.md` and `echelon.build.md` confirm subagent dispatch with no synchronous return of artifact content before disk write.
- COMMANDER's post-dispatch protocol (commander.md lines 226-234) calls only `decay_hormones` — there is no existing write-intercept step.
- The Claude Agent tool execution model does not expose a pre-write hook to the calling context.

Two technically viable paths existed per GATEKEEPER:
1. **Post-hoc-only scope** (FR-NS3B-004 downgrade path): Remove pre-commit from NS-003-B scope, amend the spec Section 1 novelty claim text, document in ADR. Lower effort, zero systemic agent-prompt risk.
2. **Write-wrapper utility** (Model B): Add a shared `scripts/write_artifact.py` that every agent prompt must call before its own Write tool call, running the Critic synchronously. Preserves the pre-commit claim but requires modifying every agent's system prompt — systemic change out of spec 017 scope, high prompt-injection risk, and touches the Echelon extension definitions which are frozen for this spec.

### Decision

**NS-003-B operates in post-hoc mode ONLY.**

Pre-commit mode (AC-2.2, FR-NS3B-004 pre-commit branch) is formally removed from the implementation scope of spec 017. The write-wrapper utility path (Model B) is rejected as out of scope and disproportionate to the spec 017 deliverable budget.

### Spec Overview Amendment (FR-NS3B-004 downgrade path activation)

The following sentence in spec.md Section 1 is formally amended by this ADR. IMPLEMENTER must use this amended text when producing documentation or experiment metadata:

**Original**: "an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph across a spec run and emits pre-commit conflict signals when new assertions contradict existing beliefs"

**Amended**: "an AGM belief revision engine (NS-003-B) that maintains a persistent belief graph across a spec run and detects post-hoc contradictions when new artifact-stage assertions conflict with existing beliefs already committed to the artifact store"

### Patent Novelty Claim Impact

The patent novelty claim does not materially weaken. GATEKEEPER confirmed (feasibility.md §2.1): the systematic search (U-015-008) found zero prior literature for the Generator-Critic + AGM combination applied to multi-agent artifact stores regardless of timing mode. The novelty is the combination of structured schema enforcement and AGM belief revision logic operating on the artifact graph — not the specific timing of application. Post-hoc detection preserves this claim in full.

### Consequences

- POSITIVE: No systemic agent-prompt changes required for spec 017. NS-003-B implementation scope is unambiguous.
- POSITIVE: Post-hoc mode is sufficient for the CCR metric (≥0.80) which is the primary quality gate for NS-003-B.
- NEGATIVE: The "pre-commit conflict signal" framing in user-facing descriptions must be replaced with "post-hoc contradiction detection." All experiment report templates must use the amended framing.
- NEUTRAL: `--mode pre-commit` flag MAY still be defined in the CLI interface (per FR-NS3B-004: "interface flag design must accommodate IS-003 findings without requiring a module redesign") but in v1 it SHALL either alias to post-hoc mode with a deprecation warning or exit with a clear "pre-commit mode not available in v1 — IS-003 resolution descoped this" message.

### Alternative Considered

Write-wrapper utility (Model B): rejected. Requires modifying every agent's system prompt in the Echelon extension, which is a systemic change that touches frozen extension definitions. Even if implemented, the wrapper depends on every agent reliably calling the utility before its own Write call — a coordination assumption that is fragile under subagent autonomy. The per-agent modification surface is large relative to the marginal novelty benefit.

---

## ADR-002: NS-003-A Critic Design — Two-Component Validator Architecture

**Status**: DECIDED
**FR addressed**: FR-NS3A-001 through FR-NS3A-005, FR-NS3A-ERR-001 through FR-NS3A-ERR-004

### Context

The NS-003-A Schema Validator must evaluate Echelon agent artifacts against structured quality criteria. The challenge is that Echelon artifacts are predominantly Markdown documents with mixed structure: some sections are table-formatted or YAML-structured (machine-parseable), while other sections are free prose reasoning (not machine-parseable via JSON Schema alone). Two separate validation concerns must be addressed:

1. **Structured field compliance** — required fields present, correct types, minimum content present. Deterministic.
2. **Prose section structure** — required section headers present, key sections non-empty, overall document structure appropriate for the artifact category. Non-deterministic (requires semantic assessment).

The existing `contradiction-scanner.py` establishes the reference parsing pattern: regex-based extraction of key-value pairs, bold-key pairs, and table row content from Markdown. This pattern is directly reusable for the Markdown-to-dict step.

### Decision

**Two-component design with sequential execution:**

**Component 1 — Deterministic JSON Schema Validator**

Input: raw Markdown artifact file path + artifact category (DISCOVER/ASSESS/HOW/PLAN/BUILD/LEARN)
Processing pipeline:
1. Parse artifact Markdown into a structured dict using the `contradiction-scanner.py` extraction pattern: `_BOLD_KEY_RE`, `_KV_LINE_RE`, `_TABLE_ROW_RE` regexes extract key-value assertions. Section headers (`##` / `###`) are extracted as a separate `_sections` list.
2. Apply the category JSON schema (loaded from `--schema-dir`) via `jsonschema.validate()`.
3. For each required field in the schema, emit a PASS/FAIL verdict. PASS confidence is fixed at 0.95 (deterministic — zero prose variance). FAIL confidence is fixed at 0.95.

**Component 2 — Claude API Prose Structure Assessor**

Input: raw Markdown text + artifact category label
Processing:
1. Assemble the fixed prose-assessment prompt (see Prompt Template below).
2. Call `anthropic.Anthropic().messages.create()` with `model="claude-sonnet-4-6"`, `temperature=0`, `max_tokens=512`, with a 30-second timeout.
3. Parse response: extract per-section verdicts and confidence scores via regex on the structured response.
4. Each prose-section verdict confidence is in [0.5, 0.85] (capped below 0.95 to distinguish from deterministic component).

**Score Combination**

Final per-field confidence: deterministic verdicts carry confidence=0.95; prose verdicts carry the API-returned confidence in [0.5, 0.85]. FPCR computation uses only PASS/FAIL — confidence scores are stored for audit but do not affect FPCR numerator/denominator.

**Prose Assessment Prompt Template (fixed, versioned)**

```
You are a structured document quality assessor evaluating Echelon squad artifacts.

Artifact category: {CATEGORY}
Required sections for this category: {REQUIRED_SECTIONS}

Artifact text:
---
{ARTIFACT_TEXT}
---

For each required section listed above, respond with exactly one line per section in this format:
SECTION_VERDICT: <section_name> | <PRESENT|ABSENT|EMPTY> | <confidence 0.50-0.85>

After all section verdicts, respond with:
OVERALL_PROSE: <PASS|FAIL> | <confidence 0.50-0.85>

Do not include any other text.
```

The `{REQUIRED_SECTIONS}` list per artifact category is defined in the category schema (see data-model.md §4).

**Structured-to-Prose Ratio Measurement (IS-007 / RSK-010 mitigation)**

Before Phase 1 schema calibration, IMPLEMENTER must instrument `ns003_critic.py` to compute and log the structured-to-prose character ratio per artifact. If any artifact category shows prose fraction > 40% across the calibration set, the experiment report MUST include a coverage limitation section. This is a mandatory pre-Phase-2 check, not optional.

**6 Artifact Category Schema Definitions — Required Fields**

Each schema lives in `scripts/schemas/<category>.json` and is loaded at startup. Required fields by category (full schemas in data-model.md):

| Category | Stage | Required fields |
|----------|-------|-----------------|
| DISCOVER | DISCOVER | `spec_id`, `agent`, `timestamp`, `scope_statement`, `assumptions`, `unknowns` |
| ASSESS | ASSESS | `spec_id`, `agent`, `timestamp`, `verdict`, `risks`, `effort_estimate` |
| HOW | HOW | `spec_id`, `agent`, `timestamp`, `adrs`, `technology_stack`, `data_model_ref` |
| PLAN | PLAN | `spec_id`, `agent`, `timestamp`, `tasks`, `critical_path`, `mvp_scope` |
| BUILD | BUILD | `spec_id`, `agent`, `timestamp`, `implementation_notes`, `test_results` |
| LEARN | LEARN | `spec_id`, `agent`, `timestamp`, `learnings`, `pattern_updates`, `quality_delta` |

### Consequences

- POSITIVE: Deterministic component produces zero-variance results across runs (NFR-REPRO-001 satisfied for structured fields).
- POSITIVE: Reusing `contradiction-scanner.py` regex patterns avoids new parsing logic.
- NEGATIVE: Prose-assessment component introduces bounded non-determinism (±0.05 FPCR target per NFR-REPRO-001).
- NEGATIVE: DISCOVER and ASSESS artifacts may have >40% prose content, meaning FPCR measures only the structured minority of those artifacts. This must be documented (IS-007 mitigation).

### Alternative Considered

Pure LLM validation (no JSON Schema): Rejected. Too expensive per call (full artifact + detailed rubric), too non-deterministic for the FPCR reproducibility requirement, and loses the patent claim of "deterministic schema enforcement."

Pure JSON Schema validation (no LLM): Rejected. Echelon artifacts are primarily Markdown prose. A schema-only validator would have near-zero coverage of most artifact content and FPCR would be trivially high (always pass on the three present structured fields), making the metric meaningless.

---

## ADR-003: NS-003-B AGM Belief Revision Engine — Post-Hoc Implementation Design

**Status**: DECIDED (Post-hoc mode only per ADR-001)
**FR addressed**: FR-NS3B-001 through FR-NS3B-006, FR-NS3B-ERR-001, FR-NS3B-ERR-002

### Context

Following ADR-001 (post-hoc mode only), the AGM engine reads completed artifact files, extracts assertions by field_identifier, and maintains a run-scoped BeliefGraph. The four AGM K*2 postulates as operationalized in FR-NS3B-003 must be implemented in Python without external libraries beyond standard library.

Key operationalization decisions from the spec:
- **Consistency predicate**: at most one ACTIVE BeliefNode per field_identifier at all times.
- **Minimality**: remove from ACTIVE only the BeliefNode whose field_identifier matches the incoming assertion — no other removals.
- **Vacuity**: if no existing ACTIVE node for the field_identifier, add without any removal.
- **Success**: if the incoming assertion is not self-contradictory (non-null, non-empty field_identifier and value), it enters ACTIVE.

### Decision

**Three-layer architecture: Assertion Extractor → BeliefGraph → Contradiction Classifier**

**Layer 1 — Assertion Extractor**

Reads artifact files from `--artifact-dir` in pipeline order (DISCOVER first, LEARN last). For each artifact, applies the same `_BOLD_KEY_RE` / `_KV_LINE_RE` / `_TABLE_ROW_RE` extraction pattern from `contradiction-scanner.py`. Each extracted key-value pair becomes a candidate BeliefNode with:
- `field_identifier` = normalized key (lowercase, underscores replace spaces)
- `value` = extracted value string
- `stage` = pipeline stage label (from `ARTIFACT_STAGE_MAP`)
- `confidence` = 0.70 initial (recalibrated after contradiction check)

Field identifiers from the generic stop-key list (`_GENERIC_STOP_KEYS` in `contradiction-scanner.py`) are excluded from belief graph insertion — they generate too many false positives across artifacts.

**Layer 2 — BeliefGraph**

In-memory dict `{field_identifier: BeliefNode}` for ACTIVE nodes plus a list of SUPERSEDED nodes. Persisted to JSON at `--belief-graph` path after each artifact is processed (atomic write via temp file + rename per FR-NS3B-ERR-002).

The four K*2 postulates map to these BeliefGraph operations:

| Postulate | Operation |
|-----------|-----------|
| Success | `add_belief(node)` — adds incoming node to ACTIVE if `field_identifier` and `value` are non-null/non-empty |
| Consistency | After `apply_revision()`, ACTIVE contains exactly one node per `field_identifier` |
| Relevance | `apply_revision()` moves only the node with matching `field_identifier` to SUPERSEDED |
| Vacuity | If `check_conflict()` returns None (no existing ACTIVE node), `add_belief()` inserts without any removal |

**Layer 3 — Contradiction Classifier**

Three contradiction type detectors (FR-NS3B-002), applied in order when `check_conflict()` finds an existing ACTIVE node:

1. **assertion_conflict**: The new value is a direct semantic antonym or numerical inversion of the existing value. Detection: look for negation patterns (`_NEGATION_RE`), status-term inversions (PASS↔FAIL, ENABLED↔DISABLED), and numerical divergence > 20% of existing value.
2. **scope_conflict**: The new assertion contains explicit scope boundary terms (`only`, `all`, `none`, `any`, `within`, `excluding`) that are incompatible with the scope terms in the existing value.
3. **architecture_conflict**: The new assertion names an architectural component (database, queue, API, cache, service) not present in the existing value, implying an architectural decision change.

Each detector produces a confidence score:
- assertion_conflict: 0.80 (high confidence — direct negation is deterministic)
- scope_conflict: 0.70 (medium — scope terms are explicit but interpretation requires context)
- architecture_conflict: 0.60 (lower — component name presence is a signal, not proof)

**ConflictSignal fields** (full dataclass in data-model.md):
- `field_identifier`, `new_value`, `existing_node_ref`, `contradiction_type`, `confidence`, `recommended_action`
- `recommended_action` logic: if confidence ≥ 0.80 → `escalate`; if 0.65-0.79 → `revert`; if < 0.65 → `accept` (low confidence = non-actionable, log only)

**Contradiction Report format**: JSON file at `--output` path listing all ConflictSignals with per-item fields from FR-NS3B-006.

**BeliefGraph persistence format**: see data-model.md §2 for the JSON structure.

### Consequences

- POSITIVE: No external libraries needed beyond stdlib + pyyaml (already in stack). Pure Python dict operations.
- POSITIVE: Reuses contradiction-scanner.py regex patterns — consistent extraction logic across tools.
- POSITIVE: Atomic write + rollback (temp file rename) satisfies FR-NS3B-ERR-002 without a database.
- NEGATIVE: Assertion extraction is heuristic (same limitation as contradiction-scanner.py). False positive rate target (≤0.20 FPR) requires calibration against the stop-key list.
- NEGATIVE: Post-hoc mode cannot prevent contradictions — it only detects them after the fact. This is documented (ADR-001) and does not affect the CCR metric.

### Alternative Considered

Full semantic embedding similarity for contradiction detection: Rejected. Would require an embeddings API call per assertion pair (expensive, slow, API-only-constraint risk per spec §4 Out-of-Scope). The heuristic pattern approach achieves the ≥0.80 CCR target at a fraction of the cost, consistent with how `contradiction-scanner.py` was designed.

---

## ADR-004: U-CA-004 AQS Proxy Scorer Design — Fixed Prompt + Structured Output

**Status**: DECIDED
**FR addressed**: FR-UCA-001 through FR-UCA-007, FR-UCA-ERR-001 through FR-UCA-ERR-003, NFR-AUD-001

### Context

P-021 authorizes an automated LLM judge proxy for AQS scoring. The proxy must use a fixed versioned prompt template, evaluate five dimensions independently (completeness, consistency, specificity, actionability, innovation), produce 0-5 integer scores, and log every call for audit. Two design concerns require decisions: (1) how to extract integer scores reliably from the API response, and (2) how to structure the audit trail.

Additionally, GATEKEEPER flagged evaluator-model circularity: the same model family (claude-sonnet-4-6) produces the artifacts being scored and scores them. This must be disclosed in all result templates.

### Decision

**Fixed Scoring Prompt Template (P-021 compliant — version 1.0.0)**

This is the exact template text. It must not be modified during an experiment batch. Its SHA-256 hash is recorded as `scoring_prompt_hash` in every EvaluationRecord.

```
You are an impartial artifact quality evaluator for a multi-agent software specification system.

Score the following agent artifact on FIVE dimensions. Each dimension is scored independently as an INTEGER from 0 to 5 (0 = absent/unusable, 5 = exemplary).

Dimension definitions:
- COMPLETENESS (0-5): Does the artifact address all required sections for its stated category? Are critical fields populated with substantive content?
- CONSISTENCY (0-5): Are claims within the artifact internally consistent? Do values, numbers, and scope statements agree with each other?
- SPECIFICITY (0-5): Are recommendations, decisions, and findings stated with sufficient precision to be actionable? (No vague statements like "should consider.")
- ACTIONABILITY (0-5): Can a downstream agent use this artifact directly to begin its work without requesting clarification?
- INNOVATION (0-5): Does the artifact demonstrate original analysis, non-obvious findings, or novel framing beyond restating the problem?

Artifact to evaluate:
---
{ARTIFACT_TEXT}
---

Respond with EXACTLY these five lines and no other text:
COMPLETENESS: <integer 0-5>
CONSISTENCY: <integer 0-5>
SPECIFICITY: <integer 0-5>
ACTIONABILITY: <integer 0-5>
INNOVATION: <integer 0-5>
```

**Score Extraction**

Parse response lines using regex: `^(COMPLETENESS|CONSISTENCY|SPECIFICITY|ACTIONABILITY|INNOVATION):\s*([0-5])\s*$`. If any line fails to match or the integer is out of [0,5], the entire invocation score is marked out-of-range per FR-UCA-ERR-001 (discard + retry once). If the retry also fails, mark SCORING_FAILED.

Structured output (Claude API `response_format`) is NOT used in v1. The structured prompt format above produces reliable line-parseable output at temperature=0 without requiring beta features that may not be stable. This is a deliberate conservative choice.

**Audit Trail Format**

Every scoring call appends one JSON object to `experiments/uca004-scoring-audit.jsonl` (newline-delimited JSON, one record per line):

```json
{
  "run_id": "<uuid4>",
  "condition": "BASELINE|CA-ACTIVE",
  "invocation_index": 0,
  "scoring_prompt_version": "1.0.0",
  "scoring_prompt_hash": "<sha256 hex>",
  "model_identifier": "claude-sonnet-4-6",
  "request_timestamp": "<ISO 8601>",
  "response_timestamp": "<ISO 8601>",
  "raw_prompt": "<full prompt text>",
  "raw_response": "<full response text>",
  "extracted_scores": {
    "completeness": 0,
    "consistency": 0,
    "specificity": 0,
    "actionability": 0,
    "innovation": 0
  },
  "extraction_status": "OK|OUT_OF_RANGE|SCORING_FAILED",
  "retry_count": 0
}
```

**Evaluator-Model Circularity Disclosure (mandatory in all result templates)**

The following statement must appear verbatim in `experiments/uca004-results.json` under the `limitations` key, and in `experiments/uca004-negative-report.md` under a "Limitations" section:

> "AQS proxy circularity: the scoring model (claude-sonnet-4-6) is from the same model family as the model that produced the artifacts being scored. Self-evaluation introduces potential evaluator bias. This limitation is disclosed per GATEKEEPER feasibility assessment. Results should be interpreted with this constraint in mind. Independent human evaluation of a sample (n≥5 per condition) is recommended before patent filing."

**Statistical Analysis**

Mann-Whitney U: `scipy.stats.mannwhitneyu(baseline_aqs_totals, ca_active_aqs_totals, alternative='two-sided')`. Cohen's d: `(mean_ca - mean_baseline) / pooled_std` where `pooled_std = sqrt(((n1-1)*var1 + (n2-1)*var2) / (n1+n2-2))`. Both computed in-script using scipy + stdlib math only.

VOID rule: checked before any statistical computation. If either condition has fewer than 16 successful completions, set `verdict = "VOID"`, `void_reason = "<condition> had <N> completions, minimum 16 required"`, and skip Mann-Whitney.

Power limitation disclosure for NEGATIVE verdicts: the negative report template MUST include: "Statistical power at N=20 with alpha=0.05 is approximately 0.56 for detecting a medium effect (d=0.5). A NEGATIVE verdict at this sample size is genuinely inconclusive for small effects — it does not rule out d<0.5 improvements."

### Consequences

- POSITIVE: Regex extraction is deterministic given structured response format. Reliable score parsing without beta API dependencies.
- POSITIVE: JSONL audit trail is append-only and human-readable. Post-hoc audit of every scoring decision is trivial.
- NEGATIVE: Evaluator-model circularity is a material limitation for patent-track use. Disclosed per GATEKEEPER requirement.
- NEGATIVE: N=20 has limited statistical power for small effects. Binary POSITIVE/NEGATIVE framing (no INCONCLUSIVE per P-020) masks this.

### Alternative Considered

Claude API structured output (JSON mode): Rejected for v1. The `response_format` JSON mode requires additional API parameters that may not be available in all SDK versions pinned in requirements.txt. The line-format prompt achieves equivalent reliability at temperature=0 with zero additional dependencies.

---

## ADR-005: CA Overlay Integration Design — Context Pack Enrichment Interface

**Status**: DECIDED (CONDITIONAL — design for HOW spec only; implementation blocked by P-006 until U-CA-004 POSITIVE)
**FR addressed**: FR-CAO-000 through FR-CAO-006
**Constraint**: This ADR describes the HOW-level design. No implementation file in `scripts/ca/` may be created until `scripts/ca/verify_gate.sh` confirms U-CA-004 POSITIVE.

### Context

Each CA overlay must hook into COMMANDER's dispatch without modifying routing logic, quality gate thresholds, or endocrine triggers (FR-CAO-006, P-016). The overlays are: Goal Stack, ACT-R Typed Buffer, LIDA Broadcast, GWT Bounded Workspace, Episodic Memory. COMMANDER must call each overlay before dispatch; the overlay enriches the context_pack and returns it.

OQ-005 (retrieval_buffer ranking method for ACT-R) is resolved here: TF-IDF via manual implementation (stdlib only, no sklearn dependency). This keeps the dependency set minimal and within the API-only constraint. Embedding API calls per retrieval request would add latency and cost per dispatch — not acceptable for a context-pack enrichment step that runs on every agent invocation.

### Decision

**Interface: `enrich_context(context_pack: dict, run_id: str) → dict`**

Each Python overlay module exposes exactly this function. COMMANDER calls it as a Python import before dispatch. The function is read-only on all COMMANDER state — it only writes to the returned context_pack dict.

**Per-overlay design:**

**Goal Stack (`scripts/ca/goal_stack.py`)**
- Persistent goal hierarchy per run stored at `.specify/squad/goal-stack-<run_id>.json`.
- Initialized at first dispatch: root goal = spec feature name from `spec.md` header.
- `enrich_context()` reads the JSON, extracts the current active goal (top of stack), and inserts `context_pack["active_goal"] = {goal_text, priority, depth}`.
- Goal stack updated by writing a new JSON after each dispatch (COMMANDER calls a separate `update_goal_stack(outcome, run_id)` function post-dispatch).

**ACT-R Typed Buffer (`scripts/ca/actr_buffer.py`)**
- Restructures an existing flat context_pack into four typed buffers:
  - `declarative`: factual content from prior artifacts (spec facts, known constraints)
  - `procedural`: the agent's role description and task instructions
  - `goal`: current task description + success criteria
  - `imaginal`: current artifact under construction (if applicable) or empty
- TF-IDF retrieval ranking for `retrieval_buffer` (read-only lookup, not a fifth buffer): manual implementation using word frequency counts across prior artifacts. Returns top-3 most relevant prior artifact excerpts by TF-IDF cosine similarity to the current task description.
- Token count verification: count words (4 chars/token heuristic) across all four buffers. If total exceeds the standard context_pack word count, evict from `declarative` first (recency = lower priority among equal-importance facts).
- FR-CAO-002 compliance: the structured output context_pack MUST NOT exceed the token count of the standard COMMANDER context_pack for the same agent type.

**LIDA Broadcast (`scripts/bash/lida_broadcast.sh`)**
- File-based mechanism. Broadcast payload written to `.specify/squad/lida-payload.json`.
- Replace-not-append semantics: each call overwrites the file entirely (FR-CAO-003).
- COMMANDER consumes (reads + deletes) the payload file at the start of the next dispatch cycle.
- Run-end cleanup: COMMANDER's run-end protocol calls `lida_broadcast.sh cleanup <run_id>` which deletes any remaining payload file.
- Bash interface: `lida_broadcast.sh broadcast <payload_json_string>` and `lida_broadcast.sh cleanup <run_id>`.
- COMMANDER integration: one `if [ -f .specify/squad/lida-payload.json ]` check at the top of each dispatch cycle, reads the file into a shell variable, deletes the file, injects variable into context_pack.

**GWT Bounded Workspace (`scripts/ca/gwt_workspace.py`)**
- Token-bounded workspace stored in `.specify/squad/gwt-workspace-<run_id>.json`.
- Configured maximum token bound: `squad-config.yml` key `ca_overlays.gwt.max_tokens` (default: 2000 tokens ≈ 8000 chars using 4-char heuristic).
- Content items have `priority = timestamp` (recency = higher priority). When adding content that would exceed the bound, evict the oldest (lowest timestamp) item first. Repeat until bound is satisfied.
- `enrich_context()` reads the workspace and inserts `context_pack["gwt_workspace"] = [list of current workspace items]`.

**Episodic Memory (`scripts/ca/episodic_memory.py`)**
- Temporal artifact index stored at `.specify/squad/episodic-index-<run_id>.json`.
- Append-only: each agent-produced artifact is indexed with `{agent_type, artifact_path, stage_timestamp, artifact_category}`.
- `enrich_context()` with `agent_type` parameter: returns the single most-recent artifact path for that agent type from the index.
- Query: `max(entries where agent_type == requested_type, key=stage_timestamp)`.
- No cross-run persistence in v1 (FR §2 Out-of-Scope).

**Gate Check Service (`scripts/ca/verify_gate.sh`)**
- Checks: (1) `experiments/uca004-results.json` exists, (2) `verdict` field equals "POSITIVE", (3) `codebase_commit_hash` field matches `git rev-parse HEAD` output.
- Exits 0 if all three pass. Exits 1 with specific error message for each failure case.
- Must be called as the first step of any CA overlay implementation task.

### Consequences

- POSITIVE: Overlay interface (`enrich_context`) is uniform across all Python overlays — COMMANDER calls the same pattern for each.
- POSITIVE: Bash overlay (LIDA) uses a file-based mechanism that requires zero Python import changes to COMMANDER.
- POSITIVE: TF-IDF via stdlib avoids adding sklearn/numpy to the dependency stack.
- NEGATIVE: Four-buffer ACT-R restructuring may reduce context_pack readability for debugging. Token count verification using word-count heuristic (not true tokenizer) introduces ≤10% estimation error.
- NEGATIVE: Goal Stack and GWT Workspace require per-run JSON files in `.specify/squad/` — these must be gitignored to avoid cluttering the artifact store with run-specific state.

### Alternative Considered

COMMANDER calls overlays via subprocess (CLI) rather than Python import: Rejected. CLI subprocesses introduce serialization overhead (JSON marshalling of context_pack per call) and require COMMANDER to handle subprocess failures explicitly. Python import is cleaner, faster, and produces a more testable interface.

---

## ADR-006: IS-005 Resolution — Endocrine Phase 3 Wiring in COMMANDER

**Status**: DECIDED
**Issue resolved**: IS-005 (HIGH — Phase 3 hooks exist in endocrine.sh but are not called from COMMANDER)
**Constraint**: Sequencing — endocrine Phase 3 wiring MUST be activated AFTER NS-003 experiment completes (RSK-003 cortisol cascade risk during calibration runs)

### Context

`endocrine.sh` Phase 3 functions exist (`cmd_on_gate_pass`, `cmd_on_gate_fail`, `cmd_on_rework`, `cmd_on_quality_improvement`, `cmd_on_quality_regression`) at lines 654-721. COMMANDER's post-dispatch protocol (commander.md §Post-Dispatch Protocol, lines 226-234) calls only `decay_hormones`. Phase 3 is not activated (`state.json: endocrine_phase: 1`).

GATEKEEPER identified RSK-003: if NS-003 triggers many `on_gate_fail` events during calibration (expected — calibration artifacts will fail schema validation intentionally), cortisol levels will cascade to circuit-breaker ceiling for all agents. This would contaminate production endocrine state before the experiment properly begins.

### Decision

**Amendment text for `commander.md` §Post-Dispatch Protocol:**

The following two steps are added to the post-dispatch protocol, immediately after the existing `decay_hormones` call, gated on `endocrine.phase >= 3`:

**Step 2 (insert after current Step 1 — decay_hormones):**
```
2. **Gate event dispatch (when endocrine.phase >= 3)**:
   Read the quality gate result from the just-completed agent dispatch.
   - If the agent's primary quality gate PASSED: run
     `scripts/bash/endocrine.sh on_gate_pass <agent>`.
     Log `ENDOCRINE_GATE_PASS` in reasoning-journal.json.
   - If the agent's primary quality gate FAILED: run
     `scripts/bash/endocrine.sh on_gate_fail <agent>`.
     Log `ENDOCRINE_GATE_FAIL` in reasoning-journal.json.
   Note: gate result is read from the agent's return state, not re-evaluated.
```

**Step 3 (insert after Step 2):**
```
3. **Quality improvement signal (when endocrine.phase >= 3)**:
   Compare the current dispatch's quality score (if available) against
   the previous dispatch's quality score for the same agent role.
   - If quality score improved by >= 0.05: run
     `scripts/bash/endocrine.sh on_quality_improvement`.
     Log `ENDOCRINE_QUALITY_IMPROVEMENT` in reasoning-journal.json.
   - If quality score regressed by >= 0.05: run
     `scripts/bash/endocrine.sh on_quality_regression`.
     Log `ENDOCRINE_QUALITY_REGRESSION` in reasoning-journal.json.
   - If no prior score for this agent role exists, skip this step.
```

**Activation sequence (mandatory ordering):**

1. NS-003 experiment (ns003_experiment.py) runs to completion and writes `experiments/ns003-results.json`.
2. A human manually sets `endocrine_phase: 3` in `squad-config.yml`.
3. COMMANDER reads the updated phase setting on next run initialization.
4. Phase 3 hooks activate from that run forward.

NS-003 calibration and experiment invocations MUST run with `endocrine_phase: 1` (current default). The calibration artifact failures that trigger `on_gate_fail` during Phase 1 have no downstream effect (the command is never called). This prevents the RSK-003 cortisol cascade.

**Which Phase 3 hooks to wire first**: `on_gate_pass` and `on_gate_fail` are wired first (highest signal value — directly correlate with dispatch quality outcomes). `on_quality_improvement` / `on_quality_regression` are wired in the same amendment (low additional complexity once the gate event dispatch logic is in place).

`on_rework` is NOT wired in this amendment (requires a rework detection criterion that is not yet defined). It is deferred to a follow-up ADR in a future spec.

### Consequences

- POSITIVE: Phase 3 activation is gated on human action (squad-config.yml edit), not automated. Prevents accidental premature activation.
- POSITIVE: `endocrine.phase >= 3` guard means the amendment is forward-compatible — activating Phase 2 in a future spec does not accidentally trigger Phase 3 hooks.
- NEGATIVE: `on_rework` is not wired. Rework events during Phase 3 will not trigger cortisol accumulation. This is a known gap documented for follow-up.
- NEGATIVE: Quality score comparison requires COMMANDER to read the current agent's quality score from the return state — this field must be standardized across all agent outputs. IMPLEMENTER must confirm the return state format includes `quality_score` or equivalent.

### Alternative Considered

Automatic Phase 3 activation at NS-003 experiment completion: Rejected. Automatic activation bypasses the human-in-the-loop requirement for constitutional changes (P-016 governs endocrine system constraints). Requiring manual squad-config.yml edit preserves human oversight of the moment Phase 3 becomes active.

---

## Design Integration Notes

### Shared Parser Module

Both `ns003_critic.py` and `ns003_agm.py` use the Markdown extraction regex patterns from `contradiction-scanner.py`. IMPLEMENTER must extract these patterns into a shared `scripts/md_parser.py` module (or inline-copy them with a comment citing the source) to avoid drift between the two implementations.

### Experiment Sequencing

1. **Phase 0**: Locate/generate calibration set (runs 015-016 artifacts). Record commit hash.
2. **Phase 1**: Run `ns003_critic.py` against calibration set. Check FRR ≤ 5%. If FRR > 5%, recalibrate schemas. Do not proceed to Phase 2 until Phase 1 passes. Measure structured-to-prose ratio.
3. **Phase 2**: Run `ns003_experiment.py` (N=30 live invocations or historical_artifacts fallback).
4. **Phase 3**: Run `uca004_runner.py` (N=20 per condition).
5. **Phase 4 (CONDITIONAL)**: If U-CA-004 POSITIVE, run `verify_gate.sh` then implement CA overlays.
6. **Phase 5**: Wire endocrine Phase 3 hooks (human activates via squad-config.yml edit).

### API Key Propagation (IS-009)

All scripts implement FR-DEP-003: check `os.environ.get("ANTHROPIC_API_KEY")` at startup, exit with code 1 and human-readable message if absent. Subagent environment inheritance of `ANTHROPIC_API_KEY` from parent shell is expected (standard Claude Code behavior) but must be verified by running a minimal SDK auth test before the first live experiment invocation. This verification is an explicit IMPLEMENTER task.

### Commit Hash Lock (IS-006)

`ns003_experiment.py` and `uca004_runner.py` both call `subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)` at startup and store the result in the results JSON. If git is unavailable, the scripts exit with code 1 — a missing commit hash makes results non-reproducible and must not be silently omitted.

### Calibration Set (IS-010)

Primary: artifacts from spec runs 015-016 at `.specify/specs/015-*/` and `.specify/specs/016-*/`. If unavailable, fallback to artifacts from any prior spec run present in `.specify/specs/`. Label the data source as `"historical_artifacts"` in `ns003-results.json` and include the DEVIATION statement in `ns003-report.md` (FR-NS3E-001 pre-registered deviation path).
