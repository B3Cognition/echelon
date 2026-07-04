# EGR-082 Spec-Scoped Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build spec-scoped Phase A checkpoints, whole-commit branch rewind, explicit manual checkpoint UX, and mandatory Echelon commit attribution for every Echelon-created commit.

**Architecture:** Add shared commit-message and Git helper modules first, then build a Phase A checkpoint ledger on top of them. Wire checkpoint creation at successful squad phase-node boundaries, expose `echelon checkpoint` commands, replace file-delete rewind with backup-ref plus branch reset, and migrate existing Echelon commit paths to structured trailers.

**Tech Stack:** Python 3, Git CLI via existing subprocess patterns, Markdown/JSON checkpoint metadata, `src/echelon/cli.py`, `src/harness/squad.py`, `src/harness/gitops.py`, pytest.

## Global Constraints

- EGR-082 source of truth: `docs/findings/echelon-grounded-review-register.md`, GitHub issue #105.
- Design source: `docs/superpowers/specs/2026-07-04-spec-scoped-checkpoint-design.md`.
- Do not scan Git history to infer Phase A checkpoints during normal operation.
- `echelon checkpoint list` reads active run state or spec-scoped checkpoint metadata only.
- Default rewind moves the active spec branch to a recorded checkpoint commit and creates a backup ref first.
- Default rewind refuses dirty worktrees.
- Path-scoped file restore is allowed only as a future manual salvage command, not default rewind.
- Every Echelon-created commit must include `Co-authored-by: Echelon <echelon@b3cognition.dev>` and stable `Echelon-*` trailers.
- Preserve unrelated user changes in the worktree. Do not revert existing uncommitted user edits.

---

## File Structure

- Create `src/echelon/commit_messages.py`: single builder for Echelon commit subjects and trailers.
- Create `src/echelon/git_helpers.py`: shared Git primitives for commit existence, dirty worktree checks, branch containment, backup refs, current branch, and branch reset.
- Create `src/harness/phase_checkpoints.py`: spec-scoped checkpoint ledger, checkpoint creation, manual accept/commit support, active spec resolution helpers.
- Create `src/echelon/checkpoint_cli.py`: `echelon checkpoint list/show/accept/commit` implementation.
- Create `src/echelon/rewind.py`: metadata-backed rewind with backup ref and branch reset.
- Modify `src/echelon/cli.py`: route `checkpoint` to `checkpoint_cli`, delegate `rewind` to `rewind.py`, and keep compatibility usage.
- Modify `src/harness/squad.py`: call checkpoint creation after successful normal and manual phase-node advancement.
- Modify `src/harness/gitops.py`, `src/harness/ralph.py`, `src/echelon/workspace_git_migration.py`, `src/echelon/workspace_source_split_migration.py`, and `src/harness/land.py`: migrate Echelon-created commits to the shared trailer builder.
- Add tests under `tests/unit/`: commit message builder, Git helpers, phase checkpoint ledger, checkpoint CLI, rewind behavior, squad checkpoint hook, and Echelon commit attribution coverage.
- Update `CHANGELOG.md` and the EGR register when implementation is complete.

---

### Task 1: Commit Message Trailer Builder

**Files:**
- Create: `src/echelon/commit_messages.py`
- Test: `tests/unit/test_commit_messages.py`

**Interfaces:**
- Produces: `EchelonCommitMetadata`, `build_echelon_commit_message(subject: str, metadata: EchelonCommitMetadata) -> str`
- Consumes: no project state.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_commit_messages.py`:

```python
from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message


def test_build_echelon_commit_message_adds_standard_trailers() -> None:
    message = build_echelon_commit_message(
        "echelon-checkpoint: 001-demo phase3-plan",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id="001-demo",
            run_id="squad-20260704-123456",
            phase="phase3-plan",
        ),
    )

    assert message.startswith("echelon-checkpoint: 001-demo phase3-plan\n\n")
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in message
    assert "Echelon-Origin: phase-a" in message
    assert "Echelon-Action: checkpoint" in message
    assert "Echelon-Spec: 001-demo" in message
    assert "Echelon-Run: squad-20260704-123456" in message
    assert "Echelon-Phase: phase3-plan" in message


def test_build_echelon_commit_message_omits_empty_optional_trailers() -> None:
    message = build_echelon_commit_message(
        "chore: initialize echelon workspace",
        EchelonCommitMetadata(origin="workspace", action="init"),
    )

    assert "Echelon-Origin: workspace" in message
    assert "Echelon-Action: init" in message
    assert "Echelon-Spec:" not in message
    assert "Echelon-Phase:" not in message


def test_build_echelon_commit_message_rejects_blank_required_fields() -> None:
    try:
        build_echelon_commit_message(
            "",
            EchelonCommitMetadata(origin="phase-a", action="checkpoint"),
        )
    except ValueError as exc:
        assert "subject" in str(exc)
    else:
        raise AssertionError("blank subject should fail")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_commit_messages.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.commit_messages'`.

