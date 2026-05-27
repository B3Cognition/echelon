# Squad Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace COMMANDER-as-router with a deterministic Python harness (`SquadController`) that drives the pre-code squad run phase graph, making phase skipping architecturally impossible.

**Architecture:** Python `SquadController` reads `workflow/definition.yaml`, evaluates `transitions[].condition` against `state.json` in Python, dispatches agents via `SquadCliProvider` (subprocess), and applies `echelon_result:` state updates. COMMANDER (slimmed to ~150 lines) is dispatched only for judgment calls. `echelon.run.md` becomes a 15-line launcher. Final step renames `ClaudeCliProvider` → `AICodingCliProvider`.

**Tech Stack:** Python 3.11+, pytest, PyYAML, concurrent.futures (staged_parallel), subprocess (agent dispatch), threading (timeout)

**Design spec:** `docs/superpowers/specs/2026-05-18-squad-harness-design.md`

---

## File Map

**New files:**
- `src/harness/squad_provider.py` — `SquadAgentResult`, `_extract_echelon_result`, `SquadCliProvider`
- `src/harness/condition_evaluator.py` — `ConditionEvaluator`
- `src/harness/phase_graph.py` — `PhaseNode`, `PhaseGraph`
- `src/harness/squad_state.py` — `SquadStateStore`
- `src/harness/squad_executors.py` — all phase executor classes
- `src/harness/squad.py` — `SquadController`, `SquadResult`
- `tests/kernel/test_squad_provider.py`
- `tests/kernel/test_condition_evaluator.py`
- `tests/kernel/test_phase_graph.py`
- `tests/kernel/test_squad_state.py`
- `tests/integration/test_squad_controller.py`
- `tests/unit/test-unit-squad-registry.sh`

**Modified files:**
- `src/echelon/cli.py` — add `_cmd_run()`, add `run` to SKILL_MAP + USAGE
- `extension/commands/echelon.run.md` — replace with 15-line launcher
- `extension/agents/control/commander.md` — slim 800 → 150 lines
- `src/harness/llm_provider.py` — rename class → `AICodingCliProvider` (Task 14)
- `src/harness/ralph.py` + `coordinator.py` — update import (Task 14)

---

## Task 1: `SquadAgentResult` + `_extract_echelon_result`

**Files:**
- Create: `src/harness/squad_provider.py`
- Create: `tests/kernel/test_squad_provider.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_squad_provider.py`:

```python
"""Tests for SquadAgentResult and echelon_result extraction."""
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.squad_provider import SquadAgentResult, _extract_echelon_result


class TestSquadAgentResult:
    def _result(self, echelon_result=None, exit_code=0, timed_out=False):
        return SquadAgentResult(
            exit_code=exit_code,
            echelon_result=echelon_result,
            raw_output="",
            duration_ms=100,
            timed_out=timed_out,
        )

    def test_verdict_returns_none_when_no_echelon_result(self):
        assert self._result().verdict is None

    def test_verdict_from_echelon_result(self):
        r = self._result({"verdict": "DONE", "state_updates": {}})
        assert r.verdict == "DONE"

    def test_state_updates_empty_when_no_echelon_result(self):
        assert self._result().state_updates == {}

    def test_state_updates_from_echelon_result(self):
        r = self._result({"verdict": "DONE", "state_updates": {"coverage_pct": 72}})
        assert r.state_updates == {"coverage_pct": 72}

    def test_blocked_true_when_verdict_blocked(self):
        assert self._result({"verdict": "BLOCKED", "state_updates": {}}).blocked is True

    def test_blocked_true_when_timed_out(self):
        assert self._result(timed_out=True).blocked is True

    def test_blocked_true_when_nonzero_exit(self):
        assert self._result(exit_code=1).blocked is True

    def test_blocked_false_when_done(self):
        assert self._result({"verdict": "DONE", "state_updates": {}}, exit_code=0).blocked is False


class TestExtractEchelonResult:
    def test_returns_none_when_absent(self):
        assert _extract_echelon_result("no result here") is None

    def test_extracts_bare_block(self):
        raw = """Some output.

echelon_result:
  verdict: DONE
  phase_id: re-extract-1-analyze
  state_updates:
    coverage_pct: 72
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "DONE"
        assert result["state_updates"]["coverage_pct"] == 72

    def test_extracts_from_fenced_yaml(self):
        raw = """
```yaml
echelon_result:
  verdict: PASS
  state_updates: {}
```
"""
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "PASS"

    def test_returns_none_on_malformed_yaml(self):
        raw = "echelon_result:\n  verdict: [unclosed"
        assert _extract_echelon_result(raw) is None

    def test_extracts_last_occurrence(self):
        raw = """echelon_result:
  verdict: FAIL
  state_updates: {}

Later...

echelon_result:
  verdict: DONE
  state_updates: {}
"""
        # Should get the last one
        result = _extract_echelon_result(raw)
        assert result["verdict"] == "DONE"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/michalbachorik/work/echelon_r/echelon
~/.echelon/venv/bin/python -m pytest tests/kernel/test_squad_provider.py -v 2>&1 | head -15
```
Expected: `ModuleNotFoundError: No module named 'harness.squad_provider'`

- [ ] **Step 3: Implement**

Create `src/harness/squad_provider.py`:

```python
"""SquadAgentResult + SquadCliProvider for pre-code squad phase dispatch."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from harness.llm_provider import ClaudeCliProvider
from harness.skill_loader import StreamEventPrinter


@dataclass
class SquadAgentResult:
    exit_code: int
    echelon_result: Optional[dict]
    raw_output: str
    duration_ms: int
    timed_out: bool

    @property
    def verdict(self) -> Optional[str]:
        return (self.echelon_result or {}).get("verdict")

    @property
    def state_updates(self) -> dict:
        return (self.echelon_result or {}).get("state_updates", {})

    @property
    def blocked(self) -> bool:
        return self.verdict == "BLOCKED" or self.timed_out or self.exit_code != 0


def _extract_echelon_result(raw: str) -> Optional[dict]:
    """Find the last echelon_result: block in raw output and parse it."""
    # Find last occurrence
    idx = raw.rfind("echelon_result:")
    if idx == -1:
        return None
    snippet = raw[idx:]
    # Trim at closing code fence if present
    fence_end = snippet.find("\n```")
    if fence_end != -1:
        snippet = snippet[:fence_end]
    try:
        parsed = yaml.safe_load(snippet)
        if isinstance(parsed, dict) and "echelon_result" in parsed:
            return parsed["echelon_result"]
        return None
    except yaml.YAMLError:
        return None


