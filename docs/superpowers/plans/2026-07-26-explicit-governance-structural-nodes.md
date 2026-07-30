# Explicit Governance Structural Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hidden post-provider governance validation with two visible,
provider-free structural nodes while preserving verdict routing, repair
semantics, evidence, and durable controller authority.

**Architecture:** First characterize and extract the current structural
validator behind its existing call site. Then add closed controller contracts,
the `deterministic_structural` executor, and exact verdict projection before
switching both graph paths atomically and deleting the hidden hook. Every
outcome uses immutable prepared results, normal transition evaluation, durable
completion, and ordinary checkpointing.

**Tech Stack:** Python 3.12, dataclasses, pathlib, JSON Schema Draft 2020-12,
PyYAML workflow definitions, pytest, Git-backed Phase A checkpoints.

## Global Constraints

- Keep one authoritative structural-validation path; no shadow mode or
  compatibility switch.
- Move feasibility and intent-alignment gates together.
- Do not change `lexicon.structural.structural_validate`, governance
  configuration keys/defaults, templates, report schema version 1, or existing
  structural state-field names.
- GATEKEEPER and TRACKER remain the only authored-artifact repair owners.
- `STOP_AND_ASK` blocks at `phase2-tracker-alignment`; it is never projected or
  routed through the structural node.
- Structural `block` returns executor verdict `FAIL`, uses
  `structural_action: block`, and follows the explicit graph edge to
  `terminal-blocked`. Never use executor verdict `BLOCKED` for this outcome.
- Provider phases cannot emit projected verdict or structural certification
  fields.
- New nodes contain no `agent`, have `allowed_state_updates: []`, and use
  `type: deterministic_structural`.
- Unknown/malformed deterministic structural nodes fail workflow startup;
  COMMANDER is never a fallback.
- Preserve `write_kill_report` and `increment_defer_count` at their current
  characterized behavior; adding durable implementations is out of scope.
- Use `.venv/bin/pytest`; the system interpreter may not contain repository
  dependencies.
- Preserve unrelated working-tree changes and commit only task-owned files.

---

## File Structure

### New files

- `src/harness/governance_structural_gate.py` — focused structural validation,
  report persistence, repair/exhaustion calculation, and immutable outcome.
- `tests/unit/test_governance_structural_gate.py` — service-level outcome,
  report-compatibility, and failure tests.

### Modified files

- `src/harness/phase_graph.py` — parse `structural_artifact`.
- `src/harness/controller_state_contract_requirements.py` — exact phase/type to
  contract mapping.
- `src/harness/workflow_validator.py` — provider-free structural-node
  invariants.
- `src/harness/squad_executors.py` — `DeterministicStructuralExecutor`.
- `src/harness/squad.py` — executor registration, verdict projection,
  state-removal/control enrichment, and hidden-hook removal.
- `extension/workflow/controller-state-contracts.yaml` — two authoring
  contracts and closed structural outcome schemas.
- `extension/workflow/definition.yaml` — two explicit nodes and rewired edges.
- `extension/workflow/phases/phase2-decide.md` — visible feasibility gate.
- `extension/workflow/phases/phase2-tracker-alignment.md` — visible alignment
  gate and STOP_AND_ASK boundary.
- `extension/agents/feasibility/gatekeeper.md` — controller-ownership wording.
- `extension/agents/control/tracker.md` — controller-ownership wording.
- `tests/kernel/test_phase_graph.py` — graph and contract loading.
- `tests/kernel/test_workflow_validator.py` — malformed-node rejection.
- `tests/kernel/test_squad_executors_journal.py` — provider-free executor.
- `tests/integration/test_squad_controller.py` — projection, routing, repair,
  block, replay, and STOP_AND_ASK behavior.
- `tests/unit/test_structural_wiring.py` — source/wiring/repair-context
  regression coverage.
- `tests/unit/test_squad_phase_checkpoints.py` — structural-node checkpoints.
- `tests/unit/test_cli_phase.py` — manual structural-node execution.
- `CHANGELOG.md` — operator-visible graph change.

---

### Task 1: Characterize and Extract the Existing Structural Service

**Files:**

- Create: `src/harness/governance_structural_gate.py`
- Create: `tests/unit/test_governance_structural_gate.py`
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**

- Consumes: resolved governance configuration, artifact key, extension root,
  run-local spec directory, prior attempts, and workflow iteration limits.
