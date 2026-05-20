# WHY1 Convergence Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the WHY1 infinite loop by giving SAGE a way to signal user-gated CRITICAL issues, making the harness mode-aware (banzai → COMMANDER judgment, semi/guided → stop), and adding a consecutive-fail safety net.

**Architecture:** Three layers: (1) `squad_state.py` gets `why_fail_count` tracking and a `_staging_changed_since` helper; (2) `squad.py` gets mode-aware escalation in `run()`, a new `_judgment_dispatch_escalation()` method, and consecutive-fail detection in `_evaluate_transitions`; (3) phase spec files (`phase1-why1.md`, `phase1-why2.md`) and `commander.md` get the user-gated signal protocol and banzai judgment format.

**Tech Stack:** Python 3.11, pathlib, existing harness (squad.py, squad_state.py), pytest, markdown phase specs.

---

## File Map

| File | Change |
|---|---|
| `src/harness/squad_state.py` | Add `why_fail_count: 0` to `initialize()`; add `increment_why_fail_count()` and `reset_why_fail_count()` methods |
| `src/harness/squad.py` | Mode-aware escalation block in `run()`; new `_judgment_dispatch_escalation()`; consecutive-fail guard + `_staging_changed_since()` in `_evaluate_transitions` |
| `extension/workflow/phases/phase1-why1.md` | Add user-gated CRITICAL section with `escalation_question` protocol |
| `extension/workflow/phases/phase1-why2.md` | Same addition |
| `extension/agents/control/commander.md` | Add §Banzai Escalation Judgment Protocol |
| `tests/kernel/test_squad_state.py` | New tests for `why_fail_count` methods |
| `tests/integration/test_squad_controller.py` | New tests for mode-aware escalation and consecutive-fail guard |

---

## Task 1: `why_fail_count` in SquadStateStore

**Files:**
- Modify: `src/harness/squad_state.py`
- Test: `tests/kernel/test_squad_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/kernel/test_squad_state.py — add at end of file

def test_initialize_sets_why_fail_count_zero(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    assert store.load()["why_fail_count"] == 0

def test_increment_why_fail_count(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    store.increment_why_fail_count()
    assert store.load()["why_fail_count"] == 1
    store.increment_why_fail_count()
    assert store.load()["why_fail_count"] == 2

def test_reset_why_fail_count(tmp_path):
    from harness.squad_state import SquadStateStore
    store = SquadStateStore(tmp_path / "squad/run-test")
    store.initialize("r1", "semi", "msg", 0, "init")
    store.increment_why_fail_count()
    store.increment_why_fail_count()
    store.reset_why_fail_count()
    assert store.load()["why_fail_count"] == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/michalbachorik/work/echelon_r/echelon
pytest tests/kernel/test_squad_state.py::test_initialize_sets_why_fail_count_zero -v
```
Expected: `FAILED` — `why_fail_count` key missing from state.

- [ ] **Step 3: Add `why_fail_count: 0` to `initialize()`**

In `src/harness/squad_state.py`, in the `initialize()` method, add to the dict passed to `self.save({...})`:
```python
"why_fail_count": 0,
```
Place it after `"issues_log": [],`.

- [ ] **Step 4: Add `increment_why_fail_count()` and `reset_why_fail_count()`**

Add these two methods after `increment_token_usage()`:
```python
def increment_why_fail_count(self) -> int:
    state = self.load()
    count = state.get("why_fail_count", 0) + 1
    state["why_fail_count"] = count
    self.save(state)
    return count

def reset_why_fail_count(self) -> None:
    state = self.load()
    state["why_fail_count"] = 0
    self.save(state)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/kernel/test_squad_state.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad_state.py tests/kernel/test_squad_state.py
git commit -m "feat: add why_fail_count tracking to SquadStateStore"
```

---

