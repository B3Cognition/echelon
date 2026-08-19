# EGR-144 Phase A Checkpoint Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record one attributed Git checkpoint for every executed required Phase A node, report exact run-scoped coverage, and expose only certified checkpoints as rewind targets.

**Architecture:** Derive Phase A scope from workflow reachability, persist versioned executed/skipped completion outcomes, and route checkpoint creation through explicit workflow policy plus controller-owned path allowlists. Keep the existing completion transaction and Git prestate protections, extend the ledger with rewind policy, provide explicit legacy migration, and validate the complete flow through a real-Git synthetic controller run.

**Tech Stack:** Python 3.11+, PyYAML, existing `harness.phase_graph`, `harness.squad`, `harness.phase_checkpoints`, and spec lifecycle locks, pytest, real temporary Git repositories.

**Spec:** `docs/superpowers/specs/2026-08-19-egr-144-phase-a-checkpoint-coverage-design.md`

## Global Constraints

- Do not scan Git history to infer ordinary checkpoint coverage.
- Do not commit arbitrary staging, state, journal, lock, ledger, or receipt files.
- Preserve completion-ID idempotency and captured-`HEAD` prestate validation.
- Automatic checkpointing runs only under the project Phase A and run execution leases.
- New runs use `checkpoint_policy_version: 2`; unversioned runs remain legacy until explicit migration.
- Coverage joins outcomes and checkpoints by completion ID, not only phase name.
- A skipped node never creates a commit or ledger row.
- Every Echelon-created commit, including implementation and migration commits, contains `Co-authored-by: Echelon <echelon@b3cognition.dev>`.
- Focused tests must pass with zero failures and require no LLM, Docker, or network access.

---

## File Structure

- `src/harness/phase_graph.py`
  - Parse checkpoint and rewind policy and derive the graph-reachable Phase A node set.
- `src/harness/workflow_validator.py`
  - Validate explicit policy for every graph-reachable Phase A node.
- `runtime/workflow/definition.yaml`
  - Declare checkpoint and rewind policy.
- `src/echelon/phase_a_start.py`
  - Bootstrap version 2 checkpoint state for new runs.
- `src/harness/squad_state.py`
  - Persist idempotent executed/skipped completion outcomes.
- `runtime/workflow/phases/phase1-*.md`
  - Write early durable artifacts to `spec_dir` while keeping control-plane files in staging.
- `src/harness/checkpoint_policy.py`
  - Resolve phase policy and additional owned paths without accepting arbitrary YAML paths.
- `src/harness/squad.py`
  - Plan required checkpoint effects, omit skipped effects, and use existing completion failure recovery.
- `src/harness/phase_checkpoints.py`
  - Persist rewind metadata and create attributed no-change commits.
- `src/echelon/checkpoint_coverage.py`
  - Compute completion-ID-based run coverage.
- `src/echelon/checkpoint_cli.py`
  - Resolve exact runs, always show coverage, support strict mode, and route legacy migration.
- `src/echelon/checkpoint_migration.py`
  - Preview and apply allowlisted legacy staging migration under lifecycle locks.
- `src/echelon/rewind.py`, `src/echelon/cli.py`
  - Filter unsupported targets and use version 2 outcome history for state pruning.
- Focused tests under `tests/kernel`, `tests/unit`, and `tests/integration`.

---

### Task 1: Add Graph-Derived Checkpoint And Rewind Policy

**Files:**
- Modify: `src/harness/phase_graph.py`
- Modify: `src/harness/workflow_validator.py`
- Modify: `runtime/workflow/definition.yaml`
- Test: `tests/kernel/test_phase_graph.py`
- Test: `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Produces: `PhaseNode.checkpoint: str | None`
- Produces: `PhaseNode.rewind: str | None`
- Produces: `phase_a_phase_ids(graph: PhaseGraph) -> tuple[str, ...]`
- Consumes: `PhaseGraph.all_phase_ids()` and `PhaseGraph.get()`.

- [ ] **Step 1: Write graph scope and parsing tests**

Add tests using the public graph API:

```python
def test_phase_a_scope_is_reachable_from_init():
    graph = PhaseGraph(PROSAIC_RUNTIME_DEFINITION)
    scoped = phase_a_phase_ids(graph)

    assert scoped[0] == "init"
    assert "phase1-discover" in scoped
    assert "phase4-document" in scoped
    assert {"done", "terminal-blocked", "escalate"} <= set(scoped)
    assert "phase-exp-tasks-quality" not in scoped
    assert "bugfix-1-init" not in scoped
    assert "build-1-init" not in scoped


def test_phase_a_nodes_parse_explicit_checkpoint_and_rewind_policy():
    graph = PhaseGraph(PROSAIC_RUNTIME_DEFINITION)

    for phase_id in phase_a_phase_ids(graph):
        node = graph.get(phase_id)
        assert node.checkpoint in {"required", "none"}
        assert node.rewind in {"supported", "none"}
