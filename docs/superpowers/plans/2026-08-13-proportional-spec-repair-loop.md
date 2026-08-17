# Proportional Specification Repair Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make proportional specification authoring use consistent requirement evidence, spend at most three automatic quality repairs, and then obtain an explicit human or COMMANDER decision about one final repair, continuation with recorded quality debt, or stopping.

**Architecture:** Understanding first projects each formal statement into one canonical requirement representation and shares one deterministic actor/action/object detector across structural and semantic scoring. A new `harness.proportional_quality` policy module owns proportional counters, candidate manifests, eligibility, ranking, restoration, debt authorization, and recommendation evidence. `SquadController` integrates those pure policies at WHAT and WHY2 boundaries and routes exhausted budgets through the existing sealed human-input/COMMANDER decision machinery. Current passing certificates remain the normal path; a separately verified debt authorization is the only alternate prerequisite for downstream Phase 1 consumers.

**Tech Stack:** Python 3.11+, frozen dataclasses, JSON, SHA-256, existing Git/checkpoint helpers, existing Understanding metrics, existing human-input v2 decisions, pytest.

## Global Constraints

- Do not lower or special-case any configured Understanding threshold.
- Do not change perfectionist authoring behavior or reinterpret the global workflow iteration cap.
- Permit exactly three consumed automatic proportional repairs and at most one consumed extension repair.
- Count an automatic repair only for a valid WHAT completion whose canonical `spec.md` digest changed.
- Once the optional extension is authorized, count any valid WHAT completion as consuming it; an unchanged extension cannot be retried for free.
- Do not count provider, timeout, result-envelope, state-contract, artifact-validation, or checkpoint failures.
- Send a valid unchanged WHAT completion directly to the quality-debt decision without consuming a repair.
- Never offer quality debt for a critical issue, contradiction, unresolved evidence/product decision, invalid product mapping or traceability, invalid mandatory artifact, or operational/state-integrity failure.
- Keep candidate selection deterministic and restore only candidate-owned specification artifacts.
- Preserve continue/resume state; initialize legacy proportional state conservatively from completed WHY2 history.
- Keep all decisions sealed: guided and semi modes await the user; banzai delegates the same options to COMMANDER with the existing two-attempt validation limit.
- Publish and summarize accepted quality debt visibly; never represent it as a passing quality certificate.
- Require a live Codex proportional Hello World run before calling the feature operationally validated.

---

### Task 1: Project formal requirements once and share role evidence

**Files:**
- Create: `src/understanding/requirement_projection.py`
- Create: `src/understanding/role_detection.py`
- Modify: `src/understanding/service.py`
- Modify: `src/understanding/requirements_metrics.py`
- Modify: `src/understanding/semantic_metrics.py`
- Create: `tests/unit/test_requirement_projection.py`
- Modify: `tests/unit/test_understanding_service.py`
- Create: `tests/unit/test_requirements_metrics.py`
- Create: `tests/unit/test_semantic_metrics.py`

**Interfaces:**
- Produces: frozen `SourceLocation(line_start: int, line_end: int)`.
- Produces: frozen `RequirementProjection(requirement_id, original_text, normative_text, traceability_references, constraints, source_location)`.
- Produces: `project_requirements(spec_text: str) -> tuple[RequirementProjection, ...]`.
- Produces: frozen `RequirementRoles(actor, action, object, detector_evidence)`.
- Produces: `detect_requirement_roles(text: str) -> RequirementRoles`.
- Preserves: `parse_requirements(spec_text)` as a compatibility dictionary projected from the canonical objects.

- [ ] **Step 1: Add failing projection tests using conventional and Lexicon syntax**

Cover bold-ID bullets, FR/NFR heading plus `Statement`, folded Lexicon output constraints, `Constraint:`/`Constraints:`, `Verified by:`, inline `FR-###`/`NFR-###`/`AC-###` references, duplicate self-references, and exact source lines. Assert that comparator and traceability metadata are absent from `normative_text`, constraints remain available for testability, and references are normalized, unique, and exclude the requirement's own identifier.

