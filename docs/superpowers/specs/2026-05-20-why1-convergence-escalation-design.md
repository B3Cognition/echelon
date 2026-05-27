# Design: WHY1 Convergence Escalation — Mode-Aware Loop Breaking

**Date:** 2026-05-20
**Status:** Approved — ready for implementation plan

## Problem

The pre-code squad run loops indefinitely when SAGE (WHY1) finds CRITICAL issues that cannot be resolved by more squad work. These are **user-gated** issues — they require user product decisions, legal facts, or business policy that no squad agent can produce. The harness has no way to distinguish them from squad-solvable CRITICAL issues, so it keeps routing back to DISCOVER and burning iterations and API budget.

Observed in practice: NavigationalPortal ran 7 consecutive WHY1 → DISCOVER → WHY1 cycles before the run was manually interrupted. SAGE diagnosed the root cause correctly by iteration 4 but the harness ignored its HALT directives.

Two independent failure modes:
- **A — No user-gated signal**: SAGE can't communicate "this needs human input" to the harness — all CRITICAL issues look the same in `state_updates`
- **B — No consecutive-fail guard**: Even if A is fixed, a future SAGE that forgets to set the signal would still loop indefinitely

---

## Architecture

```
WHY1 (SAGE) returns echelon_result
        │
        ├── user-gated CRITICAL issues?
        │   ├── yes → state_updates includes escalation_question + blocked_reason
        │   └── no  → state_updates has only quality_scores (current behavior)
        │
        ▼
harness advance() writes escalation_question to state.json
        │
        ▼
SquadController.run() checks: blocked AND escalation_question?
        │
        ├── mode = banzai → _judgment_dispatch_escalation()
        │       │
        │       ▼
        │   COMMANDER receives escalation_question + staging context
        │   COMMANDER writes staging/user-clarifications.md
        │       (BANZAI-AUTO-RESOLVED answers, confidence, reversibility notes)
        │   returns state_updates: {escalation_question: null, escalation_resolved: true, status: running}
        │   harness clears blocked state, resumes loop
        │
        └── mode = semi / guided → stop (existing behavior)
                (echelon resume "<answer>" required)

Safety net (independent):
harness tracks why_fail_count in state.json
≥2 consecutive WHY fails + no staging progress
→ force escalation_question regardless of SAGE output
```

---

## Component specifications

### 1. WHY1 / WHY2 phase spec changes

**File:** `extension/workflow/phases/phase1-why1.md` (identical pattern for `phase1-why2.md`)

Add to the Gate Check section a new subsection after the existing CRITICAL/PASS routing:

```markdown
### User-gated CRITICAL issues

When CRITICAL issues are **user-gated** — require user product decisions, legal facts,
audience policy, or business constraints that no squad agent can produce — include in
`echelon_result.state_updates`:

```yaml
escalation_question: |
  Q1: <compact blocking question with stakes>
  Q2: <compact blocking question with stakes>
  ...
blocked_reason: "WHY1: CRITICAL user-gated issues — squad-internal iteration cannot substitute for user input"
```

**Criteria for user-gated (ALL must be true):**
1. The issue cannot be resolved by more DISCOVER/SYNTHESIZER/MODELER/TRACKER work
2. The answer requires information only the user holds (legal rights, product positioning decisions, audience policy, cost envelope)
3. Proceeding without the answer would require an arbitrary coin-flip that binds all downstream phases

**Do NOT set escalation_question for squad-solvable CRITICAL issues** (e.g. missing
boundaries, glossary gaps, unread manual pages) — those should keep routing to DISCOVER.

The harness reads `escalation_question` from state.json and either stops
(semi/guided) or dispatches COMMANDER for banzai judgment.
```

### 2. Mode-aware escalation in `SquadController.run()`

**File:** `src/harness/squad.py`

**Current:** The escalation block (lines ~180-195) stops all modes and requires `echelon resume`.

**New:** Check `mode` before deciding:

