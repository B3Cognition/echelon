"""No-LLM, real-Git acceptance flow for EGR-151 spec lifecycle GitOps."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from echelon.phase_a_start import PhaseAStartOutcome, start_phase_a_spec
from harness.phase_checkpoints import create_phase_checkpoint
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS


VALID_PLAN = """# Implementation Plan: Demo

## Summary
Demo.

## Technical Context
Python.

## Architecture Decisions
- ADR-001: Keep it simple.

## Project Structure
```text
src/
```

## Implementation Phases
- Foundation.

## Testing Strategy
- Unit tests.

## Risks
- None.

## Constitution Check
| Principle | Compliance |
| --- | --- |
| Local-first | PASS |
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Echelon Tests")
    _git(repo, "config", "user.email", "echelon@example.test")
    (repo / ".gitignore").write_text(
        "/.echelon/runtime/\n/runs/.current\n/runs/*/state.json\n"
        "/runs/*/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / "package.json").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md", "package.json")
    _git(repo, "commit", "-m", "base")
    return repo


def _write_phase_a_artifacts(spec_dir: Path, *, ready: bool) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        if name == "spec.md":
            content = "---\ntargets:\n  - .\n---\n# Spec\n"
        elif name == "plan.md":
            content = VALID_PLAN
        elif name == "tasks.md":
            content = (
                "- [ ] T-001 complexity=standard phase=foundation "
                "req=INFRA depends=none target=.\n"
            )
        elif name == "constitution.md":
            content = "# Constitution\n\nProject rules.\n"
        else:
            content = f"# {name}\n"
        (spec_dir / name).write_text(content, encoding="utf-8")
    if not ready:
        (spec_dir / "constitution.md").unlink()


def _checkpoint_run(repo: Path, outcome: PhaseAStartOutcome) -> str:
    spec_dir = outcome.run_dir / "specs" / outcome.bootstrap.spec_id
    _write_phase_a_artifacts(spec_dir, ready=True)
    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=spec_dir,
        phase="phase2-plan",
        next_phase="phase3-review",
        run_id="run-a",
        spec_id=outcome.bootstrap.spec_id,
    )
    return checkpoint.commit


def _dispatch_delivery(
    repo: Path,
    spec_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    from echelon.cli import _cmd_harness_run

    config_file = repo / ".echelon" / "config.yml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("harness:\n  target_repo: .\n", encoding="utf-8")
    mirror = repo / "runs" / "mirror.git"
    mirror.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(repo)
    config = SimpleNamespace(
        buffer_limit_bytes=1024 * 1024,
        target_repo=str(repo),
        target_default_branch="main",
        provider="docker",
    )
    with (
        patch("harness.config.load_config", return_value=config),
        patch("harness.paths.mirror_path", return_value=mirror),
        patch("harness.gitops.GitOpsManager"),
        patch("harness.docker_provider.DockerWorktreeProvider"),
        patch("harness.skills.run_skill.run") as runner,
    ):
        try:
            _cmd_harness_run([spec_id])
        except SystemExit as exc:
            return runner, exc
        return runner, None


def test_checkpointed_nonfinal_a_allows_sibling_b_and_isolated_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _init_repo(tmp_path)
    main_commit = _git(repo, "rev-parse", "main^{commit}")

    a = start_phase_a_spec(repo, "run-a", "Spec A")
    checkpoint_a = _checkpoint_run(repo, a)
    assert _git(repo, "branch", "--show-current") == a.bootstrap.feature_branch
    assert _git(repo, "rev-parse", "HEAD^{commit}") == checkpoint_a

    b = start_phase_a_spec(repo, "run-b", "Spec B")
    assert b.source_checkpoint is not None
    assert b.source_checkpoint.commit == checkpoint_a
    assert _git(repo, "branch", "--show-current") == b.bootstrap.feature_branch
    assert _git(repo, "rev-parse", f"{b.bootstrap.feature_branch}^{{commit}}") == main_commit
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"

    _write_phase_a_artifacts(repo / "specs" / a.bootstrap.spec_id, ready=True)
    dirty_note = repo / "authoring-note.md"
    dirty_note.write_text("B remains dirty\n", encoding="utf-8")
    runner_a, failure_a = _dispatch_delivery(repo, a.bootstrap.spec_id, monkeypatch)

    assert failure_a is None
    runner_a.assert_called_once()
    assert _git(repo, "branch", "--show-current") == b.bootstrap.feature_branch
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"
    assert dirty_note.read_text(encoding="utf-8") == "B remains dirty\n"

    _write_phase_a_artifacts(repo / "specs" / b.bootstrap.spec_id, ready=False)
    runner_b, failure_b = _dispatch_delivery(repo, b.bootstrap.spec_id, monkeypatch)

    assert failure_b is not None
    assert failure_b.code == 1
    runner_b.assert_not_called()
    assert _git(repo, "branch", "--show-current") == b.bootstrap.feature_branch
    assert (repo / "runs" / ".current").read_text(encoding="utf-8") == "run-b\n"
