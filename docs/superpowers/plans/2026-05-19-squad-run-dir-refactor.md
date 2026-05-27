# Squad Run Directory Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move squad artifacts from gitignored `.specify/squad/` to a git-tracked `squad/<run-id>/` directory at project root, with one directory per run, automatic `.gitignore` for ephemeral state, path injection into agent prompts, and an `echelon land` archive step that moves the run directory into `specs/<id>/squad/`.

**Architecture:** Three coupled changes: (1) `SquadStateStore` switches from a single flat state path to a per-run directory it owns; (2) `_assemble_prompt()` injects `SQUAD_DIR`/`STAGING_DIR` into every agent prompt and translates the 88 legacy `.specify/squad` references at runtime so no phase spec file needs editing; (3) `_cmd_run` handles run-dir selection (new vs resume vs reset) and `_cmd_land` gains an archive step. Run IDs are human-readable timestamps (`run-20260519-1915`). A `squad/.current` file (gitignored) points to the active run.

**Tech Stack:** Python 3.11, pathlib, existing harness (squad_state.py, squad_executors.py, squad.py, cli.py), pytest.

---

## File Map

| File | Change |
|---|---|
| `src/harness/squad_state.py` | Constructor takes `squad_dir: Path`; adds `squad_dir`/`staging_dir` to state; new properties |
| `src/harness/squad_executors.py` | `PhaseExecutor.__init__` gains `squad_dir`; `_write_journal_entries` uses it; `_assemble_prompt` injects context + translates paths |
| `src/harness/squad.py` | `SquadController.__init__` gains `squad_dir`; passes to executors; `_write_journal_entries` uses `state_store.squad_dir`; `run()` simplified |
| `src/echelon/cli.py` | New helpers `_select_squad_dir`, `_setup_run_dir`, `_find_current_run_dir`; `_cmd_run` wired; `_cmd_land` gains archive prompt |
| `tests/kernel/test_squad_state.py` | Update all path references |
| `tests/kernel/test_squad_executors_journal.py` | Update all path references |
| `tests/integration/test_squad_controller.py` | Update fixture helper |

---

## Task 1: SquadStateStore — squad_dir-based constructor

**Files:**
- Modify: `src/harness/squad_state.py`
- Test: `tests/kernel/test_squad_state.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/kernel/test_squad_state.py — add to existing test file

def test_store_creates_squad_and_staging_dirs(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    assert (squad_dir).exists()
    assert (squad_dir / "staging").exists()

def test_state_path_is_inside_squad_dir(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("r1", "semi", "msg", 0, "init")
    assert (squad_dir / "state.json").exists()

def test_initialize_writes_squad_and_staging_paths(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    store.initialize("r1", "semi", "msg", 0, "init")
    state = store.load()
    assert state["squad_dir"] == str(squad_dir)
    assert state["staging_dir"] == str(squad_dir / "staging")

def test_squad_dir_property(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    assert store.squad_dir == squad_dir

def test_staging_dir_property(tmp_path):
    from harness.squad_state import SquadStateStore
    squad_dir = tmp_path / "squad" / "run-test"
    store = SquadStateStore(squad_dir)
    assert store.staging_dir == squad_dir / "staging"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/michalbachorik/work/echelon_r/echelon
pytest tests/kernel/test_squad_state.py::test_store_creates_squad_and_staging_dirs -v
```
Expected: `FAILED` — `SquadStateStore` still takes `state_path`.

- [ ] **Step 3: Replace SquadStateStore constructor**

```python
# src/harness/squad_state.py — replace __init__ and add properties

class SquadStateStore:
    def __init__(self, squad_dir: Path) -> None:
        self._squad_dir = squad_dir
        self._path = squad_dir / "state.json"
        self._staging_dir = squad_dir / "staging"
        self._squad_dir.mkdir(parents=True, exist_ok=True)
        self._staging_dir.mkdir(parents=True, exist_ok=True)

    @property
    def squad_dir(self) -> Path:
        return self._squad_dir

    @property
    def staging_dir(self) -> Path:
        return self._staging_dir
```

