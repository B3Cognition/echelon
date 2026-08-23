# Banzai Decision Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every fresh automatic human-input decision carry one durable, evidence-backed recommendation and preserve a complete, actionable resolution/recovery audit, including the proportional accepted-debt checkpoint regression.

**Architecture:** Extend the typed preparation boundary first, then persist it in blocked-decision schema v3 under the existing state-store compare-and-swap authority. Route semi, Banzai, migration, checkpoint synthesis, quality-debt currentness, rewind/replay, and CLI presentation through that versioned authority without rewriting historical schema-v2 decisions.

**Tech Stack:** Python 3.11+, frozen dataclasses and strict dictionary validators, YAML workflow contracts, pytest, `uv run --frozen --extra dev`.

**Spec:** `docs/superpowers/specs/2026-08-22-banzai-decision-recommendations-design.md`

## Global Constraints

- Fresh human-input decisions use blocked-decision schema version `3`; recovery-instruction schema remains version `2`.
- Controller/runtime compatibility increases from `1` to `2` in code and `runtime/workflow/definition.yaml`.
- A sealed choice has exactly one recommended option; an automatically eligible free-text request has one non-empty recommended answer.
- Human-only free text carries `recommended_action`, has `automatic_eligible: false`, and never treats the action as an answer.
- Recommendation confidence is exactly `high`, `medium`, or `low`; it is audit metadata and adds no acceptance threshold.
- Recommendation evidence IDs and SHA-256 digests are computed by the controller from registered state or paths.
- Provider return shape remains selected answer, rationale, and confidence; no provider-supplied recommendation evidence field is added.
- Existing schema-v2 resolved, awaiting-human, and semi decisions remain readable and are never assigned invented rationale or confidence.
- Accepted quality debt retains the raw `FAIL` evidence and remains content-bound; later reuse of `state.blocked_decision` must not invalidate its embedded decision authority.
- Failed or terminal decisions render one executable authority-valid rewind or phase-replay command; `continue` is not recovery for a terminal decision.
- The stack-context dissemination work already present on the branch is outside this change.

---

### Task 1: Typed Recommendation Preparation Boundary

**Files:**
- Modify: `src/harness/human_input.py`
- Modify: `src/harness/workflow_validator.py`
- Modify: `runtime/workflow/definition.yaml`
- Test: `tests/unit/test_human_input.py`
- Test: `tests/kernel/test_workflow_validator.py`
- Test: `tests/unit/test_human_input_static_contract.py`

**Interfaces:**
- Produces: `RecommendationEvidence(id: str, kind: str, reference: str, digest: str)`.
- Produces: schema-v2 `PreparedHumanInput` fields `recommended_action`, `automatic_eligible`, `recommendation_rationale`, `recommendation_confidence`, `recommendation_authority`, and `recommendation_evidence`.
- Produces: `HumanInputPolicy.recommendation_mode: Literal["static", "controller"]` and registry enforcement that controller mode names a registered preparer.
- Consumes: existing `HumanInputOption`, autonomy/risk rules, registered context keys/paths, and provider-escalation preparation.

- [ ] **Step 1: Write failing recommendation-contract tests**

```python
def test_prepared_choice_requires_one_recommendation_and_evidence():
    with pytest.raises(HumanInputPolicyError, match="exactly one option"):
        replace(prepared_choice, options=tuple(replace(o, recommended=False) for o in prepared_choice.options))

def test_human_only_free_text_requires_action_and_is_not_automatic():
    request = replace(
        prepared_free_text,
        recommended_answer=None,
        recommended_action='Run echelon spec resume "<answer>" with the requested value.',
        automatic_eligible=False,
    )
    assert request.recommended_action.startswith("Run echelon spec resume")

def test_static_policy_without_unique_recommendation_is_rejected():
    workflow["phases"][0]["human_input"][0]["recommendation_mode"] = "static"
    for option in workflow["phases"][0]["human_input"][0]["options"]:
        option["recommended"] = False
    with pytest.raises(WorkflowValidationError, match="exactly one recommended option"):
        validate_workflow(workflow)
```

