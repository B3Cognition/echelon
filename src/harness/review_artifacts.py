"""Validate and durably publish staged review-fix artifacts.

The review provider is deliberately restricted to an attempt directory.  This
module is the only boundary that can promote its output into the canonical spec.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import AbstractSet, Any, Literal, Sequence

from harness.state import is_process_alive


_ARTIFACT_RE = re.compile(r"review-fix-([1-9][0-9]*)\.md\Z")
_TASK_ID_RE = re.compile(r"T-([1-9][0-9]*)\Z")
_TASK_ROW_RE = re.compile(r"^- \[[ xX]\]\s+(T-[1-9][0-9]*)\b")


class ReviewArtifactError(RuntimeError):
    """Raised when staged review output cannot safely be published."""


@dataclass(frozen=True)
class ReviewAllocation:
    attempt_id: str
    comment_ids: tuple[str, ...]
    attempt_dir: Path
    artifact_names: tuple[str, ...]
    task_ids: tuple[str, ...]
    status_file: Path
    journal_file: Path


@dataclass(frozen=True)
class PublishedReviewBatch:
    attempt_id: str
    status: Literal["no_blocking_comments", "review_fix_queued"]
    artifact_paths: tuple[Path, ...]
    task_ids: tuple[str, ...]
    comment_ids: tuple[str, ...]


class ReviewArtifactPublisher:
    """Own the review lock from artifact allocation through publication."""

    def __init__(self, spec_dir: Path, state_dir: Path, strategy: str) -> None:
        self.spec_dir = Path(spec_dir)
        self.state_dir = Path(state_dir)
        self.strategy = strategy
        self.lock_file = self.spec_dir / ".echelon-review.lock"
        self.journal_file = self.state_dir / f"{strategy}-review-publication.json"
        self.status_file = self.state_dir / f"{strategy}-review-status.json"
        self._allocation: ReviewAllocation | None = None
        self._allocated_tasks_before: tuple[bool, bytes] | None = None
        self._locked = False

    def __enter__(self) -> "ReviewArtifactPublisher":
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._locked:
            try:
                self.lock_file.unlink(missing_ok=True)
                _fsync_directory(self.spec_dir)
            finally:
                self._locked = False

    def allocate(self, comment_ids: Sequence[str]) -> ReviewAllocation:
        """Reserve deterministic candidate names in a fresh staging attempt."""
        self._require_lock()
        if self._allocation is not None:
            raise ReviewArtifactError("a review attempt is already allocated under this lock")
        ids = tuple(comment_ids)
        if len(set(ids)) != len(ids) or any(not value for value in ids):
            raise ReviewArtifactError("comment IDs must be nonempty and unique")
        self._require_no_unconsumed_journal()

        existing_suffixes = [
            int(match.group(1))
            for child in self.spec_dir.iterdir()
            if (match := _ARTIFACT_RE.fullmatch(child.name)) is not None
        ]
        first_artifact = max(existing_suffixes, default=0) + 1
        artifact_names = tuple(
            f"review-fix-{number}.md" for number in range(first_artifact, first_artifact + len(ids))
        )
        if any((self.spec_dir / name).exists() for name in artifact_names):
            raise ReviewArtifactError("review artifact collision while allocating candidates")

        tasks_path = self.spec_dir / "tasks.md"
        if tasks_path.exists() and not _is_regular_file(tasks_path):
            raise ReviewArtifactError("canonical tasks.md is not a regular file")
        tasks_before = tasks_path.read_bytes() if tasks_path.exists() else b""

        task_numbers = _canonical_task_numbers(self.spec_dir / "tasks.md")
        first_task = max(task_numbers, default=0) + 1
        task_ids = tuple(f"T-{number}" for number in range(first_task, first_task + len(ids) * 3))
        staging_root = self.state_dir / "review-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"{self.strategy}-", dir=staging_root))
        attempt_id = attempt_dir.name
        self.status_file.unlink(missing_ok=True)
        _fsync_directory(self.state_dir)
        self._allocation = ReviewAllocation(
            attempt_id=attempt_id,
            comment_ids=ids,
            attempt_dir=attempt_dir,
            artifact_names=artifact_names,
            task_ids=task_ids,
            status_file=self.status_file,
            journal_file=self.journal_file,
        )
        self._allocated_tasks_before = (tasks_path.exists(), tasks_before)
        return self._allocation

    def accept_manifest(self, status_file: Path) -> PublishedReviewBatch:
        """Validate a provider manifest and atomically publish its complete batch."""
        self._require_lock()
        allocation = self._require_allocation(status_file)
        manifest = _read_manifest(allocation.status_file)
        status = manifest.get("status")
        if status == "no_blocking_comments":
            self._validate_empty_manifest(manifest, allocation)
            return PublishedReviewBatch(
                attempt_id=allocation.attempt_id,
                status="no_blocking_comments",
                artifact_paths=(),
                task_ids=(),
                comment_ids=allocation.comment_ids,
            )
        if status != "review_fix_queued":
            raise ReviewArtifactError("manifest status is invalid")

        prepared = self._validate_queued_manifest(manifest, allocation)
        journal = self._create_journal(allocation, prepared)
        self._write_journal(journal)
        self._after_publication_boundary("journal")
        return self._complete_journal(journal)

    def recover_publication(self, seen_ids: AbstractSet[str]) -> PublishedReviewBatch | None:
        """Finish an interrupted publication, or expose its completed batch once."""
        self._require_lock()
        if not self.journal_file.exists():
            return None
        journal = _read_journal(self.journal_file)
        if journal.get("complete") is not True:
            batch = self._complete_journal(journal)
        else:
            self._validate_completed_journal(journal)
            batch = _batch_from_journal(journal, self.spec_dir)
        comment_ids = frozenset(batch.comment_ids)
        if journal.get("consumed") is True or comment_ids.issubset(seen_ids):
            if journal.get("consumed") is not True:
                journal["consumed"] = True
                self._write_journal(journal)
            return None
        return batch

    def mark_consumed(self, attempt_id: str) -> None:
        """Durably acknowledge a completed batch after its review side effects run."""
        self._require_lock()
        journal = _read_journal(self.journal_file)
        if journal.get("attempt_id") != attempt_id:
            raise ReviewArtifactError("publication attempt ID does not match the journal")
        if journal.get("complete") is not True:
            raise ReviewArtifactError("cannot consume an incomplete publication")
        journal["consumed"] = True
        self._write_journal(journal)

    def _acquire_lock(self) -> None:
        payload = (
            f"pid={os.getpid()}\n"
            f"created_at={datetime.now(timezone.utc).isoformat()}\n"
            f"strategy={self.strategy}\n"
        ).encode("utf-8")
        for _ in range(2):
            try:
                fd = os.open(self.lock_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pid = _lock_pid(self.lock_file)
                if pid is not None and is_process_alive(pid):
                    raise ReviewArtifactError(f"review lock is held by PID {pid}: {self.lock_file}")
                try:
                    self.lock_file.unlink()
                    _fsync_directory(self.spec_dir)
                except OSError as exc:
                    raise ReviewArtifactError(f"could not reclaim stale review lock: {self.lock_file}") from exc
                continue
            except OSError as exc:
                raise ReviewArtifactError(f"could not acquire review lock: {self.lock_file}") from exc
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            _fsync_directory(self.spec_dir)
            self._locked = True
            return
        raise ReviewArtifactError("review lock contention")

    def _require_lock(self) -> None:
        if not self._locked:
            raise ReviewArtifactError("review artifact publication requires its context-manager lock")

    def _require_allocation(self, status_file: Path) -> ReviewAllocation:
        allocation = self._allocation
        if allocation is None:
            raise ReviewArtifactError("no review attempt has been allocated")
        if Path(status_file) != allocation.status_file:
            raise ReviewArtifactError("manifest was not written to the allocated status file")
        return allocation

    def _require_no_unconsumed_journal(self) -> None:
        if not self.journal_file.exists():
            return
        journal = _read_journal(self.journal_file)
        if journal.get("complete") is not True:
            self._complete_journal(journal)
            journal = _read_journal(self.journal_file)
        if journal.get("consumed") is not True:
            raise ReviewArtifactError("a completed review publication must be recovered before another allocation")
        self.journal_file.unlink()
        _fsync_directory(self.state_dir)

    def _validate_empty_manifest(self, manifest: dict[str, Any], allocation: ReviewAllocation) -> None:
        allowed = {"status", "groups", "artifacts", "tasks"}
        if set(manifest) - allowed or manifest.get("groups") != 0:
            raise ReviewArtifactError("no-blocking manifest has an invalid schema")
        if manifest.get("artifacts") != [] or manifest.get("tasks") != []:
            raise ReviewArtifactError("no-blocking manifest must have no artifacts or tasks")
        if any(allocation.attempt_dir.iterdir()):
            raise ReviewArtifactError("no-blocking manifest requires an empty attempt directory")

    def _validate_queued_manifest(self, manifest: dict[str, Any], allocation: ReviewAllocation) -> dict[str, Any]:
        allowed = {"status", "groups", "artifacts", "tasks", "tasks_append"}
        if set(manifest) != allowed:
            raise ReviewArtifactError("queued manifest has an invalid schema")
        groups, artifacts, tasks, append_name = (
            manifest.get("groups"), manifest.get("artifacts"), manifest.get("tasks"), manifest.get("tasks_append")
        )
        if not isinstance(groups, int) or isinstance(groups, bool) or groups <= 0:
            raise ReviewArtifactError("queued manifest groups must be positive")
        if not isinstance(artifacts, list) or not isinstance(tasks, list) or not isinstance(append_name, str):
            raise ReviewArtifactError("queued manifest has invalid fields")
        if groups != len(artifacts) or len(tasks) != groups * 3:
            raise ReviewArtifactError("queued manifest group, artifact, and task counts disagree")
        if not _is_safe_relative_name(append_name) or append_name != "tasks-append.md":
            raise ReviewArtifactError("tasks append path is invalid")
        if any(not isinstance(name, str) or not _is_safe_relative_name(name) for name in artifacts):
            raise ReviewArtifactError("artifact path is invalid")
        if len(set(artifacts)) != len(artifacts) or tuple(artifacts) != allocation.artifact_names[:groups]:
            raise ReviewArtifactError("artifacts must be a contiguous allocated prefix")
        artifact_paths = tuple(_staged_regular_file(allocation.attempt_dir, name) for name in artifacts)
        if any(path.stat().st_size == 0 for path in artifact_paths):
            raise ReviewArtifactError("staged review artifacts must be nonempty")
        append_path = _staged_regular_file(allocation.attempt_dir, append_name)
        if append_path.stat().st_size == 0:
            raise ReviewArtifactError("tasks append must be nonempty")

        expected_ids = allocation.task_ids[: groups * 3]
        task_ids: list[str] = []
        review_ids: list[str] = []
        artifact_task_counts: Counter[str] = Counter()
        artifact_task_ids: dict[str, list[str]] = {name: [] for name in artifacts}
        for entry in tasks:
            if not isinstance(entry, dict) or set(entry) != {"task_id", "review_task_id", "artifact"}:
                raise ReviewArtifactError("task entry has an invalid schema")
            task_id, review_id, artifact = entry["task_id"], entry["review_task_id"], entry["artifact"]
            if not all(isinstance(value, str) for value in (task_id, review_id, artifact)):
                raise ReviewArtifactError("task entry values must be strings")
            task_ids.append(task_id)
            review_ids.append(review_id)
            artifact_task_counts[artifact] += 1
            if artifact in artifact_task_ids:
                artifact_task_ids[artifact].append(task_id)
            match = _ARTIFACT_RE.fullmatch(artifact)
            if artifact not in artifacts or match is None:
                raise ReviewArtifactError("task entry references an unallocated artifact")
            expected_review = f"RF{match.group(1)}-T{artifact_task_counts[artifact]}"
            if review_id != expected_review:
                raise ReviewArtifactError("review task ID does not agree with artifact allocation")
        if tuple(task_ids) != expected_ids or len(set(task_ids)) != len(task_ids):
            raise ReviewArtifactError("task IDs must be a unique contiguous allocated prefix")
        if len(set(review_ids)) != len(review_ids) or any(count != 3 for count in artifact_task_counts.values()):
            raise ReviewArtifactError("each artifact requires exactly three unique review task IDs")
        for index, artifact in enumerate(artifacts):
            expected_group_ids = list(expected_ids[index * 3 : (index + 1) * 3])
            if artifact_task_ids[artifact] != expected_group_ids:
                raise ReviewArtifactError("task IDs must be contiguous per artifact")

        append_bytes = append_path.read_bytes()
        parsed_ids = _task_row_ids(append_bytes.decode("utf-8", errors="strict"))
        if len(parsed_ids) != len(task_ids) or Counter(parsed_ids) != Counter(task_ids):
            raise ReviewArtifactError("tasks append must contain exactly the manifest task rows")
        allowed_names = set(artifacts) | {append_name}
        staged_names = {path.name for path in allocation.attempt_dir.iterdir()}
        if staged_names != allowed_names:
            raise ReviewArtifactError("attempt directory contains unknown staged output")
        return {
            "artifacts": [(name, path.read_bytes()) for name, path in zip(artifacts, artifact_paths)],
            "task_ids": tuple(task_ids),
            "review_task_ids": tuple(review_ids),
            "append_bytes": append_bytes,
        }

    def _create_journal(self, allocation: ReviewAllocation, prepared: dict[str, Any]) -> dict[str, Any]:
        tasks_path = self.spec_dir / "tasks.md"
        if self._allocated_tasks_before is None:
            raise ReviewArtifactError("review allocation is missing its canonical pre-state")
        expected_exists, tasks_before = self._allocated_tasks_before
        if tasks_path.exists() and not _is_regular_file(tasks_path):
            raise ReviewArtifactError("canonical tasks.md is not a regular file")
        current_exists = tasks_path.exists()
        current = tasks_path.read_bytes() if current_exists else b""
        if current_exists != expected_exists or current != tasks_before:
            raise ReviewArtifactError("canonical tasks.md changed after allocation")
        artifacts: list[dict[str, str]] = []
        for name, content in prepared["artifacts"]:
            target = self.spec_dir / name
            if target.exists():
                raise ReviewArtifactError(f"canonical artifact already exists: {name}")
            artifacts.append({"name": name, "digest": _digest(content), "content": _encode(content)})
        return {
            "version": 1,
            "attempt_id": allocation.attempt_id,
            "status": "review_fix_queued",
            "comment_ids": list(allocation.comment_ids),
            "attempt_dir": str(allocation.attempt_dir),
            "artifact_names": list(allocation.artifact_names),
            "task_ids": list(prepared["task_ids"]),
            "review_task_ids": list(prepared["review_task_ids"]),
            "artifacts": artifacts,
            "tasks_before": {"exists": expected_exists, "digest": _digest(tasks_before), "content": _encode(tasks_before)},
            "tasks_append": {"digest": _digest(prepared["append_bytes"]), "content": _encode(prepared["append_bytes"])},
            "published_artifacts": [],
            "tasks_published": False,
            "complete": False,
            "consumed": False,
        }

    def _complete_journal(self, journal: dict[str, Any]) -> PublishedReviewBatch:
        _validate_journal_shape(journal)
        for artifact in journal["artifacts"]:
            name = artifact["name"]
            content = _decode(artifact["content"])
            target = self.spec_dir / name
            if target.exists():
                if not _is_regular_file(target) or _digest(target.read_bytes()) != artifact["digest"]:
                    raise ReviewArtifactError(f"canonical artifact conflicts with publication journal: {name}")
            else:
                _atomic_create(target, content)
            if name not in journal["published_artifacts"]:
                journal["published_artifacts"].append(name)
                self._write_journal(journal)
            self._after_publication_boundary(f"artifact:{name}")

        tasks_path = self.spec_dir / "tasks.md"
        before = journal["tasks_before"]
        append = journal["tasks_append"]
        current_exists = tasks_path.exists()
        if current_exists and not _is_regular_file(tasks_path):
            raise ReviewArtifactError("canonical tasks.md is not a regular file")
        current = tasks_path.read_bytes() if current_exists else b""
        desired = _append_bytes(_decode(before["content"]), _decode(append["content"]))
        if current != desired:
            if current_exists != before["exists"] or _digest(current) != before["digest"]:
                raise ReviewArtifactError("canonical tasks.md conflicts with publication journal")
            _atomic_replace(tasks_path, desired)
        if not journal["tasks_published"]:
            journal["tasks_published"] = True
            self._write_journal(journal)
        self._after_publication_boundary("tasks")
        self._validate_completed_journal(journal)
        journal["complete"] = True
        self._write_journal(journal)
        self._after_publication_boundary("complete")
        return _batch_from_journal(journal, self.spec_dir)

    def _validate_completed_journal(self, journal: dict[str, Any]) -> None:
        _validate_journal_shape(journal)
        for artifact in journal["artifacts"]:
            path = self.spec_dir / artifact["name"]
            if not _is_regular_file(path) or _digest(path.read_bytes()) != artifact["digest"]:
                raise ReviewArtifactError(f"published artifact digest is invalid: {artifact['name']}")
        tasks_path = self.spec_dir / "tasks.md"
        expected = _append_bytes(_decode(journal["tasks_before"]["content"]), _decode(journal["tasks_append"]["content"]))
        if not _is_regular_file(tasks_path) or tasks_path.read_bytes() != expected:
            raise ReviewArtifactError("published tasks.md does not match the journal")
        ids = _task_row_ids(expected.decode("utf-8", errors="strict"))
        if any(ids.count(task_id) != 1 for task_id in journal["task_ids"]):
            raise ReviewArtifactError("published tasks.md task rows do not match the journal")

    def _write_journal(self, journal: dict[str, Any]) -> None:
        _atomic_replace(self.journal_file, (json.dumps(journal, sort_keys=True, indent=2) + "\n").encode("utf-8"))

    def _after_publication_boundary(self, boundary: str) -> None:
        """Crash-test hook; production intentionally has no behavior here."""


def _read_manifest(path: Path) -> dict[str, Any]:
    if not _is_regular_file(path):
        raise ReviewArtifactError("review status file is missing or not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewArtifactError("review status file is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReviewArtifactError("review status manifest must be an object")
    return value


def _read_journal(path: Path) -> dict[str, Any]:
    if not _is_regular_file(path):
        raise ReviewArtifactError("review publication journal is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewArtifactError("review publication journal is corrupt") from exc
    if not isinstance(value, dict):
        raise ReviewArtifactError("review publication journal is corrupt")
    _validate_journal_shape(value)
    return value


def _validate_journal_shape(journal: dict[str, Any]) -> None:
    required = {"attempt_id", "status", "comment_ids", "task_ids", "review_task_ids", "artifacts", "tasks_before", "tasks_append", "published_artifacts", "tasks_published", "complete", "consumed"}
    if not required.issubset(journal) or journal.get("status") != "review_fix_queued":
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if not all(isinstance(journal[key], list) for key in ("comment_ids", "task_ids", "review_task_ids", "artifacts", "published_artifacts")):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if not all(isinstance(journal[key], bool) for key in ("tasks_published", "complete", "consumed")):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if not isinstance(journal["attempt_id"], str) or not all(isinstance(value, str) for value in journal["comment_ids"] + journal["task_ids"] + journal["review_task_ids"] + journal["published_artifacts"]):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if not isinstance(journal["tasks_before"], dict) or not isinstance(journal["tasks_append"], dict):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    for state in (journal["tasks_before"], journal["tasks_append"]):
        if not isinstance(state.get("digest"), str) or not isinstance(state.get("content"), str):
            raise ReviewArtifactError("review publication journal has an invalid schema")
    if not isinstance(journal["tasks_before"].get("exists"), bool):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    for artifact in journal["artifacts"]:
        if not isinstance(artifact, dict) or not all(isinstance(artifact.get(key), str) for key in ("name", "digest", "content")):
            raise ReviewArtifactError("review publication journal has an invalid schema")
        if _ARTIFACT_RE.fullmatch(artifact["name"]) is None:
            raise ReviewArtifactError("review publication journal has an invalid artifact name")


def _batch_from_journal(journal: dict[str, Any], spec_dir: Path) -> PublishedReviewBatch:
    return PublishedReviewBatch(
        attempt_id=journal["attempt_id"],
        status="review_fix_queued",
        artifact_paths=tuple(spec_dir / item["name"] for item in journal["artifacts"]),
        task_ids=tuple(journal["task_ids"]),
        comment_ids=tuple(journal["comment_ids"]),
    )


def _canonical_task_numbers(path: Path) -> list[int]:
    if not path.exists():
        return []
    if not _is_regular_file(path):
        raise ReviewArtifactError("canonical tasks.md is not a regular file")
    numbers: list[int] = []
    for task_id in _task_row_ids(path.read_text(encoding="utf-8", errors="strict")):
        match = _TASK_ID_RE.fullmatch(task_id)
        if match is not None:
            numbers.append(int(match.group(1)))
    return numbers


def _staged_regular_file(root: Path, name: str) -> Path:
    path = root / name
    if path.parent != root or not _is_regular_file(path):
        raise ReviewArtifactError(f"staged output is missing or unsafe: {name}")
    return path


def _task_row_ids(markdown: str) -> list[str]:
    """Read numeric top-level task rows, including legacy short numeric IDs."""
    task_ids: list[str] = []
    in_fence = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and (match := _TASK_ROW_RE.match(line.rstrip())) is not None:
            task_ids.append(match.group(1))
    return task_ids


def _is_safe_relative_name(name: str) -> bool:
    path = Path(name)
    return bool(name) and not path.is_absolute() and len(path.parts) == 1 and path.name == name and name not in {".", ".."}


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


def _lock_pid(path: Path) -> int | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("pid="):
                return int(line.removeprefix("pid="))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return None


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _encode(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")


def _decode(content: str) -> bytes:
    try:
        return base64.b64decode(content.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ReviewArtifactError("review publication journal contains invalid encoded content") from exc


def _append_bytes(before: bytes, append: bytes) -> bytes:
    if before and not before.endswith(b"\n"):
        before += b"\n"
    return before + append


def _atomic_create(path: Path, content: bytes) -> None:
    """Make a new file atomically without ever replacing an existing target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError as exc:
            raise ReviewArtifactError(f"canonical artifact collision during publication: {path.name}") from exc
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