- [ ] **Step 4: Add squad_dir + staging_dir to initialize()**

In `initialize()`, add two fields to the saved dict:
```python
"squad_dir": str(self._squad_dir),
"staging_dir": str(self._staging_dir),
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/kernel/test_squad_state.py -v
```
Expected: all new tests PASS; existing tests may FAIL on path assumptions — fix them in Step 6.

- [ ] **Step 6: Update existing test helpers**

In `tests/kernel/test_squad_state.py`, every helper that creates a `SquadStateStore` passes `state_path`. Change them:

```python
# Before
def _store(tmp_path: Path) -> SquadStateStore:
    return SquadStateStore(tmp_path / ".specify/squad/state.json")

# After
def _store(tmp_path: Path) -> SquadStateStore:
    return SquadStateStore(tmp_path / "squad/run-test")
```

- [ ] **Step 7: Run all kernel tests**

```bash
pytest tests/kernel/test_squad_state.py -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/harness/squad_state.py tests/kernel/test_squad_state.py
git commit -m "refactor: SquadStateStore takes squad_dir, writes squad/staging paths to state"
```

---

## Task 2: Run-dir management utilities in cli.py

**Files:**
- Modify: `src/echelon/cli.py` (add helpers before `_cmd_run`)

These are pure functions with no external dependencies — no separate test file needed; they are exercised through `_cmd_run` integration paths in Task 5.

- [ ] **Step 1: Add `_make_run_id()`**

```python
# src/echelon/cli.py — add before _cmd_run

def _make_run_id() -> str:
    from datetime import datetime
    return f"run-{datetime.now().strftime('%Y%m%d-%H%M')}"


def _setup_run_dir(project_root: Path, run_id: str) -> Path:
    """Create squad/<run_id>/ + staging/, write squad/.gitignore, update .current."""
    squad_root = project_root / "squad"
    squad_root.mkdir(exist_ok=True)

    gitignore = squad_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*/state.json\n*/*.tmp\n.current\n")

    run_dir = squad_root / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "staging").mkdir(exist_ok=True)

    (squad_root / ".current").write_text(run_id)
    return run_dir


def _find_current_run_dir(project_root: Path) -> "Optional[Path]":
    """Return the active run dir from squad/.current, or None."""
    current_file = project_root / "squad" / ".current"
    if not current_file.exists():
        return None
    run_id = current_file.read_text().strip()
    if not run_id:
        return None
    run_dir = project_root / "squad" / run_id
    return run_dir if run_dir.exists() else None


def _select_squad_dir(
    project_root: Path,
    user_message: str,
    reset: bool = False,
) -> tuple[Path, bool]:
    """Return (squad_dir, is_fresh_start).

    is_fresh_start=True  → caller should initialize state (new run).
    is_fresh_start=False → caller should resume (existing run dir, same task).
    """
    import json as _json

    if reset:
        return _setup_run_dir(project_root, _make_run_id()), True

    existing_dir = _find_current_run_dir(project_root)
    if not existing_dir:
        return _setup_run_dir(project_root, _make_run_id()), True

    try:
        state = _json.loads((existing_dir / "state.json").read_text())
    except Exception:
        return _setup_run_dir(project_root, _make_run_id()), True

    status = state.get("status")
    if status not in ("running", "in_progress"):
        return _setup_run_dir(project_root, _make_run_id()), True

    # Different task → new run dir (preserves old one, doesn't overwrite)
    if user_message and user_message != state.get("user_message", ""):
        return _setup_run_dir(project_root, _make_run_id()), True

    # Same task, resumable status → resume in existing dir
    return existing_dir, False
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import sys; sys.path.insert(0,'src'); from echelon.cli import _make_run_id, _setup_run_dir, _find_current_run_dir, _select_squad_dir; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/echelon/cli.py
git commit -m "feat: squad run-dir management helpers (_make_run_id, _setup_run_dir, _select_squad_dir)"
```

---

## Task 3: PhaseExecutor — add squad_dir, update journal path + prompt translation