- Produces:

  ```python
  StructuralAction = Literal[
      "proceed", "repair", "proceed_with_warning", "block"
  ]

  @dataclass(frozen=True)
  class GovernanceStructuralGateResult:
      artifact_key: str
      action: StructuralAction
      passed: bool
      attempts: int
      findings: int
      report_path: Path | None
      exhausted_artifact: str | None
      blocked_reason: str | None
      detail: str

      def state_updates(self) -> dict[str, object]:
          prefix = {
              "feasibility": "feasibility_structural",
              "intent-alignment-check":
                  "intent_alignment_check_structural",
          }[self.artifact_key]
          updates: dict[str, object] = {
              "structural_action": self.action,
              f"{prefix}_pass": self.passed,
              f"{prefix}_attempts": self.attempts,
              f"{prefix}_findings": self.findings,
          }
          if self.report_path is not None:
              updates[f"{prefix}_report"] = str(self.report_path)
          if self.exhausted_artifact is not None:
              updates["governance_gate_exhausted"] = (
                  self.exhausted_artifact
              )
          return updates

  def run_governance_structural_gate(
      *,
      artifact_key: str,
      spec_dir: Path | None,
      extension_root: Path,
      governance_config: Mapping[str, object],
      previous_attempts: object,
      iteration: object,
      max_iterations: object,
  ) -> GovernanceStructuralGateResult:
      raise NotImplementedError
  ```

- Task 4 relies on the exact signature and dataclass fields above.

- [ ] **Step 1: Add characterization tests around the current hidden hook**

In `tests/integration/test_squad_controller.py`, retain the current controller
entry point and assert exact report names, version-1 payload, attempts, findings,
and exhaustion behavior:

```python
@pytest.mark.parametrize(
    ("phase", "artifact", "report_name"),
    [
        ("phase2-decide", "feasibility", "feasibility-structural-report.json"),
        (
            "phase2-tracker-alignment",
            "intent-alignment-check",
            "intent-alignment-check-structural-report.json",
        ),
    ],
)
def test_hidden_structural_gate_report_contract(
    controller, store, phase, artifact, report_name
):
    node = controller._graph.get(phase)
    prepared = controller._prepare_phase_result(
        node, _valid_authoring_result(phase), store.capture_routing_snapshot(
            expected_phase=phase
        )
    )
    report = Path(
        prepared.state_updates[
            "feasibility_structural_report"
            if artifact == "feasibility"
            else "intent_alignment_check_structural_report"
        ]
    )
    assert report.name == report_name
    assert json.loads(report.read_text())["schema_version"] == 1
```

Add adjacent cases for valid artifacts, missing artifacts, missing cross
references, validator exceptions, disabled/non-structural bypass, governance
repair exhaustion, workflow-iteration exhaustion, `warn`, `block`, and report
write failure. Assert the current `write_kill_report` and
`increment_defer_count` action names are graph metadata only.

- [ ] **Step 2: Run the characterization slice**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py -k 'structural or governance'
```

Expected: PASS before extraction.

- [ ] **Step 3: Write failing focused service tests**

Create `tests/unit/test_governance_structural_gate.py` with fixtures for both
artifacts and exact assertions:

```python
def test_invalid_feasibility_requests_repair(tmp_path: Path) -> None:
    spec_dir = _write_governance_artifacts(tmp_path, feasibility="invalid")
    result = run_governance_structural_gate(
        artifact_key="feasibility",
        spec_dir=spec_dir,
        extension_root=EXTENSION_ROOT,
        governance_config=_governance(),
        previous_attempts=1,
        iteration=0,
        max_iterations=5,
    )
    assert result.action == "repair"
    assert result.passed is False
    assert result.attempts == 2
    assert result.findings >= 1
    assert result.report_path.name == "feasibility-structural-report.json"


def test_evidence_failure_blocks_without_spending_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_dir = _write_governance_artifacts(tmp_path)
    monkeypatch.setattr(
        "harness.governance_structural_gate._write_json_atomic",
        Mock(side_effect=OSError("disk full")),
    )
    result = run_governance_structural_gate(
        artifact_key="feasibility",
        spec_dir=spec_dir,
        extension_root=EXTENSION_ROOT,
        governance_config=_governance(),
        previous_attempts=2,
        iteration=0,
        max_iterations=5,
    )
    assert result.action == "block"
    assert result.attempts == 2
    assert result.report_path is None
    assert (
        result.blocked_reason
        == "governance_structural_evidence_write_failed"
    )
