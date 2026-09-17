"""Bounded filesystem and Prosaic input boundary for PR review triage."""

from __future__ import annotations

import math
import os
from pathlib import Path
import tempfile
import time

from harness.prosaic_prompt_loader import (
    ProsaicCommandArtifact,
    ProsaicPromptLoadError,
    ProsaicPromptLoader,
)
from harness.prompt_companions import prompt_companion_references
from harness.inspection_io import (
    BoundedReadChannel, InspectionReadError, _open_root_directory,
    _open_relative_directory, _require_single_regular_file, _file_flags,
    _file_identity, _read_exact, _close_descriptors,
)


_MAX_PROSE_BYTES = 128 * 1024
_MODEL_TIERS = frozenset({"fast", "balanced", "strong"})
_EFFORT_LEVELS = frozenset({"low", "medium", "high"})
_PROVIDER_METADATA_KEYS = frozenset(
    {"model", "provider", "model_id", "model_name", "reasoning_effort"}
)
_REVIEW_PROSE = (
    ("echelon.review", "commands"),
    ("echelon.review-debugger", "subagents"),
    ("echelon.review-sentinel", "subagents"),
    ("echelon.review-spec-guard", "subagents"),
)


# Compatibility names retain the established triage API and exception catch boundary.
ReviewTriageError = InspectionReadError


class ReviewReadChannel(BoundedReadChannel):
    def __init__(self, worktree: Path, spec_dir: Path) -> None:
        super().__init__({"worktree": worktree, "spec": spec_dir})


def load_review_prose(
    worktree: Path, *, timeout_s: float
) -> dict[str, ProsaicCommandArtifact]:
    """Capture and inspect the fixed neutral review-triage prose set."""
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ReviewTriageError("review prose timeout must be positive")
    deadline = time.monotonic() + float(timeout_s)
    root_fd: int | None = None
    try:
        root_fd = _open_root_directory(Path(worktree))
        captured = {
            name: _capture_prose_source(root_fd, directory, name)
            for name, directory in _REVIEW_PROSE
        }
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReviewTriageError("required review prose is missing or unsafe") from exc
    finally:
        if root_fd is not None:
            _close_descriptors((root_fd,))

    for name, content in captured.items():
        source_text = content.decode("utf-8")
        if prompt_companion_references(source_text):
            raise ReviewTriageError(
                f"required review prose declares a companion: {name}"
            )

    artifacts: dict[str, ProsaicCommandArtifact] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="echelon-review-prose-") as raw_temp:
            project = Path(raw_temp)
            source = project / ".echelon" / "prosaic"
            for name, directory in _REVIEW_PROSE:
                destination = source / directory / f"{name}.md"
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_bytes(captured[name])
            os.chmod(project, 0o700)
            for name, directory in _REVIEW_PROSE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReviewTriageError("review prose inspection timed out")
                loader = ProsaicPromptLoader(project, timeout_s=remaining)
                artifact = (
                    loader.load_command(name)
                    if directory == "commands"
                    else loader.load_subagent(name)
                )
                if artifact is None:
                    raise ReviewTriageError(f"required review prose is missing: {name}")
                _validate_review_artifact(name, artifact)
                artifacts[name] = artifact
    except ReviewTriageError:
        raise
    except (OSError, ProsaicPromptLoadError, ValueError) as exc:
        raise ReviewTriageError("required review prose could not be inspected") from exc
    return artifacts


def _capture_prose_source(root_fd: int, directory: str, name: str) -> bytes:
    parent_fd: int | None = None
    file_fd: int | None = None
    try:
        parent_fd = _open_relative_directory(
            root_fd, (".echelon", "prosaic", directory)
        )
        filename = f"{name}.md"
        before = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        _require_single_regular_file(before)
        if before.st_size > _MAX_PROSE_BYTES:
            raise OSError("review prose exceeds capture limit")
        file_fd = os.open(filename, _file_flags(), dir_fd=parent_fd)
        opened = os.fstat(file_fd)
        _require_single_regular_file(opened)
        if _file_identity(opened) != _file_identity(before):
            raise OSError("review prose changed while opening")
        content = _read_exact(file_fd, opened.st_size)
        after = os.fstat(file_fd)
        current = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_identity(after) != _file_identity(opened)
            or _file_identity(current) != _file_identity(opened)
        ):
            raise OSError("review prose changed while reading")
        content.decode("utf-8")
        if b"\0" in content:
            raise ValueError("review prose is not text")
        return content
    finally:
        _close_descriptors(fd for fd in (file_fd, parent_fd) if fd is not None)


def _validate_review_artifact(
    name: str, artifact: ProsaicCommandArtifact
) -> None:
    metadata = artifact.frontmatter
    if not artifact.body.strip():
        raise ReviewTriageError(f"required review prose is empty: {name}")
    if metadata.get("name") != name:
        raise ReviewTriageError(f"required review prose has the wrong name: {name}")
    if _PROVIDER_METADATA_KEYS.intersection(metadata):
        raise ReviewTriageError(f"required review prose is provider-specific: {name}")
    if (
        metadata.get("model_tier") not in _MODEL_TIERS
        or metadata.get("effort") not in _EFFORT_LEVELS
    ):
        raise ReviewTriageError(f"required review prose has invalid neutral metadata: {name}")
