# Issue Resolution Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-issue SAGE escalations progress one selected issue at a time through repair and WHY2 validation.

**Architecture:** `src/echelon/cli.py` records one selected decision and an artifact baseline. `SquadController` promotes it to `repaired` only after WHAT changes canonical artifacts, then to `validated` after WHY2 passes. Banzai selections are normalized through the same controller-owned ledger and recovery edge.

**Tech Stack:** Python 3.11+, pytest, existing `SquadStateStore` routing transactions.

## Global Constraints

- Keep one active selected issue; preserve all other SAGE findings and their order.
- Only controller code may mutate repair and validation lifecycle state after a user decision.
- A selected issue is not validated merely because WHAT ran; WHY2 must pass first.
- Do not add runtime dependencies.

---

### Task 1: Record a repair baseline at selection

**Files:**
- Modify: `src/echelon/cli.py:3670-3732`
- Modify: `tests/unit/test_cli_resume_escalation_options.py:367-415`

**Interfaces:**
- Produces: `issue_resolution_repair_baseline` with `issue_id`, `repair_phase`, and UTC `recorded_at`.

- [ ] **Step 1: Write the failing test**

```python
assert resolved["issue_resolution_repair_baseline"]["issue_id"] == "ISS-002"
assert resolved["issue_resolution_repair_baseline"]["repair_phase"] == "phase1-what"
assert resolved["issue_resolution_repair_baseline"]["recorded_at"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/unit/test_cli_resume_escalation_options.py::test_resolve_records_one_issue_and_starts_targeted_repair -q`
Expected: FAIL because the baseline key is absent.

- [ ] **Step 3: Write minimal implementation**

```python
from datetime import datetime, timezone
state["issue_resolution_repair_baseline"] = {
    "issue_id": issue_id,
    "repair_phase": "phase1-what",
    "recorded_at": datetime.now(timezone.utc).isoformat(),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/unit/test_cli_resume_escalation_options.py::test_resolve_records_one_issue_and_starts_targeted_repair -q`
Expected: PASS.

### Task 2: Consume the recovery edge after a real WHAT repair

**Files:**
- Modify: `src/harness/squad.py:5888-5915`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: a selected entry and `issue_resolution_repair_baseline.recorded_at`.
- Produces: selected entry status `repaired` and recovery status `consumed` only when `_phase_artifacts_changed_since` reports progress.

- [ ] **Step 1: Write the failing test**

```python
updates = ctrl._coordinate_what_repair_cycle_updates(what_node, snapshot)
assert updates["issue_resolution_ledger"]["ISS-001"]["status"] == "repaired"
assert updates["issue_resolution_recovery"]["status"] == "consumed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/integration/test_squad_controller.py -k issue_resolution -q`
Expected: FAIL because WHAT returns no issue-resolution lifecycle updates.

- [ ] **Step 3: Write minimal implementation**

```python
if selected_entry["status"] == "selected" and self._phase_artifacts_changed_since(recorded_at, state):
    ledger[selected]["status"] = "repaired"
    recovery["status"] = "consumed"
    return {"issue_resolution_ledger": ledger, "issue_resolution_recovery": recovery}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/integration/test_squad_controller.py -k issue_resolution -q`
Expected: PASS.

### Task 3: Validate only after a passing WHY2 assessment

**Files:**
- Modify: `src/harness/squad.py:5917-6037`
- Modify: `src/harness/squad_executors.py:459-479`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: a `repaired` selected entry and a non-failing `phase1-why2` result.
- Produces: `validated` ledger status and clears `selected_issue_resolution` after WHY2 acceptance.

- [ ] **Step 1: Write the failing test**

```python
override, updates = ctrl._coordinate_why_transition_state(why2_node, prepared, snapshot)
assert override is None
assert updates["issue_resolution_ledger"]["ISS-001"]["status"] == "validated"
assert updates["selected_issue_resolution"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/integration/test_squad_controller.py -k issue_resolution -q`
Expected: FAIL because a WHY2 pass only resets the fail counter.

- [ ] **Step 3: Write minimal implementation**

```python
if node.id == "phase1-why2" and selected_entry["status"] == "repaired" and not is_fail:
    ledger[selected]["status"] = "validated"
    return None, {"why_fail_count": 0, "issue_resolution_ledger": ledger,
                  "selected_issue_resolution": None, "issue_resolution_repair_baseline": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/integration/test_squad_controller.py -k issue_resolution -q`
Expected: PASS.

### Task 4: Normalize Banzai and verify the queue

**Files:**
- Modify: `src/harness/squad.py:6460-6898`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: one validated Banzai candidate selection.
- Produces: the same selected ledger entry, baseline, and recovery edge as explicit resolution.

- [ ] **Step 1: Write a failing test**

```python
assert accepted["issue_resolution_ledger"]["ISS-001"]["status"] == "selected"
assert accepted["issue_resolution_recovery"]["to_phase"] == "phase1-what"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/integration/test_squad_controller.py -k issue_resolution -q`
Expected: FAIL because Banzai does not materialize its selection.

- [ ] **Step 3: Write minimal implementation**

```python
state["issue_resolution_ledger"][issue_id] = {**candidate, "status": "selected", "decision": decision, "repair_phase": "phase1-what"}
state["selected_issue_resolution"] = issue_id
state["issue_resolution_recovery"] = {"issue_id": issue_id, "from_phase": "phase1-why2", "to_phase": "phase1-what", "reason": "issue_resolution"}
```

- [ ] **Step 4: Run focused regressions and commit**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_continue.py tests/integration/test_squad_controller.py -k 'issue_resolution or resolve or phase_dispatch_limit' -q`
Expected: PASS.

Commit command: `git add src/echelon/cli.py src/harness/squad.py src/harness/squad_executors.py tests/unit/test_cli_resume_escalation_options.py tests/integration/test_squad_controller.py && git commit -m "fix: advance issue resolution queue"`
