# Live Run and Banzai Consensus Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent unsafe concurrent continuations and automatically route evidence-backed Banzai consensus repairs.

**Architecture:** Status reads lease metadata without acquiring a lease. A completed Banzai `phase3-consensus` rejection with explicit eligible issue guidance becomes a controller-sealed repair decision; the pre-existing ledger and resolver select the documented first option. SAGE treats task-backed deferred automation as Phase-A planning evidence and reserves executed evidence for delivery.

**Tech Stack:** Python, pytest, Echelon lifecycle state machine, Markdown agent prompts.

**Spec:** Browser-3D run `spec-20260904-062901-960244`.

## Global Constraints

- Status is read-only: it never acquires, repairs, or removes a lease.
- A malformed or remote lease is conservatively active.
- Banzai selects only explicit `Banzai eligible: yes` issues from authoritative `issues.md`.
- Task-backed `deferred-automation` is valid in Phase A; Phase B must prove implemented coverage.
- Run tests with `python -m pytest`.

---

### Task 1: Distinguish live execution from stale running state

**Files:**
- Modify: `src/echelon/spec_lifecycle.py:313`
- Modify: `src/echelon/cli.py:9434`
- Test: `tests/unit/test_cli_status.py:894`

**Interfaces:**
- Produces `active_spec_run_execution_owner(run_dir: Path) -> str | None`.
- Produces `active_phase_a_execution_owner(project_root: Path) -> str | None`.

- [x] **Step 1: Write the failing test**

```python
with SpecRunExecutionLock.acquire(run_dir, "squad-exec-live"):
    _cmd_status(tmp_path)
assert "Wait for the active run to finish" in out
assert "echelon spec continue" not in out
```

- [x] **Step 2: Run the red test**

Run: `python -m pytest -q tests/unit/test_cli_status.py -k live`

Expected: the old renderer suggests `echelon spec continue`.

- [x] **Step 3: Implement the read-only probes and status branch**

```python
if execution_owner is not None:
    fields.append(("Execution", f"active ({execution_owner})"))
    fields.append(("Next", "Wait for the active run to finish; do not start a second continuation."))
else:
    fields.append(("Next", "echelon spec continue"))
```

- [x] **Step 4: Run status tests**

Run: `python -m pytest -q tests/unit/test_cli_status.py`

Expected: PASS.

### Task 2: Seal completed Banzai consensus findings as repair authority

**Files:**
- Modify: `src/harness/human_input.py:1862`
- Modify: `src/harness/squad_state.py:159`
- Modify: `src/harness/squad.py:6453`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/kernel/test_phase_graph.py:379`

**Interfaces:**
- Consumes `_banzai_issue_resolution_candidates(state)` and `_dispatch_cap_options(candidates)`.
- Produces a resolved `banzai_issue_resolution` decision whose phase is `phase3-consensus` and whose route is a valid Phase 3 repair phase.

- [x] **Step 1: Write the failing controller test**

```python
assert result.status != "blocked"
assert store.load()["selected_issue_resolution"] == "ISS-001"
assert store.load()["phase"] == "phase3-how"
```

The fixture supplies a completed consensus result with one HOW-owned issue and `Banzai eligible: yes`.

- [x] **Step 2: Run the red test**

Run: `python -m pytest -q tests/integration/test_squad_controller.py -k consensus_banzai`

Expected: it fails because the old controller persists `agent_blocked`.

- [x] **Step 3: Implement only the exact safeguard path**

```python
if node.id == "phase3-consensus" and state.get("autonomy_mode") == "banzai":
    request = registry.prepare_controller(..., option_contract=options)
    store.set_consensus_banzai_issue_decision(request)
    return self.resume_pending_human_input()
```

The state-store method validates the source phase and producer; do not expand the generic decision setter. Expand the policy's allowed source phase to `phase3-consensus` and its targets to the established Phase 3 repair corridor.

- [x] **Step 4: Run controller and phase-policy tests**

Run: `python -m pytest -q tests/integration/test_squad_controller.py -k consensus_banzai tests/kernel/test_phase_graph.py`

Expected: PASS.

### Task 3: Correct the Phase-A coverage policy

**Files:**
- Modify: `prosaic/subagents/echelon.sage.md:401`
- Test: `tests/unit/test_sage_templates.py`

- [x] **Step 1: Write the failing prompt-contract test**

```python
assert "planning-time obligation" in text
assert "Do not raise a Phase A issue" in text
assert "delivery evidence gate" in text
```

- [x] **Step 2: Run the red test**

Run: `python -m pytest -q tests/unit/test_sage_templates.py -k deferred`

Expected: the existing prompt fails because it requires a HIGH issue for every deferred row.

- [x] **Step 3: Change the WHY3 instructions**

Task-backed `deferred-automation` must be allowed to pass Phase A, with the explicit obligation that delivery executes the mapped test before merge. Missing mappings, `manual`/`none`, and unaccepted `escalated` rows remain failures.

- [x] **Step 4: Run prompt tests**

Run: `python -m pytest -q tests/unit/test_sage_templates.py`

Expected: PASS.

### Task 4: Verify and commit the composed fix

**Files:**
- Modify: `src/echelon/cli.py`, `src/echelon/spec_lifecycle.py`, `src/harness/human_input.py`, `src/harness/squad_state.py`, `src/harness/squad.py`, `prosaic/subagents/echelon.sage.md`

- [x] **Step 1: Run targeted suites**

Run: `python -m pytest -q tests/unit/test_cli_status.py tests/unit/test_sage_templates.py tests/kernel/test_phase_graph.py tests/integration/test_squad_controller.py`

Expected: PASS.

- [x] **Step 2: Check the diff**

Run: `git diff --check`

Expected: no output.

- [x] **Step 3: Check the live workspace without mutation**

Run: `PYTHONPATH=/Users/michalbachorik/work/echelon_r/echelon/src /Users/michalbachorik/.echelon/venv/bin/python -c 'from echelon.cli import main; main()' spec status`

Expected: a live lease produces wait guidance, never a concurrent continuation;
a stale Banzai consensus block explains that eligible SAGE findings route
automatically to their owning repair phase.

- [x] **Step 4: Commit the exact files and plan**

```bash
git add CHANGELOG.md README.md pyproject.toml uv.lock src/echelon/spec_lifecycle.py src/echelon/cli.py src/harness/human_input.py src/harness/squad_state.py src/harness/squad.py prosaic/subagents/echelon.sage.md tests/contract/static_contracts.py tests/unit/test_cli_status.py tests/unit/test_sage_templates.py tests/unit/test_static_contracts_pytest.py tests/kernel/test_phase_graph.py tests/integration/test_squad_controller.py docs/superpowers/plans/2026-09-04-live-run-and-banzai-consensus-recovery.md
git commit -m "fix: recover banzai consensus repairs autonomously"
```