**Files:**
- Modify: `src/harness/squad_executors.py`
- Test: `tests/kernel/test_squad_executors_journal.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/kernel/test_squad_executors_journal.py — add after existing tests

def test_journal_written_to_squad_dir(tmp_path):
    """Journal entries go to squad_dir/reasoning-journal.jsonl, not .specify/squad."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ex = _executor(tmp_path, squad_dir=squad_dir)
    ex._write_journal_entries(_result(entries=[{"type": "insight"}]), "phase1-a")
    journal = squad_dir / "reasoning-journal.jsonl"
    assert journal.exists()
    assert not (tmp_path / ".specify/squad/reasoning-journal.jsonl").exists()

def test_assemble_prompt_injects_squad_context(tmp_path):
    """_assemble_prompt prepends SQUAD_DIR and STAGING_DIR to the prompt."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    ex = _executor(tmp_path, squad_dir=squad_dir)
    node = _node("init")
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)
    assert str(squad_dir) in prompt
    assert "STAGING_DIR" in prompt

def test_assemble_prompt_translates_legacy_paths(tmp_path):
    """Legacy .specify/squad/staging/ references in spec content are replaced."""
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    (squad_dir / "staging").mkdir()
    ext_dir = tmp_path / "ext"
    ext_dir.mkdir()
    spec_dir = ext_dir / "workflow" / "phases"
    spec_dir.mkdir(parents=True)
    (spec_dir / "test.md").write_text("Write outputs to .specify/squad/staging/")
    from harness.phase_graph import PhaseNode
    node = PhaseNode(id="test", type="agent", spec_file="workflow/phases/test.md")
    provider = MagicMock()
    graph = MagicMock()
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = []
    from harness.squad_executors import AgentExecutor
    ex = AgentExecutor(provider, graph, ext_dir, tmp_path, squad_dir)
    state = {"squad_dir": str(squad_dir), "staging_dir": str(squad_dir / "staging")}
    prompt = ex._assemble_prompt(node, state)
    assert ".specify/squad/staging/" not in prompt
    assert str(squad_dir / "staging") in prompt
```

Update the `_executor` helper to accept `squad_dir`:
```python
def _executor(tmp_path: Path, squad_dir: Path = None) -> AgentExecutor:
    if squad_dir is None:
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
    provider = MagicMock()
    graph = MagicMock(spec=PhaseGraph)
    graph.agent_file.return_value = None
    graph.all_phase_ids.return_value = ["init", "phase1-discover", "DONE"]
    return AgentExecutor(
        provider=provider,
        phase_graph=graph,
        ext_dir=tmp_path / "ext",
        project_root=tmp_path,
        squad_dir=squad_dir,
    )
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/kernel/test_squad_executors_journal.py::test_journal_written_to_squad_dir -v
```
Expected: FAILED — `AgentExecutor` doesn't accept `squad_dir`.

- [ ] **Step 3: Add `squad_dir` to `PhaseExecutor.__init__`**

```python
class PhaseExecutor(ABC):
    def __init__(
        self,
        provider: "SquadCliProvider",
        phase_graph: "PhaseGraph",
        ext_dir: Path,
        project_root: Path,
        squad_dir: Optional[Path] = None,
    ) -> None:
        self._provider = provider
        self._graph = phase_graph
        self._ext_dir = ext_dir
        self._project_root = project_root
        self._squad_dir = squad_dir or (project_root / ".specify/squad")
```

- [ ] **Step 4: Update `_write_journal_entries` to use `self._squad_dir`**

```python
def _write_journal_entries(self, result, phase_id):
    ...
    journal_path = self._squad_dir / "reasoning-journal.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    ...
    # Remove the old hardcoded line:
    # journal_path = self._project_root / ".specify/squad/reasoning-journal.jsonl"
```

- [ ] **Step 5: Update `_assemble_prompt` to inject context + translate legacy paths**

Add at the end of `_assemble_prompt`, before `return`:

```python
    prompt = "\n\n".join(parts)

    # Inject squad run context so agents know where to write
    squad_dir_str = state.get("squad_dir", str(self._squad_dir))
    staging_dir_str = state.get("staging_dir", str(self._squad_dir / "staging"))
    context_preamble = (
        f"# Squad Run Context\n"
        f"SQUAD_DIR={squad_dir_str}\n"
        f"STAGING_DIR={staging_dir_str}\n"
        f"PROJECT_ROOT={self._project_root}\n\n"
    )

    # Translate legacy .specify/squad paths so phase spec files need no edits
    prompt = prompt.replace(".specify/squad/staging/", f"{staging_dir_str}/")
    prompt = prompt.replace(".specify/squad/staging", staging_dir_str)
    prompt = prompt.replace(".specify/squad/", f"{squad_dir_str}/")
    prompt = prompt.replace(".specify/squad", squad_dir_str)

    return context_preamble + prompt
```

- [ ] **Step 6: Propagate `squad_dir` through all executor constructors**

Every place `AgentExecutor(provider, graph, ext_dir, project_root)` is called, add `squad_dir`:

```python
# In SquadController.__init__ — Task 4 handles this.
# In ConditionalSequentialExecutor, StagedParallelExecutor,
# HumanGateExecutor, CommanderInternalExecutor — all inherit PhaseExecutor,
# no change needed as long as __init__ passes through.
```

Verify all subclasses call `super().__init__()` or use `PhaseExecutor.__init__` directly — they do (no custom `__init__` in any subclass).

- [ ] **Step 7: Run tests**

```bash
pytest tests/kernel/test_squad_executors_journal.py -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/harness/squad_executors.py tests/kernel/test_squad_executors_journal.py
git commit -m "refactor: PhaseExecutor uses squad_dir for journal path + translates legacy .specify/squad paths in prompts"
```

---

## Task 4: SquadController — thread squad_dir through

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/integration/test_squad_controller.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_squad_controller.py — add to TestSquadControllerBasics

def test_journal_written_to_squad_dir_not_specify(tmp_path):
    squad_dir = tmp_path / "squad" / "run-test"
    squad_dir.mkdir(parents=True)
    ctrl, store = _controller(tmp_path, squad_dir=squad_dir)
    store.initialize("r", "banzai", "msg", 0, "init", max_iterations=5)
    # Make an agent return a journal entry
    from harness.squad_provider import SquadAgentResult
    ctrl._provider.exec_agent.return_value = SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": {},
                        "journal_entries": [{"type": "insight"}]},
        raw_output="", duration_ms=0, timed_out=False,
    )
    ctrl.run("msg", "banzai")
    assert (squad_dir / "reasoning-journal.jsonl").exists()
    assert not (tmp_path / ".specify/squad/reasoning-journal.jsonl").exists()
```

Update `_controller` helper to accept `squad_dir`:
```python
def _controller(tmp_path: Path, provider=None, mode: str = "banzai", squad_dir: Path = None):
    if squad_dir is None:
        squad_dir = tmp_path / "squad" / "run-test"
        squad_dir.mkdir(parents=True, exist_ok=True)
        (squad_dir / "staging").mkdir(exist_ok=True)
    graph = PhaseGraph(DEFINITION, EXT_YML)
    store = SquadStateStore(squad_dir)
    if provider is None:
        provider = _mock_provider()
    ctrl = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=EXT_ROOT / "extension",
        project_root=tmp_path,
        token_budget=0,
        squad_dir=squad_dir,
    )
    return ctrl, store
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/integration/test_squad_controller.py::TestSquadControllerBasics::test_journal_written_to_squad_dir_not_specify -v
```
Expected: FAILED — `SquadController` doesn't accept `squad_dir`.

- [ ] **Step 3: Add `squad_dir` to `SquadController.__init__`**

```python
def __init__(
    self,
    provider: SquadCliProvider,
    state_store: SquadStateStore,
    phase_graph: PhaseGraph,
    ext_dir: Path,
    project_root: Path,
    token_budget: int = 0,
    max_iterations: int = 5,
    squad_dir: Optional[Path] = None,
) -> None:
    ...
    self._squad_dir = squad_dir or state_store.squad_dir
    self._executors: dict[str, PhaseExecutor] = {
        "agent": AgentExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
        "commander_internal": CommanderInternalExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
        "staged_parallel": StagedParallelExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
        "conditional_sequential": ConditionalSequentialExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
        "human_gate": HumanGateExecutor(provider, phase_graph, ext_dir, project_root, self._squad_dir),
    }
