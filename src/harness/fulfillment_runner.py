"""Fulfillment verification orchestration for harness convergence."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Mapping, Protocol

from harness.skill_loader import build_skill_prompt, find_skill
from harness.spec_frontmatter import find_spec_dir
from kernel.fulfillment import (
    latest_fulfillment_report,
    stamp_fulfillment_report,
    validate_fulfillment_artifacts,
)


class PromptExecutor(Protocol):
    @property
    def cli(self) -> str:
        ...

    def exec_prompt(
        self,
        worktree_path: str,
        prompt: str,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> int:
        ...


class FulfillmentRunner:
    """Runs the verify-spec skill without teaching the LLM provider Echelon semantics."""

    def __init__(self, prompt_executor: PromptExecutor) -> None:
        self._prompt_executor = prompt_executor

    def refresh(
        self,
        worktree_path: str,
        spec_id: str,
        *,
        orchestration_root: Path | str | None = None,
    ) -> int:
        skill_path = find_skill(
            "echelon.verify-spec",
            Path(worktree_path),
            self._prompt_executor.cli,
        )
        if skill_path is None:
            return 127

        spec_dir = _resolve_spec_dir(spec_id, Path(worktree_path), orchestration_root)
        arguments = spec_id
        if spec_dir is not None:
            arguments = f"{spec_id} spec_dir={spec_dir}"

        prompt = build_skill_prompt(skill_path, arguments)
        exit_code = self._prompt_executor.exec_prompt(worktree_path, prompt)
        if exit_code == 0:
            if not _latest_report_matches_latest_audit(
                Path(worktree_path),
                spec_id,
                spec_dir=spec_dir,
            ):
                return 2
            _stamp_latest_report(Path(worktree_path), spec_id, spec_dir=spec_dir)
        return exit_code


def _resolve_spec_dir(
    spec_id: str,
    worktree: Path,
    orchestration_root: Path | str | None,
) -> Path | None:
    if orchestration_root is not None:
        spec_dir = find_spec_dir(spec_id, Path(orchestration_root))
        if spec_dir is not None:
            return spec_dir
    return find_spec_dir(spec_id, worktree)


def _stamp_latest_report(
    worktree: Path,
    spec_id: str,
    *,
    spec_dir: Path | None = None,
) -> None:
    spec_dir = spec_dir or find_spec_dir(spec_id, worktree)
    commit = _current_git_commit(worktree)
    if spec_dir is None or commit is None:
        return

    report = latest_fulfillment_report(spec_dir)
    if report is None:
        return

    run_id = _current_run_id(worktree)
    stamp_fulfillment_report(report, spec_id=spec_id, commit=commit, run_id=run_id)


def _latest_report_matches_latest_audit(
    worktree: Path,
    spec_id: str,
    *,
    spec_dir: Path | None = None,
) -> bool:
    spec_dir = spec_dir or find_spec_dir(spec_id, worktree)
    if spec_dir is None:
        return True
    report = latest_fulfillment_report(spec_dir)
    audit = _latest_requirement_audit(worktree, spec_id)
    if report is None or audit is None:
        return True
    return validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
    ).ok


def _latest_requirement_audit(worktree: Path, spec_id: str) -> Path | None:
    runs = worktree / "runs"
    if not runs.exists():
        return None
    candidates = list(runs.glob(f"verify-spec-{spec_id}-*/requirement-audit.md"))
    candidates.extend(runs.glob(f"*/verify-spec/{spec_id}/requirement-audit.md"))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def _current_git_commit(worktree: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _current_run_id(worktree: Path) -> str | None:
    current = worktree / "runs" / ".current"
    if not current.exists():
        return None
    run_id = current.read_text(encoding="utf-8", errors="replace").strip()
    return run_id or None