```

- [ ] **Step 2: Run the graph tests and verify RED**

Run:

```bash
pytest tests/kernel/test_phase_graph.py -q
```

Expected: failure because policy fields and `phase_a_phase_ids()` do not exist.

- [ ] **Step 3: Extend `PhaseNode` and implement reachability**

Add fields:

```python
checkpoint: Optional[str] = None
rewind: Optional[str] = None
```

Load them with `p.get("checkpoint")` and `p.get("rewind")` in the existing
`PhaseNode(...)` construction.

Add this public helper next to `load_workspace_phase_graph()`:

```python
def phase_a_phase_ids(graph: PhaseGraph) -> tuple[str, ...]:
    pending = ["init"]
    ordered: list[str] = []
    seen: set[str] = set()
    while pending:
        phase_id = pending.pop(0)
        if phase_id in seen:
            continue
        node = graph.get(phase_id)
        seen.add(phase_id)
        ordered.append(phase_id)
        if node.type == "terminal":
            continue
        for transition in node.transitions:
            target = transition.get("to") if isinstance(transition, dict) else None
            if isinstance(target, str) and target not in seen:
                pending.append(target)
    return tuple(ordered)
```

- [ ] **Step 4: Write validator tests**

Add three fixture-based tests:

```python
def test_reachable_phase_requires_checkpoint_policy(tmp_path):
    definition = _write_definition(tmp_path, [
        {
            "id": "init",
            "type": "commander_internal",
            "checkpoint": "none",
            "rewind": "none",
            "transitions": [{"to": "phase1-discover", "condition": "always"}],
        },
        {
            "id": "phase1-discover",
            "type": "agent",
            "rewind": "supported",
            "transitions": [{"to": "done", "condition": "always"}],
        },
        {"id": "done", "type": "terminal", "checkpoint": "none", "rewind": "none"},
    ])
    report = validate_workflow_definition(definition_path=definition)
    assert any(
        issue.phase_id == "phase1-discover"
        and "checkpoint must be required or none" in issue.message
        for issue in report.issues
    )


def test_required_checkpoint_requires_explicit_rewind_policy(tmp_path):
    definition = _write_definition(tmp_path, [
        {
            "id": "init",
            "type": "commander_internal",
            "checkpoint": "none",
            "rewind": "none",
            "transitions": [{"to": "phase1-discover", "condition": "always"}],
        },
        {
            "id": "phase1-discover",
            "type": "agent",
            "checkpoint": "required",
            "transitions": [{"to": "done", "condition": "always"}],
        },
        {"id": "done", "type": "terminal", "checkpoint": "none", "rewind": "none"},
    ])
    report = validate_workflow_definition(definition_path=definition)
    assert any(
        issue.phase_id == "phase1-discover"
        and "rewind must be supported or none" in issue.message
        for issue in report.issues
    )


def test_checkpoint_none_rejects_supported_rewind(tmp_path):
    definition = _write_definition(tmp_path, [
        {
            "id": "init",
            "type": "commander_internal",
            "checkpoint": "none",
            "rewind": "supported",
            "transitions": [{"to": "done", "condition": "always"}],
        },
        {"id": "done", "type": "terminal", "checkpoint": "none", "rewind": "none"},
    ])
    report = validate_workflow_definition(definition_path=definition)
    assert any("rewind supported requires checkpoint required" in issue.message for issue in report.issues)
```

Use the test module's existing `_write_definition(tmp_path, phases)` helper.

- [ ] **Step 5: Implement static validation with repository-native issues**

After `PhaseGraph` loads successfully, iterate `phase_a_phase_ids(graph)`. Append
`WorkflowValidationIssue(message, phase_id=phase_id, path=path)` objects to
`issues`. Accept exactly `required|none` for checkpoint and `supported|none` for
rewind. Reject `checkpoint: none` with `rewind: supported`.

- [ ] **Step 6: Add the exact workflow policy**

Set `checkpoint: required` and `rewind: supported` on the 26 phases listed in
the design. Set both fields to `none` on `init`, both human gates, and all three
reachable terminals. Do not add policy to unreachable experimental, bugfix, or
build nodes.

- [ ] **Step 7: Run policy tests**

Run:

```bash
pytest tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add runtime/workflow/definition.yaml src/harness/phase_graph.py src/harness/workflow_validator.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py
git commit -m "feat: declare Phase A checkpoint policy" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 2: Version New Runs And Persist Completion Outcomes

**Files:**
- Modify: `src/echelon/phase_a_start.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_phase_a_start.py`
- Test: `tests/unit/test_squad_phase_checkpoints.py`
- Test: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Produces: `CHECKPOINT_POLICY_VERSION = 2`
- Produces: version 2 state field `phase_completion_outcomes: list[dict[str, object]]`
- Produces: one idempotent outcome per controller completion ID.