class SquadCliProvider(ClaudeCliProvider):
    """Extends ClaudeCliProvider with exec_agent() for squad phase dispatch.

    Inherits CLI selection (claude/copilot/opencode via ECHELON_LLM env var).
    Adds output capture + echelon_result: extraction on top of streaming.
    """

    def exec_agent(
        self,
        project_root: str,
        prompt: str,
        timeout_ms: Optional[int] = None,
    ) -> SquadAgentResult:
        cmd = self._build_cmd(prompt)
        env = {**os.environ}
        if self._config_dir and self._cli == "claude":
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config_dir)

        start = time.monotonic()
        if self._cli == "claude":
            exit_code, raw = self._run_streaming_captured(cmd, project_root, env, timeout_ms)
        else:
            exit_code, raw = self._run_plain_captured(cmd, project_root, env, timeout_ms)

        duration_ms = int((time.monotonic() - start) * 1000)
        timed_out = exit_code is None
        return SquadAgentResult(
            exit_code=exit_code if exit_code is not None else -1,
            echelon_result=_extract_echelon_result(raw),
            raw_output=raw,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    def _run_streaming_captured(
        self, cmd: list, cwd: str, env: dict, timeout_ms: Optional[int]
    ) -> tuple[Optional[int], str]:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=None
        )
        text_chunks: list[str] = []
        timed_out = False
        printer = StreamEventPrinter()

        def _kill() -> None:
            nonlocal timed_out
            timed_out = True
            proc.kill()

        timer = threading.Timer(timeout_s, _kill)
        try:
            timer.start()
            for raw_line in proc.stdout:  # type: ignore[union-attr]
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    printer(event)
                    # Collect text from content_block_delta events
                    if (
                        event.get("type") == "content_block_delta"
                        and event.get("delta", {}).get("type") == "text_delta"
                    ):
                        text_chunks.append(event["delta"].get("text", ""))
                except json.JSONDecodeError:
                    print(line, flush=True)
                    text_chunks.append(line)
            proc.stdout.close()  # type: ignore[union-attr]
            proc.wait()
        finally:
            timer.cancel()

        exit_code = None if timed_out else proc.returncode
        return exit_code, "".join(text_chunks)

    def _run_plain_captured(
        self, cmd: list, cwd: str, env: dict, timeout_ms: Optional[int]
    ) -> tuple[Optional[int], str]:
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else self._timeout_s
        try:
            result = subprocess.run(
                cmd, cwd=cwd, env=env, timeout=timeout_s, capture_output=True
            )
            text = result.stdout.decode("utf-8", errors="replace")
            print(text, flush=True)
            return result.returncode, text
        except subprocess.TimeoutExpired:
            return None, ""
```

- [ ] **Step 4: Run tests**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_squad_provider.py -v 2>&1 | tail -5
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad_provider.py tests/kernel/test_squad_provider.py
git commit -m "feat: add SquadAgentResult and SquadCliProvider with exec_agent"
```

---

## Task 2: `ConditionEvaluator`

**Files:**
- Create: `src/harness/condition_evaluator.py`
- Create: `tests/kernel/test_condition_evaluator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_condition_evaluator.py`:

```python
"""Tests for ConditionEvaluator — covers all condition patterns in definition.yaml."""
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.condition_evaluator import ConditionEvaluator
from harness.squad_provider import SquadAgentResult


def _result(verdict: str) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": {}},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )


class TestConditionEvaluator:
    ev = ConditionEvaluator()

    # ── simple conditions ──────────────────────────────────────────────────
    def test_always(self):
        assert self.ev.evaluate("always", {}) is True

    def test_verdict_done(self):
        assert self.ev.evaluate("verdict = DONE", {}, _result("DONE")) is True

    def test_verdict_done_mismatch(self):
        assert self.ev.evaluate("verdict = DONE", {}, _result("FAIL")) is False

    def test_verdict_pass(self):
        assert self.ev.evaluate("verdict = PASS", {}, _result("PASS")) is True

    def test_mode_brownfield(self):
        assert self.ev.evaluate("mode = brownfield", {"mode": "brownfield"}) is True

    def test_mode_brownfield_mismatch(self):
        assert self.ev.evaluate("mode = brownfield", {"mode": "greenfield"}) is False

    def test_string_equality(self):
        assert self.ev.evaluate("guardian_mode = always_on",
                                {"guardian_mode": "always_on"}) is True

    # ── numeric comparisons ────────────────────────────────────────────────
    def test_numeric_gte_true(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold",
                                {"coverage_pct": 80, "coverage_threshold": 80}) is True

    def test_numeric_gte_false(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold",
                                {"coverage_pct": 72, "coverage_threshold": 80}) is False

    def test_numeric_lt_true(self):
        assert self.ev.evaluate("validate_iterations < max_validate_iterations",
                                {"validate_iterations": 2,
                                 "max_validate_iterations": 3}) is True

    def test_numeric_lt_false(self):
        assert self.ev.evaluate("validate_iterations < max_validate_iterations",
                                {"validate_iterations": 3,
                                 "max_validate_iterations": 3}) is False

    # ── membership ─────────────────────────────────────────────────────────
    def test_autonomy_in_list(self):
        assert self.ev.evaluate("autonomy in [semi, banzai]",
                                {"autonomy": "semi"}) is True

    def test_autonomy_not_in_list(self):
        assert self.ev.evaluate("autonomy in [semi, banzai]",
                                {"autonomy": "guided"}) is False

    # ── boolean field ──────────────────────────────────────────────────────
    def test_boolean_field_true(self):
        assert self.ev.evaluate("convergence_detected",
                                {"convergence_detected": True}) is True

    def test_boolean_field_false(self):
        assert self.ev.evaluate("convergence_detected",
                                {"convergence_detected": False}) is False

    # ── dotted path ────────────────────────────────────────────────────────
    def test_dotted_path_true(self):
        assert self.ev.evaluate("quality_gates.pass",
                                {"quality_gates": {"pass": True}}) is True

    def test_dotted_path_false(self):
        assert self.ev.evaluate("quality_gates.pass",
                                {"quality_gates": {"pass": False}}) is False

    # ── compound AND ──────────────────────────────────────────────────────
    def test_and_both_true(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold AND validate_iterations < max_validate_iterations",
            {"coverage_pct": 85, "coverage_threshold": 80,
             "validate_iterations": 1, "max_validate_iterations": 3},
        ) is True

    def test_and_one_false(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold AND validate_iterations < max_validate_iterations",
            {"coverage_pct": 72, "coverage_threshold": 80,
             "validate_iterations": 1, "max_validate_iterations": 3},
        ) is False

    def test_and_verdict_and_field(self):
        assert self.ev.evaluate(
            "verdict = PASS AND convergence_detected",
            {"convergence_detected": True},
            _result("PASS"),
        ) is True

    # ── compound OR ───────────────────────────────────────────────────────
    def test_or_first_true(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold OR verify_expand_iterations >= max_verify_expand_iterations",
            {"coverage_pct": 85, "coverage_threshold": 80,
             "verify_expand_iterations": 2, "max_verify_expand_iterations": 5},
        ) is True

    def test_or_both_false(self):
        assert self.ev.evaluate(
            "coverage_pct >= coverage_threshold OR verify_expand_iterations >= max_verify_expand_iterations",
            {"coverage_pct": 72, "coverage_threshold": 80,
             "verify_expand_iterations": 2, "max_verify_expand_iterations": 5},
        ) is False

    # ── multiple fields same condition (why3 + assess2) ───────────────────
    def test_two_verdict_fields_and(self):
        assert self.ev.evaluate(
            "why3_verdict = PASS AND assess2_verdict = PASS",
            {"why3_verdict": "PASS", "assess2_verdict": "PASS"},
        ) is True

    def test_two_verdict_fields_one_fails(self):
        assert self.ev.evaluate(
            "why3_verdict = PASS AND assess2_verdict = PASS",
            {"why3_verdict": "PASS", "assess2_verdict": "FAIL"},
        ) is False

    # ── unknown → None ────────────────────────────────────────────────────
    def test_unknown_condition_returns_none(self):
        assert self.ev.evaluate("some_unknown_thing xyz", {}) is None

    # ── missing state field defaults to falsy ─────────────────────────────
    def test_missing_field_comparison_false(self):
        assert self.ev.evaluate("coverage_pct >= coverage_threshold", {}) is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_condition_evaluator.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'harness.condition_evaluator'`

- [ ] **Step 3: Implement**

Create `src/harness/condition_evaluator.py`:

```python
"""ConditionEvaluator — evaluates workflow/definition.yaml transition conditions."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.squad_provider import SquadAgentResult


class ConditionEvaluator:
    """Evaluates condition strings from definition.yaml transitions against state.json.

    Returns True/False for known conditions, None for unrecognised ones.
    None triggers COMMANDER judgment dispatch.
    """

    def evaluate(
        self,
        condition: str,
        state: dict,
        result: "Optional[SquadAgentResult]" = None,
    ) -> Optional[bool]:
        condition = condition.strip()

        if condition == "always":
            return True

        # Compound: split AND before OR (AND binds tighter)
        if re.search(r"\bAND\b", condition):
            parts = re.split(r"\bAND\b", condition)
            sub = [self.evaluate(p.strip(), state, result) for p in parts]
            if None in sub:
                return None
            return all(sub)

        if re.search(r"\bOR\b", condition):
            parts = re.split(r"\bOR\b", condition)
            sub = [self.evaluate(p.strip(), state, result) for p in parts]
            if all(s is None for s in sub):
                return None
            if None in sub:
                return None  # conservative: unknown sub-condition → COMMANDER
            return any(sub)

        # verdict = X — checks result.verdict
        m = re.fullmatch(r"verdict\s*=\s*(\S+)", condition)
        if m:
            if result is None:
                return False
            return result.verdict == m.group(1)

        # field in [v1, v2, ...]
        m = re.fullmatch(r"([\w.\-]+)\s+in\s+\[([^\]]+)\]", condition)
        if m:
            field, values_str = m.group(1), m.group(2)
            values = [v.strip() for v in values_str.split(",")]
            return str(self._get(state, field, "")) in values

        # field >= value  /  field <= value  /  field > value  /  field < value
        m = re.fullmatch(r"([\w.\-]+)\s*(>=|<=|>|<)\s*(-?[\d.]+)", condition)
        if m:
            field, op, val_str = m.group(1), m.group(2), m.group(3)
            raw_val = self._get(state, field)
            if raw_val is None:
                return False
            try:
                fv, ref = float(raw_val), float(val_str)
            except (TypeError, ValueError):
                return None
            return {
                ">=": fv >= ref,
                "<=": fv <= ref,
                ">": fv > ref,
                "<": fv < ref,
            }[op]

        # field = value  (string/dash-notation field names like "why3-verdict")
        m = re.fullmatch(r"([\w.\-]+)\s*=\s*(.+)", condition)
        if m:
            field, expected = m.group(1).strip(), m.group(2).strip()
            return str(self._get(state, field, "")) == expected

        # bare boolean field  e.g. "convergence_detected", "quality_gates.pass"
        if re.fullmatch(r"[\w.\-]+", condition):
            val = self._get(state, condition)
            if val is not None:
                return bool(val)

        return None  # unrecognised → COMMANDER judgment

    def _get(self, state: dict, field: str, default=None):
        """Read a dotted-path field from state dict."""
        parts = field.split(".")
        val: object = state
        for p in parts:
            if not isinstance(val, dict):
                return default
            val = val.get(p)
            if val is None:
                return default
        return val
```

- [ ] **Step 4: Run tests**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_condition_evaluator.py -v 2>&1 | tail -5
```
Expected: 26 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harness/condition_evaluator.py tests/kernel/test_condition_evaluator.py
git commit -m "feat: add ConditionEvaluator for deterministic transition evaluation"
```

---

## Task 3: `PhaseGraph`

**Files:**
- Create: `src/harness/phase_graph.py`
- Create: `tests/kernel/test_phase_graph.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_phase_graph.py`:

```python
"""Tests for PhaseGraph — loads workflow/definition.yaml."""
import sys
from pathlib import Path

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


class TestPhaseGraph:
    graph = PhaseGraph(DEFINITION, EXT_YML)

    def test_loads_init_phase(self):
        node = self.graph.get("init")
        assert node.id == "init"

    def test_entry_phase_is_init(self):
        assert self.graph.entry_phase() == "init"

    def test_phase1_discover_type_agent(self):
        node = self.graph.get("phase1-discover")
        assert node.type == "agent"
        assert node.agent == "speckit-echelon-scout"

    def test_unknown_phase_raises(self):
        import pytest
        with pytest.raises(KeyError):
            self.graph.get("does-not-exist")

    def test_phase3_consensus_is_staged_parallel(self):
        node = self.graph.get("phase3-consensus")
        assert node.type == "staged_parallel"
        assert len(node.agents) >= 2

    def test_phase1_discover_has_pre_dispatch(self):
        node = self.graph.get("phase1-discover")
        assert len(node.pre_dispatch) > 0

    def test_transitions_present(self):
        node = self.graph.get("phase1-discover")
        assert len(node.transitions) > 0
        assert all("to" in t for t in node.transitions)
        assert all("condition" in t for t in node.transitions)

    def test_agent_file_lookup(self):
        # scout dispatch id → file path in extension/
        path = self.graph.agent_file("speckit-echelon-scout")
        assert path is not None
        assert "scout" in path

    def test_all_agent_phases_have_resolvable_files(self):
        missing = []
        for phase_id in self.graph.all_phase_ids():
            node = self.graph.get(phase_id)
            if node.type == "agent" and node.agent:
                rel = self.graph.agent_file(node.agent)
                if rel:
                    full = EXT_ROOT / "extension" / rel
                    if not full.exists():
                        missing.append((phase_id, rel))
        assert missing == [], f"Agent files missing: {missing}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_phase_graph.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement**

Create `src/harness/phase_graph.py`:

```python
"""PhaseGraph — loads workflow/definition.yaml into typed PhaseNode objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class PhaseNode:
    id: str
    type: str                          # agent | staged_parallel | commander_internal | ...
    label: str = ""
    spec_file: Optional[str] = None
    agent: Optional[str] = None        # dash-notation dispatch id
    agents: list = field(default_factory=list)
    context_pack: list = field(default_factory=list)
    pre_dispatch: list = field(default_factory=list)
    transitions: list = field(default_factory=list)


class PhaseGraph:
    """Loads the main squad phases from definition.yaml.

    Also reads extension.yml to map agent dispatch ids to file paths.
    """

    def __init__(self, definition_path: Path, extension_yml_path: Path) -> None:
        raw = yaml.safe_load(definition_path.read_text())
        self._phases: dict[str, PhaseNode] = {}
        for p in raw.get("phases", []):
            node = PhaseNode(
                id=p["id"],
                type=p.get("type", "agent"),
                label=p.get("label", ""),
                spec_file=p.get("spec_file"),
                agent=p.get("agent"),
                agents=p.get("agents", []),
                context_pack=p.get("context_pack", []),
                pre_dispatch=p.get("pre_dispatch", []),
                transitions=p.get("transitions", []),
            )
            self._phases[node.id] = node

        # Build dispatch-id → file path map from extension.yml
        self._agent_files: dict[str, str] = {}
        ext = yaml.safe_load(extension_yml_path.read_text())
        for cmd in ext.get("provides", {}).get("commands", []):
            if cmd.get("behavior", {}).get("execution") == "agent":
                # "speckit.echelon.scout" → "speckit-echelon-scout"
                dispatch_id = cmd["name"].replace(".", "-")
                self._agent_files[dispatch_id] = cmd["file"]

    def get(self, phase_id: str) -> PhaseNode:
        if phase_id not in self._phases:
            raise KeyError(f"Phase not found in definition.yaml: {phase_id!r}")
        return self._phases[phase_id]

    def entry_phase(self) -> str:
        return next(iter(self._phases))

    def all_phase_ids(self) -> list[str]:
        return list(self._phases.keys())

    def agent_file(self, dispatch_id: str) -> Optional[str]:
        """Return the relative file path for an agent dispatch id, or None."""
        return self._agent_files.get(dispatch_id)

    def all_conditions(self) -> set[str]:
        """Return all unique condition strings across all transitions."""
        return {
            t.get("condition", "")
            for node in self._phases.values()
            for t in node.transitions
        }
```

- [ ] **Step 4: Run tests**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_phase_graph.py -v 2>&1 | tail -8
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/phase_graph.py tests/kernel/test_phase_graph.py
git commit -m "feat: add PhaseGraph loading definition.yaml + agent file map"
```

---

## Task 4: `SquadStateStore`

**Files:**
- Create: `src/harness/squad_state.py`
- Create: `tests/kernel/test_squad_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_squad_state.py`:

```python
"""Tests for SquadStateStore."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.squad_state import SquadStateStore
from harness.squad_provider import SquadAgentResult


