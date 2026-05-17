# Re-* Workflow Externalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor all 12 re-* brownfield commands from fat imperative scripts into thin wrappers backed by workflow/definition.yaml phase nodes, dedicated agent files, and a proper `re/state.json` state machine — making them fully conformant with echelon's architecture.

**Architecture:** 3 orchestrator commands + 9 standalone commands → all ~50-line wrappers. 13 new phase files in `workflow/phases/`. 9 new agent files in `agents/re/`. 3 new sections in `workflow/definition.yaml`. A new `src/kernel/re_state.py` module for state management, tested with pytest. All 12 existing fat commands replaced. GOLDDIGGER unchanged.

**Tech Stack:** Python 3 (kernel module), YAML (definition.yaml, extension.yml), Markdown (phase files, agent files, command wrappers), Bash (preflight checks in phase files), pytest (kernel tests)

**Design spec:** `docs/superpowers/specs/2026-05-17-re-workflow-externalization-design.md`

---

## File Map

**New files:**

| Path | Purpose |
|---|---|
| `src/kernel/re_state.py` | Pure functions for `.specify/echelon/re/state.json` management |
| `tests/kernel/test_re_state.py` | pytest tests for re_state.py |
| `extension/workflow/phases/re-extract-0-preflight.md` | Preflight checks + state.json init |
| `extension/workflow/phases/re-extract-1-analyze.md` | Dispatch spec for RE-ANALYZER |
| `extension/workflow/phases/re-extract-2-specify.md` | Dispatch spec for RE-SPECIFIER |
| `extension/workflow/phases/re-extract-3-verify.md` | Dispatch spec for RE-VERIFIER |
| `extension/workflow/phases/re-extract-4-expand.md` | Dispatch spec for RE-EXPANDER |
| `extension/workflow/phases/re-extract-5-validate.md` | Dispatch spec for RE-VALIDATOR |
| `extension/workflow/phases/re-extract-6-checklist.md` | Dispatch spec for RE-CHECKLISTER |
| `extension/workflow/phases/re-extract-7-constitute.md` | Dispatch spec for RE-CONSTITUTER |
| `extension/workflow/phases/re-retarget-0-preflight.md` | Checks: analysis.json + stubs exist |
| `extension/workflow/phases/re-retarget-1-input.md` | Interactive Q&A instructions |
| `extension/workflow/phases/re-planning-0-preflight.md` | Checks: constitution.md, no [REQUIRES INPUT] |
| `extension/workflow/phases/re-planning-1-plan.md` | Dispatch spec for RE-PLANNER |
| `extension/workflow/phases/re-planning-2-tasks.md` | Dispatch spec for RE-TASKER |
| `extension/agents/re/analyzer.md` | RE-ANALYZER agent prompt |
| `extension/agents/re/specifier.md` | RE-SPECIFIER agent prompt |
| `extension/agents/re/verifier.md` | RE-VERIFIER agent prompt |
| `extension/agents/re/expander.md` | RE-EXPANDER agent prompt |
| `extension/agents/re/validator.md` | RE-VALIDATOR agent prompt |
| `extension/agents/re/checklister.md` | RE-CHECKLISTER agent prompt |
| `extension/agents/re/constituter.md` | RE-CONSTITUTER agent prompt |
| `extension/agents/re/planner.md` | RE-PLANNER agent prompt |
| `extension/agents/re/tasker.md` | RE-TASKER agent prompt |

**Modified files:**

| Path | Change |
|---|---|
| `extension/workflow/definition.yaml` | Add `re_extraction:`, `re_retarget:`, `re_planning:` sections |
| `extension/extension.yml` | Remove `behavior:` from 12 re-* commands; add 9 new agent entries |
| `extension/commands/echelon.re-extract.md` | Replace with ~50-line orchestrator wrapper |
| `extension/commands/echelon.re-retarget.md` | Replace with ~50-line orchestrator wrapper |
| `extension/commands/echelon.re-plan-all.md` | Replace with ~50-line orchestrator wrapper |
| `extension/commands/echelon.re-analyze.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-specify.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-verify.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-expand.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-validate.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-checklist.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-constitute.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-plan.md` | Replace with ~50-line single-phase wrapper |
| `extension/commands/echelon.re-tasks.md` | Replace with ~50-line single-phase wrapper |
| `tests/unit/test-unit-registry-sync.sh` | Add 4 new re-* structure assertions |

---

## Task 1: `src/kernel/re_state.py` — state machine module (TDD)

**Files:**
- Create: `src/kernel/re_state.py`
- Create: `tests/kernel/test_re_state.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/kernel/test_re_state.py`:

```python
"""T052: Unit tests — re-* state machine protocol (re_state.py)."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from kernel.re_state import (
    complete_dispatch,
    get_current_phase,
    init_re_state,
    should_redispatch,
    write_last_dispatch,
)


def _base_state():
    return init_re_state()


class TestInitReState:
    def test_returns_dict_with_required_keys(self):
        s = init_re_state()
        for key in ["run_id", "status", "phase", "last_dispatch",
                    "mode", "output_dir", "domains",
                    "coverage_pct", "coverage_threshold",
                    "verify_expand_iterations",
                    "resolution_pct", "resolution_threshold",
                    "validate_iterations", "max_validate_iterations",
                    "artifacts", "issues_log"]:
            assert key in s, f"Missing key: {key}"

    def test_status_is_in_progress(self):
        assert init_re_state()["status"] == "in_progress"

    def test_post_dispatch_complete_false_on_init(self):
        s = init_re_state()
        assert s["last_dispatch"]["post_dispatch_complete"] is False

    def test_custom_thresholds(self):
        s = init_re_state(coverage_threshold=90, resolution_threshold=75, max_validate_iterations=5)
        assert s["coverage_threshold"] == 90
        assert s["resolution_threshold"] == 75
        assert s["max_validate_iterations"] == 5

    def test_default_thresholds(self):
        s = init_re_state()
        assert s["coverage_threshold"] == 80
        assert s["resolution_threshold"] == 80
        assert s["max_validate_iterations"] == 3


class TestWriteLastDispatch:
    def test_sets_phase_id_and_agent(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        assert s2["last_dispatch"]["phase_id"] == "re-extract-2-specify"
        assert s2["last_dispatch"]["agent"] == "speckit-echelon-re-specifier"

    def test_sets_post_dispatch_complete_false(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-1-analyze", "speckit-echelon-re-analyzer")
        assert s2["last_dispatch"]["post_dispatch_complete"] is False

    def test_updates_phase_field(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-3-verify", "speckit-echelon-re-verifier")
        assert s2["phase"] == "re-extract-3-verify"

    def test_dispatched_at_is_iso8601(self):
        s = _base_state()
        s2 = write_last_dispatch(s, "re-extract-1-analyze", "speckit-echelon-re-analyzer")
        # Should parse without error
        datetime.fromisoformat(s2["last_dispatch"]["dispatched_at"].replace("Z", "+00:00"))

    def test_does_not_mutate_input(self):
        s = _base_state()
        original_phase = s["phase"]
        write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        assert s["phase"] == original_phase


class TestCompleteDispatch:
    def _dispatched_state(self):
        s = _base_state()
        return write_last_dispatch(s, "re-extract-3-verify", "speckit-echelon-re-verifier")

    def test_sets_post_dispatch_complete_true(self):
        s = self._dispatched_state()
        result = {"verdict": "DONE", "phase_id": "re-extract-3-verify", "state_updates": {}}
        s2 = complete_dispatch(s, result)
        assert s2["last_dispatch"]["post_dispatch_complete"] is True

    def test_applies_coverage_pct_update(self):
        s = self._dispatched_state()
        result = {"verdict": "DONE", "phase_id": "re-extract-3-verify",
                  "state_updates": {"coverage_pct": 72}}
        s2 = complete_dispatch(s, result)
        assert s2["coverage_pct"] == 72

    def test_applies_domains_update(self):
        s = self._dispatched_state()
        result = {"verdict": "DONE", "phase_id": "re-extract-1-analyze",
                  "state_updates": {"domains": ["auth", "api"]}}
        s2 = complete_dispatch(s, result)
        assert s2["domains"] == ["auth", "api"]

    def test_applies_validate_iterations_update(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-5-validate", "speckit-echelon-re-validator")
        result = {"verdict": "DONE", "phase_id": "re-extract-5-validate",
                  "state_updates": {"resolution_pct": 85, "validate_iterations": 1}}
        s2 = complete_dispatch(s, result)
        assert s2["resolution_pct"] == 85
        assert s2["validate_iterations"] == 1

    def test_does_not_mutate_input(self):
        s = self._dispatched_state()
        original = s["last_dispatch"]["post_dispatch_complete"]
        complete_dispatch(s, {"verdict": "DONE", "phase_id": "x", "state_updates": {}})
        assert s["last_dispatch"]["post_dispatch_complete"] == original


class TestShouldRedispatch:
    def test_true_when_post_dispatch_complete_false(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        assert should_redispatch(s) is True

    def test_false_when_post_dispatch_complete_true(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-2-specify", "speckit-echelon-re-specifier")
        s = complete_dispatch(s, {"verdict": "DONE", "phase_id": "re-extract-2-specify",
                                  "state_updates": {}})
        assert should_redispatch(s) is False

    def test_false_on_fresh_state(self):
        # Fresh state has no incomplete dispatch
        s = init_re_state()
        assert should_redispatch(s) is False


class TestGetCurrentPhase:
    def test_returns_phase_field(self):
        s = _base_state()
        s = write_last_dispatch(s, "re-extract-3-verify", "speckit-echelon-re-verifier")
        assert get_current_phase(s) == "re-extract-3-verify"

    def test_returns_none_on_empty_state(self):
        assert get_current_phase({}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/michalbachorik/work/echelon_r/echelon
python3 -m pytest tests/kernel/test_re_state.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'kernel.re_state'`