- [ ] **Step 3: Implement the builder**

Create `src/echelon/commit_messages.py`:

```python
"""Structured commit messages for Echelon-created commits."""

from __future__ import annotations

from dataclasses import dataclass


ECHELON_COAUTHOR = "Co-authored-by: Echelon <echelon@b3cognition.dev>"


@dataclass(frozen=True)
class EchelonCommitMetadata:
    origin: str
    action: str
    spec_id: str = ""
    run_id: str = ""
    phase: str = ""
    strategy: str = ""
    checkpoint_id: str = ""


def _clean(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def build_echelon_commit_message(subject: str, metadata: EchelonCommitMetadata) -> str:
    subject = _clean(subject)
    origin = _clean(metadata.origin)
    action = _clean(metadata.action)
    if not subject:
        raise ValueError("commit subject is required")
    if not origin:
        raise ValueError("Echelon-Origin is required")
    if not action:
        raise ValueError("Echelon-Action is required")

    trailers = [
        ECHELON_COAUTHOR,
        f"Echelon-Origin: {origin}",
        f"Echelon-Action: {action}",
    ]
    optional = (
        ("Echelon-Spec", metadata.spec_id),
        ("Echelon-Run", metadata.run_id),
        ("Echelon-Phase", metadata.phase),
        ("Echelon-Strategy", metadata.strategy),
        ("Echelon-Checkpoint", metadata.checkpoint_id),
    )
    for key, value in optional:
        cleaned = _clean(value)
        if cleaned:
            trailers.append(f"{key}: {cleaned}")
    return subject + "\n\n" + "\n".join(trailers)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_commit_messages.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/commit_messages.py tests/unit/test_commit_messages.py
git commit -m "feat: add Echelon commit trailer builder"
```

---

### Task 2: Shared Git Helper Primitives

**Files:**
- Create: `src/echelon/git_helpers.py`
- Test: `tests/unit/test_git_helpers.py`

**Interfaces:**
- Produces: `GitHelperError`, `run_git`, `current_branch`, `is_worktree_dirty`, `commit_exists`, `ref_contains_commit`, `create_backup_ref`, `reset_branch_to_commit`.
- Consumes: local Git repositories.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_git_helpers.py`:

```python
from pathlib import Path
import subprocess

from echelon.git_helpers import (
    commit_exists,
    create_backup_ref,
    current_branch,
    is_worktree_dirty,
    ref_contains_commit,
    reset_branch_to_commit,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    return _git(repo, "rev-parse", "HEAD")


def test_git_helpers_detect_branch_dirty_and_commit_containment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)

    assert current_branch(repo) == "main"
    assert commit_exists(repo, base)
    assert ref_contains_commit(repo, "main", base)
    assert not is_worktree_dirty(repo)

    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    assert is_worktree_dirty(repo)


def test_backup_ref_and_reset_branch_to_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature")
    head = _git(repo, "rev-parse", "HEAD")

    backup = create_backup_ref(repo, "echelon/backup/test", head)
    reset_branch_to_commit(repo, base)

    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "rev-parse", backup) == head
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_git_helpers.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'echelon.git_helpers'`.

- [ ] **Step 3: Implement helper module**

Create `src/echelon/git_helpers.py`:

```python
"""Small Git primitives shared by Echelon recovery flows."""

from __future__ import annotations

from pathlib import Path
import subprocess