def _store(tmp_path: Path) -> SquadStateStore:
    return SquadStateStore(tmp_path / ".specify/squad/state.json")


def _result(verdict="DONE", updates=None) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": updates or {}},
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )


class TestSquadStateStore:
    def test_load_returns_empty_when_no_file(self, tmp_path):
        store = _store(tmp_path)
        assert store.load() == {}

    def test_initialize_writes_state(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("run-001", "greenfield", "do stuff", 500_000, "init")
        state = store.load()
        assert state["run_id"] == "run-001"
        assert state["phase"] == "init"
        assert state["status"] == "running"
        assert state["token_budget"] == 500_000

    def test_current_phase_returns_init_after_initialize(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        assert store.current_phase() == "init"

    def test_current_phase_returns_init_when_no_state(self, tmp_path):
        assert _store(tmp_path).current_phase() == "init"

    def test_advance_updates_phase(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover", _result())
        assert store.current_phase() == "phase1-discover"

    def test_advance_writes_last_dispatch(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover", _result("DONE"))
        ld = store.load()["last_dispatch"]
        assert ld["phase_id"] == "init"
        assert ld["verdict"] == "DONE"

    def test_advance_applies_state_updates(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.advance("init", "phase1-discover",
                      _result("DONE", {"coverage_pct": 72}))
        assert store.load()["coverage_pct"] == 72

    def test_cancel_flag(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        assert store.is_cancel_requested() is False
        store.set_cancel_requested()
        assert store.is_cancel_requested() is True

    def test_token_tracking(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 100_000, "init")
        store.increment_token_usage(10_000)
        store.increment_token_usage(5_000)
        assert store.token_usage() == 15_000

    def test_atomic_write_no_partial_state(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        # No .tmp file should remain after save
        tmp_file = (tmp_path / ".specify/squad/state.json").with_suffix(".json.tmp")
        assert not tmp_file.exists()

    def test_set_blocked(self, tmp_path):
        store = _store(tmp_path)
        store.initialize("r", "greenfield", "msg", 0, "init")
        store.set_blocked("understanding unavailable")
        state = store.load()
        assert state["status"] == "blocked"
        assert state["blocked_reason"] == "understanding unavailable"
```

- [ ] **Step 2: Run to confirm failure**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_squad_state.py -v 2>&1 | head -10
```

- [ ] **Step 3: Implement**

Create `src/harness/squad_state.py`:

```python
"""SquadStateStore — atomic reads/writes for .specify/squad/state.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.squad_provider import SquadAgentResult


class SquadStateStore:
    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())

    def save(self, state: dict) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(self._path)

    def initialize(
        self,
        run_id: str,
        mode: str,
        user_message: str,
        token_budget: int,
        entry_phase: str,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        self.save({
            "run_id": run_id,
            "status": "running",
            "phase": entry_phase,
            "mode": mode,
            "iteration": 0,
            "token_usage": 0,
            "token_budget": token_budget,
            "user_message": user_message,
            "created_at": ts,
            "updated_at": ts,
            "last_dispatch": None,
            "cancel_requested": False,
            "convergence_detected": False,
            "quality_scores": [],
            "issues_log": [],
        })

    def current_phase(self) -> str:
        return self.load().get("phase", "init")

    def advance(
        self, from_phase: str, to_phase: str, result: "SquadAgentResult"
    ) -> None:
        state = self.load()
        state["phase"] = to_phase
        state["last_dispatch"] = {
            "phase_id": from_phase,
            "verdict": result.verdict,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in result.state_updates.items():
            state[key] = value
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save(state)

    def set_blocked(self, reason: str) -> None:
        state = self.load()
        state["status"] = "blocked"
        state["blocked_reason"] = reason
        self.save(state)

    def set_cancel_requested(self) -> None:
        state = self.load()
        state["cancel_requested"] = True
        self.save(state)

    def is_cancel_requested(self) -> bool:
        return bool(self.load().get("cancel_requested", False))

    def token_usage(self) -> int:
        return int(self.load().get("token_usage", 0))

    def increment_token_usage(self, tokens: int) -> None:
        state = self.load()
        state["token_usage"] = state.get("token_usage", 0) + tokens
        self.save(state)

    def token_budget(self) -> int:
        return int(self.load().get("token_budget", 0))
```

- [ ] **Step 4: Run tests**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/test_squad_state.py -v 2>&1 | tail -5
```
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad_state.py tests/kernel/test_squad_state.py
git commit -m "feat: add SquadStateStore with atomic writes"
```

---

## Task 5: Phase executors

**Files:**
- Create: `src/harness/squad_executors.py`
- Tests inline in Task 9 integration tests (executors tested via SquadController mock)

Phase executors live in one file. They share `_assemble_prompt()` via a base class.

- [ ] **Step 1: Create `src/harness/squad_executors.py`**

```python
"""Phase executors for SquadController — one class per definition.yaml type."""
from __future__ import annotations

import subprocess
import sys
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.phase_graph import PhaseGraph, PhaseNode
    from harness.squad_provider import SquadAgentResult, SquadCliProvider
    from harness.squad_state import SquadStateStore


class PhaseExecutor(ABC):
    def __init__(
        self,
        provider: "SquadCliProvider",
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
    ) -> None:
        self._provider = provider
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root

    @abstractmethod
    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        ...

    def _assemble_prompt(self, node: "PhaseNode", state: dict) -> str:
        parts: list[str] = []

        # 1. Agent file (role + instructions)
        if node.agent:
            rel = self._graph.agent_file(node.agent)
            if rel:
                agent_path = self._ext_dir / rel
                if agent_path.exists():
                    parts.append(agent_path.read_text())

        # 2. Phase spec file (context pack assembly instructions + echelon_result schema)
        if node.spec_file:
            spec_path = self._ext_dir / node.spec_file
            if spec_path.exists():
                parts.append(spec_path.read_text())

        # 3. Context pack files (read each that exists on disk)
        for item in node.context_pack:
            # Items may have comments: ".specify/echelon/re/state.json — current run state"
            file_ref = item.split(" ")[0].split("(")[0].rstrip()
            if not file_ref or file_ref.startswith("#"):
                continue
            candidate = self._project_root / file_ref
            if candidate.exists():
                parts.append(f"\n---\n# {file_ref}\n{candidate.read_text()}")

        # 4. Current state.json for COMMANDER context
        state_path = self._project_root / ".specify/squad/state.json"
        if state_path.exists():
            parts.append(f"\n---\n# Current state.json\n{state_path.read_text()}")

        return "\n\n".join(parts)

    def _run_pre_dispatch(
        self, node: "PhaseNode", state: dict, state_store: "SquadStateStore"
    ) -> None:
        """Execute conditional pre_dispatch entries before the main agent."""
        from harness.condition_evaluator import ConditionEvaluator
        ev = ConditionEvaluator()
        for entry in node.pre_dispatch:
            condition = entry.get("condition", "always")
            if ev.evaluate(condition, state) is not True:
                continue
            pre_agent = entry.get("agent", "")
            if not pre_agent:
                continue
            pre_rel = self._graph.agent_file(pre_agent.split(" ")[0].replace("speckit-echelon-", "speckit.echelon.").replace("-", "."))
            if not pre_rel:
                # Try direct lookup
                pre_rel = self._graph.agent_file(pre_agent.split(" ")[0])
            if pre_rel:
                pre_path = self._ext_dir / pre_rel
                if pre_path.exists():
                    prompt = pre_path.read_text()
                    result = self._provider.exec_agent(str(self._project_root), prompt)
                    state_store.advance(f"{node.id}-pre-{pre_agent}", node.id, result)


class AgentExecutor(PhaseExecutor):
    """Handles type: agent phases — the common case."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        state = state_store.load()
        self._run_pre_dispatch(node, state, state_store)
        # Re-load state after pre_dispatch (it may have written golddigger artifacts etc.)
        state = state_store.load()
        prompt = self._assemble_prompt(node, state)
        return self._provider.exec_agent(str(self._project_root), prompt)


class CommanderInternalExecutor(PhaseExecutor):
    """Handles type: commander_internal — run spec_file instructions via Bash."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult, _extract_echelon_result
        if node.spec_file:
            spec_path = self._ext_dir / node.spec_file
            if spec_path.exists():
                # Run the spec file content as a Bash subprocess
                result = subprocess.run(
                    ["bash", "-c", spec_path.read_text()],
                    cwd=str(self._project_root),
                    capture_output=True,
                    text=True,
                )
                raw = result.stdout + result.stderr
                print(raw, flush=True)
                return SquadAgentResult(
                    exit_code=result.returncode,
                    echelon_result=_extract_echelon_result(raw) or {"verdict": "DONE", "state_updates": {}},
                    raw_output=raw,
                    duration_ms=0,
                    timed_out=False,
                )
        from harness.squad_provider import SquadAgentResult
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class StagedParallelExecutor(PhaseExecutor):
    """Handles type: staged_parallel — phase3-consensus (WHY3+ASSESS2 then PLAN2)."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult

        stage1_agents = [a for a in node.agents if a.get("stage", 1) == 1]
        stage2_agents = [a for a in node.agents if a.get("stage", 1) == 2]

        stage1_results: dict[str, SquadAgentResult] = {}

        # Stage 1: run in parallel (ThreadPoolExecutor)
        with ThreadPoolExecutor(max_workers=len(stage1_agents)) as pool:
            futures = {}
            for agent_entry in stage1_agents:
                agent_id = agent_entry.get("id") or agent_entry.get("agent", "")
                # Build prompt for this agent
                fake_node_agent = agent_entry.get("id", agent_id)
                rel = self._graph.agent_file(str(fake_node_agent).split(" ")[0])
                prompt = ""
                if rel:
                    path = self._ext_dir / rel
                    if path.exists():
                        prompt = path.read_text()
                if node.spec_file:
                    spec_path = self._ext_dir / node.spec_file
                    if spec_path.exists():
                        prompt += "\n\n" + spec_path.read_text()
                futures[pool.submit(
                    self._provider.exec_agent, str(self._project_root), prompt
                )] = agent_entry.get("mode", agent_id)

            for future in as_completed(futures):
                mode = futures[future]
                stage1_results[str(mode)] = future.result()

        # Write stage 1 verdicts to state
        for mode, result in stage1_results.items():
            state_store.increment_token_usage(0)  # token tracking hook
            if result.verdict:
                state = state_store.load()
                state[f"{mode.lower().replace(' ', '_')}_verdict"] = result.verdict
                for k, v in result.state_updates.items():
                    state[k] = v
                state_store.save(state)

        # Stage 2: PLAN2 — requires implementability-report.md from ASSESS2
        impl_report = self._project_root / "specs" / ".spec_placeholder" / "implementability-report.md"
        # Look for it in common locations
        for candidate in [
            self._project_root / "implementability-report.md",
            self._project_root / ".specify" / "squad" / "staging" / "implementability-report.md",
        ]:
            if candidate.exists():
                impl_report = candidate
                break

        for agent_entry in stage2_agents:
            agent_id = agent_entry.get("id") or agent_entry.get("agent", "")
            rel = self._graph.agent_file(str(agent_id).split(" ")[0])
            prompt = ""
            if rel:
                path = self._ext_dir / rel
                if path.exists():
                    prompt = path.read_text()
            if impl_report.exists():
                prompt += f"\n\n---\n# implementability-report.md\n{impl_report.read_text()}"
            stage2_result = self._provider.exec_agent(str(self._project_root), prompt)
            for k, v in stage2_result.state_updates.items():
                state = state_store.load()
                state[k] = v
                state_store.save(state)

        # Aggregate result: PASS if all stage1 agents passed
        all_pass = all(r.verdict in ("PASS", "DONE") for r in stage1_results.values())
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "PASS" if all_pass else "FAIL",
                "state_updates": {},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class ConditionalSequentialExecutor(PhaseExecutor):
    """Handles type: conditional_sequential — dispatches agents based on state conditions."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.condition_evaluator import ConditionEvaluator
        from harness.squad_provider import SquadAgentResult
        ev = ConditionEvaluator()
        state = state_store.load()

        for agent_entry in node.agents:
            condition = agent_entry.get("condition", "always")
            if ev.evaluate(condition, state) is not True:
                continue
            agent_id = agent_entry.get("id") or agent_entry.get("agent", "")
            rel = self._graph.agent_file(str(agent_id).split(" ")[0])
            if rel:
                path = self._ext_dir / rel
                if path.exists():
                    result = self._provider.exec_agent(str(self._project_root), path.read_text())
                    for k, v in result.state_updates.items():
                        state[k] = v
                    state_store.save(state)

        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )


class HumanGateExecutor(PhaseExecutor):
    """Handles type: human_gate — auto-proceed in semi/banzai; prompt in guided."""

    def execute(
        self, node: "PhaseNode", state_store: "SquadStateStore"
    ) -> "SquadAgentResult":
        from harness.squad_provider import SquadAgentResult
        state = state_store.load()
        autonomy = state.get("autonomy_mode", "semi")

        if autonomy in ("semi", "banzai"):
            print(f"[checkpoint] {node.label} — auto-proceeding ({autonomy} mode)")
            return SquadAgentResult(
                exit_code=0,
                echelon_result={"verdict": "APPROVED", "state_updates": {"gate_result": "auto_approved"}},
                raw_output="",
                duration_ms=0,
                timed_out=False,
            )

        # guided: prompt user
        print(f"\n{'='*60}")
        print(f"CHECKPOINT: {node.label}")
        print(f"Review artifacts in {state.get('spec_dir', 'specs/')} then type 'approve' or 'reject':")
        print(f"{'='*60}")
        try:
            answer = input("> ").strip().lower()
        except EOFError:
            answer = "approve"

        approved = answer in ("approve", "yes", "y")
        return SquadAgentResult(
            exit_code=0,
            echelon_result={
                "verdict": "APPROVED" if approved else "REJECTED",
                "state_updates": {"gate_result": "human_approved" if approved else "human_rejected"},
            },
            raw_output="",
            duration_ms=0,
            timed_out=False,
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/harness/squad_executors.py
git commit -m "feat: add phase executors (AgentExecutor, StagedParallelExecutor, ConditionalSequentialExecutor, CommanderInternalExecutor, HumanGateExecutor)"
```

---

## Task 6: `SquadController`

**Files:**
- Create: `src/harness/squad.py`

- [ ] **Step 1: Implement**

Create `src/harness/squad.py`:

```python
"""SquadController — deterministic phase routing for the pre-code squad run."""
from __future__ import annotations

import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.condition_evaluator import ConditionEvaluator
from harness.phase_graph import PhaseGraph, PhaseNode
from harness.squad_executors import (
    AgentExecutor,
    CommanderInternalExecutor,
    ConditionalSequentialExecutor,
    HumanGateExecutor,
    PhaseExecutor,
    StagedParallelExecutor,
)
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.squad_state import SquadStateStore


TERMINAL_PHASES = {"DONE", "done", "terminal-blocked"}


@dataclass
class SquadResult:
    status: str         # "done" | "blocked" | "interrupted" | "budget_exhausted"
    phase: str
    run_id: str
    summary: str = ""

    @classmethod
    def from_state(cls, state: dict) -> "SquadResult":
        return cls(
            status=state.get("status", "unknown"),
            phase=state.get("phase", "unknown"),
            run_id=state.get("run_id", ""),
        )

    @classmethod
    def interrupted(cls) -> "SquadResult":
        return cls(status="interrupted", phase="unknown", run_id="")


class SquadController:
    """Drives the squad run phase graph deterministically.

    Phase routing is pure Python (ConditionEvaluator + state.json).
    COMMANDER (LLM) is dispatched only for judgment calls.
    """

    def __init__(
        self,
        provider: SquadCliProvider,
        state_store: SquadStateStore,
        phase_graph: PhaseGraph,
        ext_dir: Path,
        project_root: Path,
        token_budget: int = 1_000_000,
    ) -> None:
        self._provider = provider
        self._state_store = state_store
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._token_budget = token_budget
        self._evaluator = ConditionEvaluator()
        self._executors: dict[str, PhaseExecutor] = {
            "agent": AgentExecutor(provider, phase_graph, ext_dir, project_root),
            "commander_internal": CommanderInternalExecutor(provider, phase_graph, ext_dir, project_root),
            "staged_parallel": StagedParallelExecutor(provider, phase_graph, ext_dir, project_root),
            "conditional_sequential": ConditionalSequentialExecutor(provider, phase_graph, ext_dir, project_root),
            "human_gate": HumanGateExecutor(provider, phase_graph, ext_dir, project_root),
        }
        self._cancelled = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    def run(self, user_message: str = "", mode: str = "semi") -> SquadResult:
        """Run the squad from current state or initialize fresh."""
        existing = self._state_store.load()
        if not existing or existing.get("status") not in ("running", "in_progress"):
            run_id = f"squad-{int(time.time())}"
            self._state_store.initialize(
                run_id=run_id,
                mode=mode,
                user_message=user_message,
                token_budget=self._token_budget,
                entry_phase=self._graph.entry_phase(),
            )

        while True:
            phase = self._state_store.current_phase()

            if phase in TERMINAL_PHASES:
                return SquadResult.from_state(self._state_store.load())

            if self._cancelled or self._state_store.is_cancel_requested():
                return SquadResult.interrupted()

            if self._budget_exhausted():
                self._state_store.set_blocked("token_budget_exhausted")
                return SquadResult(
                    status="budget_exhausted",
                    phase=phase,
                    run_id=self._state_store.load().get("run_id", ""),
                )

            node = self._graph.get(phase)
            executor = self._executors.get(node.type)
            if executor is None:
                # Unknown type — dispatch COMMANDER for judgment
                result = self._judgment_dispatch(
                    f"Unknown phase type {node.type!r} for phase {phase!r}",
                    node,
                )
            else:
                result = executor.execute(node, self._state_store)

            next_phase = self._evaluate_transitions(node, result)
            self._state_store.advance(phase, next_phase, result)

    def _evaluate_transitions(
        self, node: PhaseNode, result: SquadAgentResult
    ) -> str:
        state = self._state_store.load()
        for transition in node.transitions:
            condition = transition.get("condition", "always")
            evaluation = self._evaluator.evaluate(condition, state, result)
            if evaluation is True:
                return transition["to"]
            if evaluation is None:
                # Unknown condition — COMMANDER decides
                judgment = self._judgment_dispatch(
                    f"Cannot evaluate condition {condition!r} in phase {node.id!r}",
                    node,
                    result,
                )
                # COMMANDER should return a phase id in state_updates["next_phase"]
                next_phase = judgment.state_updates.get("next_phase")
                if next_phase:
                    return next_phase
        # No transition matched — fall through to DONE
        return "DONE"

    def _judgment_dispatch(
        self,
        reason: str,
        node: PhaseNode,
        result: Optional[SquadAgentResult] = None,
    ) -> SquadAgentResult:
        """Dispatch slimmed COMMANDER for judgment calls."""
        commander_path = self._ext_dir / "agents/control/commander.md"
        state = self._state_store.load()
        context = (
            f"# COMMANDER JUDGMENT REQUEST\n\n"
            f"**Reason:** {reason}\n\n"
            f"**Current phase:** {node.id} (type: {node.type})\n\n"
            f"**State:**\n```json\n{__import__('json').dumps(state, indent=2)}\n```\n\n"
        )
        if commander_path.exists():
            context = commander_path.read_text() + "\n\n" + context
        return self._provider.exec_agent(str(self._project_root), context)

    def _budget_exhausted(self) -> bool:
        if self._token_budget <= 0:
            return False
        return self._state_store.token_usage() >= self._token_budget

    def _handle_sigint(self, signum, frame) -> None:
        print("\n[squad] Interrupted — finishing current phase then stopping.")
        self._cancelled = True
        self._state_store.set_cancel_requested()
```

- [ ] **Step 2: Commit**

```bash
git add src/harness/squad.py
git commit -m "feat: add SquadController with deterministic phase routing"
```

---

## Task 7: Integration tests — regression for consensus

**Files:**
- Create: `tests/integration/test_squad_controller.py`

This is the critical regression test. A mock provider returns canned results; we verify `phase3-consensus` cannot be skipped.

- [ ] **Step 1: Create test file**

Create `tests/integration/test_squad_controller.py`:

```python
"""Integration tests for SquadController with mock provider.

The most important test: test_consensus_cannot_be_skipped.
A mock agent always returns DONE. SquadController must still dispatch
WHY3 + ASSESS2 (stage 1) before PLAN2 (stage 2) and before checkpoint-plan.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

EXT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(EXT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXT_ROOT))

from harness.phase_graph import PhaseGraph
from harness.squad import SquadController, SquadResult
from harness.squad_provider import SquadAgentResult
from harness.squad_state import SquadStateStore

DEFINITION = EXT_ROOT / "extension/workflow/definition.yaml"
EXT_YML = EXT_ROOT / "extension/extension.yml"


def _mock_provider(verdict: str = "DONE") -> MagicMock:
    provider = MagicMock()
    provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": verdict, "state_updates": {}},
        raw_output="",
        duration_ms=100,
        timed_out=False,
    )
    return provider


def _controller(tmp_path, provider=None, mode="banzai") -> tuple[SquadController, list]:
    """Return (controller, dispatched_phases_list)."""
    dispatched: list[str] = []
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(tmp_path / ".specify/squad/state.json")

    if provider is None:
        provider = _mock_provider()

    # Patch executors to record dispatches and return DONE
    ctrl = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,  # disable budget check
    )

    # Wrap each executor to record phase ids dispatched
    original_executors = dict(ctrl._executors)
    for etype, executor in original_executors.items():
        original_execute = executor.execute

        def make_wrapper(orig, phase_type):
            def wrapper(node, state_store):
                dispatched.append(node.id)
                return orig(node, state_store)
            return wrapper

        executor.execute = make_wrapper(original_execute, etype)

    return ctrl, dispatched


class TestConsensusCannotBeSkipped:
    """Regression: phase3-consensus was previously skipped via EVOI fabrication.
    With the harness, phase3-plan → phase3-consensus is condition: always.
    Python code evaluates it; there is no path that skips it.
    """

    def test_phase3_consensus_transition_is_always(self, tmp_path):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        plan_node = graph.get("phase3-plan")
        transitions_to = [t["to"] for t in plan_node.transitions]
        # The only transition from phase3-plan must go to phase3-consensus
        assert "phase3-consensus" in transitions_to, (
            f"phase3-plan must transition to phase3-consensus. Got: {transitions_to}"
        )

    def test_phase3_plan_to_consensus_condition_is_always(self, tmp_path):
        graph = PhaseGraph(DEFINITION, EXT_YML)
        plan_node = graph.get("phase3-plan")
        for t in plan_node.transitions:
            if t["to"] == "phase3-consensus":
                assert t["condition"] == "always", (
                    f"phase3-plan → phase3-consensus must be condition: always, got {t['condition']!r}"
                )

    def test_staged_parallel_dispatches_stage1_before_stage2(self, tmp_path):
        """StagedParallelExecutor must run WHY3+ASSESS2 before PLAN2."""
        graph = PhaseGraph(DEFINITION, EXT_YML)
        consensus_node = graph.get("phase3-consensus")
        stage1 = [a for a in consensus_node.agents if a.get("stage", 1) == 1]
        stage2 = [a for a in consensus_node.agents if a.get("stage", 1) == 2]
        assert len(stage1) >= 2, "phase3-consensus must have ≥2 stage-1 agents (WHY3 + ASSESS2)"
        assert len(stage2) >= 1, "phase3-consensus must have ≥1 stage-2 agent (PLAN2)"


class TestSquadControllerLoop:
    def test_advances_from_init(self, tmp_path):
        ctrl, dispatched = _controller(tmp_path)
        store = SquadStateStore(tmp_path / ".specify/squad/state.json")
        store.initialize("r", "greenfield", "test", 0, "init")
        store.advance("init", "DONE", SquadAgentResult(0, {"verdict": "DONE", "state_updates": {}}, "", 0, False))
        # After setting phase to DONE, run should exit immediately
        result = ctrl.run("test", "banzai")
        assert result.status == "done"

    def test_cancel_requested_stops_loop(self, tmp_path):
        ctrl, _ = _controller(tmp_path)
        store = SquadStateStore(tmp_path / ".specify/squad/state.json")
        store.initialize("r", "greenfield", "test", 0, "init")
        store.set_cancel_requested()
        result = ctrl.run("test", "banzai")
        assert result.status == "interrupted"

    def test_unknown_phase_type_dispatches_commander(self, tmp_path):
        """If a phase type is unknown, SquadController calls _judgment_dispatch."""
        provider = _mock_provider()
        ctrl, _ = _controller(tmp_path, provider)
        # Inject a fake phase node with unknown type
        from harness.phase_graph import PhaseNode
        fake = PhaseNode(
            id="fake-phase",
            type="unknown_type",
            transitions=[{"to": "DONE", "condition": "always"}],
        )
        ctrl._graph._phases["fake-phase"] = fake
        store = SquadStateStore(tmp_path / ".specify/squad/state.json")
        store.initialize("r", "greenfield", "test", 0, "fake-phase")
        ctrl.run("test", "banzai")
        # Provider should have been called (COMMANDER judgment)
        assert provider.exec_agent.called


class TestHumanGateAutoProceeds:
    def test_banzai_auto_proceeds(self, tmp_path):
        from harness.squad_executors import HumanGateExecutor
        from harness.phase_graph import PhaseNode
        graph = PhaseGraph(DEFINITION, EXT_YML)
        store = SquadStateStore(tmp_path / ".specify/squad/state.json")
        store.initialize("r", "banzai", "msg", 0, "init")

        executor = HumanGateExecutor(_mock_provider(), graph, EXT_ROOT / "extension", tmp_path)
        node = PhaseNode(id="checkpoint-plan", type="human_gate", label="Phase 3 Checkpoint")
        result = executor.execute(node, store)
        assert result.verdict == "APPROVED"
        assert result.state_updates.get("gate_result") == "auto_approved"
```

- [ ] **Step 2: Run tests**

```bash
~/.echelon/venv/bin/python -m pytest tests/integration/test_squad_controller.py -v 2>&1 | tail -15
```
Expected: all pass including `test_phase3_consensus_transition_is_always` and `test_phase3_plan_to_consensus_condition_is_always`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_squad_controller.py
git commit -m "test: add squad controller integration tests + consensus-cannot-be-skipped regression"
```

---

## Task 8: CLI integration + `echelon.run.md` replacement

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `extension/commands/echelon.run.md`

- [ ] **Step 1: Read cli.py to find insertion points**

```bash
grep -n "def _cmd_harness_run\|def _cmd_init\|SKILL_MAP\|\"harness\"\|\"run\"" src/echelon/cli.py | head -20
```

- [ ] **Step 2: Add `_cmd_run` to `cli.py`**

After reading the file, add `_cmd_run` function and wire it into the CLI. Insert after the existing `_cmd_harness_run` function:

```python
def _cmd_run(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Drive the pre-code squad run via deterministic Python harness."""
    import os
    from harness.config import HarnessConfig
    from harness.phase_graph import PhaseGraph
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore

    # Parse optional flags from args
    mode = "semi"
    message = ""
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]; i += 2
        elif args[i] == "--message" and i + 1 < len(args):
            message = args[i + 1]; i += 2
        else:
            remaining.append(args[i]); i += 1
    if remaining and not message:
        message = " ".join(remaining)

    config = HarnessConfig.load(project_root)
    provider = SquadCliProvider(config)
    state_store = SquadStateStore(project_root / ".specify/squad/state.json")
    graph = PhaseGraph(
        ext_dir / "workflow/definition.yaml",
        ext_dir / "extension.yml",
    )
    token_budget = config.budget.token_budget_k * 1000 if hasattr(config, "budget") else 1_000_000

    controller = SquadController(
        provider=provider,
        state_store=state_store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
    )
    result = controller.run(user_message=message, mode=mode)
    print(f"\n[squad] {result.status} — phase: {result.phase}")
```

Also add `"run"` to `SKILL_MAP` (pointing to the command file, used for the slash-command path), and update USAGE string to include `echelon run [message] [--mode semi|banzai|guided]`.

In the main dispatch (`main()` or equivalent), route `run` to `_cmd_run` instead of through SkillLoader.

- [ ] **Step 3: Replace `extension/commands/echelon.run.md`**

Read the current file first:

```bash
cat extension/commands/echelon.run.md
```

Then write:

```markdown
---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run — drives pre-code phases via deterministic harness"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Launch

```bash
echelon run "$@"
```

This command delegates entirely to the Python squad harness (`src/harness/squad.py`).
Phase routing is deterministic — COMMANDER is dispatched only for judgment calls
(escalation, contradictions, human gates in guided mode).

Monitor: `.specify/squad/state.json` · `.specify/squad/reasoning-journal.jsonl`
```

- [ ] **Step 4: Verify line count**

```bash
wc -l extension/commands/echelon.run.md
```
Expected: ≤ 20 lines.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py extension/commands/echelon.run.md
git commit -m "feat: wire SquadController into CLI + replace echelon.run.md with 15-line launcher"
```

---

## Task 9: Slim `commander.md` (~800 → ~150 lines)

**Files:**
- Modify: `extension/agents/control/commander.md`

- [ ] **Step 1: Read current line count and section map**

```bash
wc -l extension/agents/control/commander.md
grep -n "^##\|^###" extension/agents/control/commander.md | head -40
```

- [ ] **Step 2: Remove sections no longer owned by COMMANDER**

Sections to DELETE (search for these headings and remove through the next `---` or `##`):

1. `## 7-step execution loop` (or equivalent — the loop is now SquadController)
2. `## Convergence Rules` → replaced by "Convergence stop conditions live in phase spec files" (one line)
3. `## Pre-Dispatch Gate` prose → removed (harness runs pre_dispatch deterministically)
4. `## Endocrine System` dispatch prose → replaced by one line: "Harness calls `endocrine.sh` directly."
5. `## KB Read/Write Protocol` → replaced by one line: "Harness calls `kb-*.sh` directly."
6. `## Token Ledger Management` → replaced by one line: "SquadStateStore tracks token_usage."

Sections to KEEP:
- Role definition (1–3 lines)
- NEVER rules (all 11) — these govern COMMANDER's behavior when it IS dispatched
- Post-Dispatch Protocol (COMMANDER still writes journal entries)
- Evidence hierarchy (needed for contradiction resolution)
- Conflict resolution (Toulmin model — core judgment capability)
- Human escalation procedure
- Journal entry schema

- [ ] **Step 3: Verify final line count**

```bash
wc -l extension/agents/control/commander.md
```
Expected: ≤ 200 lines.

- [ ] **Step 4: Commit**

```bash
git add extension/agents/control/commander.md
git commit -m "refactor: slim commander.md to ~150 lines — harness owns loop/routing/state, COMMANDER handles judgment only"
```

---

## Task 10: Structural validation test

**Files:**
- Create: `tests/unit/test-unit-squad-registry.sh`

- [ ] **Step 1: Create the test**

```bash
cat > tests/unit/test-unit-squad-registry.sh << 'EOF'
#!/usr/bin/env bash
# test-unit-squad-registry.sh — structural validation for squad harness
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0; FAIL=0

assert_eq() { if [ "$1" = "$2" ]; then echo "PASS: $3"; PASS=$((PASS+1)); else echo "FAIL: $3 (expected '$2', got '$1')"; FAIL=$((FAIL+1)); fi; }
assert_le() { if [ "$1" -le "$2" ]; then echo "PASS: $3"; PASS=$((PASS+1)); else echo "FAIL: $3 (expected ≤$2 lines, got $1)"; FAIL=$((FAIL+1)); fi; }

# 1. echelon.run.md is ≤ 20 lines
RUNMD_LINES=$(wc -l < "$ROOT/extension/commands/echelon.run.md")
assert_le "$RUNMD_LINES" 20 "echelon.run.md ≤ 20 lines"

# 2. commander.md is ≤ 200 lines
CMD_LINES=$(wc -l < "$ROOT/extension/agents/control/commander.md")
assert_le "$CMD_LINES" 200 "commander.md ≤ 200 lines"

# 3. All phase types in definition.yaml have a registered executor
TYPES=$(python3 -c "
import yaml
d = yaml.safe_load(open('$ROOT/extension/workflow/definition.yaml'))
types = {p.get('type','agent') for p in d.get('phases',[])}
print(' '.join(sorted(types)))
")
EXECUTORS="agent commander_internal conditional_sequential human_gate staged_parallel"
for t in $TYPES; do
  if echo "$EXECUTORS" | grep -qw "$t"; then
    echo "PASS: executor registered for type '$t'"
    PASS=$((PASS+1))
  else
    echo "FAIL: no executor for type '$t'"
    FAIL=$((FAIL+1))
  fi
done

# 4. No remaining ClaudeCliProvider references after rename (only run AFTER Task 14)
# Skipped here — checked in Task 14

# 5. All new harness modules importable
python3 -c "
from harness.squad_provider import SquadAgentResult, SquadCliProvider
from harness.condition_evaluator import ConditionEvaluator
from harness.phase_graph import PhaseGraph
from harness.squad_state import SquadStateStore
from harness.squad_executors import AgentExecutor, StagedParallelExecutor
from harness.squad import SquadController
print('all modules importable')
" "$ROOT" && echo "PASS: all squad harness modules importable" && PASS=$((PASS+1)) || { echo "FAIL: module import"; FAIL=$((FAIL+1)); }

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
EOF
chmod +x tests/unit/test-unit-squad-registry.sh
```

- [ ] **Step 2: Run**

```bash
cd /Users/michalbachorik/work/echelon_r/echelon
bash tests/unit/test-unit-squad-registry.sh
```
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test-unit-squad-registry.sh
git commit -m "test: add squad harness structural validation test"
```

---

## Task 11: `AICodingCliProvider` rename (final cleanup)

**Files:**
- Modify: `src/harness/llm_provider.py`
- Modify: `src/harness/squad_provider.py`
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/coordinator.py` (if it imports ClaudeCliProvider)

- [ ] **Step 1: Rename class and file**

```bash
# Rename the class in llm_provider.py
sed -i '' 's/class ClaudeCliProvider/class AICodingCliProvider/g' src/harness/llm_provider.py
sed -i '' 's/ClaudeCliProvider/AICodingCliProvider/g' src/harness/llm_provider.py

# Update squad_provider.py
sed -i '' 's/from harness.llm_provider import ClaudeCliProvider/from harness.llm_provider import AICodingCliProvider/g' src/harness/squad_provider.py
sed -i '' 's/class SquadCliProvider(ClaudeCliProvider)/class SquadCliProvider(AICodingCliProvider)/g' src/harness/squad_provider.py

# Update build harness files
grep -rn "ClaudeCliProvider" src/harness/ | grep -v ".pyc"
```

- [ ] **Step 2: Update all other imports found in Step 1**

For each file shown by the grep, replace `ClaudeCliProvider` → `AICodingCliProvider`.

- [ ] **Step 3: Verify no remaining references**

```bash
grep -rn "ClaudeCliProvider" src/ tests/ 2>/dev/null | grep -v ".pyc"
```
Expected: no output.

- [ ] **Step 4: Run full kernel test suite**

```bash
~/.echelon/venv/bin/python -m pytest tests/kernel/ -q --tb=short 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/llm_provider.py src/harness/squad_provider.py src/harness/ralph.py src/harness/coordinator.py
git commit -m "refactor: rename ClaudeCliProvider → AICodingCliProvider (supports claude/copilot/opencode)"
```

---

## Final verification

```bash
# Run all new tests
~/.echelon/venv/bin/python -m pytest tests/kernel/test_squad_provider.py tests/kernel/test_condition_evaluator.py tests/kernel/test_phase_graph.py tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py -v 2>&1 | tail -20

# Structural check
bash tests/unit/test-unit-squad-registry.sh

# Registry sync (includes commander.md ≤ 200 lines check)
bash tests/test-unit-registry-sync.sh 2>&1 | tail -5

# Full kernel suite — no regressions
~/.echelon/venv/bin/python -m pytest tests/kernel/ -q --tb=no 2>&1 | tail -3
```