```python
elif existing_status == "blocked" and existing.get("escalation_question"):
    q = existing.get("escalation_question", "")
    mode_at_block = existing.get("mode", mode)  # use mode stored in state

    if mode_at_block == "banzai":
        # Dispatch COMMANDER to judge — stay autonomous
        print(
            f"\n[squad] escalation detected — banzai mode, dispatching COMMANDER judgment\n"
            f"  Questions: {q[:120]}...",
            flush=True,
        )
        # clear the block so run() proceeds after judgment
        state = self._state_store.load()
        state["status"] = "running"
        state["blocked_reason"] = None
        self._state_store.save(state)
        # judgment dispatch using existing _judgment_dispatch infrastructure
        # (see §3 below for prompt construction)
    else:
        # semi / guided: stop and ask
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

### 3. `_judgment_dispatch_escalation()` — new method on SquadController

**File:** `src/harness/squad.py`

Purpose: dispatch COMMANDER with escalation context for banzai judgment.

```python
def _judgment_dispatch_escalation(
    self, escalation_question: str, blocked_phase: str
) -> SquadAgentResult:
    """Dispatch COMMANDER to resolve a user-gated escalation in banzai mode.

    COMMANDER receives the blocking questions + full staging context and
    writes staging/user-clarifications.md with BANZAI-AUTO-RESOLVED answers.
    Returns state_updates that clear the block.
    """
    commander_path = self._ext_dir / "agents/control/commander.md"
    state = self._state_store.load()

    # Gather staging context for COMMANDER
    staging_dir = Path(state.get("staging_dir", str(self._squad_dir / "staging")))
    staging_files = sorted(staging_dir.glob("*.md"))
    staging_context = ""
    for f in staging_files[:8]:  # cap at 8 files to avoid token explosion
        try:
            staging_context += f"\n---\n# {f.name}\n{f.read_text()[:3000]}\n"
        except Exception:
            pass

    context = (
        f"# COMMANDER BANZAI ESCALATION JUDGMENT\n\n"
        f"**Mode:** banzai — you must produce best-judgment answers and continue. "
        f"Do NOT stop the run.\n\n"
        f"**Phase blocked:** {blocked_phase}\n\n"
        f"**Blocking questions:**\n{escalation_question}\n\n"
        f"**Your task:**\n"
        f"1. Read the staging context below.\n"
        f"2. For each blocking question, produce a best-judgment answer.\n"
        f"3. Write `{staging_dir}/user-clarifications.md` with your answers "
        f"   in the BANZAI-AUTO-RESOLVED format (see commander.md §Banzai Escalation).\n"
        f"4. Return state_updates that clear the block so the run continues.\n\n"
        f"**Staging context:**\n{staging_context}"
    )
    if commander_path.exists():
        context = commander_path.read_text() + "\n\n" + context

    result = self._provider.exec_agent(str(self._project_root), context)
    self._write_journal_entries(result, blocked_phase)

    # Apply state updates from COMMANDER (clears blocked state)
    if result.state_updates:
        s = self._state_store.load()
        s.update(result.state_updates)
        self._state_store.save(s)

    return result
```

### 4. BANZAI-AUTO-RESOLVED format in `commander.md`

**File:** `extension/agents/control/commander.md`

Add a new section **§ Banzai Escalation Judgment Protocol**:

```markdown
## Banzai Escalation Judgment Protocol

When dispatched with `# COMMANDER BANZAI ESCALATION JUDGMENT`, the harness has
detected user-gated CRITICAL issues but is running in banzai mode. Your job:
make the most defensible judgment (consider 3 options and pick the one that is the most defensible) and unblock the run.

### Output: `staging/user-clarifications.md`

Write this file. For each blocking question:

```markdown
## Q<N> — <question summary> [BANZAI-AUTO-RESOLVED]

**COMMANDER judgment:** <one-line answer>
**Confidence:** <0.0–1.0>
**Basis:** <2-3 sentences citing staging artifacts that support this judgment>
**Reversible:** yes/no — <note on what would need to change to override>
```

Label the whole file with a header:
```markdown
# User Clarifications — BANZAI AUTO-RESOLVED
> Generated by COMMANDER judgment in banzai mode. Treat as working assumptions,
> not confirmed decisions. Review before production release.
> Run `echelon resume` to provide confirmed answers if needed.
```

### Return `echelon_result` state_updates

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

### Judgment principles

- **Err toward the user's stated intent**: user said "addictive like Ticket to Ride" → choose entertainment-led, not education-led
- **Choose the more conservative compliance posture** when legal/regulatory (e.g. age band: pick 13+, not 9+, to avoid COPPA)
- **Consider at least 3 judgement principles based on the issue raised**: do not be satisfied with 0 or 1 judgement principle, find at least 3 that are relevant and judge the issue against them.
- **Flag irresolvable questions** (e.g. "do you have written author rights?") as HIGH-CONFIDENCE-ASSUMPTION with explicit verification note — do not fabricate legal facts
- **Never proceed on existential risks**: if the question is truly existential (e.g. "does this project have legal authority to exist?"), write the judgment file but also set `escalation_question` to a shorter summary so semi/guided runs can still catch it
```

### 5. Consecutive-fail safety net

**File:** `src/harness/squad_state.py` + `src/harness/squad.py`

**`SquadStateStore.initialize()`:** add `"why_fail_count": 0` to the initial state dict.

**`SquadController._evaluate_transitions()`:** after evaluating WHY phase transitions, check:

```python
WHY_PHASES = {"phase1-why1", "phase1-why2", "phase2-why3"}