- [ ] **Step 1: Write bootstrap tests**

Assert fresh state contains:

```python
assert state["checkpoint_policy_version"] == 2
assert state["phase_completion_outcomes"] == []
```

Also assert existing run loading does not synthesize either field.

- [ ] **Step 2: Run bootstrap tests and verify RED**

Run:

```bash
pytest tests/unit/test_phase_a_start.py -q
```

Expected: fresh state lacks the new fields.

- [ ] **Step 3: Add version 2 bootstrap fields**

Define `CHECKPOINT_POLICY_VERSION = 2` in `phase_a_start.py` and add both fields
to `_write_prepared_state()` for newly created Phase A runs. Do not add defaults
when reading historical state.

- [ ] **Step 4: Write outcome transaction tests**

Extend routing-state tests to prove:

```python
assert state["phase_completion_outcomes"] == [{
    "completion_id": completion_id,
    "phase": "phase1-modeler",
    "next_phase": "phase1-tracker",
    "outcome": "skipped",
    "checkpoint": "required",
}]
```

Replay the same prepared decision and assert the list still has one row. Prepare
a second completion for the same phase with a different completion ID and
assert both rows remain in order.

- [ ] **Step 5: Persist outcomes in the authorized state transition**

In `SquadStateStore.advance_prepared_result()`, append the outcome while building
`next_state`, next to the existing `completed_phases` update. Obtain
`completion_id` from the pending controller completion marker already bound to
the routing decision. Use:

```python
outcome = {
    "completion_id": completion_id,
    "phase": from_phase,
    "next_phase": to_phase,
    "outcome": "skipped" if decision.conditional_skip else "executed",
    "checkpoint": checkpoint_policy,
}
```

Carry `checkpoint_policy` as an explicit field on the prepared routing decision;
validate it as `required|none`. Before appending, reject a matching completion
ID with different content and ignore an exact replay.

Update controller calls to `prepare_advance()` to pass `node.checkpoint` after
validating it is `required|none`. This task records policy but does not yet use
it to change checkpoint effect planning; Task 4 adds enforcement.

- [ ] **Step 6: Run state tests**

Run:

```bash
pytest tests/unit/test_phase_a_start.py tests/unit/test_squad_phase_checkpoints.py tests/kernel/test_squad_state.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/phase_a_start.py src/harness/squad.py src/harness/squad_state.py tests/unit/test_phase_a_start.py tests/unit/test_squad_phase_checkpoints.py tests/kernel/test_squad_state.py
git commit -m "feat: record Phase A completion outcomes" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 3: Move Early Durable Outputs And Define Owned Paths

**Files:**
- Create: `src/harness/checkpoint_policy.py`
- Modify: `runtime/workflow/phases/phase1-discover.md`
- Modify: `runtime/workflow/phases/phase1-synthesizer.md`
- Modify: `runtime/workflow/phases/phase1-modeler.md`
- Modify: `runtime/workflow/phases/phase1-tracker.md`
- Modify: `runtime/workflow/phases/phase1-why1.md`
- Modify: `runtime/workflow/phases/phase1-constitution.md`
- Modify: `runtime/workflow/phases/phase1-what.md`
- Test: `tests/kernel/test_prompt_references.py`
- Test: `tests/unit/test_checkpoint_policy.py`

**Interfaces:**
- Produces: `phase_checkpoint_policy(graph: PhaseGraph, phase: str) -> tuple[str, str]`
- Produces: `checkpoint_additional_owned_paths(project_root: Path, phase: str, state: Mapping[str, object]) -> tuple[Path, ...]`

- [ ] **Step 1: Write prompt contract tests**

For discovery, synthesizer, modeler, tracker, and WHY1, assert durable output
instructions contain `{spec_dir}` or `ACTIVE_SPEC_DIR`, and reject output
instructions targeting `${STAGING_DIR}`. Keep assertions that
`{staging_dir}/user-clarifications.md` remains a readable control-plane input.

For `phase1-constitution.md`, assert the output remains
`.echelon/constitution.md`. For `phase1-what.md`, assert it consumes discovery
artifacts from `{spec_dir}` and does not move them from staging.

- [ ] **Step 2: Run prompt tests and verify RED**

Run:

```bash
pytest tests/kernel/test_prompt_references.py -q
```

Expected: current early prompts still assign durable output to staging.

- [ ] **Step 3: Update early phase prompt contracts**

Change both read and write paths for canonical early artifacts to `{spec_dir}`.
Use this invariant in each producer prompt:

```markdown
Write canonical Phase A artifacts under `{spec_dir}` (`ACTIVE_SPEC_DIR`).
`${STAGING_DIR}` is reserved for controller inputs and transient dispatch
material; do not place canonical artifacts there.
```

Keep constitution output at `.echelon/constitution.md`. Replace the
`phase1-what` move instruction with in-place consumption from `{spec_dir}`.

- [ ] **Step 4: Write policy resolver tests**

```python
def test_policy_resolver_rejects_missing_runtime_policy(real_graph):
    with pytest.raises(CheckpointPolicyError, match="missing checkpoint policy"):
        phase_checkpoint_policy(graph_without_policy, "phase1-discover")