- [ ] **Step 3: Implement `src/kernel/re_state.py`**

Create `src/kernel/re_state.py`:

```python
"""re_state.py — Pure functions for .specify/echelon/re/state.json management.

Mirrors the squad state machine protocol (last_dispatch sentinel) for the
re-* brownfield extraction sub-system.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any


def init_re_state(
    output_dir: str = ".specify/echelon/re",
    mode: str = "single",
    coverage_threshold: int = 80,
    resolution_threshold: int = 80,
    max_validate_iterations: int = 3,
) -> dict:
    """Return a fresh re/state.json dict."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "run_id": f"re-{ts}",
        "status": "in_progress",
        "phase": "re-extract-0-preflight",
        "last_dispatch": {
            "phase_id": None,
            "agent": None,
            "post_dispatch_complete": False,
            "dispatched_at": None,
        },
        "mode": mode,
        "output_dir": output_dir,
        "domains": [],
        "coverage_pct": 0,
        "coverage_threshold": coverage_threshold,
        "verify_expand_iterations": 0,
        "resolution_pct": 0,
        "resolution_threshold": resolution_threshold,
        "validate_iterations": 0,
        "max_validate_iterations": max_validate_iterations,
        "artifacts": {
            "analysis_json": f"{output_dir}/analysis.json",
            "repos_manifest": f"{output_dir}/repos-manifest.json",
            "cross_repo": None,
        },
        "issues_log": [],
    }


def write_last_dispatch(state: dict, phase_id: str, agent: str) -> dict:
    """Return a copy of state with the pre-dispatch sentinel written.

    Must be called before every agent dispatch. Sets post_dispatch_complete=False
    so that context-compaction recovery can detect incomplete dispatches.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = copy.deepcopy(state)
    s["phase"] = phase_id
    s["last_dispatch"] = {
        "phase_id": phase_id,
        "agent": agent,
        "post_dispatch_complete": False,
        "dispatched_at": ts,
    }
    return s


def complete_dispatch(state: dict, echelon_result: dict) -> dict:
    """Return a copy of state with post_dispatch_complete=True and state_updates applied.

    Call after reading the agent's echelon_result: block.
    """
    s = copy.deepcopy(state)
    s["last_dispatch"]["post_dispatch_complete"] = True
    for key, value in echelon_result.get("state_updates", {}).items():
        s[key] = value
    return s


def should_redispatch(state: dict) -> bool:
    """Return True if the last dispatch did not complete (compaction-safe resumption guard)."""
    ld = state.get("last_dispatch", {})
    if ld.get("phase_id") is None:
        return False
    return not ld.get("post_dispatch_complete", True)


def get_current_phase(state: dict) -> str | None:
    """Return the current phase id from state, or None if not set."""
    return state.get("phase") or None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/kernel/test_re_state.py -v
```

Expected: All 22 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/kernel/re_state.py tests/kernel/test_re_state.py
git commit -m "feat: add re_state kernel module with state machine protocol (TDD)"
```

---

## Task 2: YAML validation assertions (write failing tests first)

**Files:**
- Modify: `tests/unit/test-unit-registry-sync.sh`

- [ ] **Step 1: Read the current test to understand the pattern**

```bash
cat tests/unit/test-unit-registry-sync.sh
```

- [ ] **Step 2: Add 4 failing assertions at the end of the test script**

Append before the final `echo "Results..."` line:

```bash
# ── Re-* workflow externalization assertions ─────────────────────────────────