## Task 2: `_staging_changed_since()` helper and consecutive-fail guard in `_evaluate_transitions`

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_squad_controller.py`

The WHY phases are: `phase1-why1`, `phase1-why2`. After each WHY phase completes, the harness updates `why_fail_count` and checks for the safety-net condition.

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_squad_controller.py — add to TestSquadControllerBasics

def test_why_fail_increments_on_fail(tmp_path):
    """why_fail_count increments each time a WHY phase returns quality_gates.fail."""
    from harness.squad_provider import SquadAgentResult
    from harness.squad_state import SquadStateStore
    provider = _mock_provider("FAIL")
    # Override exec_agent to return a FAIL result with quality_scores
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "FAIL",
            "state_updates": {"quality_scores": [{"pass": False}]},
        },
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
    # Run one cycle — why1 will FAIL and route back to phase1-discover
    # We only care that why_fail_count was incremented
    ctrl.run("msg", "banzai")
    state = store.load()
    assert state.get("why_fail_count", 0) >= 1

def test_why_fail_resets_on_pass(tmp_path):
    """why_fail_count resets when a WHY phase passes."""
    from harness.squad_provider import SquadAgentResult
    provider = _mock_provider()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "DONE",
            "state_updates": {"quality_scores": [{"pass": True}]},
        },
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("r", "banzai", "msg", 0, "phase1-why1", max_iterations=5)
    # Prime with a fail count
    store.increment_why_fail_count()
    store.increment_why_fail_count()
    ctrl.run("msg", "banzai")
    # After a pass, count should reset (0 or was reset during evaluation)
    state = store.load()
    assert state.get("why_fail_count", 0) == 0

def test_consecutive_fails_force_escalation(tmp_path):
    """≥2 consecutive WHY fails with no staging progress → auto-escalation block."""
    import json
    from harness.squad_provider import SquadAgentResult
    provider = _mock_provider("FAIL")
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "FAIL",
            "state_updates": {"quality_scores": [{"pass": False}]},
        },
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("r", "semi", "msg", 0, "phase1-why1", max_iterations=5)
    # Pre-set why_fail_count=1 so the next fail triggers the guard
    store.increment_why_fail_count()
    result = ctrl.run("msg", "semi")
    # Should be blocked (auto-escalated), not looping
    assert result.status == "blocked"
    state = store.load()
    assert state.get("escalation_question") is not None
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/integration/test_squad_controller.py::TestSquadControllerBasics::test_consecutive_fails_force_escalation -v
```
Expected: FAILED — no consecutive-fail guard exists yet.

- [ ] **Step 3: Add `_staging_changed_since()` to `SquadController`**

Add this method after `_budget_exhausted()` in `src/harness/squad.py`:

```python
WHY_PHASES = frozenset({"phase1-why1", "phase1-why2"})

def _staging_changed_since(self, iso_timestamp: Optional[str]) -> bool:
    """Return True if any staging file is newer than iso_timestamp.

    Returns True (progress) when timestamp is None (first run) or when
    any .md file in staging_dir has mtime > timestamp.
    """
    if iso_timestamp is None:
        return True
    try:
        from datetime import datetime, timezone
        cutoff = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        state = self._state_store.load()
        staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
        for f in staging_dir.glob("*.md"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime > cutoff:
                return True
        return False
    except Exception:
        return True  # conservative: treat parse failure as progress
```

Also add `WHY_PHASES` as a module-level constant just before `class SquadController`.

- [ ] **Step 4: Add consecutive-fail guard to `_evaluate_transitions`**

In `_evaluate_transitions`, after the transition loop completes (after `return "DONE"`), insert the guard BEFORE `return "DONE"`. The guard should run after we know the result is a WHY fail. The cleanest place is at the top of `_evaluate_transitions` right after loading state:

```python
def _evaluate_transitions(
    self, node: PhaseNode, result: SquadAgentResult
) -> str:
    state = self._state_store.load()

    # ── WHY fail tracking + consecutive-fail safety net ──────────────────
    if node.id in WHY_PHASES:
        from harness.condition_evaluator import ConditionEvaluator
        _ev = ConditionEvaluator()
        is_fail = _ev.evaluate("quality_gates.fail", state, result) is True
        if is_fail:
            fail_count = self._state_store.increment_why_fail_count()
            if fail_count >= 2 and not state.get("escalation_question"):
                last_ts = (state.get("last_dispatch") or {}).get("completed_at")
                if not self._staging_changed_since(last_ts):
                    print(
                        f"[squad] ✗ consecutive-fail guard: {fail_count} WHY fails "
                        f"with no staging progress — forcing escalation",
                        flush=True,
                    )
                    s = self._state_store.load()
                    s["escalation_question"] = (
                        f"Auto-detected: {fail_count} consecutive {node.id} FAILs "
                        f"with no staging progress. User input or banzai COMMANDER "
                        f"judgment required before continuing."
                    )
                    s["blocked_reason"] = "consecutive_why_fails"
                    s["status"] = "blocked"
                    self._state_store.save(s)
                    return "terminal-blocked"
        else:
            # WHY passed — reset counter
            self._state_store.reset_why_fail_count()
    # ── end WHY tracking ────────────────────────────────────────────────

    for transition in node.transitions:
        # ... rest of existing transition loop unchanged ...
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/integration/test_squad_controller.py -v 2>&1 | tail -20
pytest tests/kernel/ tests/integration/test_squad_controller.py -q 2>&1 | tail -5
```
Expected: all new tests PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py
git commit -m "feat: consecutive-fail safety net in _evaluate_transitions + WHY phase tracking"
```

---

## Task 3: Mode-aware escalation block + `_judgment_dispatch_escalation()`

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_squad_controller.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_squad_controller.py — add to TestSquadControllerBasics

def test_banzai_escalation_dispatches_commander_not_stops(tmp_path):
    """Banzai mode: blocked+escalation_question → COMMANDER called, run doesn't stop."""
    import json
    from harness.squad_provider import SquadAgentResult

    provider = _mock_provider()
    # COMMANDER judgment result clears the block
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={
            "verdict": "JUDGMENT_RESOLVED",
            "state_updates": {
                "escalation_question": None,
                "escalation_resolved": True,
                "escalation_resolver": "COMMANDER-banzai",
                "blocked_reason": None,
            },
        },
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl, store = _controller(tmp_path, provider=provider)
    store.initialize("r", "banzai", "msg", 0, "DONE", max_iterations=5)
    # Pre-set blocked with escalation_question
    state = store.load()
    state["status"] = "blocked"
    state["escalation_question"] = "Q1: Do you have author rights?"
    state["blocked_reason"] = "WHY1: user-gated issues"
    state["mode"] = "banzai"
    store.save(state)

    result = ctrl.run("msg", "banzai")
    # Should NOT return blocked — COMMANDER judgment ran and cleared the block
    assert result.status != "blocked"
    # Provider must have been called (COMMANDER dispatched)
    assert provider.exec_agent.called

def test_semi_escalation_stops_run(tmp_path):
    """Semi mode: blocked+escalation_question → run stops with status=blocked."""
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "semi", "msg", 0, "DONE", max_iterations=5)
    state = store.load()
    state["status"] = "blocked"
    state["escalation_question"] = "Q1: Do you have author rights?"
    state["blocked_reason"] = "WHY1: user-gated issues"
    state["mode"] = "semi"
    store.save(state)

    result = ctrl.run("msg", "semi")
    assert result.status == "blocked"

def test_guided_escalation_stops_run(tmp_path):
    """Guided mode: blocked+escalation_question → run stops with status=blocked."""
    ctrl, store = _controller(tmp_path)
    store.initialize("r", "guided", "msg", 0, "DONE", max_iterations=5)
    state = store.load()
    state["status"] = "blocked"
    state["escalation_question"] = "Q1: Do you have author rights?"
    state["mode"] = "guided"
    store.save(state)

    result = ctrl.run("msg", "guided")
    assert result.status == "blocked"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/integration/test_squad_controller.py::TestSquadControllerBasics::test_banzai_escalation_dispatches_commander_not_stops -v
```
Expected: FAILED — current escalation block stops all modes.

- [ ] **Step 3: Replace the escalation block in `run()` with mode-aware logic**

Find the block starting at `# ── Escalation block — human answer required` (currently lines ~179-195 in squad.py). Replace it entirely:

```python
        # ── Escalation block ──────────────────────────────────────────────
        elif existing_status == "blocked" and existing.get("escalation_question"):
            q = existing.get("escalation_question", "")
            mode_at_block = existing.get("mode", mode)

            if mode_at_block == "banzai":
                print(
                    f"\n[squad] escalation detected — banzai mode, "
                    f"dispatching COMMANDER judgment\n"
                    f"  Questions: {q[:120]}",
                    flush=True,
                )
                # Clear the block so run() proceeds after judgment
                s = self._state_store.load()
                s["status"] = "running"
                s["blocked_reason"] = None
                self._state_store.save(s)
                existing_status = "running"
                # Dispatch COMMANDER to resolve — result applied inside method
                self._judgment_dispatch_escalation(
                    escalation_question=q,
                    blocked_phase=existing.get("phase", "unknown"),
                )
                force_resume = True
            else:
                # semi / guided: stop and require echelon resume
                print(
                    f"\n[squad] ✗ Run is blocked — human input required.\n"
                    f"  Phase:    {existing.get('phase', '?')}\n"
                    f"  Reason:   {existing.get('blocked_reason', '')}\n"
                    f"  Question: {q}\n\n"
                    f"  Answer with:  echelon resume \"<your answer>\"\n"
                    f"  Discard with: echelon run --reset \"<new task>\"\n",
                    flush=True,
                )
                return SquadResult(
                    status="blocked",
                    phase=existing.get("phase", "unknown"),
                    run_id=existing.get("run_id", ""),
                )
```

- [ ] **Step 4: Add `_judgment_dispatch_escalation()` to SquadController**

Add this method after `_judgment_dispatch()`:

```python
def _judgment_dispatch_escalation(
    self,
    escalation_question: str,
    blocked_phase: str,
) -> SquadAgentResult:
    """Dispatch COMMANDER to resolve a user-gated escalation in banzai mode.

    COMMANDER receives the blocking questions + staging context and writes
    staging/user-clarifications.md with BANZAI-AUTO-RESOLVED answers.
    Returns state_updates that clear the block.
    """
    commander_path = self._ext_dir / "agents/control/commander.md"
    state = self._state_store.load()

    staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
    staging_context = ""
    for f in sorted(staging_dir.glob("*.md"))[:8]:
        try:
            staging_context += f"\n---\n# {f.name}\n{f.read_text()[:3000]}\n"
        except Exception:
            pass

    context = (
        f"# COMMANDER BANZAI ESCALATION JUDGMENT\n\n"
        f"**Mode:** banzai — produce best-judgment answers and continue. "
        f"Do NOT stop the run.\n\n"
        f"**Phase blocked:** {blocked_phase}\n\n"
        f"**Blocking questions:**\n{escalation_question}\n\n"
        f"**Your task:**\n"
        f"1. For each blocking question, produce a best-judgment answer.\n"
        f"2. Write `{staging_dir}/user-clarifications.md` using the "
        f"BANZAI-AUTO-RESOLVED format from commander.md §Banzai Escalation.\n"
        f"3. Return echelon_result state_updates that clear the block:\n"
        f"   escalation_question: null\n"
        f"   escalation_resolved: true\n"
        f"   escalation_resolver: COMMANDER-banzai\n"
        f"   blocked_reason: null\n\n"
        f"**Staging context:**\n{staging_context}"
    )
    if commander_path.exists():
        context = commander_path.read_text() + "\n\n" + context

    result = self._provider.exec_agent(str(self._project_root), context)
    self._write_journal_entries(result, blocked_phase)

    if result.state_updates:
        s = self._state_store.load()
        for k, v in result.state_updates.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        self._state_store.save(s)

    return result
```

Note: `v is None` → `pop(k)` handles clearing `escalation_question: null` from state.

- [ ] **Step 5: Run tests**

```bash
pytest tests/integration/test_squad_controller.py -v 2>&1 | tail -20
pytest tests/kernel/ tests/integration/test_squad_controller.py -q 2>&1 | tail -5
```
Expected: all new tests PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py
git commit -m "feat: mode-aware escalation block — banzai dispatches COMMANDER, semi/guided stops"
```

---

## Task 4: Phase spec changes — user-gated CRITICAL signal

**Files:**
- Modify: `extension/workflow/phases/phase1-why1.md`
- Modify: `extension/workflow/phases/phase1-why2.md`
- Modify: `extension/agents/control/commander.md`

No Python tests — these are markdown instructions for LLM agents. Verify via structural test.

- [ ] **Step 1: Add user-gated section to `phase1-why1.md`**

After the existing Gate Check section (after `If **PASS**... → proceed to WHAT`), add:

```markdown
### User-gated CRITICAL issues

When CRITICAL issues are **user-gated** — they require information only the user holds
(legal rights, product positioning decisions, audience policy, cost envelope) and cannot
be resolved by more DISCOVER/SYNTHESIZER/MODELER/TRACKER work — include in
`echelon_result.state_updates`:

```yaml
escalation_question: |
  Q1: <compact blocking question — one line, state the stakes>
  Q2: <compact blocking question>
blocked_reason: "WHY1: CRITICAL user-gated issues — squad-internal iteration cannot substitute for user input"
```

**Criteria — ALL must be true to use escalation_question:**
1. Cannot be resolved by any squad agent (no amount of re-running DISCOVER helps)
2. Requires information only the user holds
3. Proceeding without the answer requires an arbitrary coin-flip that binds all downstream phases

**Do NOT set escalation_question for squad-solvable CRITICAL issues** (missing boundaries,
glossary gaps, unread manual pages, contradictions resolvable by ORACLE/INVESTIGATOR).
Those keep routing back to DISCOVER as normal.

The harness reads `escalation_question` and either:
- **banzai mode** → dispatches COMMANDER to produce best-judgment answers and continue
- **semi/guided mode** → stops the run; user answers via `echelon resume "<answers>"`
```

- [ ] **Step 2: Add identical section to `phase1-why2.md`**

Read `extension/workflow/phases/phase1-why2.md`. Find the WHY2 iteration stop conditions table (it ends with a row for "Otherwise → phase1-what"). After that table, add the same user-gated section as Step 1, with `WHY2` substituted for `WHY1` in the `blocked_reason` value.

- [ ] **Step 3: Add §Banzai Escalation Judgment Protocol to `commander.md`**

In `extension/agents/control/commander.md`, add a new section after `## Completion Signal`:

```markdown
## Banzai Escalation Judgment Protocol

When dispatched with `# COMMANDER BANZAI ESCALATION JUDGMENT`, the squad run is in
banzai mode and hit user-gated CRITICAL issues. Your job: make defensible judgment
calls so the run continues without stopping.

### Output: `staging/user-clarifications.md`

Write this file. Header:
```markdown
# User Clarifications — BANZAI AUTO-RESOLVED
> Generated by COMMANDER judgment in banzai mode. Treat as working assumptions,
> not confirmed decisions. Review before production release.
> Run `echelon resume "<confirmed answers>"` to provide confirmed answers.
```

For each blocking question:
```markdown
## Q<N> — <question summary> [BANZAI-AUTO-RESOLVED]
**COMMANDER judgment:** <one-line answer>
**Confidence:** <0.0–1.0>
**Basis:** <2-3 sentences citing staging artifacts>
**Reversible:** yes/no — <note on what changes to override>
```

### Judgment principles

- **Err toward stated user intent**: user said "addictive like Ticket to Ride" → entertainment-led, not education-led
- **Conservative compliance posture**: age band decisions → pick 13+ over 9+ to avoid COPPA
- **Never fabricate legal facts**: IP/rights questions → write `BANZAI-ASSUMED: yes` with explicit `Requires verification before release` note
- **Existential questions**: if truly existential (project may have no legal authority to exist), set `escalation_question` to a shorter version in state_updates so semi/guided runs can still catch it — do not silently unblock

### `echelon_result` state_updates to return

```yaml
echelon_result:
  verdict: JUDGMENT_RESOLVED
  output_files:
    - staging/user-clarifications.md
  state_updates:
    escalation_question: null
    escalation_resolved: true
    escalation_resolver: "COMMANDER-banzai"
    blocked_reason: null
```
```

- [ ] **Step 4: Structural validation**

```bash
grep -c "escalation_question" extension/workflow/phases/phase1-why1.md
grep -c "escalation_question" extension/workflow/phases/phase1-why2.md
grep -c "Banzai Escalation" extension/agents/control/commander.md
```
Expected: each returns `>= 1`.

- [ ] **Step 5: Run full suite to confirm no regressions**

```bash
pytest tests/kernel/ tests/integration/test_squad_controller.py -q 2>&1 | tail -5
bash tests/unit/test-unit-squad-registry.sh 2>&1 | tail -5
```
Expected: all PASS, 9/9 structural checks.

- [ ] **Step 6: Commit**

```bash
git add extension/workflow/phases/phase1-why1.md \
        extension/workflow/phases/phase1-why2.md \
        extension/agents/control/commander.md
git commit -m "feat: WHY1/WHY2 user-gated escalation signal + COMMANDER banzai judgment protocol"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| SAGE signals user-gated issues via `escalation_question` in state_updates | Task 4 (phase1-why1.md, phase1-why2.md) |
| Harness: banzai → COMMANDER judgment | Task 3 (`_judgment_dispatch_escalation`, mode-aware block) |
| Harness: semi/guided → stop (unchanged) | Task 3 (escalation block else branch) |
| COMMANDER banzai format (BANZAI-AUTO-RESOLVED) | Task 4 (commander.md §Banzai Escalation) |
| `why_fail_count` tracking | Task 1 (squad_state.py) |
| Consecutive-fail safety net | Task 2 (`_evaluate_transitions`) |
| `_staging_changed_since()` helper | Task 2 |
| `null` state_updates clears key from state | Task 3 (`_judgment_dispatch_escalation` — `pop` on None) |
| Tests for all new behaviors | Tasks 1, 2, 3 |

**Placeholder scan:** None found.

**Type consistency:**
- `increment_why_fail_count() -> int` defined in Task 1, used in Task 2.
- `reset_why_fail_count() -> None` defined in Task 1, used in Task 2.
- `WHY_PHASES: frozenset` defined in Task 2 as module-level, used in `_evaluate_transitions`.
- `_staging_changed_since(iso_timestamp: Optional[str]) -> bool` defined in Task 2, used in Task 2.
- `_judgment_dispatch_escalation(escalation_question, blocked_phase) -> SquadAgentResult` defined in Task 3, called in Task 3.

**Gap found and fixed:** Task 3's `_judgment_dispatch_escalation` handles `v is None → pop(k)` to correctly clear `escalation_question` and `blocked_reason` from state (a plain `s[k] = None` would leave the keys with null values, which the escalation block would still detect on the next run).