```

- [ ] **Step 4: Update `SquadController._write_journal_entries` to use `self._squad_dir`**

```python
def _write_journal_entries(self, result: SquadAgentResult, phase_id: str) -> None:
    ...
    journal_path = self._squad_dir / "reasoning-journal.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    ...
    # Remove: journal_path = self._project_root / ".specify/squad/reasoning-journal.jsonl"
```

- [ ] **Step 5: Simplify `SquadController.run()` — remove message comparison**

The message-vs-task comparison and "new task → fresh start" logic moves to `_cmd_run` (Task 5). `SquadController.run()` only needs to know: does existing state exist and is it resumable?

Remove the `new_message_provided` and `resumable` block. Replace with:

```python
existing = self._state_store.load()
existing_status = existing.get("status") if existing else None
blocked_reason = (existing.get("blocked_reason") or "") if existing else ""
force_resume = False

# Recovery: budget bumped / invalid phase / escalation block
# ... keep all existing recovery blocks unchanged ...

# Fresh start if no state or not resumable (run-dir was already chosen correctly by _cmd_run)
if not existing or existing_status not in ("running", "in_progress"):
    run_id = f"squad-{int(time.time())}"
    self._state_store.initialize(
        run_id=run_id,
        mode=mode,
        user_message=user_message,
        token_budget=self._token_budget,
        entry_phase=self._graph.entry_phase(),
        max_iterations=self._max_iterations,
    )
else:
    print(f"[squad] resuming from phase: {self._state_store.current_phase()}", flush=True)
    state = self._state_store.load()
    if state.get("cancel_requested"):
        state["cancel_requested"] = False
        self._state_store.save(state)
```

Remove the `new_message_provided` announcement print — that message now comes from `_cmd_run`.

- [ ] **Step 6: Update existing test helpers**

In `tests/integration/test_squad_controller.py`, all existing `_controller()` calls need no change if the default `squad_dir=None` falls back to `state_store.squad_dir`.

Verify: run full suite.

```bash
pytest tests/integration/test_squad_controller.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py
git commit -m "refactor: SquadController accepts squad_dir, threads it to executors and journal writes; run() simplified"
```

---

## Task 5: Wire _cmd_run to use run-dir selection

**Files:**
- Modify: `src/echelon/cli.py`

- [ ] **Step 1: Replace `_cmd_run` state store setup**

Find the block that creates `state_store` and `SquadController`:

```python
# BEFORE (current code):
    state_store = SquadStateStore(project_root / ".specify/squad/state.json")

# AFTER:
    squad_dir, is_fresh = _select_squad_dir(project_root, message, reset=reset)
    if is_fresh and reset:
        print("[squad] state reset — starting fresh", flush=True)
    elif is_fresh and message:
        existing_dir = _find_current_run_dir(project_root)
        if existing_dir and existing_dir != squad_dir:
            print(
                f"[squad] new task — starting fresh in {squad_dir.name} "
                f"(previous run preserved at {existing_dir.name})",
                flush=True,
            )
    state_store = SquadStateStore(squad_dir)
```

Remove the old `reset` block (the one that called `state_path.unlink()`) since `_select_squad_dir` handles it.

- [ ] **Step 2: Update SquadController construction**

```python
    controller = SquadController(
        provider=provider,
        state_store=state_store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
    )
    result = controller.run(user_message=message, mode=mode, next_phase_override=next_phase)
    print(f"\n[squad] {result.status} — phase: {result.phase}")
    print(f"[squad] artifacts: {squad_dir}")
```

- [ ] **Step 3: Smoke test**

```bash
python3 -c "
import sys, tempfile, pathlib
sys.path.insert(0,'src')
from echelon.cli import _select_squad_dir, _find_current_run_dir
with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    sd, fresh = _select_squad_dir(root, 'task 1')
    assert fresh
    assert sd.exists()
    assert (sd / 'staging').exists()
    assert (root / 'squad' / '.current').exists()
    sd2, fresh2 = _select_squad_dir(root, 'task 1')   # same task → resume
    assert not fresh2
    assert sd2 == sd
    sd3, fresh3 = _select_squad_dir(root, 'task 2')   # different task → new dir
    assert fresh3
    assert sd3 != sd
    print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Run full suite**