```python
def test_projection_separates_normative_text_constraints_and_traceability():
    projections = project_requirements(SPEC)
    req = projections[0]
    assert req.requirement_id == "FR-001"
    assert req.normative_text == "The command prints Hello, world! to standard output."
    assert req.constraints == ("Exit status is zero.",)
    assert req.traceability_references == ("AC-001",)
    assert req.source_location.line_start == 4
```

- [ ] **Step 2: Add a failing regression for contradictory role judgments**

Use a formal statement with a domain actor outside the legacy vocabulary, such as `The greeting command must write the configured message to standard output.` Assert that shared detection finds actor, action, and object; structural completeness counts it as complete; and `SemanticAnalyzer.extract_roles_as_dict()` reports the same booleans and tokens.

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `pytest tests/unit/test_requirement_projection.py tests/unit/test_understanding_service.py tests/unit/test_requirements_metrics.py -q`

Expected: imports or assertions fail because canonical projection and shared role detection do not exist.

- [ ] **Step 4: Implement deterministic projection and shared role detection**

Move formal-statement recognition out of `service.parse_requirements()` into `requirement_projection.py`. Preserve the original statement and source location, strip only recognized metadata from the normative projection, and fail conservatively by retaining unrecognized prose as normative text. Implement role detection without optional NLP: identify the grammatical subject before the modal/action, the first meaningful action verb, and content after the action as its object; retain detector evidence for diagnostics. Make `RequirementsAnalyzer._analyze_structure()` and `SemanticAnalyzer.extract_roles_as_dict()` consume this shared result while leaving atomicity, passive voice, pronoun, and modal calculations independent.

- [ ] **Step 5: Route metric families through the correct projection fields**

In `analyze_spec_bundle()`:

- build aggregate structure/readability/cognitive/semantic/behavioral scoring text from `normative_text`;
- append normalized constraints only to the testability input;
- build depth dependencies only from `traceability_references` and real requirement references;
- include `original_text`, the projected fields, source location, shared roles, and detector evidence in each per-requirement report.

Keep `evaluate_quality_gates()` and `kernel.quality_gates.evaluate_quality_thresholds()` unchanged.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_requirement_projection.py tests/unit/test_understanding_service.py tests/unit/test_requirements_metrics.py tests/unit/test_semantic_metrics.py -q`

- [ ] **Step 7: Commit**

```bash
git add src/understanding/requirement_projection.py src/understanding/role_detection.py src/understanding/service.py src/understanding/requirements_metrics.py src/understanding/semantic_metrics.py tests/unit/test_requirement_projection.py tests/unit/test_understanding_service.py tests/unit/test_requirements_metrics.py tests/unit/test_semantic_metrics.py
git commit -m "fix: align requirement quality evidence"
```

### Task 2: Define proportional repair state and exact accounting

**Files:**
- Create: `src/harness/proportional_quality.py`
- Create: `tests/unit/test_proportional_quality.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/state_transaction_namespace.py`
- Modify: `tests/kernel/test_squad_state.py`
- Create: `tests/unit/test_state_transaction_namespace.py`

**Interfaces:**
- Produces: `initialize_repair_state(state: Mapping[str, object]) -> dict[str, object] | None`.
- Produces: `validate_repair_state(value: object) -> dict[str, object]`.
- Produces: `record_what_outcome(repair_state, *, baseline_sha256, current_sha256, valid_completion, extension_active) -> RepairOutcome`.
- Defines controller constants `AUTOMATIC_REPAIR_LIMIT = 3`, `EXTENSION_REPAIR_LIMIT = 1`, and schema version 1.

- [ ] **Step 1: Write failing state initialization and accounting tests**

Cover:

- new proportional state starts at 0/3 automatic and 0/1 extension;
- perfectionist state returns `None` and creates no record;
- existing valid state round-trips unchanged on continue/resume;
- legacy proportional history derives consumed work from completed/certified WHY2 assessments and caps it at three;
- valid changed automatic WHAT increments only `automatic_consumed`;
- valid changed extension WHAT increments only `extension_consumed`;
- unchanged automatic success returns `no_artifact_progress` without incrementing;
- unchanged authorized-extension success sets `extension_consumed` and returns `no_artifact_progress`;
- invalid/operational outcomes return `not_consumed` without incrementing;
- malformed limits, negative counters, over-limit counters, or agent-authored overrides fail closed.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/unit/test_proportional_quality.py tests/kernel/test_squad_state.py tests/unit/test_state_transaction_namespace.py -q`