- [ ] **Step 2: Run the focused tests and observe the expected failures**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_human_input.py tests/kernel/test_workflow_validator.py tests/unit/test_human_input_static_contract.py`

Expected: FAIL because recommendation metadata and `recommendation_mode` are absent, and zero-recommendation static policies still compile.

- [ ] **Step 3: Implement the typed preparation contract**

```python
RecommendationAuthority = Literal["workflow_policy", "controller_evidence", "provider_evidence"]
RecommendationConfidence = Literal["high", "medium", "low"]
RecommendationMode = Literal["static", "controller"]

@dataclass(frozen=True)
class RecommendationEvidence:
    id: str
    kind: str
    reference: str
    digest: str

@dataclass(frozen=True)
class PreparedHumanInput:
    schema_version: Literal[2]
    # existing identity/question/answer fields remain unchanged
    recommended_action: str | None
    automatic_eligible: bool
    recommendation_rationale: str
    recommendation_confidence: RecommendationConfidence
    recommendation_authority: RecommendationAuthority
    recommendation_evidence: tuple[RecommendationEvidence, ...]
```

Enforce exactly one recommendation target, exactly one recommended option for choices, a recommended answer for automatic free text, and a recommended action only for non-automatic free text. Extend policy compilation so `static` requires one recommendation immediately and `controller` may retain an unrecommended template only for a registered controller preparer. Derive `automatic_eligible` in controller code; do not accept it from provider payloads. Update canonical workflow policies so each choice explicitly declares its recommendation mode and every static choice has one recommendation.

- [ ] **Step 4: Run the focused tests until green**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_human_input.py tests/kernel/test_workflow_validator.py tests/unit/test_human_input_static_contract.py`

Expected: PASS, including canonical workflow enumeration proving every static choice has exactly one recommendation.

- [ ] **Step 5: Commit the preparation boundary**

```bash
git add src/harness/human_input.py src/harness/workflow_validator.py runtime/workflow/definition.yaml tests/unit/test_human_input.py tests/kernel/test_workflow_validator.py tests/unit/test_human_input_static_contract.py
git commit -m "feat: require prepared decision recommendations"
```

### Task 2: Blocked-Decision Schema v3 and State Authority

**Files:**
- Modify: `src/harness/blocked_decision.py`
- Modify: `src/harness/recovery_instruction.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_blocked_decision.py`
- Test: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Consumes: Task 1 `PreparedHumanInput` and `RecommendationEvidence`.
- Produces: `SCHEMA_V3 = 3`, `validate_blocked_decision_v3(value)`, and `build_blocked_decision_v3(...)`.
- Produces: version-neutral `validate_blocked_decision(value)` and recovery-pair validation accepting v2 or v3.
- Produces: v3 seal/claim/fail/resolve compare-and-swap transitions while generic writes remain unable to mutate v2 or v3 authority.

- [ ] **Step 1: Write failing schema and state-transition tests**

```python
def test_v3_rejects_unresolved_resolution_audit():
    decision = make_v3(status="pending", resolution_rationale="already decided")
    with pytest.raises(BlockedDecisionError, match="unresolved"):
        validate_blocked_decision(decision)

def test_v3_automatic_override_requires_override_reason():
    decision = make_v3(
        status="resolved",
        selected_option_id="reject",
        resolved_by="COMMANDER",
        recommendation_followed=False,
        override_reason=None,
    )
    with pytest.raises(BlockedDecisionError, match="override_reason"):
        validate_blocked_decision(decision)

def test_recovery_pair_accepts_v2_and_v3_decisions():
    validate_human_input_recovery_pair(make_v2_decision(), make_recovery())
    validate_human_input_recovery_pair(make_v3_decision(), make_recovery())
```

- [ ] **Step 2: Run the focused tests and observe schema-v3 failures**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_blocked_decision.py tests/kernel/test_squad_state.py`

Expected: FAIL because schema `3` is unsupported and the recovery/state authority only recognizes schema `2`.

- [ ] **Step 3: Implement schema-v3 validation and builders**

```python
SCHEMA_V3 = 3

def validate_blocked_decision_v3(value: object) -> dict[str, object]:
    """Validate recommendation completeness plus resolver-specific audit invariants."""