```bash
pytest tests/kernel/ tests/integration/test_squad_controller.py -q
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py
git commit -m "refactor: _cmd_run uses _select_squad_dir — per-run squad/<id>/ directories"
```

---

## Task 6: Update echelon.run.md monitor path + squad/.gitignore doc

**Files:**
- Modify: `extension/commands/echelon.run.md`

- [ ] **Step 1: Update Step 3 monitor note**

```markdown
# BEFORE:
Monitor: `.specify/squad/state.json` · `.specify/squad/reasoning-journal.jsonl`

# AFTER:
Monitor: `squad/<run-id>/state.json` · `squad/<run-id>/reasoning-journal.jsonl`
Run `cat squad/.current` to get the active run ID.

Note: `squad/` is git-tracked (minus `state.json` per `squad/.gitignore`).
Staging artifacts in `squad/<run-id>/staging/` are versioned — commit after
each significant phase to enable rollback.
```

- [ ] **Step 2: Commit**

```bash
git add extension/commands/echelon.run.md
git commit -m "docs: update echelon.run.md to reference squad/<run-id>/ paths"
```

---

## Task 7: echelon land archive step

**Files:**
- Modify: `src/echelon/cli.py` (`_cmd_land`)
- Modify: `src/harness/land.py` (or wherever land logic is) — check actual location

- [ ] **Step 1: Locate land logic**

```bash
grep -n "def land\|merge\|branch" src/harness/land.py | head -10
```

Note the return value and what state the repo is in after `land()` returns.

- [ ] **Step 2: Add `_archive_squad_run()` helper to cli.py**

```python
def _archive_squad_run(project_dir: Path, spec_id: str) -> None:
    """Offer to archive the active squad run into specs/<spec_id>-*/squad/."""
    from harness.spec_frontmatter import find_spec_dir
    import shutil

    current_file = project_dir / "squad" / ".current"
    if not current_file.exists():
        return

    run_id = current_file.read_text().strip()
    run_dir = project_dir / "squad" / run_id
    if not run_dir.exists():
        return

    spec_dir = find_spec_dir(spec_id, project_dir)
    if spec_dir is None:
        print(f"  (squad archive skipped — spec {spec_id!r} dir not found)", flush=True)
        return

    archive_dest = spec_dir / "squad"
    print(
        f"\nArchive squad run {run_id!r} into {spec_dir.relative_to(project_dir)}/squad/ ?"
    )
    choice = input("  [Y]es archive / [n]o keep in squad/ / [s]kip: ").strip().lower()

    if choice in ("", "y", "yes"):
        shutil.move(str(run_dir), str(archive_dest))
        current_file.unlink()
        # Stage the move for the land commit (or a follow-up commit)
        import subprocess
        subprocess.run(["git", "add", str(archive_dest)], cwd=str(project_dir), check=False)
        subprocess.run(
            ["git", "rm", "-r", "--cached", str(run_dir)],
            cwd=str(project_dir), check=False, capture_output=True
        )
        print(f"  ✓ Archived to {archive_dest.relative_to(project_dir)}", flush=True)
    elif choice in ("s", "skip"):
        print("  Skipped.", flush=True)
    else:
        print(f"  Squad run left at squad/{run_id}/", flush=True)
```

- [ ] **Step 3: Call `_archive_squad_run` at the end of `_cmd_land`**

In `_cmd_land`, after the `land()` call succeeds:

```python
    success = land(spec_id, project_dir=project_dir, gitops=gitops)
    if success:
        print(f"echelon land: {spec_id} landed successfully")
        _archive_squad_run(project_dir, spec_id)
        sys.exit(0)
```

- [ ] **Step 4: Test manually**

