# Polyrepo Multi-Target Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `echelon harness run` to target one or more sub-repos from a polyrepo root, with parallel independent runs and per-repo PRs, via spec frontmatter `targets:` and walk-up spec discovery.

**Architecture:** New `src/harness/spec_frontmatter.py` handles YAML frontmatter and walk-up spec discovery. New `src/echelon/orchestrator.py` handles parallel subprocess dispatch. `cli.py` gains orchestrator mode (no local `echelon.yml` + spec has targets) and a new `echelon spec target` subcommand.

**Tech Stack:** Python 3.11, pytest, PyYAML (already a dependency), bash (e2e smoke tests).

---

## File Structure

| File | Role |
| --- | --- |
| `src/harness/spec_frontmatter.py` | NEW — `find_spec_dir()`, `read_frontmatter()`, `write_targets()` |
| `src/echelon/orchestrator.py` | NEW — `validate_targets()`, `run_multi_target()` |
| `src/echelon/cli.py` | MODIFY — orchestrator mode in `_cmd_harness_run`; new `_cmd_spec`, `_cmd_spec_target` |
| `tests/unit/test_spec_frontmatter.py` | NEW — unit tests for frontmatter parse/write |
| `tests/unit/test_find_spec_dir.py` | NEW — unit tests for walk-up discovery |
| `tests/unit/test_orchestrator.py` | NEW — orchestrator unit tests (subprocess mocked) |
| `tests/unit/test_cli_spec_target.py` | NEW — `echelon spec target` CLI unit tests |
| `tests/unit/test_harness_single_repo_unchanged.py` | NEW — regression: single-repo path untouched |
| `tests/e2e/test-e2e-spec-target-cmd.sh` | NEW — smoke: `echelon spec target` end-to-end |
| `tests/e2e/test-e2e-walk-up-spec-discovery.sh` | NEW — smoke: walk-up discovery end-to-end |
| `tests/e2e/test-e2e-orchestrator-prefixed-output.sh` | NEW — smoke: parallel orchestrator output |

---

## Task 1: `src/harness/spec_frontmatter.py`

**Files:**
- Create: `src/harness/spec_frontmatter.py`

- [ ] **Step 1: Write the file**

```python
"""Spec frontmatter: parse/write YAML front-matter in spec markdown files,
and walk-up spec directory discovery."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)


def _find_spec_md(spec_dir: Path) -> Optional[Path]:
    """Return first .md file in spec_dir (sorted), or None."""
    for p in sorted(spec_dir.glob("*.md")):
        return p
    return None


def read_frontmatter(spec_dir: Path) -> Dict[str, Any]:
    """Parse YAML frontmatter from spec_dir's first markdown file.

    Returns empty dict when no frontmatter block is present or parsing fails.
    """
    md = _find_spec_md(spec_dir)
    if md is None:
        return {}
    text = md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def write_targets(spec_dir: Path, targets: List[str]) -> Path:
    """Write (or replace) the ``targets:`` list in spec_dir's frontmatter.

    Creates a frontmatter block if none exists. Returns the modified file path.
    Preserves all other frontmatter keys.
    """
    md = _find_spec_md(spec_dir)
    if md is None:
        raise FileNotFoundError(f"No .md file found in {spec_dir}")

    text = md.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    body = text[m.end():] if m else text

    try:
        data: Dict[str, Any] = yaml.safe_load(m.group(1)) if m else {}
        data = data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        data = {}

    data["targets"] = targets
    front = yaml.dump(data, default_flow_style=False, sort_keys=False,
                      allow_unicode=True).rstrip()
    md.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")
    return md


def find_spec_dir(spec_id: str, start_dir: Path) -> Optional[Path]:
    """Walk up from start_dir to find specs/{spec_id}-* directory.

    Stops before walking into a parent directory that contains .git (git
    boundary), or at the filesystem root. Local matches (closer to start_dir)
    take precedence over parent matches.

    Args:
        spec_id: Spec numeric prefix, e.g. "024".
        start_dir: Directory to start searching from.

    Returns:
        First alphabetically-sorted matching spec directory, or None.
    """
    current = start_dir.resolve()
    while True:
        matches = sorted(current.glob(f"specs/{spec_id}-*"))
        if matches:
            return matches[0]
        parent = current.parent
        if parent == current:          # filesystem root
            break
        if (parent / ".git").exists(): # would cross into a git repo boundary
            break
        current = parent
    return None
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd /path/to/echelon
python -c "from harness.spec_frontmatter import find_spec_dir, read_frontmatter, write_targets; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/harness/spec_frontmatter.py
git commit -m "feat(harness): add spec_frontmatter module — walk-up discovery and frontmatter read/write"
```

---

## Task 2: Unit tests for `spec_frontmatter.py`

**Files:**
- Create: `tests/unit/test_spec_frontmatter.py`
- Create: `tests/unit/test_find_spec_dir.py`

- [ ] **Step 1: Write `tests/unit/test_spec_frontmatter.py`**

