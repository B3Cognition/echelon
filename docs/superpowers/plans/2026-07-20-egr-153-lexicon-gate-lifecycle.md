# EGR-153 Lexicon Gate Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent an absent or unevaluated derived lexicon artifact from being recorded as a failed Lexicon validation result or routing a spec run through a false failure loop.

**Architecture:** The Phase A controller remains the authority that validates a produced `requirements.lexicon.md`. Agents may report only repair evidence; `lexicon_pass` and `lexicon_evaluation` are reserved controller writes. The controller records a Boolean `lexicon_pass` only when deterministic validation actually ran. A missing artifact or validator execution failure becomes controller-owned `lexicon_evaluation: pending`, which re-dispatches CARTOGRAPHER to create the artifact without falsifying the validation outcome. A real validator finding remains `lexicon_evaluation: failed` plus `lexicon_pass: false`.

**Tech Stack:** Python 3.11, pytest, YAML workflow definition, Lexicon validator.

## Global Constraints

- `spec.md` remains the rich Phase A source of truth; `requirements.lexicon.md` is a derived artifact.
- Only a deterministic controller validation may set `lexicon_pass` to `true` or `false`; the agent-result contract reserves that key.
- Agent prose, absent artifacts, and validator exceptions are not validation results.
- The repair loop must remain bounded by the existing workflow iteration cap and must never fall through to WHY2 while the spec lexicon is pending before the configured exhaustion policy applies.

---

### Task 1: Represent Lexicon evaluation honestly

**Files:**
- Modify: `src/harness/squad.py:1947-2031`
- Modify: `extension/workflow/definition.yaml:425-481`
- Modify: `tests/integration/test_squad_controller.py:2360-2525`

**Interfaces:**
- Consumes: `spec.md`, optional `requirements.lexicon.md`, the configured spec Lexicon gate, and CARTOGRAPHER’s result.
- Produces: controller-owned `lexicon_evaluation` (`pending`, `passed`, or `failed`) and `lexicon_pass` only after a validator verdict.

- [x] **Step 1: Write failing lifecycle tests**

```python
def test_spec_gate_marks_missing_derived_artifact_pending_without_false_result(tmp_path):
    ctrl, store = _controller(tmp_path)
    node = ctrl._graph.get("phase1-what")
    _write_spec_only(store, tmp_path)

    result = self._result({"lexicon_pass": True, "lexicon_attempts": 0})
    assert ctrl._evaluate_transitions(node, result) == "phase1-what"
    assert "lexicon_pass" not in result.state_updates
    assert result.state_updates["lexicon_evaluation"] == "pending"
```

- [x] **Step 2: Run the focused test and observe failure**

Run: `pytest tests/integration/test_squad_controller.py::TestLexiconGateGuardDeterminism -q`

Expected: FAIL because the controller writes `lexicon_pass: false` for a missing artifact.

- [x] **Step 3: Implement pending/passed/failed controller semantics**

```python
if derived_path.is_file() and source_path.is_file():
    findings = _validate_derived_spec(...)
    updates["lexicon_evaluation"] = "passed" if not findings else "failed"
    updates["lexicon_pass"] = not findings
    return

updates.pop("lexicon_pass", None)
updates["lexicon_evaluation"] = "pending"
```

- [x] **Step 4: Route pending evaluation back to WHAT without using a false Boolean**

```yaml
- to: phase1-what
  condition: "lexicon_gate.enabled AND lexicon_evaluation = pending AND iteration < max_iterations"
  action: increment_iteration
- to: phase1-what
  condition: "lexicon_gate.enabled AND NOT lexicon_pass AND lexicon_attempts < lexicon_gate.max_repair_attempts AND iteration < max_iterations"
  action: increment_iteration
```

- [x] **Step 5: Run focused controller and workflow tests**

Run: `pytest tests/integration/test_squad_controller.py tests/kernel/test_squad_executors_journal.py tests/kernel/test_condition_evaluator.py -q`

Expected: PASS.

### Task 2: Make the agent contract match controller ownership

**Files:**
- Modify: `extension/workflow/phases/phase1-what.md:61-75`
- Modify: `extension/agents/exploration/cartographer.md:212-290`
- Test: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Consumes: the configured Lexicon gate and the derived artifact path.
- Produces: CARTOGRAPHER’s derived artifact and repair-attempt count; the controller supplies the final evaluation state.

- [x] **Step 1: Add a prompt-contract assertion**

```python
assert "A missing derived artifact is pending, never lexicon_pass: false" in phase_text
```

- [x] **Step 2: Run the prompt-contract assertion**

Run: `pytest tests/kernel/test_squad_executors_journal.py -q`

Expected: FAIL because the current contract does not distinguish pending from failed validation.

- [x] **Step 3: Add the pending-state rule**

```markdown
ALWAYS create the derived artifact before returning when the gate is enabled.
NEVER emit `lexicon_pass: false` because the artifact is missing or the validator did not run; only the controller records that pending state.
```

- [x] **Step 4: Run the focused test suite**

Run: `pytest tests/integration/test_squad_controller.py tests/kernel/test_squad_executors_journal.py tests/kernel/test_condition_evaluator.py -q`

Expected: PASS.

### Task 3: Record and verify the high-priority fix

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/superpowers/plans/2026-07-20-egr-153-lexicon-gate-lifecycle.md`

- [x] **Step 1: Add an Unreleased EGR-153 entry**

```markdown
- **EGR-153 lexicon gate lifecycle** — missing or unevaluated derived lexicon artifacts are now recorded as pending, not failed validation results.
```

- [x] **Step 2: Run regression verification**

Run: `pytest tests/integration/test_squad_controller.py tests/kernel/test_squad_executors_journal.py tests/kernel/test_condition_evaluator.py tests/unit/test_cli_continue.py -q`

Expected: PASS.

- [ ] **Step 3: Commit the implementation and EGR record**

```bash
git add src/harness/squad.py extension/workflow/definition.yaml \
  extension/workflow/phases/phase1-what.md extension/agents/exploration/cartographer.md \
  tests/integration/test_squad_controller.py tests/kernel/test_squad_executors_journal.py \
  CHANGELOG.md docs/superpowers/plans/2026-07-20-egr-153-lexicon-gate-lifecycle.md
git commit -m "fix: separate pending lexicon evaluation from failure"
```