Create a temp project with a `squad/run-20260519-test/` and a `specs/001-test/spec.md`, then run:
```bash
python3 -c "
import sys, tempfile, pathlib, json
sys.path.insert(0, 'src')
# Create minimal test structure
from pathlib import Path
import tempfile, os
d = tempfile.mkdtemp()
root = pathlib.Path(d)
(root / 'squad').mkdir()
(root / 'squad' / 'run-20260519-test').mkdir()
(root / 'squad' / 'run-20260519-test' / 'staging').mkdir()
(root / 'squad' / '.current').write_text('run-20260519-test')
(root / 'specs').mkdir()
(root / 'specs' / '001-test').mkdir()
(root / 'specs' / '001-test' / 'spec.md').write_text('---\nid: 001\n---\n# test\n')
os.chdir(d)
from echelon.cli import _archive_squad_run
_archive_squad_run(root, '001')
print('archive_dest exists:', (root / 'specs' / '001-test' / 'squad').exists())
"
```
(Type `y` when prompted.)
Expected: `archive_dest exists: True`

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py
git commit -m "feat: echelon land offers to archive squad/<run-id>/ into specs/<id>/squad/"
```

---

## Task 8: Fix remaining test references + structural validation

**Files:**
- Modify: `tests/kernel/test_squad_executors_journal.py` (already partly done in Task 3)
- Modify: `tests/integration/test_squad_controller.py` (already partly done in Task 4)
- Modify: `tests/unit/test-unit-squad-registry.sh` — check if it references `.specify/squad`

- [ ] **Step 1: Search for any remaining `.specify/squad` references in tests**

```bash
grep -rn "\.specify/squad" tests/
```

Fix each one: replace `.specify/squad` with `squad/run-test` (for squad_dir) or `squad/run-test/staging` (for staging_dir).

- [ ] **Step 2: Check structural validation script**

```bash
grep -n "specify/squad" tests/unit/test-unit-squad-registry.sh
```

Update any hardcoded paths found.

- [ ] **Step 3: Run full suite**

```bash
pytest tests/kernel/ tests/integration/test_squad_controller.py -q
bash tests/unit/test-unit-squad-registry.sh
```
Expected: all PASS, 9/9 structural checks.

- [ ] **Step 4: Run the no-direct-journal-append test to verify it still passes**

```bash
pytest tests/kernel/test_squad_executors_journal.py::test_no_direct_journal_appends_in_phase_specs -v
```
Expected: PASS (phase specs still reference `.specify/squad/staging/` — that's fine, translation happens at runtime).

- [ ] **Step 5: Final commit**

```bash
git add tests/
git commit -m "test: update all test path references to squad/<run-id>/ layout"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Covered by |
|---|---|
| `squad/<run-id>/` at project root | Task 2, 5 |
| One directory per run | Task 2 `_setup_run_dir` |
| `squad/.gitignore` ignores `state.json` | Task 2 `_setup_run_dir` |
| `squad/.current` pointer | Task 2 |
| State machine in `squad/<run-id>/state.json` | Task 1 |
| Staging artifacts git-tracked | Follows from above (only `state.json` ignored) |
| 88 legacy path references translated without file edits | Task 3 `_assemble_prompt` |
| SQUAD_DIR/STAGING_DIR injected into every agent prompt | Task 3 `_assemble_prompt` |
| Same task = resume in existing dir | Task 2 `_select_squad_dir` |
| Different task = new dir (old preserved) | Task 2 `_select_squad_dir` |
| `--reset` = new dir | Task 5 |
| `echelon land` archives squad into `specs/<id>/squad/` | Task 7 |
| All existing tests pass | Task 8 |

**Placeholder scan:** No TBD, TODO, or "similar to" references found.

**Type consistency:** `SquadStateStore(squad_dir: Path)` used consistently across Tasks 1, 3, 4, 5. `squad_dir: Optional[Path]` default of `None` falls back to `state_store.squad_dir` in Task 4 — consistent.

**Gap found:** The `SquadController.run()` simplified in Task 4 removes the "new task announcement" print. Task 5 adds it back in `_cmd_run`. Verify the print message is present after Task 5 and covers both the `reset` case and the `new task` case.