```

Add exact cases for all rows in the design's outcome table, including passing
reports versus bypass-without-report and normalized invalid prior attempts.

- [ ] **Step 4: Run focused tests and verify import failure**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_governance_structural_gate.py
```

Expected: collection fails because
`harness.governance_structural_gate` does not exist.

- [ ] **Step 5: Extract the service and delegate the hidden hook to it**

Move configuration validation, path/template/cross-reference resolution,
`structural_validate`, version-1 report creation, atomic persistence, attempts,
and exhaustion into `governance_structural_gate.py`. Keep the existing hidden
hook temporarily as a thin adapter:

```python
gate = run_governance_structural_gate(
    artifact_key=artifact_key,
    spec_dir=spec_dir,
    extension_root=self._ext_dir,
    governance_config=self._governance_config(),
    previous_attempts=state.get(attempts_key, 0),
    iteration=state.get("iteration", 0),
    max_iterations=state.get("max_iterations", self._max_iterations),
)
return gate.state_updates()
```

Use the repository atomic JSON pattern (`mkstemp`, `fsync`, `os.replace`) and
never mutate squad state from the service.

- [ ] **Step 6: Run focused and characterization tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_governance_structural_gate.py \
  tests/integration/test_squad_controller.py -k 'structural or governance'
```

Expected: PASS with report payloads and hidden-hook behavior unchanged.

- [ ] **Step 7: Commit**

```bash
git add \
  src/harness/governance_structural_gate.py \
  src/harness/squad.py \
  tests/unit/test_governance_structural_gate.py \
  tests/integration/test_squad_controller.py
git commit -m "refactor: extract governance structural gate"
```

---

### Task 2: Add Closed Contracts and Structural Graph Validation

**Files:**

- Modify: `extension/workflow/controller-state-contracts.yaml`
- Modify: `src/harness/controller_state_contract_requirements.py`
- Modify: `src/harness/phase_graph.py`
- Modify: `src/harness/workflow_validator.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`

**Interfaces:**

- Produces `PhaseNode.structural_artifact: str | None`.
- Produces contract mapping:

  ```python
  _STRUCTURAL_CONTRACTS = MappingProxyType({
      "feasibility": "feasibility_structural",
      "intent-alignment-check": "intent_alignment_structural",
  })
  ```

- Task 4 relies on the two new authoring contract names and the
  `deterministic_structural` producing type.

- [ ] **Step 1: Write failing phase-graph tests**

Add tests that load minimal phases and assert:

```python
assert required_controller_contract_name({
    "id": "phase2-feasibility-structural",
    "type": "deterministic_structural",
    "structural_artifact": "feasibility",
}) == "feasibility_structural"
```

Parametrize rejection of missing/unknown `structural_artifact`, non-empty
`allowed_state_updates`, `agent`, non-empty `agents`, wrong contract, missing
repair/block/forward edges, and provider/controller field overlap.

- [ ] **Step 2: Run graph tests and verify failure**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py -k structural
```

Expected: FAIL because `deterministic_structural` and `structural_artifact` are
not recognized.

- [ ] **Step 3: Add the exact contract-role mapping**

Update `REQUIRED_CONTROLLER_CONTRACTS`:

```python
"phase2-decide": "feasibility_authoring_verdict",
"phase2-feasibility-structural": "feasibility_structural",
"phase2-tracker-alignment": "intent_alignment_authoring_verdict",
"phase2-intent-alignment-structural": "intent_alignment_structural",
```

Add `deterministic_structural` to `CONTROLLER_PRODUCING_TYPES` and derive its
contract exclusively from `_STRUCTURAL_CONTRACTS[structural_artifact]`.

- [ ] **Step 4: Parse and validate the new node field**

Add to `PhaseNode`:

```python
structural_artifact: Optional[str] = None
```

Populate it from YAML in the existing constructor and make both validators
reject a structural node unless:

```python
node.type == "deterministic_structural"
node.structural_artifact in {
    "feasibility", "intent-alignment-check"
}
node.agent is None
node.agents == []
node.allowed_state_updates == []
```

Require exact `repair`, `block`, and certified-forward conditions.

- [ ] **Step 5: Define closed authoring and structural schemas**

In `controller-state-contracts.yaml`, add:

```yaml
feasibility_authoring_verdict:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  additionalProperties: false
  required: [verdict, state_updates]
  properties:
    verdict: {type: string, enum: [PASS, KILL, DEFER]}
    state_updates:
      type: object
      additionalProperties: false
      required: [feasibility_verdict]
      properties:
        feasibility_verdict:
          {type: string, enum: [PASS, KILL, DEFER]}

intent_alignment_authoring_verdict:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  additionalProperties: false
  required: [verdict, state_updates]
  properties:
    verdict:
      {type: string, enum: [ALIGNED, DRIFT, DRIFTING, ESCALATE, STOP_AND_ASK]}
    state_updates:
      type: object
      additionalProperties: false
      properties:
        intent_alignment_verdict:
          {type: string, enum: [ALIGNED, DRIFT, DRIFTING, ESCALATE]}
  allOf:
    - if: {properties: {verdict: {const: STOP_AND_ASK}}}
      then:
        properties:
          state_updates:
            not: {required: [intent_alignment_verdict]}
      else:
        properties:
          state_updates:
            required: [intent_alignment_verdict]
```

Extend both structural contracts with `structural_action` and closed `if/then`
branches binding `PASS/proceed`, `REPAIR/repair`, `WARN/proceed_with_warning`,
and `FAIL/block` to the exact state shapes in the design. The `FAIL/block`
schema permits the report to be absent because controller-context and evidence
failures legitimately have no persisted report. Add a preparation-time
cross-field check that permits positive findings without a report only when the
separate sealed control reason is
`governance_structural_evidence_write_failed`; all other positive-finding
outcomes require a report.

- [ ] **Step 6: Run contract and graph tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_controller_state_contracts.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  extension/workflow/controller-state-contracts.yaml \
  src/harness/controller_state_contract_requirements.py \
  src/harness/phase_graph.py \
  src/harness/workflow_validator.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py
git commit -m "feat: define structural node contracts"
```

---

### Task 3: Implement Verdict Projection and State Replacement

**Files:**

- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Test: `tests/kernel/test_prepared_phase_result.py`

**Interfaces:**

- Produces:

  ```python
  def project_authoring_verdict(
      *, phase_id: str, provider_verdict: str
  ) -> Mapping[str, str]:
      raise NotImplementedError
  ```

- Projection happens in controller enrichment before
  `prepare_phase_result()`.
- `STOP_AND_ASK` produces no projection, removes
  `intent_alignment_verdict`, and follows existing blocking-control handling.

- [ ] **Step 1: Write failing projection tests**

Add table-driven cases:

```python
@pytest.mark.parametrize(
    ("phase", "verdict", "expected"),
    [
        ("phase2-decide", "PASS", {"feasibility_verdict": "PASS"}),
        ("phase2-decide", "KILL", {"feasibility_verdict": "KILL"}),
        ("phase2-decide", "DEFER", {"feasibility_verdict": "DEFER"}),
        (
            "phase2-tracker-alignment",
            "DRIFTING",
            {"intent_alignment_verdict": "DRIFTING"},
        ),
        (
            "phase2-tracker-alignment",
            "ESCALATE",
            {"intent_alignment_verdict": "ESCALATE"},
        ),
    ],
)
def test_project_authoring_verdict(phase, verdict, expected):
    assert project_authoring_verdict(
        phase_id=phase, provider_verdict=verdict
    ) == expected
```

Assert lowercase, whitespace, missing values, and wrong phase/value pairs raise
`ControllerStateContractViolation` at `$.verdict` with validator
`projection`.

- [ ] **Step 2: Write failing STOP_AND_ASK and stale-state tests**

Create a TRACKER result satisfying the existing Echelon schema:

```python
result = _result(
    verdict="STOP_AND_ASK",
    state_updates={
        "status": "blocked",
        "blocked_reason": "human_decision_required",
        "escalation_question": "Which scope is intended?",
    },
)
```

Assert preparation contains no projected verdict, removes the stale
`intent_alignment_verdict`, remains at `phase2-tracker-alignment`, and never
executes the structural node. Add authoring-success cases that remove old
pass/findings/report/exhaustion but preserve attempts.

- [ ] **Step 3: Run projection tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_squad_controller.py \
  -k 'authoring_verdict or stop_and_ask or structural_state_removal'
```

Expected: FAIL because projection and removals are absent.

- [ ] **Step 4: Implement exact projection**

Implement without normalization:

```python
def project_authoring_verdict(
    *, phase_id: str, provider_verdict: str
) -> Mapping[str, str]:
    mapping = {
        "phase2-decide": {
            "PASS": "feasibility_verdict",
            "KILL": "feasibility_verdict",
            "DEFER": "feasibility_verdict",
        },
        "phase2-tracker-alignment": {
            "ALIGNED": "intent_alignment_verdict",
            "DRIFT": "intent_alignment_verdict",
            "DRIFTING": "intent_alignment_verdict",
            "ESCALATE": "intent_alignment_verdict",
        },
    }
    key = mapping.get(phase_id, {}).get(provider_verdict)
    if key is None:
        raise ControllerStateContractViolation(
            "provider verdict cannot be projected for authoring phase",
            contract=required_controller_contract_name({
                "id": phase_id, "type": "agent"
            }) or "authoring_verdict",
            json_path="$.verdict",
            validator="projection",
        )
    return MappingProxyType({key: provider_verdict})
```

Handle TRACKER `STOP_AND_ASK` before calling this function. Add exact
artifact-specific certification removals and use the trusted removal channel
for `blocked_reason`.

- [ ] **Step 5: Prove projection and removal attestation**

Add a prepared-result test that mutation of projected updates or removals after
preparation fails attestation and that replay uses the same contract digest.

- [ ] **Step 6: Run tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_prepared_phase_result.py \
  -k 'authoring_verdict or stop_and_ask or structural_state_removal or attestation'
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  src/harness/squad.py \
  tests/integration/test_squad_controller.py \
  tests/kernel/test_prepared_phase_result.py
git commit -m "feat: persist governance authoring verdicts"
```

---

### Task 4: Add the Provider-Free Structural Executor

**Files:**

- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**

- Produces `DeterministicStructuralExecutor.execute(node, state_store)`.
- Maps actions exactly:

  ```python
  {
      "proceed": "PASS",
      "repair": "REPAIR",
      "proceed_with_warning": "WARN",
      "block": "FAIL",
  }
  ```

- [ ] **Step 1: Write failing executor tests**

Construct one node for each artifact, patch
`run_governance_structural_gate`, and assert no provider method is called:

```python
result = executor.execute(node, store)
assert result.verdict == "PASS"
assert result.state_updates["structural_action"] == "proceed"
provider.dispatch.assert_not_called()
```

Add `repair`, warning, and block cases. Assert block is `FAIL`, includes an exact
blocked reason through controller control enrichment, and is not intercepted by
`_blocked_executor_reason`.

- [ ] **Step 2: Run executor tests and verify failure**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py \
  -k deterministic_structural
```

Expected: FAIL because the executor is absent.

- [ ] **Step 3: Implement and register the executor**

Implement the same constructor shape as other deterministic executors. Before
validation, require the artifact's projected verdict:

```python
def _normalized_attempts(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


spec_ref = str(state.get("spec_dir") or "").strip()
spec_dir = Path(spec_ref) if spec_ref else None
if spec_dir is not None and not spec_dir.is_absolute():
    spec_dir = self._project_root / spec_dir

verdict_key = {
    "feasibility": "feasibility_verdict",
    "intent-alignment-check": "intent_alignment_verdict",
}[artifact]
if state.get(verdict_key) is None:
    gate = GovernanceStructuralGateResult(
        artifact_key=artifact,
        action="block",
        passed=False,
        attempts=_normalized_attempts(state.get(attempts_key)),
        findings=0,
        report_path=None,
        exhausted_artifact=None,
        blocked_reason="governance_structural_authoring_verdict_missing",
        detail=f"run the owner phase before {node.id}",
    )
else:
    gate = run_governance_structural_gate(
        artifact_key=artifact,
        spec_dir=spec_dir,
        extension_root=self._ext_dir,
        governance_config=config,
        previous_attempts=state.get(attempts_key, 0),
        iteration=state.get("iteration", 0),
        max_iterations=state.get("max_iterations", 0),
    )
```

Return detached `SquadAgentResult` with the exact action-to-verdict mapping.
Register:

```python
"deterministic_structural": DeterministicStructuralExecutor(
    phase_graph, ext_dir, project_root, self._squad_dir
),
```

Add the type to `controller_owns_result_updates`. When action is `block`, attach
sealed `status: blocked` and the result's allowed exact `blocked_reason`; do not
set `routing_override`.

- [ ] **Step 4: Add complete state replacement**