# 1. All 13 re-* phase nodes registered in definition.yaml
RE_PHASE_COUNT=$(python3 -c "
import yaml, sys
d = yaml.safe_load(open('extension/workflow/definition.yaml'))
phases = (
    [p['id'] for p in d.get('re_extraction', {}).get('phases', [])] +
    [p['id'] for p in d.get('re_retarget', {}).get('phases', [])] +
    [p['id'] for p in d.get('re_planning', {}).get('phases', [])]
)
print(len(phases))
" 2>/dev/null || echo "0")
assert_eq "$RE_PHASE_COUNT" "13" "re-* phase nodes in definition.yaml"

# 2. All type:agent phases in re-* sections reference an existing agents/re/ file
RE_AGENT_FILE_CHECK=$(python3 -c "
import yaml, os, sys
d = yaml.safe_load(open('extension/workflow/definition.yaml'))
missing = []
for section in ['re_extraction', 're_planning']:
    for phase in d.get(section, {}).get('phases', []):
        if phase.get('type') == 'agent':
            name = phase['agent'].split('-re-')[1] if '-re-' in phase['agent'] else None
            if name:
                f = f'extension/agents/re/{name}.md'
                if not os.path.exists(f):
                    missing.append(f)
print(len(missing))
" 2>/dev/null || echo "999")
assert_eq "$RE_AGENT_FILE_CHECK" "0" "all re-* agent phases have agent files"

# 3. 9 new re-* agent entries in extension.yml
RE_AGENT_ENTRY_COUNT=$(python3 -c "
import yaml
d = yaml.safe_load(open('extension/extension.yml'))
agents = [c for c in d['provides']['commands']
          if 're-' in c['name'] and c.get('behavior', {}).get('execution') == 'agent']
print(len(agents))
" 2>/dev/null || echo "0")
assert_eq "$RE_AGENT_ENTRY_COUNT" "9" "re-* agent entries in extension.yml"

# 4. All 12 re-* command entries have no behavior block
RE_NEUTRAL_CMD_COUNT=$(python3 -c "
import yaml
d = yaml.safe_load(open('extension/extension.yml'))
neutral = [c for c in d['provides']['commands']
           if 're-' in c['name']
           and c.get('behavior', {}).get('execution') != 'agent'
           and 'behavior' not in c]
print(len(neutral))
" 2>/dev/null || echo "0")
assert_eq "$RE_NEUTRAL_CMD_COUNT" "12" "all 12 re-* commands have no behavior block"
```

- [ ] **Step 3: Run to confirm all 4 assertions fail**

```bash
bash tests/unit/test-unit-registry-sync.sh 2>&1 | grep -E "PASS|FAIL|re-\*"
```

Expected: 4 FAILs for the new assertions, existing assertions still PASS.

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/unit/test-unit-registry-sync.sh
git commit -m "test: add failing re-* structure assertions to registry-sync test"
```

---

## Task 3: `workflow/definition.yaml` — `re_extraction:` section

**Files:**
- Modify: `extension/workflow/definition.yaml`

- [ ] **Step 1: Find the end of the file to determine insertion point**

```bash
tail -20 extension/workflow/definition.yaml
```

- [ ] **Step 2: Append `re_extraction:` section**

Append to end of `extension/workflow/definition.yaml`:

```yaml
# =============================================================================
# RE-EXTRACTION — read by speckit.echelon.re-extract COMMANDER
# COMMANDER contract: read this section at init, read state_file for current
# phase, execute each phase node, write results to state_file.
# =============================================================================
re_extraction:

  state_file: .specify/echelon/re/state.json

  phases:

    - id: re-extract-0-preflight
      label: "Brownfield Extraction Preflight"
      spec_file: workflow/phases/re-extract-0-preflight.md
      type: commander_internal
      transitions:
        - to: re-extract-1-analyze
          condition: always

    - id: re-extract-1-analyze
      label: "Codebase Analysis (RE-ANALYZER)"
      spec_file: workflow/phases/re-extract-1-analyze.md
      type: agent
      agent: speckit-echelon-re-analyzer
      tier: re_extraction
      context_pack:
        - .specify/echelon/re/state.json
        - echelon-config.yml (re: section)
      outputs:
        - .specify/echelon/re/analysis.json
        - .specify/echelon/re/repos-manifest.json   # polyrepo only
        - .specify/echelon/re/cross-repo.json        # polyrepo only
      transitions:
        - to: re-extract-2-specify
          condition: verdict = DONE

    - id: re-extract-2-specify
      label: "Domain Specification (RE-SPECIFIER)"
      spec_file: workflow/phases/re-extract-2-specify.md
      type: agent
      agent: speckit-echelon-re-specifier
      tier: re_extraction
      context_pack:
        - .specify/echelon/re/analysis.json
        - .specify/echelon/re/state.json
        - .specify/echelon/re/repos-manifest.json    # if exists
      outputs:
        - specs/000-re-overview/overview.md
        - specs/NNN-re-{domain}/spec.md               # one per domain
      transitions:
        - to: re-extract-3-verify
          condition: verdict = DONE

    - id: re-extract-3-verify
      label: "Coverage Verification (RE-VERIFIER)"
      spec_file: workflow/phases/re-extract-3-verify.md
      type: agent
      agent: speckit-echelon-re-verifier
      tier: re_extraction
      context_pack:
        - specs/NNN-re-*/spec.md
        - .specify/echelon/re/analysis.json
        - .specify/echelon/re/state.json
      outputs:
        - specs/000-re-overview/coverage-report.md
        - state.json[coverage_pct, verify_expand_iterations]
      transitions:
        - to: re-extract-4-expand
          condition: "coverage_pct < coverage_threshold"
        - to: re-extract-5-validate
          condition: "coverage_pct >= coverage_threshold"

    - id: re-extract-4-expand
      label: "Coverage Expansion (RE-EXPANDER)"
      spec_file: workflow/phases/re-extract-4-expand.md
      type: agent
      agent: speckit-echelon-re-expander
      tier: re_extraction
      context_pack:
        - specs/000-re-overview/coverage-report.md
        - .specify/echelon/re/analysis.json
        - .specify/echelon/re/state.json
      outputs:
        - specs/NNN-re-{domain}/spec.md    # new or expanded domains
        - state.json[verify_expand_iterations]
      transitions:
        - to: re-extract-3-verify
          condition: always                  # loop back until coverage met

    - id: re-extract-5-validate
      label: "Quality Validation (RE-VALIDATOR)"
      spec_file: workflow/phases/re-extract-5-validate.md
      type: agent
      agent: speckit-echelon-re-validator
      tier: re_extraction
      context_pack:
        - specs/NNN-re-*/spec.md
        - .specify/echelon/re/analysis.json
        - .specify/echelon/re/state.json
      outputs:
        - specs/000-re-overview/validation-report.md
        - state.json[resolution_pct, validate_iterations]
      transitions:
        - to: re-extract-5-validate
          condition: "resolution_pct < resolution_threshold AND validate_iterations < max_validate_iterations"
        - to: re-extract-6-checklist
          condition: "resolution_pct >= resolution_threshold OR validate_iterations >= max_validate_iterations"

    - id: re-extract-6-checklist
      label: "Quality Checklists (RE-CHECKLISTER)"
      spec_file: workflow/phases/re-extract-6-checklist.md
      type: agent
      agent: speckit-echelon-re-checklister
      tier: re_extraction
      context_pack:
        - specs/NNN-re-*/spec.md
        - specs/000-re-overview/coverage-report.md
        - specs/000-re-overview/validation-report.md
      outputs:
        - specs/NNN-re-{domain}/checklist.md
        - specs/000-re-overview/checklist.md
      transitions:
        - to: re-extract-7-constitute
          condition: always

    - id: re-extract-7-constitute
      label: "Strategic Artifacts (RE-CONSTITUTER)"
      spec_file: workflow/phases/re-extract-7-constitute.md
      type: agent
      agent: speckit-echelon-re-constituter
      tier: re_extraction
      context_pack:
        - specs/NNN-re-*/spec.md
        - specs/000-re-overview/checklist.md
        - .specify/echelon/re/analysis.json
        - .specify/echelon/re/state.json
      outputs:
        - constitution.md
        - migration-strategy.md
        - risk-matrix.md
        - gap-analysis.md
        - adrs/ADR-*.md
      transitions:
        - to: DONE
          condition: always
```

- [ ] **Step 3: Validate YAML**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('extension/workflow/definition.yaml'))
phases = [p['id'] for p in d['re_extraction']['phases']]
assert len(phases) == 8, f'Expected 8, got {len(phases)}: {phases}'
print('re_extraction phases:', phases)
"
```

Expected: 8 phase ids printed, no errors.

- [ ] **Step 4: Commit**

```bash
git add extension/workflow/definition.yaml
git commit -m "feat: add re_extraction phase graph to workflow/definition.yaml"
```

---

## Task 4: `workflow/definition.yaml` — `re_retarget:` and `re_planning:` sections

**Files:**
- Modify: `extension/workflow/definition.yaml`

- [ ] **Step 1: Append `re_retarget:` and `re_planning:` sections**

Append to end of `extension/workflow/definition.yaml`:

```yaml
# =============================================================================
# RE-RETARGET — read by speckit.echelon.re-retarget COMMANDER
# =============================================================================
re_retarget:

  state_file: .specify/echelon/re/state.json

  phases:

    - id: re-retarget-0-preflight
      label: "Retarget Preflight"
      spec_file: workflow/phases/re-retarget-0-preflight.md
      type: commander_internal
      transitions:
        - to: re-retarget-1-input
          condition: always

    - id: re-retarget-1-input
      label: "Human Decision Input"
      spec_file: workflow/phases/re-retarget-1-input.md
      type: commander_internal    # interactive — COMMANDER prompts user directly, no agent dispatch
      transitions:
        - to: DONE
          condition: always

# =============================================================================
# RE-PLANNING — read by speckit.echelon.re-plan-all COMMANDER
# =============================================================================
re_planning:

  state_file: .specify/echelon/re/state.json

  phases:

    - id: re-planning-0-preflight
      label: "Planning Preflight"
      spec_file: workflow/phases/re-planning-0-preflight.md
      type: commander_internal
      transitions:
        - to: re-planning-1-plan
          condition: always

    - id: re-planning-1-plan
      label: "Per-Domain Plans (RE-PLANNER)"
      spec_file: workflow/phases/re-planning-1-plan.md
      type: agent
      agent: speckit-echelon-re-planner
      tier: re_planning
      context_pack:
        - specs/NNN-re-{domain}/spec.md
        - constitution.md
        - migration-strategy.md
        - .specify/echelon/re/state.json
      outputs:
        - specs/NNN-re-{domain}/plan.md
      transitions:
        - to: re-planning-2-tasks
          condition: verdict = DONE

    - id: re-planning-2-tasks
      label: "Per-Domain Tasks (RE-TASKER)"
      spec_file: workflow/phases/re-planning-2-tasks.md
      type: agent
      agent: speckit-echelon-re-tasker
      tier: re_planning
      context_pack:
        - specs/NNN-re-{domain}/plan.md
        - specs/NNN-re-{domain}/spec.md
        - constitution.md
      outputs:
        - specs/NNN-re-{domain}/tasks.md
      transitions:
        - to: DONE
          condition: always
```

- [ ] **Step 2: Validate YAML and total phase count**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('extension/workflow/definition.yaml'))
all_phases = (
    [p['id'] for p in d['re_extraction']['phases']] +
    [p['id'] for p in d['re_retarget']['phases']] +
    [p['id'] for p in d['re_planning']['phases']]
)
assert len(all_phases) == 13, f'Expected 13, got {len(all_phases)}: {all_phases}'
print('Total re-* phases:', len(all_phases))
print(all_phases)
"
```

Expected: 13 phase ids, no errors.

- [ ] **Step 3: Commit**

```bash
git add extension/workflow/definition.yaml
git commit -m "feat: add re_retarget and re_planning phase graphs to workflow/definition.yaml"
```

---

## Task 5: Phase files — `re-extract-0-preflight` through `re-extract-2-specify`

**Files:**
- Create: `extension/workflow/phases/re-extract-0-preflight.md`
- Create: `extension/workflow/phases/re-extract-1-analyze.md`
- Create: `extension/workflow/phases/re-extract-2-specify.md`

- [ ] **Step 1: Create `re-extract-0-preflight.md`**

Create `extension/workflow/phases/re-extract-0-preflight.md`:

```markdown
# Phase: re-extract-0-preflight
# Read by: speckit-echelon-commander (COMMANDER) — brownfield extraction preflight
# Type: commander_internal — COMMANDER executes these steps directly, no agent dispatch

**Execution Continuity:** After each step, immediately proceed to the next without pausing.

## Preflight checks — ANY failure is a HARD STOP

### 1. jq availability

```bash
command -v jq
```

If exit code non-zero: report error "jq is required for brownfield extraction. Install via: `brew install jq` (macOS) or `apt-get install jq` (Linux)". HARD STOP.

### 2. Output directory

```bash
mkdir -p .specify/echelon/re
```

### 3. Codebase non-empty

Use Glob tool to count source files matching `**/*.{ts,js,py,go,rs,java,kt,cs,rb,cpp,c,swift}`.
If count < 5: warn "Fewer than 5 source files found — analysis may be sparse" but continue.

### 4. Read thresholds from echelon-config.yml

```bash
COVERAGE_THRESHOLD=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.coverage_threshold 2>/dev/null || echo "80")
RESOLUTION_THRESHOLD=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.resolution_threshold 2>/dev/null || echo "80")
MAX_VALIDATE=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.workflow.max_validate_iterations 2>/dev/null || echo "3")
OUTPUT_DIR=$(bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.output.directory 2>/dev/null || echo ".specify/echelon/re")
```

### 5. Initialize `.specify/echelon/re/state.json`

If the file does not exist, create it using `src/kernel/re_state.py::init_re_state` logic:

```python
import json, sys, os
from pathlib import Path
state_path = Path('.specify/echelon/re/state.json')
if not state_path.exists():
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    state = {
        'run_id': f're-{ts}', 'status': 'in_progress',
        'phase': 're-extract-0-preflight',
        'last_dispatch': {'phase_id': None, 'agent': None, 'post_dispatch_complete': False, 'dispatched_at': None},
        'mode': 'single', 'output_dir': os.environ.get('OUTPUT_DIR', '.specify/echelon/re'),
        'domains': [], 'coverage_pct': 0,
        'coverage_threshold': int(os.environ.get('COVERAGE_THRESHOLD', 80)),
        'verify_expand_iterations': 0, 'resolution_pct': 0,
        'resolution_threshold': int(os.environ.get('RESOLUTION_THRESHOLD', 80)),
        'validate_iterations': 0,
        'max_validate_iterations': int(os.environ.get('MAX_VALIDATE', 3)),
        'artifacts': {'analysis_json': '.specify/echelon/re/analysis.json',
                      'repos_manifest': '.specify/echelon/re/repos-manifest.json', 'cross_repo': None},
        'issues_log': []
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)
    sys.stdout.write('Initialized re/state.json\n')
else:
    sys.stdout.write('Re-using existing re/state.json (resumption mode)\n')
```

Preflight complete. Advance to `re-extract-1-analyze`.
```

- [ ] **Step 2: Create `re-extract-1-analyze.md`**

Create `extension/workflow/phases/re-extract-1-analyze.md`:

```markdown
# Phase: re-extract-1-analyze
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-ANALYZER
# Agent: speckit-echelon-re-analyzer

## Context Pack

Provide RE-ANALYZER with:
- `.specify/echelon/re/state.json` — current run state (output_dir, mode)
- `echelon-config.yml` `re:` section — analysis scope, extensions, depth settings

## Dispatch Prompt

Instruct RE-ANALYZER to:
1. Run `discover-repos.sh` to detect single vs. polyrepo workspace
2. Resolve echelon `re:` config and export `ECHELON_CFG_RE_*` env vars
3. Run `run-analysis.sh` to produce `analysis.json` (and per-repo files if polyrepo)
4. Summarize outputs and return `echelon_result:`

## Expected Outputs

| File | Required |
|---|---|
| `.specify/echelon/re/analysis.json` | Yes |
| `.specify/echelon/re/repos-manifest.json` | Yes |
| `.specify/echelon/re/cross-repo.json` | Polyrepo only |
| `.specify/echelon/re/codegraph-analysis.json` | Optional (Node.js) |

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-1-analyze
  state_updates:
    mode: single | polyrepo     # discovered by discover-repos.sh
    domains: []                 # empty at this stage, populated by re-specifier
    artifacts:
      analysis_json: .specify/echelon/re/analysis.json
      repos_manifest: .specify/echelon/re/repos-manifest.json
      cross_repo: .specify/echelon/re/cross-repo.json   # null if single
  output_files:
    - .specify/echelon/re/analysis.json
  journal_entries:
    - type: phase_complete
      phase: re-extract-1-analyze
      summary: "Analyzed {N} files across {M} repo(s)"
  blocked_reason: null
```
```

- [ ] **Step 3: Create `re-extract-2-specify.md`**

Create `extension/workflow/phases/re-extract-2-specify.md`:

```markdown
# Phase: re-extract-2-specify
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-SPECIFIER
# Agent: speckit-echelon-re-specifier

## Context Pack

Provide RE-SPECIFIER with:
- `.specify/echelon/re/analysis.json` — extracted codebase data
- `.specify/echelon/re/repos-manifest.json` — polyrepo structure (if exists)
- `.specify/echelon/re/state.json` — run state (output_dir, domains)

## Dispatch Prompt

Instruct RE-SPECIFIER to:
1. Read `analysis.json` and identify functional domains
2. Determine starting spec number (highest existing NNN + 1)
3. Generate `specs/000-re-overview/overview.md` — migration summary
4. Generate one `specs/NNN-re-{domain}/spec.md` per domain
5. Write discovered domain list to `echelon_result: state_updates: domains`

## Expected Outputs

| File | Required |
|---|---|
| `specs/000-re-overview/overview.md` | Yes |
| `specs/NNN-re-{domain}/spec.md` | Yes, one per domain |

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-2-specify
  state_updates:
    domains: [auth, api, data-layer]    # list of domain names identified
  output_files:
    - specs/000-re-overview/overview.md
    - specs/001-re-auth/spec.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-2-specify
      summary: "Generated {N} domain specs"
  blocked_reason: null
```
```

- [ ] **Step 4: Verify files exist and are valid markdown**

```bash
ls extension/workflow/phases/re-extract-{0,1,2}-*.md
wc -l extension/workflow/phases/re-extract-{0,1,2}-*.md
```

- [ ] **Step 5: Commit**

```bash
git add extension/workflow/phases/re-extract-0-preflight.md \
        extension/workflow/phases/re-extract-1-analyze.md \
        extension/workflow/phases/re-extract-2-specify.md
git commit -m "feat: add re-extract-0 through re-extract-2 phase files"
```

---

## Task 6: Phase files — `re-extract-3-verify` through `re-extract-7-constitute`

**Files:**
- Create: `extension/workflow/phases/re-extract-3-verify.md`
- Create: `extension/workflow/phases/re-extract-4-expand.md`
- Create: `extension/workflow/phases/re-extract-5-validate.md`
- Create: `extension/workflow/phases/re-extract-6-checklist.md`
- Create: `extension/workflow/phases/re-extract-7-constitute.md`

Each file follows the same 4-section format established in Task 5 (Context Pack / Dispatch Prompt / Expected Outputs / echelon_result schema). Content for each:

- [ ] **Step 1: Create `re-extract-3-verify.md`**

```markdown
# Phase: re-extract-3-verify
# Agent: speckit-echelon-re-verifier

## Context Pack
- `specs/NNN-re-*/spec.md` — all current domain specs
- `.specify/echelon/re/analysis.json` — full file list for coverage computation
- `.specify/echelon/re/state.json` — current coverage_pct, verify_expand_iterations

## Dispatch Prompt
Instruct RE-VERIFIER to: compute coverage % (source files covered by specs / total source files), identify orphan files (not covered by any spec), cluster orphans by similarity, write `coverage-report.md`, update `coverage_pct` and increment `verify_expand_iterations` in echelon_result.

## Expected Outputs
- `specs/000-re-overview/coverage-report.md`

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-3-verify
  state_updates:
    coverage_pct: 72
    verify_expand_iterations: 2
  output_files:
    - specs/000-re-overview/coverage-report.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-3-verify
      summary: "Coverage: {coverage_pct}% ({orphan_count} orphan files)"
  blocked_reason: null
```
```

- [ ] **Step 2: Create `re-extract-4-expand.md`**

```markdown
# Phase: re-extract-4-expand
# Agent: speckit-echelon-re-expander

## Context Pack
- `specs/000-re-overview/coverage-report.md` — orphan file clusters
- `.specify/echelon/re/analysis.json` — file metadata for orphan files
- `.specify/echelon/re/state.json` — domain list, output_dir

## Dispatch Prompt
Instruct RE-EXPANDER to: read orphan clusters from coverage-report.md, create or expand domain specs to cover high-confidence clusters (≥3 related files), preserve existing spec content, write new/updated spec.md files.

## Expected Outputs
- `specs/NNN-re-{domain}/spec.md` — new or expanded domains

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-4-expand
  state_updates:
    domains: [auth, api, data-layer, utils]   # updated with any new domains
  output_files:
    - specs/004-re-utils/spec.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-4-expand
      summary: "Added {N} new domain(s), expanded {M} existing"
  blocked_reason: null
```
```

- [ ] **Step 3: Create `re-extract-5-validate.md`**

```markdown
# Phase: re-extract-5-validate
# Agent: speckit-echelon-re-validator

## Context Pack
- `specs/NNN-re-*/spec.md` — all domain specs
- `.specify/echelon/re/analysis.json` — source code for ambiguity resolution
- `.specify/echelon/re/state.json` — resolution_pct, validate_iterations, max_validate_iterations

## Dispatch Prompt
Instruct RE-VALIDATOR to: apply quality checks (Basic strategy first, then Deep if resolution_pct < threshold and iterations < max, then Extended), auto-resolve ambiguities by reading source code, write validation-report.md with per-domain resolution scores, update resolution_pct and increment validate_iterations.

## Expected Outputs
- `specs/000-re-overview/validation-report.md`

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-5-validate
  state_updates:
    resolution_pct: 85
    validate_iterations: 1
  output_files:
    - specs/000-re-overview/validation-report.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-5-validate
      summary: "Resolution: {resolution_pct}% (iteration {validate_iterations})"
  blocked_reason: null
```
```

- [ ] **Step 4: Create `re-extract-6-checklist.md`**

```markdown
# Phase: re-extract-6-checklist
# Agent: speckit-echelon-re-checklister

## Context Pack
- `specs/NNN-re-*/spec.md` — all domain specs
- `specs/000-re-overview/coverage-report.md`
- `specs/000-re-overview/validation-report.md`

## Dispatch Prompt
Instruct RE-CHECKLISTER to: generate per-domain checklists (`NNN-re-{domain}/checklist.md`) with domain-specific quality items, generate summary checklist (`000-re-overview/checklist.md`) covering cross-domain migration concerns.

## Expected Outputs
- `specs/NNN-re-{domain}/checklist.md` — one per domain
- `specs/000-re-overview/checklist.md`

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-6-checklist
  state_updates: {}
  output_files:
    - specs/000-re-overview/checklist.md
    - specs/001-re-auth/checklist.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-6-checklist
      summary: "Generated checklists for {N} domains"
  blocked_reason: null
```
```

- [ ] **Step 5: Create `re-extract-7-constitute.md`**

```markdown
# Phase: re-extract-7-constitute
# Agent: speckit-echelon-re-constituter

## Context Pack
- `specs/NNN-re-*/spec.md`
- `specs/000-re-overview/checklist.md`
- `.specify/echelon/re/analysis.json`
- `.specify/echelon/re/state.json`

## Dispatch Prompt
Instruct RE-CONSTITUTER to: synthesize `constitution.md` (legacy analysis + target stack decisions with [REQUIRES INPUT] for unknowns), `migration-strategy.md` (6R/7R per domain), `risk-matrix.md`, `gap-analysis.md`, ADRs in `adrs/ADR-NNN-*.md`. Use preset templates if installed (check `.specify/presets/`).

## Expected Outputs
- `constitution.md`
- `migration-strategy.md`
- `risk-matrix.md`
- `gap-analysis.md`
- `adrs/ADR-001-*.md` (at minimum one ADR)

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-7-constitute
  state_updates:
    status: done
  output_files:
    - constitution.md
    - migration-strategy.md
    - risk-matrix.md
    - gap-analysis.md
    - adrs/ADR-001-tech-debt-classification.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-7-constitute
      summary: "Strategic artifacts generated. {N} [REQUIRES INPUT] markers need human decisions."
  blocked_reason: null
```
```

- [ ] **Step 6: Commit**

```bash
git add extension/workflow/phases/re-extract-3-verify.md \
        extension/workflow/phases/re-extract-4-expand.md \
        extension/workflow/phases/re-extract-5-validate.md \
        extension/workflow/phases/re-extract-6-checklist.md \
        extension/workflow/phases/re-extract-7-constitute.md
git commit -m "feat: add re-extract-3 through re-extract-7 phase files"
```

---

## Task 7: Phase files — retarget and planning

**Files:**
- Create: `extension/workflow/phases/re-retarget-0-preflight.md`
- Create: `extension/workflow/phases/re-retarget-1-input.md`
- Create: `extension/workflow/phases/re-planning-0-preflight.md`
- Create: `extension/workflow/phases/re-planning-1-plan.md`
- Create: `extension/workflow/phases/re-planning-2-tasks.md`

- [ ] **Step 1: Create `re-retarget-0-preflight.md`**

```markdown
# Phase: re-retarget-0-preflight
# Type: commander_internal

## Preflight checks

### 1. analysis.json exists
Read `.specify/echelon/re/analysis.json` using Read tool. If not found: HARD STOP — "Run /speckit.echelon.re-extract first."

### 2. Strategic stubs exist
Check that `constitution.md` exists (created by re-extract Phase 7). If not found: HARD STOP — "Run /speckit.echelon.re-extract first to generate strategic artifacts."

### 3. Count [REQUIRES INPUT] markers
```bash
grep -r "\[REQUIRES INPUT\]" constitution.md migration-strategy.md risk-matrix.md gap-analysis.md adrs/ 2>/dev/null | wc -l
```
Report count to user: "Found {N} decisions needing human input."

Preflight complete. Advance to `re-retarget-1-input`.
```

- [ ] **Step 2: Create `re-retarget-1-input.md`**

Create `extension/workflow/phases/re-retarget-1-input.md` with this exact content (the Q&A protocol COMMANDER executes directly — no agent dispatch):

```markdown
# Phase: re-retarget-1-input
# Type: commander_internal — COMMANDER prompts the user directly, no agent dispatch
# Source: migrated from extension/commands/echelon.re-retarget.md

> **Bash Command Guidelines**: Never use multi-line bash. Chain commands with `&&`. Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration — use Glob, Read, and Grep tools. Reserve bash only for git commands, `mkdir`, and system operations.

Guided walkthrough to fill in `[REQUIRES INPUT]` sections in strategic artifacts.

## Step 1: Scan for [REQUIRES INPUT] markers

Count markers across all strategic artifacts:

```bash
grep -r "\[REQUIRES INPUT\]" constitution.md migration-strategy.md risk-matrix.md gap-analysis.md adrs/ 2>/dev/null | wc -l
```

Report to user: "Found {count} sections requiring your input."

If count is 0: report "All decisions are already filled in. You can proceed to `/speckit.echelon.re-plan-all`." and stop.

## Step 2: Present introduction

```
========================================
Reverse Engineering: Define Target State
========================================

This will guide you through filling in the [REQUIRES INPUT] sections
in your strategic artifacts.

Files to review:
  - constitution.md       (target technology stack)
  - migration-strategy.md (6R/7R decisions per domain)
  - risk-matrix.md        (risk owners, mitigations)
  - gap-analysis.md       (gap priorities)
  - adrs/*.md             (architecture decisions)

Sections requiring input: {count}

For each section, I will:
  1. Show you the context from the file
  2. Ask for your decision
  3. Update the file with your answer

You can say "skip" to defer any question and return to it later.
```

## Step 3: Constitution — Target Technology Stack

Read `constitution.md`. For each `[REQUIRES INPUT]` found in the Target Technology Stack section, present to user:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTITUTION: Target Technology Stack
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Legacy stack (extracted from codebase):
  {list the actual values found in constitution.md}

Question {N}:
  {Show the exact [REQUIRES INPUT] label from the file}
  
  Examples: {provide relevant examples based on the question type}

  Your choice:
```

Record the user's answer. Update `constitution.md`: replace `[REQUIRES INPUT]` with the user's answer, preserving surrounding markdown structure.

## Step 4: Constitution — Coding Standards

For each `[REQUIRES INPUT]` in the Coding Standards section of `constitution.md`, present in the same format as Step 3. Common questions include test coverage threshold, naming conventions, error handling policy.

## Step 5: Migration Strategy — 6R/7R Decisions

Read `migration-strategy.md`. For each domain with a `[REQUIRES INPUT]` on its migration strategy:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MIGRATION STRATEGY: {domain-name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Extracted recommendation: {recommendation from file}
Rationale: {rationale from file}

Do you agree with this approach, or choose a different 6R/7R strategy?

  1. Rehost       (lift-and-shift)
  2. Replatform   (lift-and-reshape)
  3. Repurchase   (replace with SaaS)
  4. Refactor     (significant changes, preserve structure)
  5. Retire       (decommission)
  6. Retain       (keep as-is)
  7. Rebuild      (rewrite from scratch)

  Your choice:
  Rationale (optional):
```

Update `migration-strategy.md` with the user's choice.

## Step 6: Risk Matrix — Risk Owners and Mitigations

Read `risk-matrix.md`. For each `[REQUIRES INPUT]` on risk owner or mitigation:

Present the risk row with its description, severity, and probability. Ask:
1. Who owns this risk? (person or team name)
2. What is the mitigation plan?

Update `risk-matrix.md` with answers.

## Step 7: Gap Analysis — Gap Priorities

Read `gap-analysis.md`. For each `[REQUIRES INPUT]` on priority or owner:

Present the gap with its description and impact. Ask:
1. Priority: Critical / High / Medium / Low
2. Target date (optional)
3. Owner (optional)

Update `gap-analysis.md` with answers.

## Step 8: ADRs — Architecture Decision Records

Read each `adrs/*.md` file. For each `[REQUIRES INPUT]`:

Present the ADR title, context, and the specific question. Record the user's decision text.

Update the ADR file with the decision.

## Step 9: Completion summary

After processing all questions (or when user says "done"):

```bash
REMAINING=$(grep -r "\[REQUIRES INPUT\]" constitution.md migration-strategy.md risk-matrix.md gap-analysis.md adrs/ 2>/dev/null | wc -l)
```

Report:
```
Retargeting complete.
Remaining [REQUIRES INPUT] markers: {REMAINING}

{if REMAINING == 0}
All decisions filled. Run /speckit.echelon.re-plan-all to generate per-domain plans.

{if REMAINING > 0}
{REMAINING} decisions deferred. You can run /speckit.echelon.re-retarget again
to fill them, or proceed with /speckit.echelon.re-plan-all (planning will work
around the remaining placeholders).
```
```

- [ ] **Step 3: Create `re-planning-0-preflight.md`**

```markdown
# Phase: re-planning-0-preflight
# Type: commander_internal

## Preflight checks

### 1. constitution.md exists
Read `constitution.md` with Read tool. If not found: HARD STOP — "Run /speckit.echelon.re-retarget first to fill target decisions."

### 2. No unresolved [REQUIRES INPUT] markers
```bash
grep -r "\[REQUIRES INPUT\]" constitution.md migration-strategy.md risk-matrix.md gap-analysis.md adrs/ 2>/dev/null | wc -l
```
If count > 0: HARD STOP — "Found {N} unresolved [REQUIRES INPUT] markers. Run /speckit.echelon.re-retarget to fill them before planning."

### 3. Domain specs exist
Use Glob: `specs/NNN-re-*/spec.md`. If no files found: HARD STOP — "No re-* specs found. Run /speckit.echelon.re-extract first."

Preflight complete. Advance to `re-planning-1-plan`.
```

- [ ] **Step 4: Create `re-planning-1-plan.md`**

```markdown
# Phase: re-planning-1-plan
# Agent: speckit-echelon-re-planner

## Context Pack
- `specs/NNN-re-{domain}/spec.md` — domain spec (one per iteration)
- `constitution.md` — non-negotiable coding rules and target decisions
- `migration-strategy.md` — 6R/7R per domain
- `.specify/echelon/re/state.json` — domain list

## Dispatch Prompt
Instruct RE-PLANNER to: iterate over all domains in `state.json.domains`, for each read the domain spec + constitution + migration strategy, generate `specs/NNN-re-{domain}/plan.md` with implementation phases, milestones, dependencies, and effort estimates.

## Expected Outputs
- `specs/NNN-re-{domain}/plan.md` — one per domain

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-planning-1-plan
  state_updates: {}
  output_files:
    - specs/001-re-auth/plan.md
    - specs/002-re-api/plan.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-1-plan
      summary: "Generated plans for {N} domains"
  blocked_reason: null
```
```

- [ ] **Step 5: Create `re-planning-2-tasks.md`**

```markdown
# Phase: re-planning-2-tasks
# Agent: speckit-echelon-re-tasker

## Context Pack
- `specs/NNN-re-{domain}/plan.md`
- `specs/NNN-re-{domain}/spec.md`
- `constitution.md`

## Dispatch Prompt
Instruct RE-TASKER to: iterate over all domains, for each read plan.md + spec.md + constitution, generate `specs/NNN-re-{domain}/tasks.md` with actionable task items (IDs, descriptions, acceptance criteria, dependencies). After all domains complete, optionally offer `speckit.analyze` for consistency analysis.

## Expected Outputs
- `specs/NNN-re-{domain}/tasks.md` — one per domain

## echelon_result schema
```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-planning-2-tasks
  state_updates:
    status: done
  output_files:
    - specs/001-re-auth/tasks.md
    - specs/002-re-api/tasks.md
  journal_entries:
    - type: phase_complete
      phase: re-planning-2-tasks
      summary: "Generated tasks for {N} domains"
  blocked_reason: null
```
```

- [ ] **Step 6: Commit**

```bash
git add extension/workflow/phases/re-retarget-0-preflight.md \
        extension/workflow/phases/re-retarget-1-input.md \
        extension/workflow/phases/re-planning-0-preflight.md \
        extension/workflow/phases/re-planning-1-plan.md \
        extension/workflow/phases/re-planning-2-tasks.md
git commit -m "feat: add re-retarget and re-planning phase files"
```

---

## Task 8: Agent files — `agents/re/` directory and `analyzer.md`

**Files:**
- Create: `extension/agents/re/analyzer.md`

The agent files migrate work instructions from the fat commands. The template for every agent file is:

```
# speckit-echelon-re-{name} (RE-{NAME}) Agent

You are RE-{NAME}. {One-sentence role definition.}

You are dispatched as a subagent by speckit-echelon-commander (COMMANDER). This prompt
is your complete instruction set.

## NEVER rules
{From the fat command's "Enforcement Rules" and "NEVER" blocks}

## Bash Command Guidelines
Never use multi-line bash. Chain commands with `&&`. Do NOT use bash `ls`, `find`,
`cat`, `echo`, or `grep` for file exploration — use Glob, Read, and Grep tools.
Reserve bash only for git commands, `mkdir`, and system operations.

## Configuration
Read config values via:
```bash
bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.{key}
```

## Work Instructions
{From the fat command's "## Steps" section, adapted to agent format}

## echelon_result format
{Paste the schema from the matching phase file}
```

- [ ] **Step 1: Create `extension/agents/re/` directory marker and `analyzer.md`**

```bash
mkdir -p extension/agents/re
```

Create `extension/agents/re/analyzer.md`:

```markdown
# speckit-echelon-re-analyzer (RE-ANALYZER) Agent

You are RE-ANALYZER. You extract structured data from the codebase by running analysis scripts and summarising their output.

You are dispatched as a subagent by speckit-echelon-commander (COMMANDER). This prompt is your complete instruction set.

## NEVER rules

1. **NEVER skip running the analysis scripts.** You must invoke `run-analysis.sh` via Bash and wait for it to return before reporting results. Manual estimation is not a substitute.
2. **NEVER report jq as missing without running the script first.** Attempt the script — only report jq missing if the script returns a non-zero exit code indicating jq is unavailable.
3. **NEVER use `print()` in python3 scripts that read or write JSON files.** Use `sys.stdout.write()` instead to avoid corrupting state.json.

## Bash Command Guidelines

Never use multi-line bash. Chain commands with `&&`. Do NOT use bash `ls`, `find`, `cat`, `echo`, or `grep` for file exploration — use Glob, Read, and Grep tools. Reserve bash only for script execution, `mkdir`, and system operations.

## Configuration

Read config values at point of use:

```bash
eval "$(specify extension config resolve echelon --format env --prefix ECHELON_CFG_RE_)"
```

Or per-key:

```bash
bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh re.sources.git_history_limit
```

## Work Instructions

### Step 1: Check for project markers

Verify you are in a valid project root (presence of `.git`, `package.json`, `pyproject.toml`, `go.mod`, or `Cargo.toml`). If none found: warn but continue.

For polyrepo check: if `repos-manifest.json` exists and `repo_count > 1`, missing root-level `analysis.json` is expected — check per-repo files instead.

### Step 2: Create output directory

```bash
OUTPUT_DIR=".specify/echelon/re" && mkdir -p "$OUTPUT_DIR"
```

### Step 3: Run repo discovery

```bash
"$EXTENSION_PATH/scripts/bash/re/discover-repos.sh" ".specify/echelon/re/repos-manifest.json"
```

Read the resulting `repos-manifest.json`. Report `mode: single` or `mode: polyrepo` to the user.

### Step 4: Run extraction

```bash
eval "$(specify extension config resolve echelon --format env --prefix ECHELON_CFG_RE_)" && "$EXTENSION_PATH/scripts/bash/re/run-analysis.sh" ".specify/echelon/re" ".specify/echelon/re/repos-manifest.json"
```

### Step 5: Summarise outputs

After script returns, verify these files exist using Glob:
- `.specify/echelon/re/analysis.json` — required
- `.specify/echelon/re/repos-manifest.json` — required
- `.specify/echelon/re/cross-repo.json` — only if `repo_count > 1`
- `.specify/echelon/re/codegraph-analysis.json` — optional

If `analysis.json` is missing: verdict = BLOCKED, blocked_reason = "run-analysis.sh did not produce analysis.json".

Read `analysis.json` and report:
- Total files analyzed
- Languages detected (top 5 by file count)
- Repo count and mode
- CodeGraph: total symbols if `codegraph-analysis.json` exists

### Step 6: Emit echelon_result

```yaml
echelon_result:
  verdict: DONE
  phase_id: re-extract-1-analyze
  state_updates:
    mode: single          # or polyrepo
    artifacts:
      analysis_json: .specify/echelon/re/analysis.json
      repos_manifest: .specify/echelon/re/repos-manifest.json
      cross_repo: null    # or path if polyrepo
  output_files:
    - .specify/echelon/re/analysis.json
    - .specify/echelon/re/repos-manifest.json
  journal_entries:
    - type: phase_complete
      phase: re-extract-1-analyze
      summary: "Analyzed {N} files across {M} repo(s)"
  blocked_reason: null
```
```

- [ ] **Step 2: Verify file created**

```bash
wc -l extension/agents/re/analyzer.md
```

Expected: ~100 lines.

- [ ] **Step 3: Commit**

```bash
git add extension/agents/re/analyzer.md
git commit -m "feat: add RE-ANALYZER agent file"
```

---

## Task 9: Agent files — `specifier.md` through `constituter.md`

**Files:**
- Create: `extension/agents/re/specifier.md`
- Create: `extension/agents/re/verifier.md`
- Create: `extension/agents/re/expander.md`
- Create: `extension/agents/re/validator.md`
- Create: `extension/agents/re/checklister.md`
- Create: `extension/agents/re/constituter.md`

Each agent file is created by migrating work instructions from the corresponding fat command. Follow the template from Task 8. For each file:

1. Open the source fat command (e.g., `extension/commands/echelon.re-specify.md`)
2. Extract: Enforcement Rules → NEVER rules; `## Steps` content → Work Instructions section; `## Output` → document in Work Instructions
3. Remove: Prerequisites checks (moved to preflight); cross-references to next command (moved to transitions); loop diagrams (moved to definition.yaml)
4. Add: standard Bash Command Guidelines, Configuration section, echelon_result format (from matching phase file)

- [ ] **Step 1: Create `specifier.md`** — source: `extension/commands/echelon.re-specify.md`

The specifier is the most complex (1,037 lines). Key content to migrate:
- NEVER rules (Enforcement Rules block at top)
- Polyrepo detection logic (Step 1.5)
- Domain identification strategy (how to name domains from code structure)
- Spec structure requirements (5-10 user stories per domain, NNN-re-{domain} naming, 000-re-overview fixed)
- Auto-numbering logic (detect highest existing NNN, continue from there)
- Ordering rule (foundational components first)
- The traceability.md generation
- echelon_result schema from `re-extract-2-specify.md`

Reduce from 1,037 → ~350 lines by removing: prerequisites checks, bash setup boilerplate, "Next steps" cross-references, repetitive prose. Keep all behavioral rules and LLM instructions.

- [ ] **Step 2: Create `verifier.md`** — source: `extension/commands/echelon.re-verify.md`

Key content to migrate: coverage computation algorithm, orphan file identification, clustering by file similarity (same directory/prefix/language), coverage-report.md format, threshold comparison logic. ~150 lines.

- [ ] **Step 3: Create `expander.md`** — source: `extension/commands/echelon.re-expand.md`

Key content: how to identify high-confidence clusters (≥3 files, similar purpose), spec creation for new domains vs. expanding existing, preserving manual edits. ~130 lines.

- [ ] **Step 4: Create `validator.md`** — source: `extension/commands/echelon.re-validate.md`

Key content: three resolution strategies (Basic: re-read spec + source, Deep: trace call paths, Extended: full file body), per-domain resolution scoring, validation-report.md format, when to self-loop vs. advance. ~300 lines.

- [ ] **Step 5: Create `checklister.md`** — source: `extension/commands/echelon.re-checklist.md`

Key content: per-domain checklist structure (completeness, clarity, consistency, implementability), summary checklist items (cross-domain concerns, migration risks). ~200 lines.

- [ ] **Step 6: Create `constituter.md`** — source: `extension/commands/echelon.re-constitute.md`

Key content: `constitution.md` structure (legacy profile + target decisions + [REQUIRES INPUT] placeholders), `migration-strategy.md` 6R/7R framework, `risk-matrix.md` format, `gap-analysis.md` structure, ADR template. Preset detection (`check .specify/presets/echelon-brownfield-*/` for installed templates). ~400 lines.

- [ ] **Step 7: Commit all 6 files**

```bash
git add extension/agents/re/specifier.md \
        extension/agents/re/verifier.md \
        extension/agents/re/expander.md \
        extension/agents/re/validator.md \
        extension/agents/re/checklister.md \
        extension/agents/re/constituter.md
git commit -m "feat: add RE-SPECIFIER through RE-CONSTITUTER agent files"
```

---

## Task 10: Agent files — `planner.md` and `tasker.md`

**Files:**
- Create: `extension/agents/re/planner.md`
- Create: `extension/agents/re/tasker.md`

- [ ] **Step 1: Create `planner.md`** — source: `extension/commands/echelon.re-plan.md`

Key content: plan.md structure (implementation phases, milestones, dependencies, effort estimates per phase), how to sequence phases from constitution.md migration strategy, cross-domain dependency ordering. ~190 lines.

- [ ] **Step 2: Create `tasker.md`** — source: `extension/commands/echelon.re-tasks.md`

Key content: tasks.md structure (task IDs, descriptions, acceptance criteria, dependencies, estimated effort), granularity rules (one task = one logical unit of work, not too large), the optional post-completion `speckit.analyze` prompt (moved from manifest hook to in-body suggestion). ~210 lines.

- [ ] **Step 3: Commit**

```bash
git add extension/agents/re/planner.md extension/agents/re/tasker.md
git commit -m "feat: add RE-PLANNER and RE-TASKER agent files"
```

---

## Task 11: Thin command wrappers — 3 orchestrators

**Files:**
- Modify: `extension/commands/echelon.re-extract.md`
- Modify: `extension/commands/echelon.re-retarget.md`
- Modify: `extension/commands/echelon.re-plan-all.md`

Replace each fat command with the Pattern A orchestrator template from the design spec. The three commands differ only in which `definition.yaml` section they read and which phase they start from.

- [ ] **Step 1: Replace `echelon.re-extract.md`**

```markdown
---
name: speckit.echelon.re-extract
description: "Phase 1 brownfield extraction — analyze codebase and generate domain specs + strategic artifacts"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield extraction pipeline.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, and all NEVER rules.

Then read `workflow/definition.yaml` `re_extraction:` section. Start at phase
`re-extract-0-preflight`, read each phase node's `spec_file` before dispatching,
write all state to `.specify/echelon/re/state.json`.

**This command extracts and specifies. It never writes implementation code.**

---

## Resumption

If `.specify/echelon/re/state.json` exists with `status: in_progress`, resume from
`last_dispatch.phase_id`. If `post_dispatch_complete: false`, re-run that phase
before advancing.

---

## Execution Continuity

**Tool completions are never stopping points.** After any Agent or Skill tool returns,
immediately execute the next transition in the graph without ending your response.
Stop only when: (a) the graph reaches DONE, (b) a BLOCKED condition cannot be
self-resolved.

---

## User Input

$ARGUMENTS
```

- [ ] **Step 2: Replace `echelon.re-retarget.md`**

```markdown
---
name: speckit.echelon.re-retarget
description: "Phase 2 brownfield — guided prompts to fill target stack and strategic decisions"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield retargeting phase.

**Read `agents/control/commander.md` first.**

Then read `workflow/definition.yaml` `re_retarget:` section. Start at phase
`re-retarget-0-preflight`, read each phase node's `spec_file` before executing,
write all state to `.specify/echelon/re/state.json`.

**This command elicits human decisions. It never generates code or specs.**

---

## Resumption

If `.specify/echelon/re/state.json` exists with `status: in_progress` and
`last_dispatch.phase_id` in `re_retarget:`, resume from there.

---

## Execution Continuity

After each phase completes, immediately execute the next transition. Stop only on DONE.

---

## User Input

$ARGUMENTS
```

- [ ] **Step 3: Replace `echelon.re-plan-all.md`**

```markdown
---
name: speckit.echelon.re-plan-all
description: "Phase 3 brownfield — generate per-domain plans and tasks after strategic decisions are filled"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER executing the brownfield planning phase.

**Read `agents/control/commander.md` first.**

Then read `workflow/definition.yaml` `re_planning:` section. Start at phase
`re-planning-0-preflight`, read each phase node's `spec_file` before dispatching,
write all state to `.specify/echelon/re/state.json`.

**This command generates plans and tasks. It never writes implementation code.**

---

## Resumption

If `.specify/echelon/re/state.json` exists with `status: in_progress` and
`last_dispatch.phase_id` in `re_planning:`, resume from there. If
`post_dispatch_complete: false`, re-run that phase before advancing.

---

## Execution Continuity

After any Agent tool returns, immediately execute the next transition. Stop only on DONE
or unresolvable BLOCKED.

---

## User Input

$ARGUMENTS
```

- [ ] **Step 4: Verify line counts**

```bash
wc -l extension/commands/echelon.re-extract.md \
        extension/commands/echelon.re-retarget.md \
        extension/commands/echelon.re-plan-all.md
```

Expected: all ≤ 55 lines.

- [ ] **Step 5: Commit**

```bash
git add extension/commands/echelon.re-extract.md \
        extension/commands/echelon.re-retarget.md \
        extension/commands/echelon.re-plan-all.md
git commit -m "feat: replace fat re-extract/retarget/plan-all commands with thin orchestrator wrappers"
```

---

## Task 12: Thin command wrappers — 9 standalone sub-steps

**Files:**
- Modify: `extension/commands/echelon.re-analyze.md`
- Modify: `extension/commands/echelon.re-specify.md`
- Modify: `extension/commands/echelon.re-verify.md`
- Modify: `extension/commands/echelon.re-expand.md`
- Modify: `extension/commands/echelon.re-validate.md`
- Modify: `extension/commands/echelon.re-checklist.md`
- Modify: `extension/commands/echelon.re-constitute.md`
- Modify: `extension/commands/echelon.re-plan.md`
- Modify: `extension/commands/echelon.re-tasks.md`

Each follows Pattern B (single-phase standalone). The commands differ only in `phase_id` and which `definition.yaml` section they reference. Here are all 9:

- [ ] **Step 1: Replace all 9 commands**

For each, use this template filling in `{NAME}`, `{phase_id}`, `{section}`, `{description}`:

```markdown
---
name: speckit.echelon.re-{name}
description: "{description}"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are COMMANDER running a single extraction phase.

**Read `agents/control/commander.md` first.**

Read `workflow/definition.yaml` `{section}:` section. Execute **only** phase
`{phase_id}` — dispatch the agent, write result to
`.specify/echelon/re/state.json`, then stop. Do not advance to the next transition.

---

## Resumption

If `last_dispatch.phase_id = {phase_id}` with `post_dispatch_complete: false`,
re-run the dispatch before writing results.

---

## User Input

$ARGUMENTS
```

Filled values for all 9:

| Command | `{name}` | `{phase_id}` | `{section}` | `{description}` |
|---|---|---|---|---|
| re-analyze | `re-analyze` | `re-extract-1-analyze` | `re_extraction` | Extract structured data from codebase into analysis.json |
| re-specify | `re-specify` | `re-extract-2-specify` | `re_extraction` | Generate domain specifications from analysis artifacts |
| re-verify | `re-verify` | `re-extract-3-verify` | `re_extraction` | Verify spec coverage against codebase and identify orphan files |
| re-expand | `re-expand` | `re-extract-4-expand` | `re_extraction` | Expand spec coverage by filling gaps from orphan file clusters |
| re-validate | `re-validate` | `re-extract-5-validate` | `re_extraction` | Validate specs for quality, auto-resolve ambiguities from code |
| re-checklist | `re-checklist` | `re-extract-6-checklist` | `re_extraction` | Generate quality checklists for specs (per-domain + summary) |
| re-constitute | `re-constitute` | `re-extract-7-constitute` | `re_extraction` | Generate strategic artifacts (constitution, strategy, risks, gaps, ADRs) |
| re-plan | `re-plan` | `re-planning-1-plan` | `re_planning` | Generate per-domain plan.md files |
| re-tasks | `re-tasks` | `re-planning-2-tasks` | `re_planning` | Generate per-domain tasks.md files |

- [ ] **Step 2: Verify all 9 are ≤ 50 lines**

```bash
wc -l extension/commands/echelon.re-analyze.md \
        extension/commands/echelon.re-specify.md \
        extension/commands/echelon.re-verify.md \
        extension/commands/echelon.re-expand.md \
        extension/commands/echelon.re-validate.md \
        extension/commands/echelon.re-checklist.md \
        extension/commands/echelon.re-constitute.md \
        extension/commands/echelon.re-plan.md \
        extension/commands/echelon.re-tasks.md
```

Expected: all ≤ 50 lines.

- [ ] **Step 3: Verify old fat content is gone**

```bash
grep -l "## Enforcement Rules\|## Steps\|## Prerequisites" extension/commands/echelon.re-*.md
```

Expected: no output (0 matches).

- [ ] **Step 4: Commit**

```bash
git add extension/commands/echelon.re-analyze.md \
        extension/commands/echelon.re-specify.md \
        extension/commands/echelon.re-verify.md \
        extension/commands/echelon.re-expand.md \
        extension/commands/echelon.re-validate.md \
        extension/commands/echelon.re-checklist.md \
        extension/commands/echelon.re-constitute.md \
        extension/commands/echelon.re-plan.md \
        extension/commands/echelon.re-tasks.md
git commit -m "feat: replace fat re-* sub-commands with thin single-phase standalone wrappers"
```

---

## Task 13: `extension.yml` changes

**Files:**
- Modify: `extension/extension.yml`

- [ ] **Step 1: Remove `behavior:` block from all 12 re-* command entries**

Find each of the 12 re-* command entries (search for `name: "speckit.echelon.re-`). For each, delete the entire `behavior:` block:

```yaml
# DELETE these lines from each re-* command entry:
      behavior:
        execution: isolated
        invocation: automatic
        capability: strong
        effort: high
        tools: full
```

Only the `re-analyze` entry also has a `scripts:` block — keep that:

```yaml
    - name: "speckit.echelon.re-analyze"
      file: "commands/echelon.re-analyze.md"
      description: "Extract structured data from codebase into analysis.json"
      scripts:
        sh: "scripts/bash/re/run-analysis.sh"
```

- [ ] **Step 2: Add 9 agent entries**

Find the `# ── Understanding commands ──` comment block. Insert a new `# ── Re-extraction layer ──` block immediately after the last understanding agent entry:

```yaml
    # ── Re-extraction layer ──────────────────────────────────────────────────
    - name: "speckit.echelon.re-analyzer"
      file: "agents/re/analyzer.md"
      description: "RE-ANALYZER — extracts structured codebase data via analysis scripts"
      behavior:
        execution: agent
        capability: strong
        tools: full
        color: orange
    - name: "speckit.echelon.re-specifier"
      file: "agents/re/specifier.md"
      description: "RE-SPECIFIER — synthesises domain specifications from analysis artifacts"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-verifier"
      file: "agents/re/verifier.md"
      description: "RE-VERIFIER — computes spec coverage and clusters orphan files"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-expander"
      file: "agents/re/expander.md"
      description: "RE-EXPANDER — fills coverage gaps from orphan file clusters"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-validator"
      file: "agents/re/validator.md"
      description: "RE-VALIDATOR — quality-checks specs and auto-resolves ambiguities from code"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-checklister"
      file: "agents/re/checklister.md"
      description: "RE-CHECKLISTER — generates per-domain and summary quality checklists"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-constituter"
      file: "agents/re/constituter.md"
      description: "RE-CONSTITUTER — generates strategic artifacts (constitution, strategy, risks, gaps, ADRs)"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-planner"
      file: "agents/re/planner.md"
      description: "RE-PLANNER — generates per-domain plan.md informed by constitution"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
    - name: "speckit.echelon.re-tasker"
      file: "agents/re/tasker.md"
      description: "RE-TASKER — generates per-domain tasks.md files"
      behavior:
        execution: agent
        capability: strong
        tools: write
        color: orange
```

- [ ] **Step 3: Validate YAML and check counts**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('extension/extension.yml'))
cmds = d['provides']['commands']
re_agents = [c for c in cmds if 're-' in c['name'] and c.get('behavior',{}).get('execution')=='agent']
re_commands = [c for c in cmds if 're-' in c['name'] and 'behavior' not in c]
print(f're-* agents: {len(re_agents)} (expected 9)')
print(f're-* neutral commands: {len(re_commands)} (expected 12)')
assert len(re_agents) == 9
assert len(re_commands) == 12
print('PASS')
"
```

- [ ] **Step 4: Commit**

```bash
git add extension/extension.yml
git commit -m "feat: update extension.yml — neutral re-* commands, add 9 re-* agent entries"
```

---

## Task 14: Final validation and test run

**Files:**
- No new files — verification only

- [ ] **Step 1: Run the 4 YAML structure assertions (should now all pass)**

```bash
bash tests/unit/test-unit-registry-sync.sh 2>&1 | grep -E "re-\*|PASS|FAIL"
```

Expected: all 4 re-* assertions PASS.

- [ ] **Step 2: Run kernel tests**

```bash
python3 -m pytest tests/kernel/ -v --tb=short 2>&1 | tail -20
```

Expected: `tests/kernel/test_re_state.py` all pass; existing kernel tests unchanged.

- [ ] **Step 3: Run existing brownfield bash tests**

```bash
bash tests/integration/re/test-discover-repos.sh 2>&1 | tail -3
bash tests/integration/re/test-extract-cross-repo.sh 2>&1 | tail -3
bash tests/integration/re/test-run-analysis-polyrepo.sh 2>&1 | tail -3
```

Expected: 16/0, 11/0, 21/0.

- [ ] **Step 4: Run dry-run and extension validate**

```bash
bash scripts/bash/dry-run.sh 2>&1 | tail -10
specify extension validate extension/ 2>&1
```

Expected: clean exit.

- [ ] **Step 5: Verify all command line counts**

```bash
wc -l extension/commands/echelon.re-*.md | sort -n | tail -3
```

Expected: all ≤ 55 lines. If any exceed 55, the fat content was not fully migrated.

- [ ] **Step 6: Verify all agent files exist**

```bash
ls extension/agents/re/
```

Expected: `analyzer.md checklister.md constituter.md expander.md planner.md specifier.md tasker.md validator.md verifier.md`

- [ ] **Step 7: Run full test suite**

```bash
bash tests/run-all.sh 2>&1 | tail -20
```

Expected: `Integration/RE Tests: 3 passed, 0 failed`. Kernel Tests: same count as before (+ 22 new from test_re_state.py). No new failures.

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "feat: re-* workflow externalization complete — all 12 commands thin-wrapped, 13 phase files, 9 agent files, state machine conformant"
```