- [ ] **Step 3: Implement the pure state policy**

Derive authoring mode from the existing persisted authoring decision, treating an existing missing/legacy mode as proportional. For legacy runs, count completed WHY2 assessment evidence from the run history rather than the mutable global iteration field; if history is absent, use the current global iteration capped at three. Record whether migration used candidate history or the iteration fallback. Return new dictionaries rather than mutating caller data. Make all limits module-owned constants.

- [ ] **Step 4: Register controller ownership**

Add `phase1_quality_repair` to the state schema/initialization path only for proportional authoring and to the controller-owned transaction namespace. Reject the key from agent `state_updates`. Do not add it to perfectionist state snapshots.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_proportional_quality.py tests/kernel/test_squad_state.py tests/unit/test_state_transaction_namespace.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/harness/proportional_quality.py src/harness/squad_state.py src/harness/state_transaction_namespace.py tests/unit/test_proportional_quality.py tests/kernel/test_squad_state.py tests/unit/test_state_transaction_namespace.py
git commit -m "feat: track proportional quality repairs"
```

### Task 3: Capture, rank, and restore eligible quality candidates

**Files:**
- Modify: `src/harness/proportional_quality.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_proportional_quality.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Produces: frozen `QualityCandidateManifest` with schema version, candidate ID, checkpoint commit, owned artifact digests, evidence references/digests, normalized gates, SAGE finding routes, counts, repair number, and eligibility reasons.
- Produces: `capture_quality_candidate(...) -> QualityCandidateManifest`.
- Produces: `rank_quality_candidates(candidates) -> tuple[QualityCandidateManifest, ...]`.
- Produces: `restore_quality_candidate(project_root, spec_dir, candidate, *, run_id, spec_id) -> PhaseCheckpoint`.
- Stores manifests under the run artifact root at `quality-candidates/<candidate-id>.json`.

- [ ] **Step 1: Write failing manifest and ranking tests**

Create candidates that differ on failed-gate count, worst margin, overall score, formal-statement count, and assessment order. Assert the exact lexicographic ordering from the design. Assert candidates with hard-blocker eligibility reasons never enter the ranked eligible set.

- [ ] **Step 2: Write failing restoration-integrity tests**

Initialize a temporary Git repository and record two candidates. Assert restoration reads only the manifest-owned `spec.md`, optional `requirements-overview.md`, `quality-gates.md`, and `issues.md` from the selected commit, leaves unrelated tracked files and controller state untouched, verifies restored SHA-256 digests, and creates a new `phase1-quality-candidate-restored` checkpoint. Immutable Understanding evidence remains referenced in the run artifact store and is re-verified rather than copied from Git. Assert missing commits, missing owned artifacts, path escape, digest mismatch, dirty conflicting candidate paths, and checkpoint failure raise a state-integrity error rather than returning a debt-eligible result.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `pytest tests/unit/test_proportional_quality.py tests/unit/test_phase_checkpoints.py -q`

- [ ] **Step 4: Implement candidate capture at a committed assessment boundary**

Use `create_phase_checkpoint()` with a unique candidate checkpoint ID immediately after a valid WHY2 assessment has produced immutable Understanding evidence and current SAGE artifacts. Hash `spec.md`, optional `requirements-overview.md`, Understanding JSON, `quality-gates.md`, and `issues.md`; reject required missing/malformed inputs. Persist the manifest atomically after the checkpoint succeeds. Record the candidate ID in `phase1_quality_repair.candidate_ids` and set `baseline_candidate_id` only once.