For each action, return the full state shape and exact removals from the design:
passing validation retains its new report, bypass removes report, repair removes
exhaustion, warning retains exhaustion, and block persists available evidence.

- [ ] **Step 5: Run executor and preparation tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_governance_structural_gate.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py \
  -k 'structural or governance'
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/harness/squad_executors.py \
  src/harness/squad.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py
git commit -m "feat: add deterministic structural executor"
```

---

### Task 5: Switch the Workflow and Remove the Hidden Hook

**Files:**

- Modify: `extension/workflow/definition.yaml`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_structural_wiring.py`

**Interfaces:**

- Provider phases always route to their structural successor after projectable
  results.
- Structural nodes route only from `structural_action` plus the persisted
  provider verdict.

- [ ] **Step 1: Write failing exact-wiring tests**

Assert:

```python
assert _targets("phase2-decide") == ["phase2-feasibility-structural"]
assert _targets("phase2-tracker-alignment") == [
    "phase2-intent-alignment-structural"
]
assert _node("phase2-feasibility-structural").agent is None
assert _node("phase2-intent-alignment-structural").agent is None
```

Assert every forward route contains
`structural_action in [proceed, proceed_with_warning]`, repair increments
iteration, block targets `terminal-blocked`, and STOP_AND_ASK is absent from
structural conditions.

- [ ] **Step 2: Run wiring tests and verify failure**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/unit/test_structural_wiring.py
```

Expected: FAIL against the old graph.

- [ ] **Step 3: Rewire both paths in one edit**

Add the two YAML nodes exactly as specified by the design. Change provider
contracts to authoring contracts and replace each provider transition list with
one `condition: always` edge. Move `write_kill_report` and
`increment_defer_count` unchanged to certified feasibility edges.

- [ ] **Step 4: Remove the old implementation**

Delete from `SquadController`:

```text
_governance_structural_gate_updates
_validate_governance_structural_artifact
_governance_exhaustion_enrichment
_enforce_governance_structural_gate_result
_governance_gate_must_stop_on_exhaustion
```

Remove their invocation from `_controller_enrichment()` and transition
evaluation. Keep configuration rendering used by prompts only if another call
site remains; verify with `rg` before deleting helpers.

- [ ] **Step 5: Add routing integration cases**

Cover feasibility PASS/KILL/DEFER, DEFER limit, feasibility repair, alignment
ALIGNED/DRIFT/DRIFTING, ESCALATE loop, repair, warn, block, disabled bypass, and
STOP_AND_ASK staying at TRACKER. Assert structural block persists report/state
and reaches `terminal-blocked` through an ordinary transition.

- [ ] **Step 6: Run graph and controller tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/unit/test_structural_wiring.py \
  tests/integration/test_squad_controller.py \
  -k 'structural or governance or authoring_verdict or stop_and_ask'
```

Expected: PASS and `rg` finds no hidden structural hook:

```bash
! rg '_enforce_governance_structural_gate_result|_validate_governance_structural_artifact|_governance_gate_must_stop_on_exhaustion' src/harness/squad.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  extension/workflow/definition.yaml \
  src/harness/squad.py \
  tests/kernel/test_phase_graph.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_structural_wiring.py
git commit -m "feat: expose governance structural nodes"
```

---

### Task 6: Complete Recovery, Manual Execution, Checkpoints, and Documentation

**Files:**

- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`
- Modify: `tests/unit/test_cli_phase.py`
- Modify: `extension/workflow/phases/phase2-decide.md`
- Modify: `extension/workflow/phases/phase2-tracker-alignment.md`
- Modify: `extension/agents/feasibility/gatekeeper.md`
- Modify: `extension/agents/control/tracker.md`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Manual execution requires an already persisted projected verdict.
- Old prepared results are never reinterpreted under a new contract digest.
- Ordinary completion/checkpoint machinery remains the only recovery authority.

- [ ] **Step 1: Write failing recovery and manual-run tests**

Add tests that:

```python
assert run_manual("phase2-feasibility-structural", state_without_verdict).phase \
    == "terminal-blocked"
assert state["blocked_reason"] \
    == "governance_structural_authoring_verdict_missing"
assert not report_path.exists()
```

Then add valid-verdict manual runs for both nodes and assert zero provider
calls. Add recovery tests for same-digest prepared projection replay, stale
contract-digest rejection, stale routing-snapshot rejection, and pending
completion recovery before redispatch.

- [ ] **Step 2: Write failing checkpoint tests**

For pass, repair, warning, and block, assert the structural phase receives its
own checkpoint and that the checkpoint commit contains the report when one is
required. Assert repair checkpoints before returning to the owner phase.

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_cli_phase.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/integration/test_squad_controller.py \
  -k 'structural and (manual or checkpoint or recover or stale)'
```