def build_blocked_decision_v3(*, prepared: PreparedHumanInput, decision_id: str,
                              status: str, autonomy_mode: str,
                              attempts: int = 0, created_at: str | None = None,
                              **resolution_fields: object) -> dict[str, object]:
    """Build the canonical fresh decision postimage."""
```

Require v3 choices to bind `recommended_option_id` to the sole recommended option. Require automatic resolved decisions to have rationale, confidence, and Boolean follow state; require an override reason exactly when the answer differs. Permit human rationale/confidence to remain null. Require `recommendation_followed: null` for human-only `recommended_action`. Permit `awaiting_human` attempts `{0, 1}` for a migrated Banzai request. Update `ensure_blocked_decision`, recovery validation, state sealing, claim, failure, and resolution helpers to preserve both versioned authorities and to create v3 for fresh requests.

- [ ] **Step 4: Run schema and state tests until green**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_blocked_decision.py tests/kernel/test_squad_state.py`

Expected: PASS for v3 strictness, v2 readability, restart validation, and unauthorized generic-write rejection.

- [ ] **Step 5: Commit schema v3**

```bash
git add src/harness/blocked_decision.py src/harness/recovery_instruction.py src/harness/squad_state.py tests/unit/test_blocked_decision.py tests/kernel/test_squad_state.py
git commit -m "feat: persist decision recommendation audits"
```

### Task 3: Applied Resolution Audit, Routing, and Legacy Compatibility

**Files:**
- Modify: `src/harness/human_input.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_human_input_resolution_contract.py`
- Test: `tests/integration/test_human_input_routing.py`
- Test: `tests/unit/test_cli_continue.py`

**Interfaces:**
- Consumes: Task 2 v3 state transitions.
- Produces: `AppliedHumanInputResolution(selected_option_id, answer_text, resolved_by, rationale, confidence)`.
- Produces: COMMANDER conversion that copies the complete `DecisionResolution`; semi conversion that copies sealed recommendation rationale/confidence; user conversion with nullable audit.
- Produces: a dedicated revision-checked v2 Banzai migration/failure transaction; legacy v2 awaiting-human and semi paths remain v2.

- [ ] **Step 1: Write failing audit/routing/migration tests**

```python
def test_commander_resolution_persists_low_confidence_follow_audit():
    provider.returns(DecisionResolution("approve", None, "Debt is authorized.", "low"))
    controller.resume_pending_human_input()
    assert state.blocked_decision["resolution_confidence"] == "low"
    assert state.blocked_decision["recommendation_followed"] is True

def test_banzai_human_only_free_text_waits_and_accepts_user_answer():
    decision = seal_banzai_free_text(recommended_answer=None)
    assert decision["status"] == "awaiting_human"
    assert commander.call_count == 0
    resume("actual user answer")
    assert state.blocked_decision["recommendation_followed"] is None

def test_legacy_v2_awaiting_human_choice_remains_v2_on_restart():
    restart_with(v2_awaiting_human_choice_without_recommendation)
    resume("approve")
    assert state.blocked_decision["schema_version"] == 2
```

- [ ] **Step 2: Run the focused tests and observe lost-audit and routing failures**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_human_input_resolution_contract.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py`

Expected: FAIL because COMMANDER is narrowed to answer-only state, Banzai rejects all human input, and no v2 migration authority exists.

- [ ] **Step 3: Implement applied resolution and version-aware continuation**

```python
@dataclass(frozen=True)
class AppliedHumanInputResolution:
    selected_option_id: str | None
    answer_text: str | None
    resolved_by: Literal["user", "semi", "COMMANDER"]
    rationale: str | None
    confidence: Literal["high", "medium", "low"] | None
```

Change every closed resolution handler and the atomic apply transition to accept this type. Compute follow/override from the sealed recommendation, not provider output. Route v3 `automatic_eligible: false` Banzai free text to human input and reject human injection only when the v3 decision is automatic. Grandfather v2 `awaiting_human` through existing human application and v2 semi pending/resolving through deterministic selection. Migrate only pending Banzai v2 with a revision/ID/status compare-and-swap; resolving first follows existing recovery. When reconstruction fails, write one canonical failed v2 decision/recovery pair with `failure_code: decision_recommendation_unavailable`, preserve identity/policy/question/options/attempts/time, and dispatch no provider.

- [ ] **Step 4: Run routing and compatibility tests until green**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_human_input_resolution_contract.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py`