- [ ] **Step 5: Implement deterministic ranking and narrow restoration**

Sort eligible candidates by `(failed_gate_count, -worst_gate_margin, -overall_score, formal_statement_count, assessment_index)`. Add a checkpoint helper that uses the existing safe Git runner to read explicit repository-relative manifest-owned paths from the recorded commit, writes through temporary sibling files plus `os.replace`, re-hashes every restored artifact, and then records the restoration checkpoint. Do not use checkout/reset and do not restore run state, decisions, journals, or unrelated files.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_proportional_quality.py tests/unit/test_phase_checkpoints.py -q`

- [ ] **Step 7: Commit**

```bash
git add src/harness/proportional_quality.py src/harness/phase_checkpoints.py tests/unit/test_proportional_quality.py tests/unit/test_phase_checkpoints.py
git commit -m "feat: preserve proportional quality candidates"
```

### Task 4: Register the sealed quality-budget decisions

**Files:**
- Modify: `src/harness/human_input.py`
- Modify: `src/harness/blocked_decision.py`
- Modify: `tests/integration/test_human_input_routing.py`
- Modify: `tests/unit/test_blocked_decision.py`
- Modify: `tests/kernel/test_phase_graph.py`

**Interfaces:**
- Adds controller safeguard reason `proportional_quality_budget_exhausted` with exact option IDs `extend_once`, `continue_with_debt`, and `stop`.
- Adds controller safeguard reason `proportional_quality_extension_exhausted` with exact option IDs `continue_with_debt` and `stop`.
- Adds resolution handler `proportional_quality_debt`.
- Allows controller-prepared recommendation metadata while keeping provider-authored options forbidden.

- [ ] **Step 1: Write failing policy-compilation tests**

Assert both policies are registered only for `phase1-why2`, are `material`, require a sealed option, forbid free text, expose no unregistered targets, and contain exactly the designed IDs. Assert the first policy cannot be prepared after extension authorization and the second cannot contain `extend_once`.

- [ ] **Step 2: Write failing recommendation tests**

Build sealed evidence where all residual failures are within the configured borderline margin, each still-failing score improved in the latest repair, and formal-statement count did not grow; assert `extend_once` is the sole recommended option. Vary each predicate independently and assert `continue_with_debt` becomes the sole recommendation. Ensure provider fields cannot alter IDs, descriptions, targets, outcomes, or recommendation evidence.

- [ ] **Step 3: Write failing autonomy tests**

Assert guided and semi decisions become `awaiting_human`; banzai decisions become `pending` for COMMANDER; and malformed COMMANDER output still uses the existing maximum of two attempts before blocking. Do not change `blocked_decision` schema version or generic retry count.

- [ ] **Step 4: Run the focused tests and verify RED**

Run: `pytest tests/integration/test_human_input_routing.py tests/unit/test_blocked_decision.py tests/kernel/test_phase_graph.py -q`

- [ ] **Step 5: Add closed controller policies and bounded dynamic recommendation**

Extend `_RESOLUTION_HANDLERS` and `_CONTEXT_STATE_KEYS` for `phase1_quality_repair`, current Understanding evidence, and a bounded candidate/eligibility evidence reference. Define static option contracts in `controller_safeguard_policies()`. Add a controller-only preparation helper that may change only the single `recommended` flag after validating the complete option tuple against the registered policy. Keep ordinary `HumanInputPolicyRegistry.prepare(options=...)` provider-only.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest tests/integration/test_human_input_routing.py tests/unit/test_blocked_decision.py tests/kernel/test_phase_graph.py -q`

- [ ] **Step 7: Commit**