```python
"""Unit tests for harness.spec_frontmatter — frontmatter parse and write."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.spec_frontmatter import read_frontmatter, write_targets


def _make_spec_dir(tmp_path: Path, content: str, filename: str = "spec.md") -> Path:
    spec_dir = tmp_path / "specs" / "024-test"
    spec_dir.mkdir(parents=True)
    (spec_dir / filename).write_text(content, encoding="utf-8")
    return spec_dir


@pytest.mark.unit
class TestReadFrontmatter:
    def test_reads_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - og-platform\n---\n# Body\n")
        result = read_frontmatter(spec_dir)
        assert result["targets"] == ["og-platform"]

    def test_reads_multiple_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - repo-a\n  - repo-b\n---\n")
        assert read_frontmatter(spec_dir)["targets"] == ["repo-a", "repo-b"]

    def test_no_frontmatter_returns_empty(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# Just a spec\nNo frontmatter here.\n")
        assert read_frontmatter(spec_dir) == {}

    def test_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\n: bad: yaml: [\n---\n# body\n")
        assert read_frontmatter(spec_dir) == {}

    def test_no_md_file_returns_empty(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "024-empty"
        spec_dir.mkdir(parents=True)
        assert read_frontmatter(spec_dir) == {}

    def test_preserves_other_keys(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nid: '024'\ntargets:\n  - repo-a\n---\n")
        data = read_frontmatter(spec_dir)
        assert data["id"] == "024"
        assert data["targets"] == ["repo-a"]


@pytest.mark.unit
class TestWriteTargets:
    def test_creates_frontmatter_when_absent(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# Spec body\n")
        write_targets(spec_dir, ["og-platform"])
        data = read_frontmatter(spec_dir)
        assert data["targets"] == ["og-platform"]

    def test_replaces_existing_targets(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - old-repo\n---\n# Body\n")
        write_targets(spec_dir, ["new-repo"])
        assert read_frontmatter(spec_dir)["targets"] == ["new-repo"]

    def test_preserves_body_content(self, tmp_path: Path) -> None:
        body = "# My Spec\n\nSome content.\n"
        spec_dir = _make_spec_dir(tmp_path, f"---\ntargets:\n  - r\n---\n{body}")
        write_targets(spec_dir, ["other"])
        md = next((spec_dir).glob("*.md"))
        assert "# My Spec" in md.read_text(encoding="utf-8")

    def test_preserves_other_frontmatter_keys(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\nid: '024'\ntargets:\n  - old\n---\n")
        write_targets(spec_dir, ["new"])
        data = read_frontmatter(spec_dir)
        assert data["id"] == "024"
        assert data["targets"] == ["new"]

    def test_no_duplication_on_rewrite(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "---\ntargets:\n  - r\n---\n# body\n")
        write_targets(spec_dir, ["a", "b"])
        write_targets(spec_dir, ["c"])
        md = next(spec_dir.glob("*.md"))
        text = md.read_text(encoding="utf-8")
        assert text.count("targets:") == 1

    def test_no_md_file_raises(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "024-empty"
        spec_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            write_targets(spec_dir, ["repo"])

    def test_returns_modified_path(self, tmp_path: Path) -> None:
        spec_dir = _make_spec_dir(tmp_path, "# body\n")
        result = write_targets(spec_dir, ["r"])
        assert result.exists()
        assert result.suffix == ".md"
```

