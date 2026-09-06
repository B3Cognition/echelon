# Banzai Default Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve one eligible missing-recommendation Banzai product decision through COMMANDER and route its repair through the normal Phase A validation loop.

**Architecture:** SAGE emits an untrusted but typed default-candidate envelope with its WHY2 human question. The harness validates the envelope against a workflow-owned capability, seals it as a pending decision, then uses the existing COMMANDER decision dispatch and clarification resolution path. A state-owned ledger prevents repeat resolution and retains the future `super-banzai` capability boundary.

**Tech Stack:** Python 3, Pytest, YAML workflow definitions, Prosaic agent instructions.

**Spec:** `docs/superpowers/specs/2026-09-06-banzai-default-resolution-design.md`

## Global Constraints

- `banzai_default` is the only recognized autonomous-default authority in this change.
- Provider output can propose a candidate but cannot claim automatic eligibility or elevated authority.
- The current direct evidence-backed Banzai recommendation behavior must remain unchanged.
- All malformed or unrecognized candidate data must fail closed to awaiting-human.

---

### Task 1: Define and validate the typed WHY2 candidate

**Files:**
- Modify: `runtime/workflow/definition.yaml`, `runtime/workflow/phases/phase1-why2.md`, `prosaic/subagents/echelon.sage.md`
- Modify: `src/harness/human_input.py`
- Test: `tests/unit/test_human_input.py`

**Interfaces:**
- Consumes: `state_updates.autonomous_default_candidate` from `phase1-why2`.
- Produces: a validated `AutonomousDefaultCandidate` with `fingerprint`, `authority_capability`, and registered context references.

- [ ] **Step 1: Write the failing unit tests**

```python
def test_banzai_default_candidate_requires_one_bounded_material_envelope() -> None:
    with pytest.raises(HumanInputPolicyError, match="authority_capability"):
        validate_autonomous_default_candidate({"authority_capability": "super_banzai"})


def test_banzai_default_candidate_fingerprint_is_stable() -> None:
    candidate = validate_autonomous_default_candidate(_candidate_payload())
    assert candidate.fingerprint == validate_autonomous_default_candidate(_candidate_payload()).fingerprint
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run --extra dev pytest tests/unit/test_human_input.py -k autonomous_default -q`

Expected: FAIL because the candidate validator does not exist.

- [ ] **Step 3: Implement the closed candidate validator**

```python
@dataclass(frozen=True)
class AutonomousDefaultCandidate:
    issue_id: str
    question: str
    authority_capability: Literal["banzai_default"]
    affected_requirements: tuple[str, ...]
    alternatives: tuple[str, ...]
    constraints: tuple[str, ...]
    source_references: tuple[str, ...]
    fingerprint: str
```

Accept only `banzai_default`, a non-empty question, two or more alternatives,
one or more requirements/constraints/references, and bounded text. Compute the
fingerprint from canonical candidate content.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `uv run --extra dev pytest tests/unit/test_human_input.py -k autonomous_default -q`

Expected: PASS.

### Task 2: Seal and resolve an eligible Banzai candidate once

**Files:**
- Modify: `src/harness/squad.py`, `src/harness/squad_state.py`
- Test: `tests/integration/test_human_input_routing.py`, `tests/kernel/test_squad_state.py`

**Interfaces:**
- Consumes: validated candidate and awaiting Banzai human-input decision.
- Produces: a pending decision, `autonomous_default_ledger` entry, and exactly one COMMANDER resolution.

- [ ] **Step 1: Write the failing integration and state tests**

```python
def test_banzai_resolves_one_eligible_missing_recommendation_candidate(tmp_path: Path) -> None:
    controller, store, provider = _controller_with_why2_candidate(tmp_path)
    assert controller.resume_pending_human_input() is True
    assert store.load()["phase"] == "phase1-what"
    assert provider.exec_agent.call_count == 1


def test_default_candidate_fingerprint_cannot_be_resolved_twice(tmp_path: Path) -> None:
    store = _store_with_resolved_default(tmp_path)
    with pytest.raises(StateAdvanceError, match="already resolved"):
        store.rearm_awaiting_banzai_default_decision(...)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run --extra dev pytest tests/integration/test_human_input_routing.py -k missing_recommendation_candidate -q && uv run --extra dev pytest tests/kernel/test_squad_state.py -k autonomous_default -q`