```bash
git add src/harness/human_input.py src/harness/blocked_decision.py tests/integration/test_human_input_routing.py tests/unit/test_blocked_decision.py tests/kernel/test_phase_graph.py
git commit -m "feat: seal proportional quality decisions"
```

### Task 5: Integrate proportional accounting and decisions into the controller

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Adds a focused proportional WHY2 coordinator called from `_coordinate_why_transition_state()` before legacy stagnation/consecutive-failure policy.
- Adds WHAT baseline/finalization hooks in `_controller_enrichment()`.
- Adds `_proportional_quality_debt_resolution(...)` to the existing resolution-handler dispatch table.

- [ ] **Step 1: Write failing three-repair lifecycle tests**

Drive a proportional run through initial WHY2 failure and three valid changed WHAT repairs. Assert:

- the initial assessment creates candidate 0 without consuming a repair;
- each valid changed WHAT consumes exactly one automatic repair;
- Understanding and WHY2 rerun after each repair;
- after the third repair's failing WHY2 assessment, the best eligible candidate is restored and a `proportional_quality_budget_exhausted` decision is created;
- the legacy `why2_metric_stagnation` and consecutive-fail safeguards do not pre-empt the dedicated proportional budget;
- perfectionist mode follows the old route unchanged.

- [ ] **Step 2: Write failing no-op and operational-failure tests**

Assert a valid unchanged WHAT completion creates the decision immediately with `no_artifact_progress` and no counter increment. Parameterize timeout, provider error, missing result envelope, invalid mandatory artifact, state-contract rejection, and checkpoint failure; assert each retains its existing recovery/block reason and never changes either proportional counter or creates quality debt.

- [ ] **Step 3: Write failing extension tests**

Resolve `extend_once`; assert `extension_authorized` becomes one and the run routes to WHAT. Assert either a valid changed or a valid unchanged completion consumes the extension once, while provider/controller failure leaves the same authorization recoverable and unconsumed. On the next failing WHY2 assessment, assert only `continue_with_debt` and `stop` remain. Assert decision replay, ordinary continue, resume, and provider retry cannot authorize or consume a second extension.

- [ ] **Step 4: Run focused tests and verify RED**

Run: `pytest tests/integration/test_squad_controller.py tests/unit/test_squad_phase_checkpoints.py -q`

- [ ] **Step 5: Integrate initialization, candidate capture, and routing**

At the first proportional WHY2 assessment, initialize/validate the controller record, capture the candidate, classify hard blockers, and update candidate IDs transactionally. On quality failure:

- route to WHAT while automatic budget remains;
- open the sealed decision after the third consumed repair;
- open it immediately for a valid unchanged WHAT result;
- after an authorized extension, consume its first valid completion even when unchanged, assess the resulting candidate, and then use the extension-exhausted policy for residual failure;
- otherwise defer to existing issue-resolution, investigation, operational recovery, and hard-blocker routes.

Set `quality_gate_remediation.baseline_spec_sha256` from the current canonical digest, but replace the old generic no-artifact terminal block with the proportional decision only when the completion is otherwise valid and debt-eligible.

- [ ] **Step 6: Implement decision resolution effects**

- `extend_once`: atomically set `extension_authorized=1`, clear the active decision, retain candidate history, and route to WHAT.
- `continue_with_debt`: invoke the debt authorization builder from Task 6 and route to `phase1-lexicon-derive` when the Lexicon gate is enabled, otherwise `checkpoint-assess`.
- `stop`: set terminal blocked state with reason `proportional_quality_debt_declined`, retain evidence/candidates, and make ordinary continue refuse to reopen it.

Use the selected resolution's durable `decision_id` and `resolved_by` value (`user` or `COMMANDER`) in later authorization evidence.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `pytest tests/integration/test_squad_controller.py tests/unit/test_squad_phase_checkpoints.py tests/integration/test_human_input_routing.py -q`

