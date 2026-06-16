"""Fulfillment verification orchestration for harness convergence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import subprocess
import tempfile
from typing import Mapping, Protocol

from harness.canonical_requirements import INVENTORY_JSON
from harness.scoped_verify import (
    build_scoped_verify_plan,
    merge_scoped_fulfillment_report,
)
from harness.skill_loader import build_skill_prompt, find_skill
from harness.spec_frontmatter import find_spec_dir
from kernel.fulfillment import (
    fulfillment_table_ids,
    latest_fulfillment_report,
    read_fulfillment_metadata,
    stamp_fulfillment_report,
    validate_fulfillment_artifacts,
)

AUDIT_SCOPE_DROP_THRESHOLD = 0.10
SCOPE_INPUT_FILENAMES = (
    "spec.md",
    "plan.md",
    "tasks.md",
    "coverage-map.md",
    "user-clarifications.md",
)


@dataclass(frozen=True)
class FulfillmentRefreshResult:
    """Result of a verify-spec fulfillment refresh attempt."""

    status: str
    exit_code: int
    used_cache: bool = False
    scope: str = "full"
    reason: str = ""
    cache_key: str | None = None
    report_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


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
        scope: str = "full",
        completed_task_ids: list[str] | tuple[str, ...] | None = None,
        changed_files: list[str] | tuple[str, ...] | None = None,
    ) -> FulfillmentRefreshResult:
        worktree = Path(worktree_path)
        spec_dir = _resolve_spec_dir(spec_id, Path(worktree_path), orchestration_root)
        commit = _current_git_commit(worktree)
        spec_input_hash = _spec_input_hash(spec_dir) if spec_dir is not None else None
        cache_key = _verify_cache_key(
            spec_id=spec_id,
            commit=commit,
            spec_input_hash=spec_input_hash,
        )
        report = latest_fulfillment_report(spec_dir) if spec_dir is not None else None
        report_path = str(report) if report is not None else None
        if scope == "scoped":
            return self._refresh_scoped(
                worktree_path=worktree_path,
                worktree=worktree,
                spec_id=spec_id,
                spec_dir=spec_dir,
                commit=commit,
                report=report,
                report_path=report_path,
                completed_task_ids=completed_task_ids or [],
                changed_files=changed_files or [],
            )
        if _latest_full_report_matches_cache(
            worktree,
            spec_id,
            spec_dir=spec_dir,
            commit=commit,
            spec_input_hash=spec_input_hash,
            cache_key=cache_key,
        ):
            return FulfillmentRefreshResult(
                status="cached",
                exit_code=0,
                used_cache=True,
                scope="full",
                reason="full verify-spec cache hit",
                cache_key=cache_key,
                report_path=report_path,
            )

        skill_path = find_skill(
            "echelon.verify-spec",
            worktree,
            self._prompt_executor.cli,
        )
        if skill_path is None:
            return FulfillmentRefreshResult(
                status="missing_skill",
                exit_code=127,
                scope="full",
                reason="verify-spec skill missing",
                cache_key=cache_key,
                report_path=report_path,
            )

        arguments = spec_id
        if spec_dir is not None:
            arguments = f"{spec_id} spec_dir={spec_dir}"

        prompt = build_skill_prompt(skill_path, arguments)
        exit_code = self._prompt_executor.exec_prompt(worktree_path, prompt)
        if exit_code == 0:
            if not _latest_report_matches_latest_audit(
                worktree,
                spec_id,
                spec_dir=spec_dir,
            ):
                return FulfillmentRefreshResult(
                    status="failed",
                    exit_code=2,
                    scope="full",
                    reason="full verify-spec artifact validation failed",
                    cache_key=cache_key,
                    report_path=report_path,
                )
            _stamp_latest_report(
                worktree,
                spec_id,
                spec_dir=spec_dir,
                commit=commit,
                spec_input_hash=spec_input_hash,
                cache_key=cache_key,
            )
            report = latest_fulfillment_report(spec_dir) if spec_dir is not None else None
            report_path = str(report) if report is not None else None
            return FulfillmentRefreshResult(
                status="refreshed",
                exit_code=0,
                scope="full",
                reason="full verify-spec completed",
                cache_key=cache_key,
                report_path=report_path,
            )
        return FulfillmentRefreshResult(
            status="failed",
            exit_code=exit_code,
            scope="full",
            reason="full verify-spec failed",
            cache_key=cache_key,
            report_path=report_path,
        )

    def _refresh_scoped(
        self,
        *,
        worktree_path: str,
        worktree: Path,
        spec_id: str,
        spec_dir: Path | None,
        commit: str | None,
        report: Path | None,
        report_path: str | None,
        completed_task_ids: list[str] | tuple[str, ...],
        changed_files: list[str] | tuple[str, ...],
    ) -> FulfillmentRefreshResult:
        if spec_dir is None or commit is None:
            return FulfillmentRefreshResult(
                status="failed",
                exit_code=2,
                scope="scoped",
                reason="scoped verify-spec missing spec dir or commit",
                report_path=report_path,
            )
        plan = build_scoped_verify_plan(
            spec_dir=spec_dir,
            completed_task_ids=completed_task_ids,
            changed_files=changed_files,
        )
        if not plan.impacted_requirement_ids:
            return FulfillmentRefreshResult(
                status="cached",
                exit_code=0,
                used_cache=True,
                scope="scoped",
                reason="scoped verify-spec skipped; no impacted requirements",
                report_path=report_path,
            )
        if report is None:
            return FulfillmentRefreshResult(
                status="failed",
                exit_code=2,
                scope="scoped",
                reason="scoped verify-spec requires a base full fulfillment report",
                report_path=report_path,
            )

        skill_path = find_skill(
            "echelon.verify-spec",
            worktree,
            self._prompt_executor.cli,
        )
        if skill_path is None:
            return FulfillmentRefreshResult(
                status="missing_skill",
                exit_code=127,
                scope="scoped",
                reason="verify-spec skill missing",
                report_path=report_path,
            )

        scoped_ids = ",".join(plan.impacted_requirement_ids)
        arguments = (
            f"{spec_id} spec_dir={spec_dir} scope=scoped scoped_ids={scoped_ids}"
        )
        if plan.base_full_verify_commit:
            arguments += f" base_full_verify_commit={plan.base_full_verify_commit}"

        prompt = build_skill_prompt(skill_path, arguments)
        with tempfile.TemporaryDirectory() as temp_dir:
            base_snapshot = Path(temp_dir) / "base-full-fulfillment-report.md"
            base_snapshot.write_text(
                report.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
            exit_code = self._prompt_executor.exec_prompt(worktree_path, prompt)
            if exit_code != 0:
                return FulfillmentRefreshResult(
                    status="failed",
                    exit_code=exit_code,
                    scope="scoped",
                    reason="scoped verify-spec failed",
                    report_path=report_path,
                )
            scoped_report = latest_fulfillment_report(spec_dir)
            if scoped_report is None:
                return FulfillmentRefreshResult(
                    status="failed",
                    exit_code=2,
                    scope="scoped",
                    reason="scoped verify-spec did not write fulfillment report",
                    report_path=report_path,
                )
            merge_scoped_fulfillment_report(
                base_report_path=base_snapshot,
                scoped_report_path=scoped_report,
                output_report_path=report,
                impacted_requirement_ids=plan.impacted_requirement_ids,
                spec_id=spec_id,
                commit=commit,
                base_full_verify_commit=plan.base_full_verify_commit,
            )
            return FulfillmentRefreshResult(
                status="refreshed",
                exit_code=0,
                scope="scoped",
                reason="scoped verify-spec completed",
                report_path=str(report),
            )


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
    commit: str | None = None,
    spec_input_hash: str | None = None,
    cache_key: str | None = None,
) -> None:
    spec_dir = spec_dir or find_spec_dir(spec_id, worktree)
    if spec_dir is None or commit is None:
        return

    report = latest_fulfillment_report(spec_dir)
    if report is None:
        return

    run_id = _current_run_id(worktree)
    extra_metadata: dict[str, str] = {"verify_scope": "full"}
    if spec_input_hash:
        extra_metadata["spec_input_hash"] = spec_input_hash
    if cache_key:
        extra_metadata["verify_cache_key"] = cache_key
    stamp_fulfillment_report(
        report,
        spec_id=spec_id,
        commit=commit,
        run_id=run_id,
        extra_metadata=extra_metadata,
    )


def _latest_full_report_matches_cache(
    worktree: Path,
    spec_id: str,
    *,
    spec_dir: Path | None,
    commit: str | None,
    spec_input_hash: str | None,
    cache_key: str | None,
) -> bool:
    if spec_dir is None or commit is None or spec_input_hash is None or cache_key is None:
        return False
    report = latest_fulfillment_report(spec_dir)
    if report is None:
        return False
    metadata = read_fulfillment_metadata(report)
    if metadata.get("verify_scope") != "full":
        return False
    if metadata.get("verified_commit") != commit:
        return False
    if metadata.get("spec_input_hash") != spec_input_hash:
        return False
    if metadata.get("verify_cache_key") != cache_key:
        return False
    return _latest_report_matches_latest_audit(worktree, spec_id, spec_dir=spec_dir)


def _spec_input_hash(spec_dir: Path | None) -> str | None:
    if spec_dir is None:
        return None
    digest = hashlib.sha256()
    for filename in SCOPE_INPUT_FILENAMES:
        path = spec_dir / filename
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(b"1\0")
            digest.update(path.read_bytes())
        else:
            digest.update(b"0\0")
    return digest.hexdigest()


def _verify_cache_key(
    *,
    spec_id: str,
    commit: str | None,
    spec_input_hash: str | None,
) -> str | None:
    if commit is None or spec_input_hash is None:
        return None
    digest = hashlib.sha256()
    digest.update(b"verify-spec-cache-v1\0")
    digest.update(spec_id.encode("utf-8"))
    digest.update(b"\0full\0")
    digest.update(commit.encode("utf-8"))
    digest.update(b"\0")
    digest.update(spec_input_hash.encode("utf-8"))
    return digest.hexdigest()


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
    if not _latest_audit_scope_is_stable(
        worktree,
        spec_id,
        latest_audit=audit,
        spec_dir=spec_dir,
    ):
        return False
    return validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
        canonical_inventory_path=_latest_canonical_inventory(worktree, spec_id),
    ).ok


def _latest_requirement_audit(worktree: Path, spec_id: str) -> Path | None:
    audits = _requirement_audits(worktree, spec_id)
    return audits[-1] if audits else None


def _latest_canonical_inventory(worktree: Path, spec_id: str) -> Path | None:
    runs = worktree / "runs"
    if not runs.exists():
        return None
    candidates = list(runs.glob(f"verify-spec-{spec_id}-*/{INVENTORY_JSON}"))
    candidates.extend(runs.glob(f"*/verify-spec/{spec_id}/{INVENTORY_JSON}"))
    existing = [path for path in candidates if path.is_file()]
    return sorted(existing, key=lambda path: path.stat().st_mtime)[-1] if existing else None


def _requirement_audits(worktree: Path, spec_id: str) -> list[Path]:
    runs = worktree / "runs"
    if not runs.exists():
        return []
    candidates = list(runs.glob(f"verify-spec-{spec_id}-*/requirement-audit.md"))
    candidates.extend(runs.glob(f"*/verify-spec/{spec_id}/requirement-audit.md"))
    existing = [path for path in candidates if path.is_file()]
    return sorted(existing, key=lambda path: path.stat().st_mtime)


def _latest_audit_scope_is_stable(
    worktree: Path,
    spec_id: str,
    *,
    latest_audit: Path,
    spec_dir: Path,
) -> bool:
    audits = _requirement_audits(worktree, spec_id)
    previous = [path for path in audits if path != latest_audit]
    if not previous:
        return True
    previous_audit = previous[-1]
    previous_ids = fulfillment_table_ids(
        previous_audit.read_text(encoding="utf-8", errors="replace")
    )
    latest_ids = fulfillment_table_ids(
        latest_audit.read_text(encoding="utf-8", errors="replace")
    )
    if not previous_ids or len(latest_ids) >= len(previous_ids):
        return True
    dropped_ids = previous_ids - latest_ids
    drop_ratio = len(dropped_ids) / len(previous_ids)
    if drop_ratio <= AUDIT_SCOPE_DROP_THRESHOLD:
        return True
    return _scope_inputs_changed_after(spec_dir, previous_audit)


def _scope_inputs_changed_after(spec_dir: Path, previous_audit: Path) -> bool:
    try:
        previous_mtime = previous_audit.stat().st_mtime
    except OSError:
        return True
    for filename in SCOPE_INPUT_FILENAMES:
        path = spec_dir / filename
        try:
            if path.is_file() and path.stat().st_mtime > previous_mtime:
                return True
        except OSError:
            continue
    return False


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