Expected: FAIL until new node IDs and recovery expectations are wired.

- [ ] **Step 4: Complete recovery/checkpoint integration**

Use only current `PreparedPhaseResult`, routing snapshot, completion outbox, and
publication outbox APIs. Do not add a special structural receipt. Ensure manual
missing-verdict preflight happens before service validation/report persistence.

Before installing the changed extension in a live project, scan affected run
states and refuse activation if either pending marker is present:

```bash
if rg -l \
  '"pending_(controller_completion|external_publication)"[[:space:]]*:' \
  runs --glob 'state.json'
then
  echo "Drain listed runs with the old installed workflow before activation."
  exit 1
fi
```

Drain those runs with the old installed workflow first; do not migrate marker
payloads or contract digests.

- [ ] **Step 5: Update phase and agent documentation**

Document:

- GATEKEEPER authors and repairs `feasibility.md`; the visible node certifies it.
- TRACKER authors and repairs `intent-alignment-check.md`.
- `STOP_AND_ASK` blocks at TRACKER before certification.
- `ESCALATE` is certified and loops back through the explicit structural node.
- Providers must not emit projected verdict or structural state fields.
- Exact report names and manual recovery owner phases.

Add a concise `[Unreleased]` CHANGELOG entry naming both new nodes.

- [ ] **Step 6: Run focused recovery/documentation tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_cli_phase.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_structural_wiring.py \
  tests/integration/test_squad_controller.py \
  -k 'structural or governance or stop_and_ask'
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_cli_phase.py \
  extension/workflow/phases/phase2-decide.md \
  extension/workflow/phases/phase2-tracker-alignment.md \
  extension/agents/feasibility/gatekeeper.md \
  extension/agents/control/tracker.md \
  CHANGELOG.md
git commit -m "docs: document explicit structural gates"
```

---

### Task 7: Run Migration and Repository Verification

**Files:**

- Modify only files required by failures caused by this package.

**Interfaces:**

- Produces a verified single authoritative path and an installable extension.

- [ ] **Step 1: Run static design invariants**

Run:

```bash
rg -n 'phase2-feasibility-structural|phase2-intent-alignment-structural' \
  extension/workflow/definition.yaml
! rg '_enforce_governance_structural_gate_result|_validate_governance_structural_artifact|_governance_gate_must_stop_on_exhaustion' \
  src/harness/squad.py
git diff --check
```

Expected: both nodes found, hidden hooks absent, no whitespace errors.

- [ ] **Step 2: Run the focused package suite**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_governance_structural_gate.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_controller_state_contracts.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_structural_wiring.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_cli_phase.py \
  tests/integration/test_squad_controller.py
```

Expected: PASS.

- [ ] **Step 3: Run the repository suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: PASS with no new failures.

- [ ] **Step 4: Validate and reinstall the development extension**

Before replacement, run the pending-marker preflight from Task 6 in the target
project and confirm it exits zero, then run:

```bash
bash scripts/bash/dry-run.sh
specify extension add --dev --force \
  /Users/michalbachorik/work/echelon_r/echelon/extension
```

Expected: validation succeeds, preflight is clean, and the installed workflow
contains both explicit structural nodes.

- [ ] **Step 5: Run one representative governed Phase A flow**

Use governance enabled with valid feasibility and alignment artifacts. Expected:
telemetry shows both `deterministic_structural` phases, no provider dispatch for
either phase, both report files exist, and the run advances to
`phase3-specialists`.

- [ ] **Step 6: Review final scope and commit verification-only fixes**

Run:

```bash
git status --short
git diff --stat
git log --oneline -7
```

Expected: only package-owned files changed and one focused commit per task. If
verification required corrections, commit only those corrections:

```bash
git add \
  src/harness/governance_structural_gate.py \
  src/harness/phase_graph.py \
  src/harness/controller_state_contract_requirements.py \
  src/harness/workflow_validator.py \
  src/harness/squad_executors.py \
  src/harness/squad.py \
  extension/workflow/controller-state-contracts.yaml \
  extension/workflow/definition.yaml
git commit -m "fix: harden explicit structural gate migration"
```