def test_constitution_adds_only_canonical_constitution_path(tmp_path):
    paths = checkpoint_additional_owned_paths(
        tmp_path,
        "phase1-constitution",
        {"spec_id": "001-demo"},
    )
    assert paths == (tmp_path / ".echelon/constitution.md",)


def test_ordinary_phase_has_no_additional_owned_paths(tmp_path):
    assert checkpoint_additional_owned_paths(
        tmp_path, "phase1-discover", {"spec_id": "001-demo"}
    ) == ()
```

- [ ] **Step 5: Implement the strict policy resolver**

`phase_checkpoint_policy()` calls `graph.get(phase)` and raises
`CheckpointPolicyError` for unknown or invalid values. It never defaults.

`checkpoint_additional_owned_paths()` returns the canonical constitution path
only for `phase1-constitution`. Keep existing final-publication path expansion
in `SquadController._completion_checkpoint_inputs()` because it requires
published-spec and accepted-KB validation already owned there.

- [ ] **Step 6: Run prompt and policy tests**

Run:

```bash
pytest tests/kernel/test_prompt_references.py tests/unit/test_checkpoint_policy.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add runtime/workflow/phases/phase1-discover.md runtime/workflow/phases/phase1-synthesizer.md runtime/workflow/phases/phase1-modeler.md runtime/workflow/phases/phase1-tracker.md runtime/workflow/phases/phase1-why1.md runtime/workflow/phases/phase1-constitution.md runtime/workflow/phases/phase1-what.md src/harness/checkpoint_policy.py tests/kernel/test_prompt_references.py tests/unit/test_checkpoint_policy.py
git commit -m "fix: checkpoint early Phase A artifacts" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 4: Make Controller Completion Policy-Aware

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_squad_phase_checkpoints.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: `phase_checkpoint_policy()` and `checkpoint_additional_owned_paths()`.
- Produces: checkpoint effect only for executed version 2 required completions.
- Produces: version 1 compatibility with no new missing-checkpoint enforcement.

- [ ] **Step 1: Write effect-plan tests**

Cover this matrix:

```text
version 2 + executed + required + spec_dir present   -> checkpoint effect
version 2 + skipped  + required + spec_dir present   -> no checkpoint effect
version 2 + executed + none                           -> no checkpoint effect
version 2 + executed + required + spec_dir missing   -> preparation failure
version 1 + completed phase                           -> existing compatibility behavior
```

Assert a skipped required completion persists an outcome but does not change
Git `HEAD` and does not create a ledger row.

- [ ] **Step 2: Run controller tests and verify RED**

Run:

```bash
pytest tests/unit/test_squad_phase_checkpoints.py tests/integration/test_squad_controller.py -q
```

Expected: current planning is based only on `spec_dir` existence.

- [ ] **Step 3: Pass policy through routing preparation**

At every call to `SquadStateStore.prepare_advance()`, pass the current node's
validated checkpoint policy. Add it to the prepared routing decision and its
attestation so the state transition cannot substitute policy after dispatch.

- [ ] **Step 4: Build the completion effect plan from policy and outcome**

In `_prepare_controller_completion()`, resolve policy before creating the
effect plan. For routed completions, append `checkpoint` only when all are true:

```python
checkpoint_version == 2
and checkpoint_policy == "required"
and not conditional_skip
```

Validate `spec_dir` during preparation for that case. Raise `StateAdvanceError`
with validator `checkpoint_target` when it is missing; let the existing
controller completion failure machinery persist the block. Do not directly
load, mutate, and save an unrelated state snapshot from
`_checkpoint_successful_phase()`.

For version 1, retain the old existence-based checkpoint effect so historical
runs continue rather than becoming newly blocked.

- [ ] **Step 5: Add phase-owned paths and no-change forcing**

In `_completion_checkpoint_inputs()`, append
`checkpoint_additional_owned_paths(project_root, phase, state)` to validated
additional owned paths. Preserve the phase4 publication paths.

In `_apply_controller_completion_effect_ordered()`, pass:

```python
force_commit=(checkpoint_version == 2 and checkpoint_policy == "required")
```

Obtain version and policy from the sealed completion intent, not mutable current
state.

- [ ] **Step 6: Replace the legacy helper test**