Expected: PASS for semi/COMMANDER/human audit semantics, low-confidence acceptance, no silent overrides, and v2 restart compatibility.

- [ ] **Step 5: Commit routing and compatibility**

```bash
git add src/harness/human_input.py src/harness/squad.py src/harness/squad_state.py tests/unit/test_human_input_resolution_contract.py tests/integration/test_human_input_routing.py tests/unit/test_cli_continue.py
git commit -m "fix: preserve automatic decision resolution audit"
```

### Task 4: Controller Recommendation Producers and Checkpoint Synthesis

**Files:**
- Modify: `src/harness/human_input.py`
- Modify: `src/harness/squad.py`
- Modify: `runtime/workflow/definition.yaml`
- Test: `tests/unit/test_checkpoint_policy.py`
- Test: `tests/unit/test_squad_checkpoint_context.py`
- Test: `tests/unit/test_squad_phase_checkpoints.py`
- Test: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Consumes: Task 1 preparation contract and Task 3 routing.
- Produces: checkpoint-assess preparer that returns an approve recommendation for current PASS+Lexicon or current accepted debt.
- Produces: dynamic proportional-quality and phase-dispatch-cap preparers with bounded evidence.
- Produces: COMMANDER prompt `Authoritative Recommendation` section rendered before raw context.

- [ ] **Step 1: Write failing producer and prompt tests**

```python
def test_checkpoint_assess_accepted_debt_recommends_approve():
    prepared = prepare_checkpoint_assess(current_accepted_debt_state)
    assert prepared.recommended_option_id == "approve"
    assert "accepted_with_debt" in prepared.recommendation_rationale
    assert any(e.kind == "quality_gate_failure" for e in prepared.recommendation_evidence)

def test_missing_checkpoint_authority_blocks_before_provider():
    result = run_checkpoint_assess(stale_quality_authority_state)
    assert result.blocked_reason == "decision_recommendation_unavailable"
    assert commander.call_count == 0

def test_phase_dispatch_cap_recommends_first_eligible_document_entry():
    prepared = prepare_phase_dispatch_cap(issues_document)
    assert prepared.recommended_option_id == "issue-2"
    assert "first eligible entry" in prepared.recommendation_rationale
```

- [ ] **Step 2: Run producer tests and observe missing synthesis failures**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_checkpoint_policy.py tests/unit/test_squad_checkpoint_context.py tests/unit/test_squad_phase_checkpoints.py tests/integration/test_human_input_routing.py`

Expected: FAIL because checkpoint-assess has no controller recommendation, dynamic evidence is not sealed, and the prompt lacks the authoritative section.

- [ ] **Step 3: Implement registered controller preparers**

Add a closed preparer dispatch keyed by policy triple. At checkpoint-assess, validate either current ordinary Phase 1 PASS plus current Lexicon pass, or a current accepted-debt authority, then select the existing `approve` option. For debt, name resolver and authorization digest while retaining the raw `FAIL` artifact as `quality_gate_failure` evidence. On missing/stale authority, persist `decision_recommendation_unavailable` and recovery without calling COMMANDER. Preserve checkpoint-plan's existing static approve recommendation. Select phase-dispatch-cap recommendations by first eligible `issues.md` document entry, never by invented priority. Render the sealed recommendation/evidence before raw provider context.

- [ ] **Step 4: Run producer tests until green**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_checkpoint_policy.py tests/unit/test_squad_checkpoint_context.py tests/unit/test_squad_phase_checkpoints.py tests/integration/test_human_input_routing.py`

Expected: PASS for PASS, accepted-debt, stale-authority, deterministic issue ordering, and prompt ordering cases.

- [ ] **Step 5: Commit controller recommendation synthesis**

```bash
git add src/harness/human_input.py src/harness/squad.py runtime/workflow/definition.yaml tests/unit/test_checkpoint_policy.py tests/unit/test_squad_checkpoint_context.py tests/unit/test_squad_phase_checkpoints.py tests/integration/test_human_input_routing.py
git commit -m "fix: synthesize authoritative checkpoint recommendations"
```