Expected: FAIL because no eligible missing-recommendation path exists.

- [ ] **Step 3: Implement controller-owned eligibility and atomic rearm**

The controller must verify Banzai mode, exact WHY2 policy identity,
`banzai_default` candidate capability, material classification, no
recommendation, no high/critical risk, matching question, and no ledger match.
The state store performs the compare-and-swap rearm and appends a ledger entry
only after these controller checks. It may not modify provider-owned candidate
content.

- [ ] **Step 4: Extend the COMMANDER prompt and resolution effects**

Include the candidate alternatives and constraints in the registered prompt.
On success record the sealed answer and candidate fingerprint, then route the
existing clarification handler to `phase1-what` for candidate-based decisions.

- [ ] **Step 5: Run the focused tests and verify they pass**

Run: `uv run --extra dev pytest tests/integration/test_human_input_routing.py -k missing_recommendation_candidate -q && uv run --extra dev pytest tests/kernel/test_squad_state.py -k autonomous_default -q`

Expected: PASS.

### Task 3: Make SAGE propose candidates without giving it authority

**Files:**
- Modify: `runtime/workflow/definition.yaml`, `runtime/workflow/phases/phase1-why2.md`, `prosaic/subagents/echelon.sage.md`
- Test: `tests/kernel/test_phase_graph.py`, `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Consumes: a WHY2 ambiguity.
- Produces: `state_updates.autonomous_default_candidate` only for a bounded product calibration; otherwise retains the current human decision route.

- [ ] **Step 1: Write failing workflow-contract tests**

```python
def test_why2_declares_controller_owned_banzai_default_capability() -> None:
    why2 = PhaseGraph(DEFINITION, prosaic_subagents_dir=PROSAIC_SUBAGENTS).get("phase1-why2")
    assert "autonomous_default_candidate" in why2.allowed_state_updates
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `uv run --extra dev pytest tests/kernel/test_phase_graph.py -k banzai_default -q`

Expected: FAIL because the WHY2 contract does not expose the candidate field.

- [ ] **Step 3: Add the closed workflow and agent contract**

Document the exact candidate schema and state explicitly that SAGE may propose
only `banzai_default`; it cannot classify itself eligible, choose an answer, or
name an elevated capability. Keep the existing `human_decision` instructions
for all non-eligible cases.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `uv run --extra dev pytest tests/kernel/test_phase_graph.py -k banzai_default -q`

Expected: PASS.

### Task 4: Regression verification and documentation review

**Files:**
- Modify: `docs/superpowers/specs/2026-09-06-banzai-default-resolution-design.md`
- Test: `tests/unit/test_human_input.py`, `tests/integration/test_human_input_routing.py`, `tests/kernel/test_squad_state.py`, `tests/kernel/test_phase_graph.py`, `tests/kernel/test_workflow_validator.py`

- [ ] **Step 1: Add fail-closed regression cases**

Cover non-Banzai, external prerequisite, high/critical risk, malformed
candidate, candidate question mismatch, duplicate fingerprint, COMMANDER
failure, and existing evidence-backed recommendation behavior.

- [ ] **Step 2: Run focused regression suites**

Run: `uv run --extra dev pytest tests/unit/test_human_input.py tests/integration/test_human_input_routing.py tests/kernel/test_squad_state.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q`

Expected: PASS.

- [ ] **Step 3: Run static integrity checks**

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 4: Review the design against implementation**

Confirm that the implementation recognizes only `banzai_default`, preserves
the capability field in the ledger, and does not add an implicit
`super-banzai` bypass.