- [ ] **Step 8: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py tests/unit/test_squad_phase_checkpoints.py
git commit -m "feat: bound proportional quality repair"
```

### Task 6: Authorize, verify, and invalidate explicit quality debt

**Files:**
- Create: `src/harness/phase1_quality_debt.py`
- Modify: `src/harness/phase1_quality.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/state_transaction_namespace.py`
- Create: `tests/unit/test_phase1_quality_debt.py`
- Modify: `tests/unit/test_phase1_quality.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `build_quality_debt_authorization(...) -> dict[str, object]` with schema version 1.
- Produces: `has_current_quality_debt_authorization(state, *, project_root) -> bool`.
- Produces: `has_current_phase1_quality_prerequisite(state, *, project_root) -> bool`, true for either a current passing certificate or current debt authorization.
- Writes `quality-debt.json` beside the active specification.

- [ ] **Step 1: Write failing authorization contract tests**

Assert the authorization contains source spec/evidence/candidate/debt artifact paths and SHA-256 digests, decision ID, resolver exactly `user` or `COMMANDER`, UTC timestamp, selected candidate ID, failed gates, margins, and qualitative debt. Assert `quality-debt.json` has the same evidence and is content-addressed by the authorization.

- [ ] **Step 2: Write failing invalidation and hard-blocker tests**

Assert authorization is invalid after any change to `spec.md`, Understanding evidence, candidate manifest, `quality-debt.json`, or decision linkage. Assert builder rejection for every hard-failure class listed in the design. Assert a passing certificate is neither fabricated nor stored when debt is accepted.

- [ ] **Step 3: Write failing downstream guard tests**

Assert `_guard_phase1_quality_evidence()` accepts either a current passing certificate or current debt authorization before Lexicon/checkpoint phases. Assert WHAT amendments remove both stale certificate and stale debt authorization, and delete/replace stale `quality-debt.json` only through the controlled amendment path. Assert an invalid authorization routes back through Understanding and cannot silently advance.

- [ ] **Step 4: Run focused tests and verify RED**

Run: `pytest tests/unit/test_phase1_quality_debt.py tests/unit/test_phase1_quality.py tests/integration/test_squad_controller.py -q`

- [ ] **Step 5: Implement content-bound debt authorization**

Build authorization only from the restored eligible candidate, its verified manifest, immutable Understanding report, current SAGE findings, and resolved sealed decision. Write `quality-debt.json` atomically before storing the controller-owned authorization, then verify all hashes on every prerequisite check. Register `spec_quality_debt_authorization` as controller-owned and reject agent attempts to set it.

- [ ] **Step 6: Replace the downstream prerequisite without weakening certification**

Keep `has_current_phase1_quality_certificate()` unchanged. Add the explicit OR helper and use it only at the current Phase 1 downstream guards. On any WHAT amendment, remove both forms of prior authorization so the next Understanding/WHY2 result must certify or re-authorize the new content.