if node.id in WHY_PHASES and result.verdict in ("FAIL", "BLOCKED"):
    state = self._state_store.load()
    fail_count = state.get("why_fail_count", 0) + 1
    state["why_fail_count"] = fail_count
    self._state_store.save(state)

    if fail_count >= 2 and not state.get("escalation_question"):
        # Check for staging progress since last WHY dispatch
        last_why_ts = state.get("last_dispatch", {}).get("completed_at")
        staging_changed = self._staging_changed_since(last_why_ts)
        if not staging_changed:
            # No progress — force escalation regardless of SAGE output
            state = self._state_store.load()
            state["escalation_question"] = (
                f"Auto-detected: ≥{fail_count} consecutive WHY fails on {node.id} "
                f"with no staging progress. User input or banzai COMMANDER judgment required."
            )
            state["blocked_reason"] = "consecutive_why_fails"
            state["status"] = "blocked"
            self._state_store.save(state)
elif node.id in WHY_PHASES and result.verdict not in ("FAIL", "BLOCKED"):
    # reset on pass
    state = self._state_store.load()
    state["why_fail_count"] = 0
    self._state_store.save(state)
```

**`_staging_changed_since(ts: str | None) -> bool`** — helper that checks if any file in `staging_dir` has mtime newer than `ts` (ISO-8601). Returns `True` (progress) if `ts` is None (first run).

---

## Data flow summary

```
WHY1 FAIL with user-gated issues
        │
        ▼
state.json: {status: "blocked", escalation_question: "Q1..Q2..Q3", why_fail_count: 1}
        │
Next echelon run invocation
        │
        ├── banzai → _judgment_dispatch_escalation()
        │           → COMMANDER writes user-clarifications.md
        │           → state: {status: "running", escalation_question: null,
        │                     escalation_resolved: true, why_fail_count: 0}
        │           → WHY1 re-dispatched with user-clarifications.md in context
        │           → expected PASS (user-gated issues resolved by COMMANDER answers)
        │
        └── semi/guided → [squad] ✗ Run is blocked — human input required
                        → echelon resume "Q1: yes Q2: entertainment-led Q3: 13+"
                        → state_updates applied, run continues

Safety net (if SAGE forgets escalation_question):
        ─── why_fail_count ≥ 2 AND no staging progress ──→ force block → same flow above
```

---

## New / Modified files

| File | Change |
|---|---|
| `extension/workflow/phases/phase1-why1.md` | Add user-gated CRITICAL distinction + `escalation_question` in state_updates |
| `extension/workflow/phases/phase1-why2.md` | Same addition |
| `src/harness/squad.py` | Mode-aware escalation block; `_judgment_dispatch_escalation()`; consecutive-fail tracking in `_evaluate_transitions`; `_staging_changed_since()` helper |
| `src/harness/squad_state.py` | Add `why_fail_count: 0` to `initialize()` |
| `extension/agents/control/commander.md` | Add §Banzai Escalation Judgment Protocol |

---

## Testing

### Unit tests

- `test_why_fail_count_increments_on_fail` — harness increments `why_fail_count` after WHY1 FAIL
- `test_why_fail_count_resets_on_pass` — harness resets `why_fail_count` after WHY1 PASS
- `test_consecutive_fail_forces_escalation` — `why_fail_count ≥ 2` + no staging change → `escalation_question` set
- `test_staging_changed_since_true` — new staging file after ts → returns True
- `test_staging_changed_since_false` — no new files → returns False

### Integration tests

- `test_banzai_escalation_dispatches_commander` — mock WHY1 returns FAIL with `escalation_question`; banzai mode → `_judgment_dispatch_escalation` called, not stopped
- `test_semi_escalation_stops_run` — same WHY1 result; semi mode → `SquadResult.status == "blocked"`, not dispatched
- `test_consecutive_fail_safety_net` — two WHY1 FAILs with no staging change → run blocked, not infinite loop

### Structural validation

`test-unit-squad-registry.sh`: add check that `phase1-why1.md` and `phase1-why2.md` both contain the word `escalation_question` (verifies the signal is present in the spec).

---

## Out of scope

- Changing `definition.yaml` transitions — not needed; the existing `quality_gates.fail AND iteration < max_iterations` condition is correct once the escalation signal is in state
- Changing how `echelon resume` works — the existing resume path is unchanged for semi/guided
- Multi-question structured UI — COMMANDER writes plain markdown; a richer UI can come later