class GitHelperError(RuntimeError):
    pass


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise GitHelperError(
            f"git {' '.join(args)} failed in {repo}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def current_branch(repo: Path) -> str:
    return run_git(repo, "branch", "--show-current").stdout.strip()


def is_worktree_dirty(repo: Path, *, include_untracked: bool = True) -> bool:
    args = ["status", "--porcelain"]
    if not include_untracked:
        args.append("--untracked-files=no")
    return bool(run_git(repo, *args, check=False).stdout.strip())


def commit_exists(repo: Path, commit: str) -> bool:
    if not commit.strip():
        return False
    result = run_git(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
    return result.returncode == 0


def ref_contains_commit(repo: Path, ref: str, commit: str) -> bool:
    if not ref.strip() or not commit_exists(repo, commit):
        return False
    result = run_git(repo, "merge-base", "--is-ancestor", commit, ref, check=False)
    return result.returncode == 0


def create_backup_ref(repo: Path, ref_name: str, target: str = "HEAD") -> str:
    cleaned = ref_name.strip().removeprefix("refs/heads/")
    if not cleaned.startswith("echelon/backup/"):
        raise ValueError("backup refs must live under echelon/backup/")
    run_git(repo, "branch", cleaned, target)
    return cleaned


def reset_branch_to_commit(repo: Path, commit: str) -> None:
    if not commit_exists(repo, commit):
        raise GitHelperError(f"checkpoint commit does not exist: {commit}")
    run_git(repo, "reset", "--hard", commit)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_git_helpers.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/git_helpers.py tests/unit/test_git_helpers.py
git commit -m "feat: add shared Echelon git helpers"
```

---

### Task 3: Spec-Scoped Checkpoint Ledger

**Files:**
- Create: `src/harness/phase_checkpoints.py`
- Test: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Consumes: `build_echelon_commit_message`, `git_helpers`, spec directory, run state.
- Produces: `PhaseCheckpoint`, `CheckpointLedger`, `load_checkpoint_ledger`, `record_phase_checkpoint`, `resolve_checkpoint`.

- [ ] **Step 1: Write failing ledger tests**

Create `tests/unit/test_phase_checkpoints.py`:

```python
from pathlib import Path
import json
import subprocess

from harness.phase_checkpoints import (
    CheckpointLedger,
    PhaseCheckpoint,
    load_checkpoint_ledger,
    record_checkpoint_metadata,
    resolve_checkpoint,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_checkpoint_ledger_round_trips_under_spec_dir(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    checkpoint = PhaseCheckpoint(
        id="phase3-plan",
        spec_id="001-demo",
        phase="phase3-plan",
        next_phase="phase3-consensus",
        commit="abc123",
        metadata_commit="",
        source="auto",
        run_id="squad-1",
        created_at="2026-07-04T12:00:00Z",
    )

    record_checkpoint_metadata(spec_dir, checkpoint)
    ledger = load_checkpoint_ledger(spec_dir)

    assert ledger.spec_id == "001-demo"
    assert ledger.checkpoints[0] == checkpoint
    assert json.loads((spec_dir / ".echelon/checkpoints.json").read_text())["spec_id"] == "001-demo"


def test_resolve_checkpoint_by_phase_uses_latest_matching_entry(tmp_path: Path) -> None:
    ledger = CheckpointLedger(
        spec_id="001-demo",
        checkpoints=[
            PhaseCheckpoint("phase3-plan", "001-demo", "phase3-plan", "phase3-consensus", "old", "", "auto", "run1", "2026-07-04T01:00:00Z"),
            PhaseCheckpoint("phase3-plan-2", "001-demo", "phase3-plan", "phase3-consensus", "new", "", "auto", "run2", "2026-07-04T02:00:00Z"),
        ],
    )

    assert resolve_checkpoint(ledger, "phase3-plan").commit == "new"
    assert resolve_checkpoint(ledger, "checkpoint:phase3-plan-2").commit == "new"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_phase_checkpoints.py -q`

Expected: FAIL with `ModuleNotFoundError` or missing symbols.

- [ ] **Step 3: Implement metadata-only ledger functions**

Create `src/harness/phase_checkpoints.py` with dataclasses and JSON read/write:

```python
"""Spec-scoped Phase A checkpoint metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


CHECKPOINT_LEDGER_REL = Path(".echelon") / "checkpoints.json"


@dataclass(frozen=True)
class PhaseCheckpoint:
    id: str
    spec_id: str
    phase: str
    next_phase: str
    commit: str
    metadata_commit: str
    source: str
    run_id: str
    created_at: str


@dataclass(frozen=True)
class CheckpointLedger:
    spec_id: str
    checkpoints: list[PhaseCheckpoint]


def checkpoint_ledger_path(spec_dir: Path) -> Path:
    return spec_dir / CHECKPOINT_LEDGER_REL


def _spec_id_from_dir(spec_dir: Path) -> str:
    name = spec_dir.name
    if name.startswith("spec-"):
        return name.removeprefix("spec-")
    return name


def load_checkpoint_ledger(spec_dir: Path) -> CheckpointLedger:
    path = checkpoint_ledger_path(spec_dir)
    if not path.exists():
        return CheckpointLedger(spec_id=_spec_id_from_dir(spec_dir), checkpoints=[])
    raw = json.loads(path.read_text(encoding="utf-8"))
    checkpoints = [PhaseCheckpoint(**item) for item in raw.get("checkpoints", [])]
    return CheckpointLedger(spec_id=str(raw.get("spec_id") or _spec_id_from_dir(spec_dir)), checkpoints=checkpoints)


def write_checkpoint_ledger(spec_dir: Path, ledger: CheckpointLedger) -> None:
    path = checkpoint_ledger_path(spec_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "spec_id": ledger.spec_id,
        "checkpoints": [asdict(item) for item in ledger.checkpoints],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_checkpoint_metadata(spec_dir: Path, checkpoint: PhaseCheckpoint) -> CheckpointLedger:
    ledger = load_checkpoint_ledger(spec_dir)
    checkpoints = [item for item in ledger.checkpoints if item.id != checkpoint.id]
    checkpoints.append(checkpoint)
    updated = CheckpointLedger(spec_id=checkpoint.spec_id, checkpoints=checkpoints)
    write_checkpoint_ledger(spec_dir, updated)
    return updated


def resolve_checkpoint(ledger: CheckpointLedger, target: str) -> PhaseCheckpoint:
    name = target.removeprefix("checkpoint:").strip()
    matches = [item for item in ledger.checkpoints if item.id == name]
    if not matches and not target.startswith("checkpoint:"):
        matches = [item for item in ledger.checkpoints if item.phase == name]
    if not matches:
        raise KeyError(f"checkpoint not found for spec {ledger.spec_id}: {target}")
    return matches[-1]


def new_checkpoint_id(phase: str, source: str = "auto") -> str:
    if source == "auto":
        return phase
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{source}-{phase}-{stamp}"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/test_phase_checkpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/phase_checkpoints.py tests/unit/test_phase_checkpoints.py
git commit -m "feat: add spec-scoped checkpoint ledger"
```

---

### Task 4: Phase Checkpoint Commit Creation

**Files:**
- Modify: `src/harness/phase_checkpoints.py`
- Test: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Consumes: project root, spec dir, phase, next phase, run id, clean Git worktree.
- Produces: `create_phase_checkpoint(project_root: Path, spec_dir: Path, phase: str, next_phase: str, run_id: str) -> PhaseCheckpoint | None`

- [ ] **Step 1: Add failing checkpoint commit test**

Append to `tests/unit/test_phase_checkpoints.py`:

```python
from harness.phase_checkpoints import create_phase_checkpoint


def test_create_phase_checkpoint_commits_artifacts_and_records_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        next_phase="phase3-consensus",
        run_id="squad-1",
    )

    assert checkpoint is not None
    assert checkpoint.phase == "phase3-plan"
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")
    assert "Co-authored-by: Echelon" in _git(repo, "log", "-1", "--format=%B")
    assert load_checkpoint_ledger(spec_dir).checkpoints[-1].commit == checkpoint.commit
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_phase_checkpoints.py::test_create_phase_checkpoint_commits_artifacts_and_records_sha -q`

Expected: FAIL because `create_phase_checkpoint` is missing.

- [ ] **Step 3: Implement checkpoint commit creation**

Add to `src/harness/phase_checkpoints.py`:

```python
from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import commit_exists, is_worktree_dirty, run_git


def _has_staged_or_unstaged_changes(project_root: Path) -> bool:
    return bool(run_git(project_root, "status", "--porcelain", check=False).stdout.strip())


def create_phase_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    next_phase: str,
    run_id: str,
) -> PhaseCheckpoint | None:
    if not _has_staged_or_unstaged_changes(project_root):
        return None
    spec_id = _spec_id_from_dir(spec_dir)
    run_git(project_root, "add", "-A")
    if run_git(project_root, "diff", "--cached", "--quiet", check=False).returncode != 0:
        subject = f"echelon-checkpoint: {spec_id} {phase}"
        message = build_echelon_commit_message(
            subject,
            EchelonCommitMetadata(
                origin="phase-a",
                action="checkpoint",
                spec_id=spec_id,
                run_id=run_id,
                phase=phase,
                checkpoint_id=phase,
            ),
        )
        run_git(project_root, "commit", "-m", message)
    commit = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    checkpoint = PhaseCheckpoint(
        id=phase,
        spec_id=spec_id,
        phase=phase,
        next_phase=next_phase,
        commit=commit,
        metadata_commit="",
        source="auto",
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    record_checkpoint_metadata(spec_dir, checkpoint)
    return checkpoint
```

The `git diff --cached --quiet` command returns `1` when staged changes exist, so the implementation commits only when `returncode != 0`.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/unit/test_phase_checkpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/phase_checkpoints.py tests/unit/test_phase_checkpoints.py
git commit -m "feat: create phase checkpoint commits"
```

---

### Task 5: Checkpoint CLI

**Files:**
- Create: `src/echelon/checkpoint_cli.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_checkpoint.py`

**Interfaces:**
- Produces: `run_checkpoint_command(args: list[str], project_root: Path) -> None`
- Consumes: active spec dir or `--spec`, checkpoint ledger.

- [ ] **Step 1: Write failing CLI tests**

Create `tests/unit/test_cli_checkpoint.py`:

```python
from pathlib import Path

from echelon.checkpoint_cli import run_checkpoint_command
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata


def test_checkpoint_list_requires_spec_when_no_active_spec(tmp_path: Path, capsys) -> None:
    run_checkpoint_command(["list"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "No active spec resolved" in out
    assert "echelon checkpoint list --spec 001" in out


def test_checkpoint_list_prints_spec_scoped_ledger(tmp_path: Path, capsys) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint(
            id="phase3-plan",
            spec_id="001-demo",
            phase="phase3-plan",
            next_phase="phase3-consensus",
            commit="abcdef123456",
            metadata_commit="",
            source="auto",
            run_id="squad-1",
            created_at="2026-07-04T12:00:00Z",
        ),
    )

    run_checkpoint_command(["list", "--spec", "001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "CHECKPOINTS - spec 001-demo" in out
    assert "phase3-plan" in out
    assert "abcdef1" in out
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_cli_checkpoint.py -q`

Expected: FAIL because `echelon.checkpoint_cli` does not exist.

- [ ] **Step 3: Implement checkpoint CLI**

Create `src/echelon/checkpoint_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from harness.phase_checkpoints import load_checkpoint_ledger


def _find_spec_dir(project_root: Path, spec: str) -> Path | None:
    specs = project_root / "specs"
    if not specs.exists():
        return None
    matches = sorted(path for path in specs.iterdir() if path.is_dir() and path.name.startswith(spec))
    return matches[0] if matches else None


def _arg_value(args: list[str], name: str) -> str:
    if name not in args:
        return ""
    idx = args.index(name)
    if idx + 1 >= len(args):
        return ""
    return args[idx + 1]


def run_checkpoint_command(args: list[str], *, project_root: Path) -> None:
    subcmd = args[0] if args else "list"
    if subcmd not in {"list", "show"}:
        print("Usage: echelon checkpoint list [--spec <id>]")
        return
    spec = _arg_value(args, "--spec")
    if not spec:
        print("No active spec resolved.\n\nUse:\n  echelon checkpoint list --spec 001\n  echelon phase list")
        return
    spec_dir = _find_spec_dir(project_root, spec)
    if spec_dir is None:
        print(f"No spec directory found for {spec!r}.")
        return
    ledger = load_checkpoint_ledger(spec_dir)
    print(f"CHECKPOINTS - spec {ledger.spec_id}\n")
    if not ledger.checkpoints:
        print("(none)")
        return
    print("ID                       PHASE                 COMMIT      SOURCE")
    for item in ledger.checkpoints:
        print(f"{item.id:<24} {item.phase:<21} {item.commit[:7]:<11} {item.source}")
```

Modify `src/echelon/cli.py` command dispatch to route `checkpoint`:

```python
    if command == "checkpoint":
        from echelon.checkpoint_cli import run_checkpoint_command

        run_checkpoint_command(args[1:], project_root=project_root)
        return
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/unit/test_cli_checkpoint.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/checkpoint_cli.py src/echelon/cli.py tests/unit/test_cli_checkpoint.py
git commit -m "feat: add spec-scoped checkpoint CLI"
```

---

### Task 6: Branch-Level Rewind

**Files:**
- Create: `src/echelon/rewind.py`
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_rewind.py`

**Interfaces:**
- Produces: `prepare_rewind(project_root: Path, spec: str, target: str, confirm: bool) -> RewindResult`
- Consumes: checkpoint ledger, Git helpers.

- [ ] **Step 1: Write failing rewind tests**

Create `tests/unit/test_rewind.py`:

```python
from pathlib import Path
import subprocess

import pytest

from echelon.rewind import RewindError, prepare_rewind
from harness.phase_checkpoints import PhaseCheckpoint, record_checkpoint_metadata


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _repo_with_checkpoint(tmp_path: Path) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "001-demo")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("v1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "checkpoint")
    checkpoint = _git(repo, "rev-parse", "HEAD")
    record_checkpoint_metadata(
        spec_dir,
        PhaseCheckpoint("phase3-plan", "001-demo", "phase3-plan", "phase3-consensus", checkpoint, "", "auto", "squad-1", "2026-07-04T12:00:00Z"),
    )
    (spec_dir / "spec.md").write_text("v2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "later")
    later = _git(repo, "rev-parse", "HEAD")
    return repo, spec_dir, checkpoint, later


def test_rewind_requires_confirmation_when_branch_has_later_commits(tmp_path: Path) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=False)

    assert not result.applied
    assert result.from_commit == later
    assert result.to_commit == checkpoint
    assert "echelon rewind phase3-plan --confirm" in result.message


def test_rewind_creates_backup_ref_and_resets_branch_when_confirmed(tmp_path: Path) -> None:
    repo, _spec_dir, checkpoint, later = _repo_with_checkpoint(tmp_path)

    result = prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)

    assert result.applied
    assert _git(repo, "rev-parse", "HEAD") == checkpoint
    assert _git(repo, "rev-parse", result.backup_ref) == later


def test_rewind_refuses_dirty_worktree(tmp_path: Path) -> None:
    repo, spec_dir, _checkpoint, _later = _repo_with_checkpoint(tmp_path)
    (spec_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RewindError, match="dirty worktree"):
        prepare_rewind(project_root=repo, spec="001", target="phase3-plan", confirm=True)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_rewind.py -q`

Expected: FAIL because `echelon.rewind` does not exist.

- [ ] **Step 3: Implement rewind module**

Create `src/echelon/rewind.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from echelon.git_helpers import create_backup_ref, current_branch, is_worktree_dirty, reset_branch_to_commit, run_git
from harness.phase_checkpoints import load_checkpoint_ledger, resolve_checkpoint


class RewindError(RuntimeError):
    pass


@dataclass(frozen=True)
class RewindResult:
    applied: bool
    spec_id: str
    checkpoint_id: str
    from_commit: str
    to_commit: str
    backup_ref: str
    message: str


def _find_spec_dir(project_root: Path, spec: str) -> Path:
    specs = project_root / "specs"
    matches = sorted(path for path in specs.iterdir() if path.is_dir() and path.name.startswith(spec)) if specs.exists() else []
    if not matches:
        raise RewindError(f"no spec directory found for {spec!r}")
    return matches[0]


def prepare_rewind(*, project_root: Path, spec: str, target: str, confirm: bool) -> RewindResult:
    spec_dir = _find_spec_dir(project_root, spec)
    ledger = load_checkpoint_ledger(spec_dir)
    checkpoint = resolve_checkpoint(ledger, target)
    branch = current_branch(project_root)
    if checkpoint.spec_id not in branch:
        raise RewindError(f"active branch {branch!r} does not match spec {checkpoint.spec_id!r}")
    if is_worktree_dirty(project_root):
        raise RewindError("dirty worktree blocks rewind; commit, stash, or discard changes first")
    head = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    if head == checkpoint.commit:
        return RewindResult(True, checkpoint.spec_id, checkpoint.id, head, checkpoint.commit, "", "Already at checkpoint.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_ref = f"echelon/backup/{checkpoint.spec_id}-before-rewind-{stamp}"
    message = (
        f"Rewind will move branch {branch}:\n"
        f"  from: {head[:7]} current HEAD\n"
        f"  to:   {checkpoint.commit[:7]} {checkpoint.phase} checkpoint\n\n"
        f"Backup branch:\n  {backup_ref}\n\n"
        f"Continue with:\n  echelon rewind {checkpoint.phase} --confirm"
    )
    if not confirm:
        return RewindResult(False, checkpoint.spec_id, checkpoint.id, head, checkpoint.commit, backup_ref, message)
    created = create_backup_ref(project_root, backup_ref, "HEAD")
    reset_branch_to_commit(project_root, checkpoint.commit)
    return RewindResult(True, checkpoint.spec_id, checkpoint.id, head, checkpoint.commit, created, "Rewind complete.")
```

Modify `src/echelon/cli.py` `_cmd_rewind` to delegate to `prepare_rewind` for checkpoint-backed specs. Preserve old behavior only behind an internal legacy fallback for branchless recovery if tests require it.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/unit/test_rewind.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/rewind.py src/echelon/cli.py tests/unit/test_rewind.py
git commit -m "feat: rewind spec branches to checkpoint commits"
```

---

### Task 7: Squad Phase Boundary Integration

**Files:**
- Modify: `src/harness/squad.py`
- Test: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Consumes: `create_phase_checkpoint`.
- Produces: automatic checkpoint calls after successful normal and manual phase-node advance.

- [ ] **Step 1: Write failing integration test**

Create `tests/unit/test_squad_phase_checkpoints.py` with a narrow monkeypatch test:

```python
from pathlib import Path
from unittest.mock import MagicMock

from harness.squad import SquadController


def test_squad_records_checkpoint_after_successful_advance(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_checkpoint(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr("harness.squad.create_phase_checkpoint", fake_checkpoint)

    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    controller._state_store = MagicMock()
    controller._state_store.load.return_value = {
        "run_id": "squad-1",
        "spec_dir": "specs/001-demo",
    }

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    controller._checkpoint_successful_phase("phase3-plan", "phase3-consensus")

    assert calls[0]["project_root"] == tmp_path
    assert calls[0]["spec_dir"] == spec_dir
    assert calls[0]["phase"] == "phase3-plan"
    assert calls[0]["next_phase"] == "phase3-consensus"
    assert calls[0]["run_id"] == "squad-1"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_squad_phase_checkpoints.py -q`

Expected: FAIL because `_checkpoint_successful_phase` does not exist.

- [ ] **Step 3: Implement squad hook**

In `src/harness/squad.py`, import:

```python
from harness.phase_checkpoints import create_phase_checkpoint
```

Add method on `SquadController`:

```python
    def _checkpoint_successful_phase(self, phase: str, next_phase: str) -> None:
        state = self._state_store.load()
        spec_ref = str(state.get("spec_dir") or "").strip()
        if not spec_ref:
            return
        spec_dir = Path(spec_ref)
        if not spec_dir.is_absolute():
            spec_dir = self._project_root / spec_dir
        if not spec_dir.exists():
            return
        try:
            create_phase_checkpoint(
                project_root=self._project_root,
                spec_dir=spec_dir,
                phase=phase,
                next_phase=next_phase,
                run_id=str(state.get("run_id") or ""),
            )
        except Exception as exc:
            logger.warning("Could not create phase checkpoint for %s: %s", phase, exc)
```

Call it immediately after `self._state_store.advance(...)` in both `run()` and `run_phase_once()`.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/unit/test_squad_phase_checkpoints.py tests/unit/test_cli_phase.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py tests/unit/test_squad_phase_checkpoints.py
git commit -m "feat: checkpoint successful squad phases"
```

---

### Task 8: Manual Checkpoint Accept and Commit

**Files:**
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `src/echelon/checkpoint_cli.py`
- Test: `tests/unit/test_cli_checkpoint.py`

**Interfaces:**
- Produces: `accept_checkpoint_baseline`, `commit_manual_checkpoint`.
- Consumes: clean/dirty worktree state.

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_cli_checkpoint.py`:

```python
import subprocess


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo_with_spec(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "001-demo")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir


def test_checkpoint_accept_refuses_dirty_files(tmp_path: Path) -> None:
    from harness.phase_checkpoints import accept_checkpoint_baseline

    repo, spec_dir = _repo_with_spec(tmp_path)
    (spec_dir / "tasks.md").write_text("# Dirty Tasks\n", encoding="utf-8")

    try:
        accept_checkpoint_baseline(
            project_root=repo,
            spec_dir=spec_dir,
            phase="phase3-plan",
            run_id="squad-1",
        )
    except RuntimeError as exc:
        assert "dirty worktree" in str(exc)
    else:
        raise AssertionError("dirty worktree should block checkpoint accept")


def test_checkpoint_commit_writes_echelon_trailers(tmp_path: Path) -> None:
    from harness.phase_checkpoints import commit_manual_checkpoint

    repo, spec_dir = _repo_with_spec(tmp_path)
    (spec_dir / "tasks.md").write_text("# Manual Tasks\n", encoding="utf-8")

    checkpoint = commit_manual_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase3-plan",
        run_id="squad-1",
        message="docs: accept manual Phase A checkpoint",
    )

    body = _git(repo, "log", "-1", "--format=%B")
    assert checkpoint.source == "user-committed"
    assert "Co-authored-by: Echelon <echelon@b3cognition.dev>" in body
    assert "Echelon-Action: user-committed-checkpoint" in body
    assert "Echelon-Spec: 001-demo" in body
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_cli_checkpoint.py -q`

Expected: FAIL because accept/commit subcommands are missing.

- [ ] **Step 3: Implement accept and commit**

In `src/harness/phase_checkpoints.py`, add:

```python
def accept_checkpoint_baseline(*, project_root: Path, spec_dir: Path, phase: str, run_id: str) -> PhaseCheckpoint:
    if is_worktree_dirty(project_root):
        raise RuntimeError("dirty worktree cannot be accepted; commit, stash, or discard changes first")
    commit = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    checkpoint = PhaseCheckpoint(new_checkpoint_id(phase, "user-accepted"), _spec_id_from_dir(spec_dir), phase, phase, commit, "", "user-accepted", run_id, datetime.now(timezone.utc).isoformat())
    record_checkpoint_metadata(spec_dir, checkpoint)
    return checkpoint


def commit_manual_checkpoint(*, project_root: Path, spec_dir: Path, phase: str, run_id: str, message: str) -> PhaseCheckpoint:
    if not is_worktree_dirty(project_root):
        raise RuntimeError("no changes to commit")
    spec_id = _spec_id_from_dir(spec_dir)
    checkpoint_id = new_checkpoint_id(phase, "user-committed")
    commit_message = build_echelon_commit_message(
        message,
        EchelonCommitMetadata(origin="phase-a", action="user-committed-checkpoint", spec_id=spec_id, run_id=run_id, phase=phase, checkpoint_id=checkpoint_id),
    )
    run_git(project_root, "add", "-A")
    run_git(project_root, "commit", "-m", commit_message)
    commit = run_git(project_root, "rev-parse", "HEAD").stdout.strip()
    checkpoint = PhaseCheckpoint(checkpoint_id, spec_id, phase, phase, commit, "", "user-committed", run_id, datetime.now(timezone.utc).isoformat())
    record_checkpoint_metadata(spec_dir, checkpoint)
    return checkpoint
```

Wire `accept` and `commit` in `src/echelon/checkpoint_cli.py`.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/unit/test_cli_checkpoint.py tests/unit/test_phase_checkpoints.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/phase_checkpoints.py src/echelon/checkpoint_cli.py tests/unit/test_cli_checkpoint.py
git commit -m "feat: support manual checkpoint baselines"
```

---

### Task 9: Migrate Existing Echelon Commit Paths to Trailers

**Files:**
- Modify: `src/harness/gitops.py`
- Modify: `src/harness/ralph.py`
- Modify: `src/echelon/workspace_git_migration.py`
- Modify: `src/echelon/workspace_source_split_migration.py`
- Modify: `src/harness/land.py`
- Test: `tests/unit/test_echelon_commit_attribution.py`

**Interfaces:**
- Consumes: `build_echelon_commit_message`.
- Produces: all Echelon-created commits include required trailers.

- [ ] **Step 1: Write attribution tests**

Create `tests/unit/test_echelon_commit_attribution.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_echelon_commit_paths_use_shared_commit_message_builder() -> None:
    files = [
        ROOT / "src/harness/ralph.py",
        ROOT / "src/echelon/workspace_git_migration.py",
        ROOT / "src/echelon/workspace_source_split_migration.py",
        ROOT / "src/harness/land.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "build_echelon_commit_message" in text, str(path)


def test_no_new_raw_harness_checkpoint_subjects_without_trailers() -> None:
    text = (ROOT / "src/harness/ralph.py").read_text(encoding="utf-8")
    assert "harness-checkpoint:" in text
    assert "EchelonCommitMetadata" in text
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_echelon_commit_attribution.py -q`

Expected: FAIL because existing files still use raw commit subjects.

- [ ] **Step 3: Migrate commit call sites**

For every Echelon-created commit subject, wrap it before calling `gitops.commit()` or `git commit -m`.

Example in `src/harness/ralph.py` checkpoint creation:

```python
message = build_echelon_commit_message(
    f"harness-checkpoint: {self._spec_id}/{self._strategy_id} iter-{outer_iter} {phase} {label}",
    EchelonCommitMetadata(
        origin="delivery",
        action="checkpoint",
        spec_id=self._spec_id,
        run_id=self._build_id,
        phase=phase,
        strategy=self._strategy_id,
    ),
)
```

Example for salvage:

```python
message = build_echelon_commit_message(
    f"harness-salvage: {spec_id} {strategy_id} iter-{outer_iter}",
    EchelonCommitMetadata(
        origin="delivery",
        action="salvage",
        spec_id=spec_id,
        strategy=strategy_id,
    ),
)
```

Example for workspace init:

```python
message = build_echelon_commit_message(
    "chore: initialize echelon workspace",
    EchelonCommitMetadata(origin="workspace", action="init"),
)
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/unit/test_echelon_commit_attribution.py tests/unit/test_ralph_outer.py::TestOuterLoopConvergence::test_checkpoint_commit_records_task_progress_delta -q`

Expected: PASS. Update assertions that inspect raw messages to expect trailers while preserving readable subject prefixes.

- [ ] **Step 5: Commit**

```bash
git add src/harness/gitops.py src/harness/ralph.py src/echelon/workspace_git_migration.py src/echelon/workspace_source_split_migration.py src/harness/land.py tests/unit/test_echelon_commit_attribution.py tests/unit/test_ralph_outer.py
git commit -m "feat: add Echelon attribution to generated commits"
```

---

### Task 10: EGR Completion Docs and Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Test: focused and relevant existing tests.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: completed EGR-082 documentation and verification evidence.

- [ ] **Step 1: Update changelog**

Add under `[Unreleased]`:

```markdown
- **EGR-085 spec-scoped checkpoints and rewind** - added spec-scoped
  Phase A checkpoint metadata, `echelon checkpoint` commands, branch-level
  rewind with backup refs, manual checkpoint UX, and mandatory Echelon commit
  attribution trailers for generated commits.
```

- [ ] **Step 2: Update EGR register**

Change EGR-082 status from `in-progress` to `fixed`. Replace next action with:

```text
Fixed: Phase A checkpoints are spec-scoped and metadata-backed, rewind moves the spec branch to recorded checkpoint commits with backup refs, manual artifact edits require explicit accept/commit handling, and Echelon-created commits carry parseable attribution trailers.
```

Add a review note with the final commit SHA and verification commands.

- [ ] **Step 3: Run focused verification**

Run:

```bash
pytest tests/unit/test_commit_messages.py tests/unit/test_git_helpers.py tests/unit/test_phase_checkpoints.py tests/unit/test_cli_checkpoint.py tests/unit/test_rewind.py tests/unit/test_squad_phase_checkpoints.py tests/unit/test_echelon_commit_attribution.py -q
```

Expected: PASS.

- [ ] **Step 4: Run recovery regression verification**

Run:

```bash
pytest tests/unit/test_harness_recovery.py tests/unit/test_cli_harness_resume.py tests/unit/test_ralph_outer.py -q
```

Expected: PASS or known unrelated failures documented with exact failing test names.

- [ ] **Step 5: Sync EGR issue**

Run:

```bash
python3 scripts/sync-egr-issues.py --repo B3Cognition/echelon
```

Expected: output includes `updated EGR-082: https://github.com/B3Cognition/echelon/issues/105`.

- [ ] **Step 6: Commit completion docs**

```bash
git add CHANGELOG.md docs/findings/echelon-grounded-review-register.md
git commit -m "docs: mark EGR-082 fixed"
```
