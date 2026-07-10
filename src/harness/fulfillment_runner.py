"""Fulfillment verification orchestration for harness convergence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
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
    fulfillment_report_is_current,
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

IMPLEMENTATION_INPUT_DIRS = (
    "src",
    "app",
    "apps",
    "lib",
    "packages",
    "tests",
    "test",
)

IMPLEMENTATION_INPUT_FILES = (
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Makefile",
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
        spec_dir: Path | str | None = None,
        orchestration_root: Path | str | None = None,
        scope: str = "full",
        completed_task_ids: list[str] | tuple[str, ...] | None = None,
        changed_files: list[str] | tuple[str, ...] | None = None,
    ) -> FulfillmentRefreshResult:
        worktree = Path(worktree_path)
        resolved_spec_dir = _resolve_spec_dir(
            spec_id,
            Path(worktree_path),
            orchestration_root,
            explicit_spec_dir=spec_dir,
        )
        commit = _current_git_commit(worktree)
        spec_input_hash = (
            _spec_input_hash(resolved_spec_dir)
            if resolved_spec_dir is not None
            else None
        )
        implementation_input_hash = _implementation_input_hash(worktree)
        cache_key = _verify_cache_key(
            spec_id=spec_id,
            commit=commit,
            spec_input_hash=spec_input_hash,
            implementation_input_hash=implementation_input_hash,
        )
        report = (
            latest_fulfillment_report(resolved_spec_dir)
            if resolved_spec_dir is not None
            else None
        )
        report_path = str(report) if report is not None else None
        if scope == "scoped":
            return self._refresh_scoped(
                worktree_path=worktree_path,
                worktree=worktree,
                spec_id=spec_id,
                spec_dir=resolved_spec_dir,
                commit=commit,
                report=report,
                report_path=report_path,
                completed_task_ids=completed_task_ids or [],
                changed_files=changed_files or [],
            )
        if _latest_full_report_matches_cache(
            worktree,
            spec_id,
            spec_dir=resolved_spec_dir,
            commit=commit,
            spec_input_hash=spec_input_hash,
            implementation_input_hash=implementation_input_hash,
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
        if resolved_spec_dir is not None:
            arguments = f"{spec_id} spec_dir={resolved_spec_dir}"

        prompt = _build_verify_spec_prompt(worktree, skill_path, arguments)
        exit_code = self._prompt_executor.exec_prompt(worktree_path, prompt)
        provider_limit_reason = _provider_session_limit_reason(
            self._prompt_executor,
            existing_report=report,
            current_commit=commit,
        )
        if exit_code != 0 and provider_limit_reason:
            return FulfillmentRefreshResult(
                status="provider_session_limit",
                exit_code=exit_code,
                scope="full",
                reason=provider_limit_reason,
                cache_key=cache_key,
                report_path=report_path,
            )
        if exit_code == 0:
            if not _latest_report_matches_latest_audit(
                worktree,
                spec_id,
                spec_dir=resolved_spec_dir,
                artifact_root=_run_pointer_root(
                    worktree,
                    spec_dir=resolved_spec_dir,
                    orchestration_root=orchestration_root,
                ),
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
                spec_dir=resolved_spec_dir,
                orchestration_root=orchestration_root,
                commit=commit,
                spec_input_hash=spec_input_hash,
                implementation_input_hash=implementation_input_hash,
                cache_key=cache_key,
            )
            report = (
                latest_fulfillment_report(resolved_spec_dir)
                if resolved_spec_dir is not None
                else None
            )
            report_path = str(report) if report is not None else None
            if (
                report is None
                or commit is None
                or not fulfillment_report_is_current(report, current_commit=commit)
            ):
                return FulfillmentRefreshResult(
                    status="failed",
                    exit_code=2,
                    scope="full",
                    reason="full verify-spec report was not stamped for current HEAD",
                    cache_key=cache_key,
                    report_path=report_path,
                )
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
            if report is None or not fulfillment_report_is_current(
                report, current_commit=commit
            ):
                return self.refresh(
                    worktree_path,
                    spec_id,
                    orchestration_root=spec_dir.parent.parent,
                    scope="full",
                )
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

        prompt = _build_verify_spec_prompt(worktree, skill_path, arguments)
        with tempfile.TemporaryDirectory() as temp_dir:
            base_snapshot = Path(temp_dir) / "base-full-fulfillment-report.md"
            base_snapshot.write_text(
                report.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
            exit_code = self._prompt_executor.exec_prompt(worktree_path, prompt)
            provider_limit_reason = _provider_session_limit_reason(
                self._prompt_executor,
                existing_report=report,
                current_commit=commit,
            )
            if exit_code != 0 and provider_limit_reason:
                return FulfillmentRefreshResult(
                    status="provider_session_limit",
                    exit_code=exit_code,
                    scope="scoped",
                    reason=provider_limit_reason,
                    report_path=report_path,
                )
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
    *,
    explicit_spec_dir: Path | str | None = None,
) -> Path | None:
    if explicit_spec_dir is not None:
        candidate = Path(explicit_spec_dir)
        if not candidate.is_absolute() and orchestration_root is not None:
            candidate = Path(orchestration_root) / candidate
        return candidate
    if orchestration_root is not None:
        spec_dir = find_spec_dir(spec_id, Path(orchestration_root))
        if spec_dir is not None:
            return spec_dir
    return find_spec_dir(spec_id, worktree)


def _build_verify_spec_prompt(worktree: Path, skill_path: Path, arguments: str) -> str:
    prompt = build_skill_prompt(skill_path, arguments)
    phase_context = _verify_spec_phase_context(worktree)
    if not phase_context:
        return prompt
    return f"{prompt}\n\n{_VERIFY_SPEC_DIRECT_INVOCATION_GUARD}\n\n{phase_context}"


_VERIFY_SPEC_DIRECT_INVOCATION_GUARD = """\
## Direct verify-spec invocation guard