### Task 5: Canonical Quality-Debt Resolution and Durable Currentness

**Files:**
- Modify: `src/harness/phase1_quality_debt.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_phase1_quality_debt.py`
- Test: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Consumes: version-neutral blocked-decision validation and Task 3 `AppliedHumanInputResolution`.
- Produces: one canonical resolved decision postimage shared by current state, authorization, and `quality-debt.json` during debt acceptance.
- Produces: `_current_quality_debt_authorization` validation rooted in embedded decision/digest/completion and content-bound inputs, independent of the reusable current decision slot.

- [ ] **Step 1: Write failing canonicalization/currentness tests**

```python
def test_debt_acceptance_embeds_exact_state_postimage():
    accept_quality_debt()
    assert state.blocked_decision == state.phase1_quality_debt_authorization["resolved_decision"]
    assert artifact["resolved_decision"] == state.blocked_decision

def test_later_checkpoint_decision_does_not_stale_embedded_debt():
    accept_quality_debt()
    seal_and_resolve_checkpoint_assess()
    assert current_quality_debt_authorization(state) is not None

def test_tampered_embedded_decision_or_completion_is_stale():
    accept_quality_debt()
    state.phase1_quality_debt_authorization["resolved_decision"]["resolution_rationale"] += " tampered"
    assert current_quality_debt_authorization(state) is None
```

- [ ] **Step 2: Run debt tests and observe reusable-slot currentness failure**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py -k 'quality_debt or accepted_debt or checkpoint_assess'`

Expected: FAIL because replacing `state.blocked_decision` invalidates accepted debt and acceptance independently constructs decision snapshots.

- [ ] **Step 3: Implement canonical debt postimage and embedded currentness**

Construct the resolved v2/v3 postimage once inside the debt-acceptance compare-and-swap transaction. Pass that exact validated mapping to the state decision field, state authorization, and artifact payload; abort before artifact publication if equality or the revision/decision ID check fails. Store and verify its SHA-256 digest plus the existing durable completion receipt. In `_current_quality_debt_authorization`, validate the embedded decision using `validate_blocked_decision`, compare authorization/artifact snapshots and digests, verify completion and all existing candidate/Understanding/repair/spec bindings, and remove only the requirement that current `state.blocked_decision` equal the embedded snapshot.

- [ ] **Step 4: Run debt and downstream guard tests until green**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py -k 'quality_debt or accepted_debt or checkpoint_assess'`

Expected: PASS, including checkpoint replacement, tamper failures, legacy-v2 authorization, v3 authorization, and downstream Phase 2 guard cases.

- [ ] **Step 5: Commit durable debt authority**

```bash
git add src/harness/phase1_quality_debt.py src/harness/squad.py src/harness/squad_state.py tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py
git commit -m "fix: retain accepted debt across later decisions"
```

### Task 6: Executable Rewind and Source-Phase Replay Recovery

**Files:**
- Modify: `src/harness/squad_state.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_rewind.py`
- Test: `tests/unit/test_cli_continue.py`
- Test: `tests/unit/test_cli_status.py`
- Test: `tests/unit/test_cli_checkpoint.py`

**Interfaces:**
- Consumes: validated v2/v3 decision/recovery pairs and checkpoint ledger.
- Produces: confirmed failed-human-gate rewind transition that checks revision/ID/status/source/mode/eligibility/predecessor and atomically retires its authority while resetting phase progress.
- Produces: provider-escalation/controller-safeguard manual phase replay transition with exact source-phase checks and reconstructed v2 eligibility.
- Produces: ledger-derived terminal rejection command and source-specific failed-decision command.

- [ ] **Step 1: Write failing executable-recovery tests**