Update the test that currently expects missing active spec to return success.
Assert version 2 required completion preparation fails with
`phase_checkpoint_target_missing: phase1-discover`, while an unversioned state
still follows compatibility behavior.

- [ ] **Step 7: Run controller tests**

Run:

```bash
pytest tests/unit/test_squad_phase_checkpoints.py tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/harness/squad.py src/harness/squad_state.py tests/unit/test_squad_phase_checkpoints.py tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py
git commit -m "fix: enforce versioned Phase A checkpoints" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 5: Extend Ledger Metadata And Certify Rewind

**Files:**
- Modify: `src/echelon/commit_messages.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `src/echelon/checkpoint_cli.py`
- Modify: `src/echelon/rewind.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_commit_messages.py`
- Test: `tests/unit/test_phase_checkpoints.py`
- Test: `tests/unit/test_cli_checkpoint.py`
- Test: `tests/unit/test_cli_rewind.py`

**Interfaces:**
- Extends: `PhaseCheckpoint.rewind: str = "supported"`
- Extends: `PhaseCheckpoint.rewind_reason: str = ""`
- Extends: `PhaseCheckpoint.boundary_completion_id: str = ""`
- Extends: `create_or_recover_completion_checkpoint(..., source: str = "auto")`
- Produces: `rewindable_checkpoint_targets(ledger: CheckpointLedger) -> list[str]`

- [ ] **Step 1: Write backward-compatible ledger tests**

Assert a legacy row without rewind fields loads as:

```python
assert checkpoint.rewind == "supported"
assert checkpoint.rewind_reason == ""
```

Assert a version 2 row with `rewind: none` requires a non-empty safe reason
code and survives write/load exactly.

- [ ] **Step 2: Write attributed changed and empty commit tests**

Call `create_or_recover_completion_checkpoint()` with
`checkpoint_prestate={"kind": "git_head", "head": head}`. Test one changed
`spec_dir` and one clean `spec_dir` with `force_commit=True`. Assert each commit
contains:

```python
message = _git(repo, "show", "-s", "--format=%B", commit)
assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in message
assert "Echelon-Action: checkpoint" in message
assert "Echelon-Completion:" in message
assert "Echelon-Checkpoint-Source: auto" in message
```

For constitution, pass `.echelon/constitution.md` as an additional owned path
and assert `git show --name-only` contains both its path and the changed spec
artifact, but not checkpoint ledger or lock files.

- [ ] **Step 3: Run ledger tests and verify RED**

Run:

```bash
pytest tests/unit/test_phase_checkpoints.py -q
```

Expected: rewind metadata assertions fail; existing `force_commit` behavior may
already pass and must remain unchanged.

- [ ] **Step 4: Extend checkpoint row parsing and writing**

Add optional rewind fields to the strict allowed row keys. Default absent fields
to legacy-supported. Validate exactly:

```python
if rewind not in {"supported", "none"}:
    raise PhaseCheckpointError("invalid checkpoint rewind policy")
if rewind == "supported" and rewind_reason:
    raise PhaseCheckpointError("supported checkpoint cannot have rewind reason")
if rewind == "none" and not SAFE_REASON.fullmatch(rewind_reason):
    raise PhaseCheckpointError("unsupported checkpoint requires rewind reason")
```

Pass the sealed workflow rewind policy into completion checkpoint creation and
store it on the row. Add a `source` argument accepting exactly `auto` and
`user-committed`, and `legacy-migration`; persist it on the row and include it
in completion identity validation. Extend `EchelonCommitMetadata` with
`checkpoint_source` and emit
`Echelon-Checkpoint-Source` so crash recovery can authenticate the source from
the commit itself. Ordinary controller callers rely on the `auto` default.

Automatic rows set `boundary_completion_id` equal to `completion_id`.

- [ ] **Step 5: Preserve manual checkpoint movement**

Add CLI tests proving `accept` creates no commit and `commit` creates a fully
attributed commit. For version 2 state, resolve the latest executed
`phase_completion_outcomes` row matching `--phase` and pass its completion ID as
`boundary_completion_id`. Reject a phase with no executed outcome. Persist the
binding on `user-accepted` and `user-committed` rows.

Assert strict coverage still requires the automatic row, while phase-only
rewind selects the later manual row and prunes state using its bound boundary.

- [ ] **Step 6: Write rewind filtering tests**

Create a ledger with one supported and one unsupported row. Assert CLI preview
rejects the unsupported row before branch mutation, prints its reason, and lists
only supported targets. Assert the legacy row remains selectable.

- [ ] **Step 7: Use version 2 outcomes for rewind pruning**