This prompt is the complete verify-spec instruction set for this direct
fulfillment refresh. Treat the embedded phase context below as the current phase
prompt. Do not search for or read `.claude/skills`, `SKILL.md`, workflow phase
files, or workflow definition files. Use the provided spec_dir argument and the
embedded Python-owned commands.
"""


def _verify_spec_phase_context(worktree: Path) -> str:
    phase_dir = (
        worktree
        / ".specify"
        / "extensions"
        / "echelon"
        / "workflow"
        / "phases"
    )
    if not phase_dir.is_dir():
        return ""
    phase_files = sorted(phase_dir.glob("verify-spec-*.md"))
    if not phase_files:
        return ""
    sections = ["## Embedded Verify-Spec Phase Context"]
    for path in phase_files:
        sections.append(f"### {path.name}")
        sections.append(path.read_text(encoding="utf-8", errors="replace").strip())
    return "\n\n".join(sections).strip()


def _stamp_latest_report(
    worktree: Path,
    spec_id: str,
    *,
    spec_dir: Path | None = None,
    orchestration_root: Path | str | None = None,
    commit: str | None = None,
    spec_input_hash: str | None = None,
    implementation_input_hash: str | None = None,
    cache_key: str | None = None,
) -> None:
    spec_dir = spec_dir or find_spec_dir(spec_id, worktree)
    if spec_dir is None or commit is None:
        return

    report = latest_fulfillment_report(spec_dir)
    if report is None:
        return

    run_root = _run_pointer_root(
        worktree,
        spec_dir=spec_dir,
        orchestration_root=orchestration_root,
    )
    run_id = _current_run_id(run_root)
    extra_metadata: dict[str, str] = {"verify_scope": "full"}
    if spec_input_hash:
        extra_metadata["spec_input_hash"] = spec_input_hash
    if implementation_input_hash:
        extra_metadata["implementation_input_hash"] = implementation_input_hash
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
    implementation_input_hash: str | None,
    cache_key: str | None,
) -> bool:
    if (
        spec_dir is None
        or commit is None
        or spec_input_hash is None
        or implementation_input_hash is None
        or cache_key is None
    ):
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
    if metadata.get("implementation_input_hash") != implementation_input_hash:
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


def _implementation_input_hash(worktree: Path) -> str:
    """Hash implementation files that verify-spec maps to requirements.

    The git commit alone is insufficient while Ralph is evaluating a fresh build
    slice: the worktree may contain uncommitted source/test changes before the
    checkpoint commit is written. This hash keeps full verify-spec caching valid
    only when the actual implementation inputs are unchanged.
    """
    digest = hashlib.sha256()
    for path in _implementation_input_paths(worktree):
        rel = path.relative_to(worktree).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


def _implementation_input_paths(worktree: Path) -> list[Path]:
    paths: set[Path] = set()
    for dirname in IMPLEMENTATION_INPUT_DIRS:
        root = worktree / dirname
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and not _is_ignored_implementation_path(path):
                paths.add(path)
    for filename in IMPLEMENTATION_INPUT_FILES:
        path = worktree / filename
        if path.is_file():
            paths.add(path)
    return sorted(paths, key=lambda path: path.relative_to(worktree).as_posix())


def _is_ignored_implementation_path(path: Path) -> bool:
    parts = set(path.parts)
    return bool(
        parts
        & {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "node_modules",
            "dist",
            "build",
            ".venv",
            "venv",
        }
    )


def _verify_cache_key(
    *,
    spec_id: str,
    commit: str | None,
    spec_input_hash: str | None,
    implementation_input_hash: str | None,
) -> str | None:
    if commit is None or spec_input_hash is None or implementation_input_hash is None:
        return None
    digest = hashlib.sha256()
    digest.update(b"verify-spec-cache-v2\0")
    digest.update(spec_id.encode("utf-8"))
    digest.update(b"\0full\0")
    digest.update(commit.encode("utf-8"))
    digest.update(b"\0")
    digest.update(spec_input_hash.encode("utf-8"))
    digest.update(b"\0")
    digest.update(implementation_input_hash.encode("utf-8"))
    return digest.hexdigest()


def _provider_session_limit_reason(
    prompt_executor: PromptExecutor,
    *,
    existing_report: Path | None,
    current_commit: str | None,
) -> str:
    text = _provider_limit_text(prompt_executor)
    if not _is_provider_session_limit_text(text):
        return ""

    reason = (
        _provider_session_limit_summary(text)
        or "LLM provider session limit reached during verify-spec"
    )
    stale_detail = _existing_report_stale_detail(
        existing_report=existing_report,
        current_commit=current_commit,
    )
    if stale_detail:
        reason = f"{reason}; {stale_detail}"
    return reason


def _provider_limit_text(prompt_executor: PromptExecutor) -> str:
    parts = [
        str(getattr(prompt_executor, "last_stdout", "") or ""),
        str(getattr(prompt_executor, "last_stderr", "") or ""),
    ]
    return "\n".join(part for part in parts if part).strip()


def _provider_session_limit_summary(text: str) -> str:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line and _is_provider_session_limit_text(line):
            return _truncate_provider_reason(line)

    patterns = (
        r"you(?:'|\u2019)ve hit your [^.:\n;]*?limit[^.\n;]*"
        r"(?:resets? [^.\n;]*)?",
        r"(?:session|usage|rate) limit[^.\n;]*(?:resets? [^.\n;]*)?",
        r"quota exceeded[^.\n;]*(?:resets? [^.\n;]*)?",
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if matches:
            return _truncate_provider_reason(matches[-1].group(0).strip())

    return _truncate_provider_reason(text.strip())


def _truncate_provider_reason(text: str, limit: int = 240) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _is_provider_session_limit_text(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return False
    return any(
        needle in lowered
        for needle in (
            "session limit",
            "usage limit",
            "rate limit",
            "quota exceeded",
            "resets ",
            "reset window",
        )
    )


def _existing_report_stale_detail(
    *,
    existing_report: Path | None,
    current_commit: str | None,
) -> str:
    if existing_report is None or current_commit is None:
        return ""
    metadata = read_fulfillment_metadata(existing_report)
    verified_commit = metadata.get("verified_commit")
    if not isinstance(verified_commit, str) or not verified_commit:
        return (
            f"existing fulfillment report {existing_report} has no "
            f"verified_commit for current HEAD {current_commit}"
        )
    if verified_commit == current_commit:
        return ""
    return (
        f"existing fulfillment report {existing_report} was verified at "
        f"{verified_commit}, current HEAD is {current_commit}; do not use it "
        "as current fulfillment evidence"
    )


def _latest_report_matches_latest_audit(
    worktree: Path,
    spec_id: str,
    *,
    spec_dir: Path | None = None,
    artifact_root: Path | None = None,
) -> bool:
    spec_dir = spec_dir or find_spec_dir(spec_id, worktree)
    artifact_root = artifact_root or worktree
    if spec_dir is None:
        return True
    report = latest_fulfillment_report(spec_dir)
    audit = _latest_requirement_audit(artifact_root, spec_id)
    if report is None or audit is None:
        return True
    if not _latest_audit_scope_is_stable(
        artifact_root,
        spec_id,
        latest_audit=audit,
        spec_dir=spec_dir,
    ):
        return False
    return validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
        canonical_inventory_path=_latest_canonical_inventory(artifact_root, spec_id),
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


def _run_pointer_root(
    worktree: Path,
    *,
    spec_dir: Path | None = None,
    orchestration_root: Path | str | None = None,
) -> Path:
    if orchestration_root is not None:
        return Path(orchestration_root)
    if spec_dir is not None:
        if spec_dir.parent.name == "specs":
            return spec_dir.parent.parent
    return worktree


def _current_run_id(worktree: Path) -> str | None:
    current = worktree / "runs" / ".current"
    if not current.exists():
        return None
    run_id = current.read_text(encoding="utf-8", errors="replace").strip()
    return run_id or None
