"""Classify and apply build-produced dirty worktree files before landing."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


CLASSIFICATIONS = {"commit", "ignore", "leave", "block"}
SOURCE_LIKE_PREFIXES = (
    "src/",
    "lib/",
    "app/",
    "apps/",
    "packages/",
    "tests/",
    "test/",
    "specs/",
    "docs/",
    "migrations/",
)
SOURCE_LIKE_SUFFIXES = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".lock",
)
DISPOSABLE_PATTERNS = (
    re.compile(r"(^|/)\.pytest_cache/"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)\.mypy_cache/"),
    re.compile(r"(^|/)\.ruff_cache/"),
    re.compile(r"(^|/)node_modules/"),
    re.compile(r"(^|/)coverage/"),
    re.compile(r"(^|/)dist/"),
    re.compile(r"(^|/)build/"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.tmp$"),
    re.compile(r"\.log$"),
)
GENERATED_CACHE_PATTERNS = (
    re.compile(r"(^|/)\.pytest_cache/"),
    re.compile(r"(^|/)__pycache__/"),
    re.compile(r"(^|/)\.mypy_cache/"),
    re.compile(r"(^|/)\.ruff_cache/"),
    re.compile(r"\.pyc$"),
)
LLM_CONFIDENCE_THRESHOLD = 0.75


@dataclass(frozen=True)
class DirtyPathDecision:
    path: str
    git_status: str
    classification: str
    reason: str
    confidence: float
    action: str
    source: str = "deterministic"

    def to_state_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "git_status": self.git_status,
            "classification": self.classification,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "action": self.action,
            "source": self.source,
        }


@dataclass(frozen=True)
class DirtyAdjudicationResult:
    status: str
    decisions: tuple[DirtyPathDecision, ...]
    summary: dict[str, int]
    telemetry_event: dict[str, object]
    llm_used: bool = False
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return (
            self.status == "blocked"
            or self.summary.get("blocked", 0) > 0
            or self.summary.get("left", 0) > 0
        )

    def to_state_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": 1,
            "status": self.status,
            "summary": dict(self.summary),
            "llm_used": self.llm_used,
            "decisions": [decision.to_state_dict() for decision in self.decisions],
            "telemetry_event": dict(self.telemetry_event),
        }
        if self.reason:
            result["reason"] = self.reason
        return result


@dataclass(frozen=True)
class DirtyPath:
    path: str
    git_status: str
    tracked: bool


def adjudicate_dirty_worktree(
    worktree: Path,
    *,
    llm_provider: object | None = None,
    exclude_paths: Sequence[str] = (),
) -> DirtyAdjudicationResult:
    """Classify dirty files and apply safe ignore decisions."""
    paths = _dirty_paths(worktree)
    if paths is None:
        return _result("skipped", (), llm_used=False, reason="not_git_worktree")
    paths = tuple(
        path for path in paths if not _matches_any(path.path, exclude_paths)
    )
    if not paths:
        return _result("clean", (), llm_used=False)

    llm_paths = tuple(
        path
        for path in paths
        if not (path.tracked and _is_generated_cache(path.path))
    )
    llm_decisions = (
        _ask_llm(worktree, llm_paths, llm_provider) if llm_paths else {}
    )
    refreshed = _dirty_paths(worktree)
    if refreshed is not None:
        refreshed = tuple(
            path for path in refreshed if not _matches_any(path.path, exclude_paths)
        )
    if refreshed is not None and _path_signature(refreshed) != _path_signature(paths):
        paths = refreshed
        allowed = {path.path for path in paths}
        llm_decisions = {
            path: decision
            for path, decision in llm_decisions.items()
            if path in allowed
        }
    decisions = tuple(
        _decision_for_path(path, llm_decisions.get(path.path)) for path in paths
    )
    applied = tuple(_apply_decisions(worktree, decisions))
    status = (
        "blocked"
        if any(d.classification in {"block", "leave"} for d in applied)
        else "applied"
    )
    return _result(status, applied, llm_used=bool(llm_decisions))


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    relative = PurePosixPath(path)
    for raw_pattern in patterns:
        pattern = str(raw_pattern).strip().lstrip("/")
        if not pattern:
            continue
        if relative.match(pattern):
            return True
        if pattern.endswith("/**"):
            root = pattern[:-3].rstrip("/")
            if path == root or path.startswith(f"{root}/"):
                return True
    return False


def dirty_summary_text(value: Mapping[str, object] | None) -> str | None:
    if not isinstance(value, Mapping):
        return None
    summary = value.get("summary")
    if not isinstance(summary, Mapping):
        return None
    total = int(summary.get("total", 0) or 0)
    if total <= 0:
        return None
    return (
        f"dirty: {int(summary.get('committed', 0) or 0)} committed, "
        f"{int(summary.get('ignored', 0) or 0)} ignored, "
        f"{int(summary.get('left', 0) or 0)} left, "
        f"{int(summary.get('blocked', 0) or 0)} blocked"
    )


def _dirty_paths(worktree: Path) -> tuple[DirtyPath, ...] | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=worktree,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    entries = [entry for entry in result.stdout.split(b"\x00") if entry]
    paths: list[DirtyPath] = []
    index = 0
    while index < len(entries):
        entry = entries[index].decode("utf-8", errors="replace")
        status = entry[:2]
        path = entry[3:]
        if status.startswith("R") or status.startswith("C"):
            index += 1
        paths.append(DirtyPath(path=path, git_status=status, tracked=status != "??"))
        index += 1
    return tuple(paths)


def _path_signature(paths: tuple[DirtyPath, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((path.path, path.git_status) for path in paths)


def _decision_for_path(
    path: DirtyPath,
    llm_decision: Mapping[str, object] | None,
) -> DirtyPathDecision:
    if path.tracked and _is_generated_cache(path.path):
        return DirtyPathDecision(
            path=path.path,
            git_status=path.git_status,
            classification="commit",
            reason="tracked generated cache is removed from product history",
            confidence=1.0,
            action="remove_pending",
        )
    if llm_decision:
        parsed = _parse_llm_decision(path, llm_decision)
        if parsed is not None:
            return parsed

    if path.tracked:
        return DirtyPathDecision(
            path=path.path,
            git_status=path.git_status,
            classification="commit",
            reason="tracked file changed by verified build",
            confidence=0.9,
            action="stage_pending",
        )
    if _is_disposable(path.path) and not _is_source_like(path.path):
        return DirtyPathDecision(
            path=path.path,
            git_status=path.git_status,
            classification="ignore",
            reason="untracked generated cache/build output",
            confidence=0.92,
            action="ignore_pending",
        )
    return DirtyPathDecision(
        path=path.path,
        git_status=path.git_status,
        classification="commit",
        reason="untracked build output is not safely disposable",
        confidence=0.78,
        action="stage_pending",
    )


def _parse_llm_decision(
    path: DirtyPath,
    raw: Mapping[str, object],
) -> DirtyPathDecision | None:
    classification = str(raw.get("classification") or "").strip().lower()
    confidence_raw = raw.get("confidence")
    if classification not in CLASSIFICATIONS:
        return None
    if isinstance(confidence_raw, bool) or not isinstance(confidence_raw, (int, float)):
        return None
    confidence = float(confidence_raw)
    if confidence < LLM_CONFIDENCE_THRESHOLD:
        return None
    if classification == "ignore" and (path.tracked or _is_source_like(path.path)):
        return DirtyPathDecision(
            path=path.path,
            git_status=path.git_status,
            classification="block",
            reason="LLM attempted unsafe ignore of tracked or source-like path",
            confidence=1.0,
            action="blocked",
            source="safety_rail",
        )
    reason = str(raw.get("reason") or "LLM-classified dirty path").strip()
    action = {
        "commit": "stage_pending",
        "ignore": "ignore_pending",
        "leave": "left_unstaged",
        "block": "blocked",
    }[classification]
    return DirtyPathDecision(
        path=path.path,
        git_status=path.git_status,
        classification=classification,
        reason=reason[:500],
        confidence=confidence,
        action=action,
        source="llm",
    )


def _apply_decisions(
    worktree: Path,
    decisions: Iterable[DirtyPathDecision],
) -> Iterable[DirtyPathDecision]:
    ignore_patterns = [
        _ignore_pattern(decision.path)
        for decision in decisions
        if decision.classification == "ignore" or decision.action == "remove_pending"
    ]
    if ignore_patterns:
        _append_gitignore_patterns(worktree / ".gitignore", ignore_patterns)
    for decision in decisions:
        if decision.action == "remove_pending":
            _remove_generated_cache(worktree, decision.path)
            yield DirtyPathDecision(
                **{
                    **decision.to_state_dict(),
                    "action": "removed_tracked_cache",
                }  # type: ignore[arg-type]
            )
        elif decision.classification == "ignore":
            yield DirtyPathDecision(
                **{**decision.to_state_dict(), "action": "gitignore_updated"}  # type: ignore[arg-type]
            )
        else:
            yield decision


def _append_gitignore_patterns(path: Path, patterns: Iterable[str]) -> None:
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = existing.splitlines()
    additions = [pattern for pattern in dict.fromkeys(patterns) if pattern not in lines]
    if not additions:
        return
    block = ["", "# Echelon-adjudicated disposable build outputs", *additions]
    suffix = "\n" if existing and not existing.endswith("\n") else ""
    path.write_text(existing + suffix + "\n".join(block).lstrip("\n") + "\n", encoding="utf-8")


def _ignore_pattern(path: str) -> str:
    if "/" in path:
        return f"/{path}"
    return path


def _remove_generated_cache(worktree: Path, relative_path: str) -> None:
    root = worktree.resolve()
    candidate = worktree / relative_path
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError):
        return
    if candidate.is_file() or candidate.is_symlink():
        candidate.unlink()


def _ask_llm(
    worktree: Path,
    paths: tuple[DirtyPath, ...],
    llm_provider: object | None,
) -> dict[str, Mapping[str, object]]:
    if llm_provider is None or not hasattr(llm_provider, "run_prompt_result"):
        return {}
    prompt = _llm_prompt(paths)
    try:
        result = llm_provider.run_prompt_result(
            str(worktree),
            prompt,
            timeout_ms=120_000,
            request_metadata={"phase": "dirty_worktree_adjudication"},
        )
    except Exception:
        return {}
    if int(getattr(result, "exit_code", 1)) != 0:
        return {}
    payload = _extract_json_object(str(getattr(result, "stdout", "") or ""))
    if not isinstance(payload, Mapping):
        return {}
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        return {}
    decisions: dict[str, Mapping[str, object]] = {}
    allowed = {path.path for path in paths}
    for item in raw_decisions:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "")
        if path in allowed:
            decisions[path] = item
    return decisions


def _llm_prompt(paths: tuple[DirtyPath, ...]) -> str:
    rows = [
        {"path": path.path, "git_status": path.git_status, "tracked": path.tracked}
        for path in paths[:200]
    ]
    return (
        "Classify dirty files produced by an autonomous build. Return only JSON "
        "with a decisions array. Each decision must contain path, classification "
        "(commit|ignore|leave|block), confidence from 0 to 1, and reason. "
        "Commit durable source, tests, config, docs, lockfiles, and verification "
        "evidence. Ignore reproducible caches and disposable runtime outputs. "
        "Never ignore tracked files or source-like paths.\n\n"
        f"Dirty paths:\n{json.dumps(rows, indent=2, sort_keys=True)}"
    )


def _extract_json_object(text: str) -> Mapping[str, object] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _is_disposable(path: str) -> bool:
    return any(pattern.search(path) for pattern in DISPOSABLE_PATTERNS)


def _is_generated_cache(path: str) -> bool:
    return any(pattern.search(path) for pattern in GENERATED_CACHE_PATTERNS)


def _is_source_like(path: str) -> bool:
    return path.startswith(SOURCE_LIKE_PREFIXES) or path.endswith(SOURCE_LIKE_SUFFIXES)


def _result(
    status: str,
    decisions: tuple[DirtyPathDecision, ...],
    *,
    llm_used: bool,
    reason: str | None = None,
) -> DirtyAdjudicationResult:
    summary = {
        "total": len(decisions),
        "committed": sum(1 for item in decisions if item.classification == "commit"),
        "ignored": sum(1 for item in decisions if item.classification == "ignore"),
        "left": sum(1 for item in decisions if item.classification == "leave"),
        "blocked": sum(1 for item in decisions if item.classification == "block"),
    }
    event = {
        "schema_version": 1,
        "type": "dirty_adjudication.completed",
        "event_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "llm_used": llm_used,
        **summary,
    }
    return DirtyAdjudicationResult(
        status=status,
        decisions=decisions,
        summary=summary,
        telemetry_event=event,
        llm_used=llm_used,
        reason=reason,
    )