- [ ] **Step 2: Run and confirm they fail (module exists but tests haven't run yet)**

```bash
python -m pytest tests/unit/test_spec_frontmatter.py -v
```

Expected: All PASS (module already written in Task 1)

- [ ] **Step 3: Write `tests/unit/test_find_spec_dir.py`**

```python
"""Unit tests for harness.spec_frontmatter.find_spec_dir — walk-up discovery."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.spec_frontmatter import find_spec_dir


def _make_spec(parent: Path, spec_name: str) -> Path:
    spec_dir = parent / "specs" / spec_name
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# spec\n", encoding="utf-8")
    return spec_dir


@pytest.mark.unit
class TestFindSpecDir:
    def test_found_locally(self, tmp_path: Path) -> None:
        spec = _make_spec(tmp_path, "024-test")
        result = find_spec_dir("024", tmp_path)
        assert result == spec

    def test_found_one_level_up(self, tmp_path: Path) -> None:
        spec = _make_spec(tmp_path, "024-test")
        child = tmp_path / "repo-a"
        child.mkdir()
        result = find_spec_dir("024", child)
        assert result == spec

    def test_found_two_levels_up(self, tmp_path: Path) -> None:
        spec = _make_spec(tmp_path, "024-test")
        child = tmp_path / "org" / "repo-a"
        child.mkdir(parents=True)
        result = find_spec_dir("024", child)
        assert result == spec

    def test_local_takes_precedence_over_parent(self, tmp_path: Path) -> None:
        _make_spec(tmp_path, "024-parent")
        child = tmp_path / "repo-a"
        local_spec = _make_spec(child, "024-local")
        result = find_spec_dir("024", child)
        assert result == local_spec

    def test_stops_at_git_boundary_in_parent(self, tmp_path: Path) -> None:
        # P has .git — walk-up from P/A should not find P/specs/
        _make_spec(tmp_path, "024-test")
        (tmp_path / ".git").mkdir()
        child = tmp_path / "repo-a"
        child.mkdir()
        result = find_spec_dir("024", child)
        assert result is None

    def test_starts_in_git_repo_walks_up_to_non_git_parent(self, tmp_path: Path) -> None:
        # P (no .git) has specs. A (has .git) is child of P.
        spec = _make_spec(tmp_path, "024-test")
        child = tmp_path / "repo-a"
        child.mkdir()
        (child / ".git").mkdir()  # A is a git repo
        result = find_spec_dir("024", child)
        assert result == spec

    def test_not_found_returns_none(self, tmp_path: Path) -> None:
        child = tmp_path / "repo-a"
        child.mkdir()
        result = find_spec_dir("999", child)
        assert result is None

    def test_returns_first_alphabetically_when_multiple(self, tmp_path: Path) -> None:
        spec_b = _make_spec(tmp_path, "024-beta")
        spec_a = _make_spec(tmp_path, "024-alpha")
        result = find_spec_dir("024", tmp_path)
        assert result == spec_a  # alpha < beta
```

- [ ] **Step 4: Run both test files**

```bash
python -m pytest tests/unit/test_spec_frontmatter.py tests/unit/test_find_spec_dir.py -v
```

Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_spec_frontmatter.py tests/unit/test_find_spec_dir.py
git commit -m "test(harness): unit tests for spec_frontmatter and find_spec_dir"
```

---

## Task 3: `src/echelon/orchestrator.py`

**Files:**
- Create: `src/echelon/orchestrator.py`

- [ ] **Step 1: Write the file**

```python
"""Multi-target orchestrator: run 'echelon harness run' in parallel across sub-repos."""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional


_ECHELON_YML_REL = ".specify/extensions/echelon/echelon.yml"


def validate_targets(
    targets_rel: List[str],
    polyrepo_root: Path,
) -> List[Path]:
    """Resolve and validate target sub-repo paths.

    Args:
        targets_rel: List of target names/paths relative to polyrepo_root.
        polyrepo_root: Root directory of the polyrepo.

    Returns:
        List of resolved absolute target paths.

    Raises:
        SystemExit(1) with a descriptive message on the first validation failure.
    """
    resolved: List[Path] = []
    for rel in targets_rel:
        target = (polyrepo_root / rel).resolve()
        if not target.exists():
            print(
                f"✗ Target '{rel}' not found at {target}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (target / _ECHELON_YML_REL).exists():
            print(
                f"✗ {rel}: not initialised — run 'echelon harness init' inside {rel} first.",
                file=sys.stderr,
            )
            sys.exit(1)
        resolved.append(target)
    return resolved


def run_multi_target(
    spec_id: str,
    targets: List[Path],
    extra_args: List[str],
    echelon_bin: Optional[str] = None,
) -> int:
    """Run 'echelon harness run <spec_id> [extra_args]' in each target in parallel.

    Streams each target's stdout/stderr prefixed with [target-name].
    Returns 0 if all targets succeed, 1 if any fail.

    Args:
        spec_id: Spec ID to pass to each harness run.
        targets: List of resolved absolute target paths.
        extra_args: Additional CLI args to forward (e.g. ["strategy=codegen"]).
        echelon_bin: Path to echelon binary (resolved from PATH if None).
    """
    if echelon_bin is None:
        echelon_bin = shutil.which("echelon") or sys.argv[0]

    results: dict[str, int] = {}
    lock = threading.Lock()

    def _run_one(target: Path) -> None:
        name = target.name
        cmd = [echelon_bin, "harness", "run", spec_id] + extra_args
        proc = subprocess.Popen(
            cmd,
            cwd=str(target),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                sys.stdout.write(f"[{name}] {line}")
                sys.stdout.flush()
        proc.wait()
        with lock:
            results[name] = proc.returncode

    threads = [threading.Thread(target=_run_one, args=(t,)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print()
    all_ok = True
    for name in sorted(results):
        rc = results[name]
        status = "✓" if rc == 0 else "✗"
        print(f"{status} [{name}]: exit {rc}")
        if rc != 0:
            all_ok = False

    return 0 if all_ok else 1
```

- [ ] **Step 2: Verify import**

```bash
python -c "from echelon.orchestrator import validate_targets, run_multi_target; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/echelon/orchestrator.py
git commit -m "feat(echelon): add multi-target orchestrator with parallel subprocess dispatch"
```

---

## Task 4: Unit tests for `orchestrator.py`

**Files:**
- Create: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write the test file**

```python
"""Unit tests for echelon.orchestrator — validate_targets and run_multi_target."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echelon.orchestrator import run_multi_target, validate_targets

_ECHELON_YML = ".specify/extensions/echelon/echelon.yml"


def _make_target(tmp_path: Path, name: str, initialised: bool = True) -> Path:
    t = tmp_path / name
    t.mkdir()
    if initialised:
        yml = t / _ECHELON_YML
        yml.parent.mkdir(parents=True)
        yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
    return t


@pytest.mark.unit
class TestValidateTargets:
    def test_valid_targets_returned(self, tmp_path: Path) -> None:
        t = _make_target(tmp_path, "repo-a")
        result = validate_targets(["repo-a"], tmp_path)
        assert result == [t]

    def test_nonexistent_target_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc:
            validate_targets(["does-not-exist"], tmp_path)
        assert exc.value.code == 1

    def test_uninitialised_target_exits(self, tmp_path: Path) -> None:
        _make_target(tmp_path, "repo-b", initialised=False)
        with pytest.raises(SystemExit) as exc:
            validate_targets(["repo-b"], tmp_path)
        assert exc.value.code == 1

    def test_multiple_valid_targets(self, tmp_path: Path) -> None:
        a = _make_target(tmp_path, "repo-a")
        b = _make_target(tmp_path, "repo-b")
        result = validate_targets(["repo-a", "repo-b"], tmp_path)
        assert result == [a, b]


@pytest.mark.unit
class TestRunMultiTarget:
    def _fake_popen(self, outputs: dict[str, str], exit_codes: dict[str, int]):
        """Return a Popen factory that simulates per-target output."""
        import io

        call_index = {"n": 0}
        targets_order = list(outputs.keys())

        def popen_factory(cmd, cwd, stdout, stderr, text):
            name = Path(cwd).name
            mock = MagicMock()
            lines = outputs.get(name, "").splitlines(keepends=True)
            mock.stdout = iter(lines)
            mock.returncode = exit_codes.get(name, 0)
            mock.wait.return_value = None
            return mock

        return popen_factory

    def test_all_succeed_returns_zero(self, tmp_path: Path) -> None:
        targets = [tmp_path / "a", tmp_path / "b"]
        for t in targets:
            t.mkdir()
        outputs = {"a": "line1\n", "b": "line2\n"}
        exit_codes = {"a": 0, "b": 0}
        with patch("subprocess.Popen", side_effect=self._fake_popen(outputs, exit_codes)):
            rc = run_multi_target("024", targets, [], echelon_bin="echelon")
        assert rc == 0

    def test_one_failure_returns_one(self, tmp_path: Path) -> None:
        targets = [tmp_path / "a", tmp_path / "b"]
        for t in targets:
            t.mkdir()
        exit_codes = {"a": 0, "b": 1}
        with patch("subprocess.Popen", side_effect=self._fake_popen({"a": "", "b": ""}, exit_codes)):
            rc = run_multi_target("024", targets, [], echelon_bin="echelon")
        assert rc == 1

    def test_output_prefixed_with_target_name(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "myrepo"
        target.mkdir()
        mock_proc = MagicMock()
        mock_proc.stdout = iter(["hello\n"])
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc):
            run_multi_target("024", [target], [], echelon_bin="echelon")
        captured = capsys.readouterr()
        assert "[myrepo] hello" in captured.out

    def test_extra_args_forwarded(self, tmp_path: Path) -> None:
        target = tmp_path / "r"
        target.mkdir()
        captured_cmd = {}
        def fake_popen(cmd, cwd, stdout, stderr, text):
            captured_cmd["cmd"] = cmd
            m = MagicMock()
            m.stdout = iter([])
            m.returncode = 0
            m.wait.return_value = None
            return m
        with patch("subprocess.Popen", side_effect=fake_popen):
            run_multi_target("024", [target], ["strategy=codegen", "max_outer=3"],
                             echelon_bin="echelon")
        assert captured_cmd["cmd"] == ["echelon", "harness", "run", "024",
                                       "strategy=codegen", "max_outer=3"]
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/unit/test_orchestrator.py -v
```

Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_orchestrator.py
git commit -m "test(echelon): unit tests for multi-target orchestrator"
```

---

## Task 5: Modify `cli.py` — orchestrator mode + `echelon spec target`

**Files:**
- Modify: `src/echelon/cli.py`

- [ ] **Step 1: Add `_cmd_spec_target` function (insert before `main()` at line ~466)**

```python
# ── spec subcommands ──────────────────────────────────────────────────────────

def _cmd_spec(args: list[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: echelon spec <subcommand> [args...]\n\n"
            "  target <spec_id> <repo> [repo...]   Set targets: in spec frontmatter\n",
            file=sys.stderr,
        )
        sys.exit(0)
    subcmd = args[0]
    if subcmd == "target":
        _cmd_spec_target(args[1:])
    else:
        print(f"echelon spec: unknown subcommand '{subcmd}'\n", file=sys.stderr)
        sys.exit(1)


def _cmd_spec_target(args: list[str]) -> None:
    if len(args) < 2:
        print(
            "echelon spec target: usage: echelon spec target <spec_id> <repo> [repo...]\n",
            file=sys.stderr,
        )
        sys.exit(1)

    spec_id, repos = args[0], args[1:]

    from harness.spec_frontmatter import find_spec_dir, write_targets

    # Check for ambiguity: multiple specs/ dirs matching spec_id at the found level
    start = Path.cwd()
    current = start
    while True:
        matches = sorted(current.glob(f"specs/{spec_id}-*"))
        if len(matches) > 1:
            print(f"✗ Ambiguous spec id '{spec_id}': multiple matches:", file=sys.stderr)
            for m in matches:
                print(f"  {m}", file=sys.stderr)
            sys.exit(1)
        if matches:
            break
        parent = current.parent
        if parent == current or (parent / ".git").exists():
            break
        current = parent

    spec_dir = find_spec_dir(spec_id, start)
    if spec_dir is None:
        print(f"✗ Spec '{spec_id}' not found (searched from {start})", file=sys.stderr)
        sys.exit(1)

    md = write_targets(spec_dir, repos)
    try:
        display = md.relative_to(start)
    except ValueError:
        display = md
    print(f"Updated {display}")
    print("  targets:")
    for r in repos:
        print(f"    - {r}")
```

- [ ] **Step 2: Modify `_cmd_harness_run` — add orchestrator mode**

Replace the `if not echelon_yml.exists():` block (lines ~361–368) with:

```python
    if not echelon_yml.exists():
        # Orchestrator mode: no local echelon.yml — check if spec has targets
        from harness.spec_frontmatter import find_spec_dir, read_frontmatter
        from echelon.orchestrator import validate_targets, run_multi_target

        spec_dir = find_spec_dir(spec_id, Path.cwd())
        if spec_dir is not None:
            frontmatter = read_frontmatter(spec_dir)
            targets_rel: list[str] = frontmatter.get("targets") or []
            if targets_rel:
                polyrepo_root = spec_dir.parent.parent
                targets = validate_targets(targets_rel, polyrepo_root)
                sys.exit(run_multi_target(spec_id, targets, args[1:]))

        print(
            "✗ Harness not initialised for this project.\n"
            f"  Expected: {echelon_yml}\n"
            "  Fix: run 'echelon harness init' first, or add 'targets:' to your spec.",
            file=sys.stderr,
        )
        sys.exit(1)
```

- [ ] **Step 3: Wire `spec` command in `main()`**

In the `main()` function, add after the `if command == "harness":` block:

```python
    if command == "spec":
        _cmd_spec(args[1:])
        return
```

- [ ] **Step 4: Update USAGE string**

Replace:
```
  harness run  <spec_id> [strategy=<s>]     Run build→verify→PR loop
```
With:
```
  harness run  <spec_id> [strategy=<s>]     Run build→verify→PR loop
  spec target  <spec_id> <repo> [repo...]   Set target repos in spec frontmatter
```

- [ ] **Step 5: Verify import is clean**

```bash
python -c "from echelon.cli import main; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add src/echelon/cli.py
git commit -m "feat(echelon): orchestrator mode in harness run; add echelon spec target command"
```

---

## Task 6: Regression + CLI unit tests

**Files:**
- Create: `tests/unit/test_harness_single_repo_unchanged.py`
- Create: `tests/unit/test_cli_spec_target.py`

- [ ] **Step 1: Write `tests/unit/test_harness_single_repo_unchanged.py`**

```python
"""Regression: single-repo harness run path is unchanged by polyrepo changes.

Verifies that when a local echelon.yml IS present, the orchestrator mode
is never entered — the run proceeds exactly as before.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestSingleRepoPathUnchanged:
    def test_local_echelon_yml_bypasses_orchestrator(self, tmp_path: Path) -> None:
        """If echelon.yml exists locally, run_multi_target is never called."""
        echelon_yml = tmp_path / ".specify" / "extensions" / "echelon" / "echelon.yml"
        echelon_yml.parent.mkdir(parents=True)
        echelon_yml.write_text("harness:\n  target_repo: .\n", encoding="utf-8")

        with patch("echelon.orchestrator.run_multi_target") as mock_orch:
            with patch("harness.config.load_config") as mock_cfg:
                mock_cfg.return_value = MagicMock(buffer_limit_bytes=1024 * 1024)
                with patch("harness.gitops.GitOpsManager"):
                    with patch("harness.docker_provider.DockerWorktreeProvider"):
                        with patch("harness.skills.run_skill.run"):
                            import os
                            orig = os.getcwd()
                            try:
                                os.chdir(tmp_path)
                                import sys
                                sys.argv = ["echelon", "harness", "run", "024"]
                                from echelon.cli import _cmd_harness_run
                                try:
                                    _cmd_harness_run(["024"])
                                except SystemExit:
                                    pass
                            finally:
                                os.chdir(orig)
            mock_orch.assert_not_called()

    def test_spec_without_targets_falls_through_to_init_error(self, tmp_path: Path) -> None:
        """Spec found but no targets: still shows the init error, not orchestrator."""
        spec_dir = tmp_path / "specs" / "024-test"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# No frontmatter\n", encoding="utf-8")

        import os
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            from echelon.cli import _cmd_harness_run
            with pytest.raises(SystemExit) as exc:
                _cmd_harness_run(["024"])
            assert exc.value.code == 1
        finally:
            os.chdir(orig)

    def test_find_spec_dir_local_takes_precedence(self, tmp_path: Path) -> None:
        """Local spec shadows parent-level spec of same id."""
        from harness.spec_frontmatter import find_spec_dir

        parent_spec = tmp_path / "specs" / "024-parent"
        parent_spec.mkdir(parents=True)
        (parent_spec / "spec.md").write_text("# parent\n", encoding="utf-8")

        child = tmp_path / "repo-a"
        local_spec = child / "specs" / "024-local"
        local_spec.mkdir(parents=True)
        (local_spec / "spec.md").write_text("# local\n", encoding="utf-8")

        result = find_spec_dir("024", child)
        assert result == local_spec
```

- [ ] **Step 2: Write `tests/unit/test_cli_spec_target.py`**

```python
"""Unit tests for 'echelon spec target' CLI command."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.spec_frontmatter import read_frontmatter


def _setup_spec(tmp_path: Path, spec_name: str, content: str = "# spec\n") -> Path:
    spec_dir = tmp_path / "specs" / spec_name
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(content, encoding="utf-8")
    return spec_dir


@pytest.mark.unit
class TestCliSpecTarget:
    def _run_spec_target(self, tmp_path: Path, args: list[str]) -> int:
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            from echelon.cli import _cmd_spec_target
            try:
                _cmd_spec_target(args)
                return 0
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0
        finally:
            os.chdir(orig)

    def test_single_target_written(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-psd-import")
        rc = self._run_spec_target(tmp_path, ["024", "og-platform"])
        assert rc == 0
        spec_dir = tmp_path / "specs" / "024-psd-import"
        assert read_frontmatter(spec_dir)["targets"] == ["og-platform"]

    def test_multiple_targets_written(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-psd-import")
        rc = self._run_spec_target(tmp_path, ["024", "og-platform", "fet-libs"])
        assert rc == 0
        spec_dir = tmp_path / "specs" / "024-psd-import"
        assert read_frontmatter(spec_dir)["targets"] == ["og-platform", "fet-libs"]

    def test_in_place_replacement_no_duplication(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-psd-import", "---\ntargets:\n  - old\n---\n# body\n")
        self._run_spec_target(tmp_path, ["024", "new-repo"])
        spec_dir = tmp_path / "specs" / "024-psd-import"
        md = next(spec_dir.glob("*.md"))
        assert md.read_text(encoding="utf-8").count("targets:") == 1

    def test_spec_not_found_exits_one(self, tmp_path: Path) -> None:
        rc = self._run_spec_target(tmp_path, ["999", "og-platform"])
        assert rc == 1

    def test_missing_repo_arg_exits_one(self, tmp_path: Path) -> None:
        rc = self._run_spec_target(tmp_path, ["024"])
        assert rc == 1

    def test_ambiguous_spec_id_exits_one(self, tmp_path: Path) -> None:
        _setup_spec(tmp_path, "024-alpha")
        _setup_spec(tmp_path, "024-beta")
        rc = self._run_spec_target(tmp_path, ["024", "og-platform"])
        assert rc == 1
        # Neither spec should have been modified
        for name in ("024-alpha", "024-beta"):
            data = read_frontmatter(tmp_path / "specs" / name)
            assert "targets" not in data
```

- [ ] **Step 3: Run all new tests**

```bash
python -m pytest tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_cli_spec_target.py -v
```

Expected: All PASS

- [ ] **Step 4: Run full unit suite to check for regressions**

```bash
python -m pytest tests/unit/ -v --tb=short
```

Expected: All 414 original tests pass, plus new tests pass. Zero regressions.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_harness_single_repo_unchanged.py tests/unit/test_cli_spec_target.py
git commit -m "test(echelon): regression and CLI unit tests for spec target command"
```

---

## Task 7: E2E smoke tests

**Files:**
- Create: `tests/e2e/test-e2e-spec-target-cmd.sh`
- Create: `tests/e2e/test-e2e-walk-up-spec-discovery.sh`
- Create: `tests/e2e/test-e2e-orchestrator-prefixed-output.sh`

- [ ] **Step 1: Write `tests/e2e/test-e2e-spec-target-cmd.sh`**

```bash
#!/usr/bin/env bash
# E2E: echelon spec target command — writes/replaces targets: frontmatter
# Runs in isolated tmpdir; uses installed echelon binary.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"

pass=0
fail=0
assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1)); printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1)); printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result()   { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

# ── Setup: polyrepo with one spec ─────────────────────────────────────────────
mkdir -p "$tmpdir/specs/024-psd-import"
printf '# PSD Import Spec\n' > "$tmpdir/specs/024-psd-import/spec.md"

cd "$tmpdir"

# ── Test 1: write single target ───────────────────────────────────────────────
echelon spec target 024 og-platform
result="$(python3 -c "
import re, sys
text = open('specs/024-psd-import/spec.md').read()
import yaml
m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
data = yaml.safe_load(m.group(1)) if m else {}
print(data.get('targets', []))
")"
if [[ "$result" == "['og-platform']" ]]; then
  assert "single target written" "$(ok_result)"
else
  assert "single target written" "$(fail_result " got: $result")"
fi

# ── Test 2: replace with multiple targets ─────────────────────────────────────
echelon spec target 024 og-platform fet-frontend-libs
result="$(python3 -c "
import re, yaml
text = open('specs/024-psd-import/spec.md').read()
m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
data = yaml.safe_load(m.group(1)) if m else {}
print(data.get('targets', []))
")"
if [[ "$result" == "['og-platform', 'fet-frontend-libs']" ]]; then
  assert "multiple targets written" "$(ok_result)"
else
  assert "multiple targets written" "$(fail_result " got: $result")"
fi

# ── Test 3: no duplication on rewrite ─────────────────────────────────────────
targets_count="$(grep -c 'targets:' specs/024-psd-import/spec.md || true)"
if [[ "$targets_count" == "1" ]]; then
  assert "no duplication on rewrite" "$(ok_result)"
else
  assert "no duplication on rewrite" "$(fail_result " targets: appears $targets_count times")"
fi

# ── Test 4: ambiguous spec id exits non-zero, writes nothing ──────────────────
mkdir -p "$tmpdir/specs/024-alpha"
printf '# alpha\n' > "$tmpdir/specs/024-alpha/spec.md"
set +e
echelon spec target 024 og-platform 2>/dev/null
ambig_rc=$?
set -e
alpha_has_targets="$(python3 -c "
import re, yaml
text = open('specs/024-alpha/spec.md').read()
m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
data = yaml.safe_load(m.group(1)) if m else {}
print('targets' in data)
" 2>/dev/null || echo False)"
if [[ "$ambig_rc" -ne 0 && "$alpha_has_targets" == "False" ]]; then
  assert "ambiguous id exits 1, writes nothing" "$(ok_result)"
else
  assert "ambiguous id exits 1, writes nothing" "$(fail_result " rc=$ambig_rc written=$alpha_has_targets")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "spec-target-cmd smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
```

- [ ] **Step 2: Write `tests/e2e/test-e2e-walk-up-spec-discovery.sh`**

```bash
#!/usr/bin/env bash
# E2E: walk-up spec discovery — find_spec_dir via Python helper
# Runs in isolated tmpdir; no echelon binary required (Python module call).
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"

pass=0
fail=0
assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1)); printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1)); printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result()   { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

PYTHONPATH="$REPO_ROOT/src"

find_spec() {
  local spec_id="$1" start_dir="$2"
  PYTHONPATH="$PYTHONPATH" python3 -c "
from pathlib import Path
from harness.spec_frontmatter import find_spec_dir
r = find_spec_dir('$spec_id', Path('$start_dir'))
print(r if r else 'None')
"
}

# ── Setup ─────────────────────────────────────────────────────────────────────
# P/specs/024-test/ and P/A/ (A has .git)
mkdir -p "$tmpdir/specs/024-test"
printf '# spec\n' > "$tmpdir/specs/024-test/spec.md"
mkdir -p "$tmpdir/A"
mkdir "$tmpdir/A/.git"

# ── Test 1: walk-up finds parent spec ─────────────────────────────────────────
result="$(find_spec 024 "$tmpdir/A")"
expected="$tmpdir/specs/024-test"
if [[ "$result" == "$expected" ]]; then
  assert "walk-up finds parent spec" "$(ok_result)"
else
  assert "walk-up finds parent spec" "$(fail_result " got: $result, expected: $expected")"
fi

# ── Test 2: local spec takes precedence ───────────────────────────────────────
mkdir -p "$tmpdir/A/specs/024-local"
printf '# local\n' > "$tmpdir/A/specs/024-local/spec.md"
result="$(find_spec 024 "$tmpdir/A")"
expected="$tmpdir/A/specs/024-local"
if [[ "$result" == "$expected" ]]; then
  assert "local spec takes precedence" "$(ok_result)"
else
  assert "local spec takes precedence" "$(fail_result " got: $result, expected: $expected")"
fi

# ── Test 3: stops when parent has .git ────────────────────────────────────────
mkdir "$tmpdir/.git"   # P now has .git — walk-up from A must not cross into it
rm -rf "$tmpdir/A/specs/024-local"  # remove local so we'd need parent
result="$(find_spec 024 "$tmpdir/A")"
if [[ "$result" == "None" ]]; then
  assert "stops at git boundary in parent" "$(ok_result)"
else
  assert "stops at git boundary in parent" "$(fail_result " got: $result, expected None")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "walk-up-spec-discovery smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
```

- [ ] **Step 3: Write `tests/e2e/test-e2e-orchestrator-prefixed-output.sh`**

```bash
#!/usr/bin/env bash
# E2E: orchestrator mode — prefixed output, parallel dispatch, exit code propagation
# Uses a stub 'echelon' binary injected via PATH.
set -uo pipefail

REPO_ROOT="$(CDPATH='' cd "$(dirname "$0")/../.." && pwd)"

pass=0
fail=0
assert() {
  local desc="$1" result="$2"
  if [[ "$result" == "OK" ]]; then
    pass=$((pass+1)); printf 'PASS: %s\n' "$desc"
  else
    fail=$((fail+1)); printf 'FAIL: %s — %s\n' "$desc" "${result#FAIL:}"
  fi
}
ok_result()   { echo "OK"; }
fail_result() { printf 'FAIL:%s' "$*"; }

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

PYTHONPATH="$REPO_ROOT/src"
ECHELON_YML=".specify/extensions/echelon/echelon.yml"

# ── Setup: polyrepo P with spec and two initialised sub-repos ─────────────────
mkdir -p "$tmpdir/specs/024-test"
printf -- "---\ntargets:\n  - repo-a\n  - repo-b\n---\n# spec\n" \
  > "$tmpdir/specs/024-test/spec.md"

for repo in repo-a repo-b; do
  mkdir -p "$tmpdir/$repo/$(dirname $ECHELON_YML)"
  printf 'harness:\n  target_repo: .\n' \
    > "$tmpdir/$repo/$ECHELON_YML"
done

# ── Stub: echelon binary that echoes and exits 0 ──────────────────────────────
mkdir -p "$tmpdir/bin"
cat > "$tmpdir/bin/echelon" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == "harness" && "$2" == "run" ]]; then
    echo "hello from $(basename $(pwd))"
    exit 0
fi
# Fall through to real echelon for other commands (spec target etc.)
exec "$(which -a echelon | grep -v "$tmpdir/bin/echelon" | head -1)" "$@"
STUB
chmod +x "$tmpdir/bin/echelon"
export PATH="$tmpdir/bin:$PATH"

# ── Test 1: both succeed → exit 0, output prefixed ────────────────────────────
cd "$tmpdir"
set +e
output="$(PYTHONPATH="$PYTHONPATH" python3 -m echelon harness run 024 2>&1 || true)"
set -e
# Run via Python module so we get the modified cli.py from source
run_rc=0
PYTHONPATH="$PYTHONPATH" python3 -c "
import sys
sys.argv = ['echelon', 'harness', 'run', '024']
from echelon.cli import main
try:
    main()
except SystemExit as e:
    sys.exit(e.code or 0)
" > "$tmpdir/out_success.txt" 2>&1 || run_rc=$?

if grep -q '\[repo-a\]' "$tmpdir/out_success.txt" && \
   grep -q '\[repo-b\]' "$tmpdir/out_success.txt"; then
  assert "output contains [repo-a] and [repo-b] prefixes" "$(ok_result)"
else
  assert "output contains [repo-a] and [repo-b] prefixes" \
    "$(fail_result " output: $(cat $tmpdir/out_success.txt)")"
fi

if [[ "$run_rc" -eq 0 ]]; then
  assert "both succeed → exit 0" "$(ok_result)"
else
  assert "both succeed → exit 0" "$(fail_result " exit code: $run_rc")"
fi

# ── Test 2: one failure → exit 1, both outputs still appear ──────────────────
cat > "$tmpdir/bin/echelon" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == "harness" && "$2" == "run" ]]; then
    repo="$(basename $(pwd))"
    echo "output from $repo"
    if [[ "$repo" == "repo-b" ]]; then exit 1; fi
    exit 0
fi
exec "$(which -a echelon | grep -v "$tmpdir/bin/echelon" | head -1)" "$@"
STUB
chmod +x "$tmpdir/bin/echelon"

fail_rc=0
PYTHONPATH="$PYTHONPATH" python3 -c "
import sys
sys.argv = ['echelon', 'harness', 'run', '024']
from echelon.cli import main
try:
    main()
except SystemExit as e:
    sys.exit(e.code or 0)
" > "$tmpdir/out_fail.txt" 2>&1 || fail_rc=$?

if grep -q '\[repo-a\]' "$tmpdir/out_fail.txt" && \
   grep -q '\[repo-b\]' "$tmpdir/out_fail.txt"; then
  assert "both outputs appear even when one fails" "$(ok_result)"
else
  assert "both outputs appear even when one fails" \
    "$(fail_result " output: $(cat $tmpdir/out_fail.txt)")"
fi

if [[ "$fail_rc" -ne 0 ]]; then
  assert "one failure → exit 1" "$(ok_result)"
else
  assert "one failure → exit 1" "$(fail_result " expected non-zero, got 0")"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "orchestrator-prefixed-output smoke: $pass passed, $fail failed"
[[ "$fail" -eq 0 ]] || exit 1
```

- [ ] **Step 4: Make smoke tests executable**

```bash
chmod +x tests/e2e/test-e2e-spec-target-cmd.sh
chmod +x tests/e2e/test-e2e-walk-up-spec-discovery.sh
chmod +x tests/e2e/test-e2e-orchestrator-prefixed-output.sh
```

- [ ] **Step 5: Run all three smoke tests**

```bash
bash tests/e2e/test-e2e-spec-target-cmd.sh
bash tests/e2e/test-e2e-walk-up-spec-discovery.sh
bash tests/e2e/test-e2e-orchestrator-prefixed-output.sh
```

Expected: Each script prints `N passed, 0 failed` and exits 0.

- [ ] **Step 6: Run full unit suite one final time**

```bash
python -m pytest tests/unit/ -v --tb=short -q
```

Expected: All original 414 tests pass plus all new tests pass. Zero failures.

- [ ] **Step 7: Commit**

```bash
git add tests/e2e/test-e2e-spec-target-cmd.sh \
        tests/e2e/test-e2e-walk-up-spec-discovery.sh \
        tests/e2e/test-e2e-orchestrator-prefixed-output.sh
git commit -m "test(e2e): smoke tests for spec target, walk-up discovery, and orchestrator"
```

---

## Final validation

- [ ] **Run the complete test suite**

```bash
bash tests/run-all.sh
```

Expected: Unit, integration, and e2e suites all green. Summary shows 0 failures.

- [ ] **Push**

```bash
git push
```