- [ ] **Step 7: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_phase1_quality_debt.py tests/unit/test_phase1_quality.py tests/integration/test_squad_controller.py tests/unit/test_state_transaction_namespace.py -q`

- [ ] **Step 8: Commit**

```bash
git add src/harness/phase1_quality_debt.py src/harness/phase1_quality.py src/harness/squad.py src/harness/state_transaction_namespace.py tests/unit/test_phase1_quality_debt.py tests/unit/test_phase1_quality.py tests/integration/test_squad_controller.py tests/unit/test_state_transaction_namespace.py
git commit -m "feat: record explicit spec quality debt"
```

### Task 7: Surface quality debt in publication, status, recovery, and summaries

**Files:**
- Modify: `src/harness/squad_publication.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/run_summary.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_squad_publication.py`
- Modify: `tests/unit/test_run_summary.py`
- Modify: `tests/unit/test_cli_status.py`
- Modify: `tests/unit/test_cli_continue.py`

**Interfaces:**
- Publishes `quality-debt.json` with the accepted specification.
- Shows `quality debt` and the residual failed gates in `echelon spec status` and the terminal `SQUAD SUMMARY`.
- Produces an explicit next action for pending decisions and terminal debt-declined runs.

- [ ] **Step 1: Write failing publication and presentation tests**

Assert accepted debt is copied to the published spec directory, retained in run artifacts, and never omitted from the publication manifest. Assert later planning and verification prompts receive the exact verified debt artifact and `accepted_with_debt` status rather than an inferred summary. Assert status and terminal summary say that the spec continued with authorized quality debt, name the residual gate families, identify human versus COMMANDER resolution, and do not say quality passed. Assert the narrative summarizer receives these facts in its bounded evidence.

- [ ] **Step 2: Write failing decision/recovery display tests**

Assert pending budget decisions render the exact sealed choices and recommendation, including remaining automatic/extension counts and selected candidate. Assert `proportional_quality_debt_declined` suggests inspecting the debt evidence or explicitly starting a new/amended run, not ordinary `spec continue`. Assert provider-limit information remains independently visible in the same summary when present.

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `pytest tests/unit/test_squad_publication.py tests/unit/test_run_summary.py tests/unit/test_cli_status.py tests/unit/test_cli_continue.py -q`

- [ ] **Step 4: Implement publication and concise human-readable output**

Extend existing publication ownership lists for `quality-debt.json` and preserve `accepted_with_debt` in published specification metadata/readiness state. Attach the digest-verified artifact to downstream planning and verification context without translating it into PASS. Add compact fields to `_print_squad_summary()` and status rendering; do not introduce a second banner. Add debt facts to `RunSummaryContext` so the separate low-effort summary agent can explain the outcome, while deterministic fallback prose retains the same truth. Keep provider-limit and quality-debt lines independent so dual cases show both.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_squad_publication.py tests/unit/test_run_summary.py tests/unit/test_cli_status.py tests/unit/test_cli_continue.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad_publication.py src/harness/squad.py src/harness/run_summary.py src/echelon/cli.py tests/unit/test_squad_publication.py tests/unit/test_run_summary.py tests/unit/test_cli_status.py tests/unit/test_cli_continue.py
git commit -m "feat: surface specification quality debt"
```

### Task 8: Update workflow contracts and operator documentation

**Files:**
- Modify: `runtime/workflow/phases/phase1-why2.md`
- Modify: `runtime/workflow/definition.yaml`
- Modify: `README.md`
- Modify: `docs/re-overview.md`
- Modify: `tests/unit/test_prosaic_package_install.py`
- Modify: `tests/unit/test_workspace_init_deploy_runtime.py`
- Modify: `tests/kernel/test_phase_graph.py`

- [ ] **Step 1: Write failing deployed-runtime and workflow tests**

Assert installed/new workspaces receive the updated WHY2 instructions and workflow metadata. Assert the graph still routes perfectionist failures under the current global iteration conditions, while proportional exhaustion is declared controller-owned and cannot be waived by SAGE/CARTOGRAPHER output.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest tests/unit/test_prosaic_package_install.py tests/unit/test_workspace_init_deploy_runtime.py tests/kernel/test_phase_graph.py -q`

- [ ] **Step 3: Update runtime and user documentation**

Document the initial assessment plus three automatic repairs, the one optional extension, the difference between passing certification and authorized debt, the guided/semi/banzai decision owner, the hard-failure exclusions, and how status/continue behave. In WHY2 instructions, explicitly prohibit agents from authorizing debt or changing controller counters. Keep generic workflow transitions available for perfectionist mode; annotate proportional routing as a controller policy rather than duplicating counter logic in YAML expressions.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_prosaic_package_install.py tests/unit/test_workspace_init_deploy_runtime.py tests/kernel/test_phase_graph.py -q`

- [ ] **Step 5: Commit**

```bash
git add runtime/workflow/phases/phase1-why2.md runtime/workflow/definition.yaml README.md docs/re-overview.md tests/unit/test_prosaic_package_install.py tests/unit/test_workspace_init_deploy_runtime.py tests/kernel/test_phase_graph.py
git commit -m "docs: explain proportional quality repair"
```