In `_reset_rewind_state()`, branch on `checkpoint_policy_version == 2`.
For version 2, resolve the selected row's `boundary_completion_id`, retain only
outcome rows before that completion ID, retain only distinct executed phases from those rows in
`completed_phases`, prune dispatch counts to that set, and set the active phase
to the selected checkpoint phase. Do not add `_ROADMAP_PHASES` predecessors.
Keep the current roadmap fallback unchanged for legacy state.

- [ ] **Step 8: Add whole-commit rewind certification tests**

Use real Git to cover:

```text
phase1-discover              early spec_dir artifact restored
phase1-constitution          .echelon/constitution.md restored
phase1-investigate           conditional branch history pruned correctly
phase1-what twice            exact completion ID selects the requested cycle
phase1-understanding         empty checkpoint remains selectable
phase4-document              published owned paths restored
phase3-plan user-accepted    user commit restored with bound state boundary
```

For every case, assert branch `HEAD`, artifact bytes, retained ledger rows,
`phase_completion_outcomes`, `completed_phases`, and next active phase.

- [ ] **Step 9: Run checkpoint and rewind tests**

Run:

```bash
pytest tests/unit/test_commit_messages.py tests/unit/test_phase_checkpoints.py tests/unit/test_cli_checkpoint.py tests/unit/test_cli_rewind.py -q
```

Expected: PASS. A failure for any declared supported policy class blocks
implementation and requires a reviewed design-policy revision before release.

- [ ] **Step 10: Commit**

```bash
git add runtime/workflow/definition.yaml src/echelon/commit_messages.py src/harness/phase_checkpoints.py src/echelon/checkpoint_cli.py src/echelon/rewind.py src/echelon/cli.py tests/kernel/test_phase_graph.py tests/unit/test_commit_messages.py tests/unit/test_phase_checkpoints.py tests/unit/test_cli_checkpoint.py tests/unit/test_cli_rewind.py
git commit -m "fix: certify checkpoint rewind targets" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 6: Compute Exact Run-Scoped Coverage

**Files:**
- Create: `src/echelon/checkpoint_coverage.py`
- Modify: `src/echelon/checkpoint_cli.py`
- Test: `tests/unit/test_cli_checkpoint.py`

**Interfaces:**
- Produces: `CheckpointCoverageRow`
- Produces: `compute_spec_checkpoint_coverage(graph: PhaseGraph, state: Mapping[str, object], ledger: CheckpointLedger) -> tuple[CheckpointCoverageRow, ...]`
- Consumes: `resolve_spec_run()` and `resolve_active_spec_run()` from `echelon.spec_lifecycle`.

- [ ] **Step 1: Write completion-ID coverage tests**

Create state with executed, skipped, repeated, and none-policy outcomes. Create
ledger rows for only selected completion IDs. Assert statuses are:

```text
executed required + matching row     recorded
executed required + no row           missing
skipped required                     skipped
executed none                        not-checkpointed
legacy unversioned completion        legacy-untracked
migrated legacy completion           legacy-migrated
```

Assert two executions of the same phase produce two coverage rows and only the
unmatched completion is missing.

- [ ] **Step 2: Write CLI resolution and empty-ledger tests**

Cover:

- no `--spec`: exact active run;
- `--spec <run-id>`: exact inactive run;
- ambiguous numeric spec prefix: exit `1` with matching run IDs;
- no ledger rows: print `(none)` and still print `COVERAGE`;
- normal mode with missing required rows: exit `0`;
- `--strict` with missing version 2 rows: exit `2`;
- `--strict` with only legacy-untracked rows: exit `0`.

- [ ] **Step 3: Run CLI tests and verify RED**

Run:

```bash
pytest tests/unit/test_cli_checkpoint.py -q
```

Expected: coverage model and strict mode do not exist.

- [ ] **Step 4: Implement the coverage model**

Define:

```python
@dataclass(frozen=True)
class CheckpointCoverageRow:
    completion_id: str
    phase: str
    status: str
    rewind: str
```

For version 2, index ledger rows by non-empty completion ID and iterate
`phase_completion_outcomes` in stored order. Validate each referenced phase with
`graph.get()`. Derive status from outcome, policy, legacy marker, and matching
row. Raise `CheckpointCoverageError` for duplicate completion IDs or identity
drift.

For legacy state, iterate distinct `completed_phases` in stored order and report
recorded rows by phase or `legacy-untracked`; never report `missing`.

- [ ] **Step 5: Resolve the exact run before resolving its spec directory**

Replace active-only state lookup in list handling:

```python
run = resolve_spec_run(project_root, spec) if spec else resolve_active_spec_run(project_root)
state = json.loads((run.run_dir / "state.json").read_text(encoding="utf-8"))
spec_dir = run.spec_dir
```

Catch `SpecRunNotFound` and `SpecRunAmbiguous` and render their deterministic
run identities. Do not fall back to `find_spec_dir()` for coverage because that
can detach a spec directory from its run state.

- [ ] **Step 6: Always render coverage and strict result**

Remove the early return after `(none)`. Print ledger rows when present, then the
coverage table. Parse `--strict` only for `list`; remove it before rejecting
unexpected arguments. Exit `2` only when a row status is `missing`.

- [ ] **Step 7: Run CLI tests**

Run:

```bash
pytest tests/unit/test_cli_checkpoint.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/checkpoint_coverage.py src/echelon/checkpoint_cli.py tests/unit/test_cli_checkpoint.py
git commit -m "feat: report exact checkpoint coverage" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 7: Add Explicit Legacy Checkpoint Migration