```python
def test_resolved_gate_rejection_rewind_preserves_terminal_authority():
    result = invoke("spec", "rewind", "phase1-lexicon", "--confirm")
    assert result.exit_code == 0
    validate_state(load_state())
    assert load_state()["blocked_decision"]["status"] == "resolved"

def test_failed_human_gate_displayed_rewind_retires_failure_and_reseals():
    command = status_next_command(failed_banzai_human_gate)
    assert command == "echelon spec rewind phase1-lexicon --confirm"
    execute_cli(command)
    execute_cli("echelon spec continue")
    assert load_state()["blocked_decision"]["status"] in {"pending", "resolving", "resolved"}

def test_failed_provider_displayed_phase_replay_is_executable():
    command = status_next_command(failed_provider_decision)
    assert command == "echelon phase run phase1-tracker"
    execute_cli(command)
    assert load_state()["blocked_decision"]["id"] != failed_provider_decision["id"]
```

- [ ] **Step 2: Run recovery tests and observe inoperative-command failures**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_cli_rewind.py tests/unit/test_cli_continue.py tests/unit/test_cli_status.py tests/unit/test_cli_checkpoint.py`

Expected: FAIL because rewind manufactures invalid display state, failed human gates block bootstrap, and manual replay recognizes only a narrower safeguard case.

- [ ] **Step 3: Implement authority-valid recovery transitions and rendering**

Keep resolved `gate_rejected` decision/display authority unchanged during generic rewind; do not write `escalation_resolved: false`. For failed Banzai human gates, add a dedicated state-store compare-and-swap used by confirmed rewind that validates the exact predecessor from the active checkpoint ledger and retires decision/recovery/display in the same save as the rewind reset. Extend explicit manual phase replay to failed Banzai `provider_escalation` and `controller_safeguard` only when source phase matches; trust v3 eligibility after schema validation and reconstruct registered policy for v2. Give migration failure-code classification priority over generic legacy recovery. Render the exact rewind or `echelon phase run <source-phase>` command and never terminal `continue` or prose-only diagnosis.

- [ ] **Step 4: Run recovery and CLI tests until green**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_cli_rewind.py tests/unit/test_cli_continue.py tests/unit/test_cli_status.py tests/unit/test_cli_checkpoint.py`

Expected: PASS for command rendering and execution, next-gate resealing, mismatched authority rejection, and restart-stable migration failure.

- [ ] **Step 5: Commit executable recovery**

```bash
git add src/harness/squad_state.py src/echelon/cli.py tests/unit/test_cli_rewind.py tests/unit/test_cli_continue.py tests/unit/test_cli_status.py tests/unit/test_cli_checkpoint.py
git commit -m "fix: make decision recovery commands executable"
```

### Task 7: Compatibility Handshake, Status Audit, and Exact Regression

**Files:**
- Modify: `src/harness/workflow_validator.py`
- Modify: `runtime/workflow/definition.yaml`
- Modify: `src/echelon/cli.py`
- Test: `tests/kernel/test_workflow_validator.py`
- Test: `tests/unit/test_cli_workspace.py`
- Test: `tests/unit/test_cli_status.py`
- Test: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Consumes: all preceding versioned state, synthesis, debt, and recovery interfaces.
- Produces: compatibility version `2` guard before run side effects.
- Produces: status/summary rendering for recommendation target, rationale, confidence, follow/override, override reason, and exact command.
- Produces: accepted-debt → reject → rewind → fresh approve → `phase2-decide` end-to-end regression.

- [ ] **Step 1: Write failing compatibility, presentation, and Hello World sequence tests**

```python
def test_runtime_compatibility_v1_fails_before_initialization():
    workflow["controller_runtime_compatibility_version"] = 1
    result = run_spec(workflow)
    assert result.blocked_reason == "controller_runtime_compatibility_mismatch"
    assert not target_repo.exists()

def test_status_renders_complete_resolution_audit_and_recovery():
    output = render_status(resolved_override_decision)
    assert "Recommended: approve" in output
    assert "Confidence: low" in output
    assert "Overrode recommendation" in output
    assert "echelon spec rewind phase1-lexicon --confirm" in output

def test_accepted_debt_reject_rewind_approve_reaches_phase2_decide():
    accept_debt_then_reject_checkpoint()
    rewind("phase1-lexicon")
    continue_with_commander_selection("approve")
    assert load_state()["phase"] == "phase2-decide"
```

- [ ] **Step 2: Run compatibility/presentation/regression tests and observe failures**