### Task 9: Run regression verification and the live Codex benchmark

**Files:**
- Create: `tests/fixtures/understanding/proportional-hello-world-first-candidate.md`
- Modify: `tests/unit/test_requirement_projection.py`
- Modify: `tests/integration/test_squad_controller.py`
- Evidence only: a fresh temporary Hello World workspace outside this repository

- [ ] **Step 1: Add the live-run regression fixture**

Preserve the 13-statement first assessed Hello World candidate that exposed contradictory structure/semantic scoring. Assert canonical projection excludes traceability/comparator metadata, shared role judgments do not contradict, thresholds are unchanged, and the resulting failed-gate set is stable and explainable.

- [ ] **Step 2: Run the complete focused feature suite**

Run:

```bash
pytest \
  tests/unit/test_requirement_projection.py \
  tests/unit/test_understanding_service.py \
  tests/unit/test_requirements_metrics.py \
  tests/unit/test_semantic_metrics.py \
  tests/unit/test_proportional_quality.py \
  tests/unit/test_phase1_quality.py \
  tests/unit/test_phase1_quality_debt.py \
  tests/unit/test_phase_checkpoints.py \
  tests/integration/test_human_input_routing.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_squad_publication.py \
  tests/unit/test_run_summary.py \
  tests/unit/test_cli_status.py \
  tests/unit/test_cli_continue.py \
  tests/kernel/test_squad_state.py \
  tests/kernel/test_phase_graph.py -q
```

- [ ] **Step 3: Run repository-wide automated verification**

Run the repository's documented lint/type checks and full pytest suite. If the branch retains known failures from main, prove they reproduce unchanged on main before classifying them as unrelated; do not silently omit them.

- [ ] **Step 4: Install the branch into a fresh temporary workspace**

Use the normal package/workspace initialization path, configure Codex as the provider, and request a minimal Python Hello World specification in proportional mode. Do not reuse the earlier workspace or its state.

- [ ] **Step 5: Verify the live acceptance criteria**

Record the run ID, elapsed time, CARTOGRAPHER/WHY2 dispatch counts, each candidate's failed gates and statement count, the final decision/certificate/debt status, and terminal summary. The run passes operational validation only if:

- it reaches passing certification within the initial assessment plus no more than three automatic repairs; or
- after no more than three automatic repairs it stops at the correct sealed decision with truthful remaining debt;
- no repair is consumed for an operational failure or unchanged WHAT result;
- structure and semantic evidence never disagree about actor/action/object presence for the same projected statement;
- banzai mode, if used, records a valid COMMANDER decision through the same sealed choices;
- the terminal summary states quality debt and provider-limit information independently when applicable.

- [ ] **Step 6: Request an independent final code review**

Use `superpowers:requesting-code-review` against the approved design and this plan. Address every confirmed correctness, state-integrity, or test gap, then rerun the affected focused tests and full verification.

- [ ] **Step 7: Commit final regression evidence**

```bash
git add tests/fixtures/understanding/proportional-hello-world-first-candidate.md tests/unit/test_requirement_projection.py tests/integration/test_squad_controller.py
git commit -m "test: verify proportional quality repair"
```

## Completion Criteria

- Canonical requirement projection and shared role detection eliminate contradictory structure/semantic evidence without changing thresholds.
- A new proportional run receives exactly three consumed automatic repairs at most.
- The optional extension can be authorized and consumed exactly once.
- Candidate restoration is digest-verified and cannot alter unrelated Git or controller state.
- Hard failures remain fail-closed and can never be converted into quality debt.
- Guided/semi users and banzai COMMANDER see the same sealed choices and evidence.
- Accepted debt is content-bound, invalidated by amendments, published, and visible in status and the one terminal summary banner.
- Perfectionist behavior and the global iteration safeguard remain unchanged.
- Focused tests, repository checks, and a fresh live Codex Hello World run satisfy the acceptance criteria.