**Files:**
- Create: `src/echelon/checkpoint_migration.py`
- Modify: `src/echelon/checkpoint_cli.py`
- Test: `tests/unit/test_checkpoint_migration.py`
- Test: `tests/unit/test_cli_checkpoint.py`

**Interfaces:**
- Produces: `prepare_legacy_checkpoint_migration(project_root: Path, run: SpecRun) -> LegacyCheckpointMigrationPlan`
- Produces: `apply_legacy_checkpoint_migration(project_root: Path, plan: LegacyCheckpointMigrationPlan) -> PhaseCheckpoint`

- [ ] **Step 1: Write preview safety tests**

Use this exact allowlist:

```python
LEGACY_EARLY_ARTIFACTS = frozenset({
    "glossary.md",
    "mental-model.md",
    "boundaries.md",
    "assumptions.md",
    "unknowns.md",
    "reference-architectures.md",
    "contradictions-and-gaps.md",
    "risks.md",
    "mental-model-code.md",
    "codebase-graph.md",
    "user-intent.md",
    "stakeholder-model.md",
})
```

Assert preview includes allowlisted regular files, ignores known control-plane
files, lists unknown regular files as ignored, rejects symlinked allowlisted
sources, and rejects destination collisions whose bytes differ.

- [ ] **Step 2: Write locking and mutation tests**

Assert confirmed migration:

- fails before copying or committing while `PhaseAExecutionLock` is held;
- re-resolves the same run after both execution leases are acquired;
- preserves staging originals;
- copies allowlisted artifacts only;
- sets `checkpoint_policy_version` to `2`;
- writes legacy outcome records with `legacy: true`;
- creates one `source: legacy-migration` ledger row;
- creates one commit with the Echelon co-author and action trailers; and
- is idempotent when repeated with the same plan and completion ID.

- [ ] **Step 3: Run migration tests and verify RED**

Run:

```bash
pytest tests/unit/test_checkpoint_migration.py tests/unit/test_cli_checkpoint.py -q
```

Expected: migration module and command do not exist.

- [ ] **Step 4: Implement immutable preview planning**

`LegacyCheckpointMigrationPlan` stores run ID, spec ID, resolved run/spec/staging
paths, source file size and SHA-256, destination disposition, destination
preimage bytes and hashes, captured Git `HEAD`, and a generated
operation/completion ID. Legacy synthetic outcome IDs are deterministic
64-character lowercase SHA-256 values derived from run ID, phase, and original
completion order. Reject version 2 runs.

Do not copy in preview mode. CLI prints the file table and the exact confirmed
command including the resolved run ID:

```text
echelon spec checkpoint migrate --spec <run-id> --confirm
```

- [ ] **Step 5: Implement confirmed migration under lifecycle locks**

Acquire `PhaseAExecutionLock`, then `SpecRunExecutionLock`. Re-resolve the run,
re-hash every source, re-check destination collisions and Git `HEAD`, and seal a
run-local migration intent before mutation. Copy with atomic regular-file
writes, then call the existing checkpoint commit path with `force_commit=True`
and `source="legacy-migration"`. Only after commit and ledger recovery succeeds,
persist version/outcomes through `SquadStateStore` and mark the intent complete.
Pass `rewind="none"`, `rewind_reason="legacy-migration-boundary"`, and an empty
boundary completion ID because migration does not fabricate a historical phase
boundary.

On failure before a matching commit exists, restore every destination preimage
from the sealed intent and leave version 1 state authoritative. On recovery
after the commit exists, use completion ID lookup to repair the ledger and
finish the state transition exactly once.

- [ ] **Step 6: Route the CLI subcommand**

Extend usage with:

```text
echelon spec checkpoint migrate [--spec <run-or-spec-id>] [--confirm]
```

Reject `--strict`, `--phase`, and `--message` for migrate.

- [ ] **Step 7: Run migration tests**

Run:

```bash
pytest tests/unit/test_checkpoint_migration.py tests/unit/test_cli_checkpoint.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/echelon/checkpoint_migration.py src/echelon/checkpoint_cli.py tests/unit/test_checkpoint_migration.py tests/unit/test_cli_checkpoint.py
git commit -m "feat: migrate legacy spec checkpoints" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

### Task 8: Add Controller-Driven Integration Coverage And Close EGR-144

**Files:**
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_cli_rewind.py`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/findings/2026-07-16-egr-144-146-checkpoint-rewind-rerun.md`

**Interfaces:**
- Consumes: versioned outcomes, policy-aware completion effects, real Git checkpointing, coverage CLI, migration, and rewind filtering.
- Produces: release evidence for EGR-144.

- [ ] **Step 1: Write a real-Git synthetic controller integration test**

Create a temporary initialized workspace and Git repository. Use the real
workflow graph and `SquadController`, replace provider dispatch with deterministic
`SquadAgentResult` fixtures, and let normal controller preparation, authorized
state advance, completion draining, checkpoint commit, and next-phase routing
execute.

Exercise this path:

```text
phase1-discover          writes glossary.md under spec_dir
phase1-synthesizer       rewrites glossary.md
phase1-modeler           conditionally skipped
phase1-tracker           writes user-intent.md
phase1-why1              returns identical owned bytes, forcing an empty commit
phase1-constitution      writes .echelon/constitution.md
phase1-what              writes spec.md and requirements-overview.md
```

Assert after every executed required node:

- `HEAD` advanced by exactly one commit;
- commit parent equals the prior `HEAD`;
- commit message has the Echelon co-author and completion identity;
- ledger row completion ID matches the state outcome;
- committed paths are owned by that phase; and
- the next provider is not dispatched until the prior ledger row exists.

Assert the skipped modeler has an outcome, no ledger row, and no commit.

- [ ] **Step 2: Extend the same test through coverage and rewind**

Invoke `echelon spec checkpoint list --strict --spec <run-id>` through the CLI
entrypoint and assert zero missing rows. Add a later artifact commit, rewind to
the constitution checkpoint with confirmation, and assert whole-commit artifact
restoration plus version 2 outcome/state pruning.

- [ ] **Step 3: Add execution-lease exclusion integration coverage**

Hold `PhaseAExecutionLock`, invoke controller continuation and confirmed legacy
migration, and assert both stop before Git or state mutation. Hold only a
different worktree's lock and assert the current worktree remains independent.

- [ ] **Step 4: Run the focused EGR-144 matrix**

Run:

```bash
pytest \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_prompt_references.py \
  tests/kernel/test_workflow_validator.py \
  tests/unit/test_phase_a_start.py \
  tests/kernel/test_squad_state.py \
  tests/unit/test_checkpoint_policy.py \
  tests/unit/test_commit_messages.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_cli_checkpoint.py \
  tests/unit/test_checkpoint_migration.py \
  tests/unit/test_cli_rewind.py \
  tests/integration/test_squad_controller.py \
  -q
```

Expected: PASS with zero failures.

- [ ] **Step 5: Run the broad suite and compare failures to baseline**

Run:

```bash
pytest tests -q
```

Expected: PASS. If it fails, run each failing test against the pre-change commit
in a separate temporary worktree. Only failures reproduced there may be recorded
as unrelated baseline failures; any new failure blocks EGR closure.

- [ ] **Step 6: Update EGR evidence**

Mark EGR-144 fixed only after Step 4 passes with zero failures and Step 5 has no
new failures. Record:

- the implementation commit range;
- the exact focused command and pass count;
- the broad-suite result and baseline comparison, if needed;
- the policy version;
- the synthetic executed/skipped/no-change/constitution evidence; and
- the legacy migration and rewind certification evidence.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_squad_controller.py tests/unit/test_cli_rewind.py docs/findings/echelon-grounded-review-register.md docs/findings/2026-07-16-egr-144-146-checkpoint-rewind-rerun.md
git commit -m "test: certify Phase A checkpoint coverage" -m "Co-authored-by: Echelon <echelon@b3cognition.dev>"
```

---

## Self-Review Checklist

- Phase A scope comes from graph reachability, not naming prefixes.
- Every scoped node has explicit checkpoint and rewind policy.
- New runs are versioned; legacy runs are not silently subjected to new enforcement.
- Executed and skipped completions are distinguishable by completion ID.
- Early durable artifacts are written directly to `spec_dir`.
- Constitution is included in its checkpoint commit.
- No-change required nodes produce attributed empty commits.
- Every planned Git commit includes the Echelon co-author trailer.
- Empty-ledger CLI output still shows coverage.
- `--spec` resolves an exact run and rejects ambiguity.
- Unsupported rewind points cannot be selected.
- Version 2 rewind does not synthesize completion from `_ROADMAP_PHASES`.
- Legacy migration is explicit, previewable, locked, allowlisted, and recoverable.
- Integration coverage drives the controller rather than calling the checkpoint writer directly.
- The focused suite requires zero failures before EGR-144 is marked fixed.