Run: `uv run --frozen --extra dev pytest -q tests/kernel/test_workflow_validator.py tests/unit/test_cli_workspace.py tests/unit/test_cli_status.py tests/integration/test_human_input_routing.py`

Expected: FAIL while version `1` is still accepted, audit rendering is absent, or the exact accepted-debt sequence does not reach Phase 2.

- [ ] **Step 3: Complete compatibility and operator presentation**

Set `CONTROLLER_RUNTIME_COMPATIBILITY_VERSION = 2` and `controller_runtime_compatibility_version: 2`. Ensure the compatibility check remains before initialization/provider work. Render option/answer/action, recommendation rationale/confidence, resolver rationale/confidence, followed/overrode state, override reason, and the one executable recovery command from validated decision authority. Build the end-to-end fixture from the reproduced proportional run state and assert debt currentness at acceptance, after rejection, after rewind, after fresh approval, and at the Phase 2 guard.

- [ ] **Step 4: Run the focused acceptance suite until green**

Run: `uv run --frozen --extra dev pytest -q tests/kernel/test_workflow_validator.py tests/unit/test_cli_workspace.py tests/unit/test_cli_status.py tests/integration/test_human_input_routing.py`

Expected: PASS with no provider call for unavailable recommendations and the exact Hello World regression reaching `phase2-decide`.

- [ ] **Step 5: Run the full targeted regression suite**

Run: `uv run --frozen --extra dev pytest -q tests/unit/test_human_input.py tests/unit/test_blocked_decision.py tests/kernel/test_squad_state.py tests/integration/test_human_input_routing.py tests/unit/test_phase1_quality_debt.py tests/unit/test_cli_status.py tests/unit/test_cli_rewind.py tests/unit/test_cli_continue.py tests/kernel/test_workflow_validator.py tests/unit/test_cli_workspace.py tests/unit/test_human_input_resolution_contract.py tests/unit/test_human_input_static_contract.py tests/unit/test_checkpoint_policy.py tests/unit/test_squad_checkpoint_context.py tests/unit/test_squad_phase_checkpoints.py tests/unit/test_cli_checkpoint.py`

Expected: PASS.

- [ ] **Step 6: Commit compatibility and regression coverage**

```bash
git add src/harness/workflow_validator.py runtime/workflow/definition.yaml src/echelon/cli.py tests/kernel/test_workflow_validator.py tests/unit/test_cli_workspace.py tests/unit/test_cli_status.py tests/integration/test_human_input_routing.py
git commit -m "test: cover banzai recommendation regression"
```

### Task 8: Final Review and Verification

**Files:**
- Inspect: all files changed by Tasks 1-7
- Test: complete repository test suite

**Interfaces:**
- Consumes: completed implementation and commits from Tasks 1-7.
- Produces: evidence that the implementation matches the approved spec without scope expansion.

- [ ] **Step 1: Inspect the diff for state-authority and scope regressions**

Run: `git diff --check && git diff --stat $(git merge-base HEAD master)..HEAD && git status --short`

Expected: no whitespace errors, only planned production/tests/docs changes, and no generated run artifacts.

- [ ] **Step 2: Run the complete test suite**

Run: `uv run --frozen --extra dev pytest -q`

Expected: PASS.

- [ ] **Step 3: Re-run the exact regression tests without cached outcomes**

Run: `uv run --frozen --extra dev pytest -q -p no:cacheprovider tests/integration/test_human_input_routing.py tests/unit/test_phase1_quality_debt.py tests/unit/test_cli_rewind.py tests/unit/test_cli_status.py`

Expected: PASS, with fresh output confirming the accepted-debt checkpoint and executable recovery cases.

- [ ] **Step 4: Review every acceptance invariant against the final code**

Check: unique recommendation target, controller-computed evidence digest, no confidence threshold, complete automatic audit, human-only null follow state, v2 grandfathering, v2 Banzai-only migration, canonical debt postimage, decision-slot-independent debt currentness, executable recovery commands, compatibility `2`, and no stack-dissemination changes.

- [ ] **Step 5: Commit plan completion metadata if test-driven edits changed it**

```bash
git add docs/superpowers/plans/2026-08-23-banzai-decision-recommendations.md
git commit -m "docs: record banzai recommendation implementation plan"
```
