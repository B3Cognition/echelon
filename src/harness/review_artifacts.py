"""Validate and durably publish staged review-fix artifacts.

The review provider is deliberately restricted to an attempt directory.  This
module is the only boundary that can promote its output into the canonical spec.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import AbstractSet, Any, Literal, Sequence
from uuid import uuid4

from harness.state import is_process_alive
from kernel.task_contract import parse_task_rows


_ARTIFACT_RE = re.compile(r"review-fix-([1-9][0-9]*)\.md\Z")
_NUMERIC_TASK_ID_RE = re.compile(r"T-([0-9]{3,4})\Z")
_TITLE_RE = re.compile(r"^  \*\*Title:\*\* (RF[1-9][0-9]*-T[123]) - \S.*\Z")
_SECTION_RE = re.compile(r"^(?:---|## Review Fix [1-9][0-9]*: \S.*|> Source: review-fix-[1-9][0-9]*\.md|> PR: \S.*|> Status: pending)\Z")
_LOCK_FIELDS = {"pid", "created_at", "strategy", "token", "released"}
_JOURNAL_FIELDS = {
    "version", "attempt_id", "status", "comment_ids", "attempt_dir",
    "artifact_names", "task_ids", "review_task_ids", "artifacts",
    "tasks_before", "tasks_append", "published_artifacts", "tasks_published",
    "complete", "consumed",
}


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
        self._lock_fd: int | None = None
        self._lock_token: str | None = None
        self._lock_identity: tuple[int, int] | None = None

    def __enter__(self) -> "ReviewArtifactPublisher":
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._release_lock()

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

        task_ids = _allocate_canonical_task_ids(tasks_path, len(ids) * 3)
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
        self._after_publication_boundary("journal-created")
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
        """Take an advisory OS lock and install owner metadata while it is held.

        The lock file is intentionally retained after release.  Reusing its inode
        makes ``flock`` contention unambiguous and avoids check/unlink takeover
        races during stale-lock recovery.
        """
        for _ in range(3):
            fd: int | None = None
            created = False
            old_bytes = b""
            try:
                fd, created = _open_review_lock(self.lock_file)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                identity = _fd_identity(fd)
                if not _path_has_identity(self.lock_file, identity):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    os.close(fd)
                    continue
                old_bytes = _read_fd_bytes(fd)
                previous = _parse_lock_metadata(old_bytes)
                if previous is not None and previous["released"] != "true":
                    pid = int(previous["pid"])
                    if is_process_alive(pid):
                        raise ReviewArtifactError(f"review lock is held by PID {pid}: {self.lock_file}")
                elif previous is None:
                    legacy_pid = _lock_pid_from_bytes(old_bytes)
                    if legacy_pid is not None and is_process_alive(legacy_pid):
                        raise ReviewArtifactError(f"review lock is held by PID {legacy_pid}: {self.lock_file}")
                token = uuid4().hex
                payload = _lock_payload(self.strategy, token)
                _write_fd_bytes(fd, payload)
                self._lock_fd = fd
                self._lock_identity = identity
                self._lock_token = token
                self._locked = True
                return
            except BlockingIOError as exc:
                self._cleanup_failed_lock_acquire(fd, created, old_bytes)
                raise ReviewArtifactError(f"review lock is held: {self.lock_file}") from exc
            except ReviewArtifactError:
                self._cleanup_failed_lock_acquire(fd, created, old_bytes)
                raise
            except OSError as exc:
                self._cleanup_failed_lock_acquire(fd, created, old_bytes)
                raise ReviewArtifactError(f"could not acquire review lock: {self.lock_file}") from exc
        raise ReviewArtifactError("review lock changed while acquiring it")

    def _cleanup_failed_lock_acquire(self, fd: int | None, created: bool, old_bytes: bytes) -> None:
        if fd is None:
            self._clear_lock_state()
            return
        try:
            if created and _path_has_identity(self.lock_file, _fd_identity(fd)):
                try:
                    self.lock_file.unlink()
                except OSError:
                    pass
            elif old_bytes:
                try:
                    _write_fd_bytes(fd, old_bytes)
                except OSError:
                    pass
        finally:
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            finally:
                os.close(fd)
                self._clear_lock_state()

    def _release_lock(self) -> None:
        fd = self._lock_fd
        if fd is None:
            self._clear_lock_state()
            return
        release_error: OSError | None = None
        keep_locked = False
        try:
            identity = self._lock_identity
            token = self._lock_token
            if identity is not None and token is not None and _path_has_identity(self.lock_file, identity):
                metadata = _parse_lock_metadata(_read_fd_bytes(fd))
                if metadata is not None and metadata.get("token") == token:
                    metadata["released"] = "true"
                    try:
                        _write_fd_bytes(fd, _render_lock_metadata(metadata))
                    except OSError as exc:
                        release_error = exc
                        if _path_has_identity(self.lock_file, identity):
                            try:
                                self.lock_file.unlink()
                            except OSError:
                                keep_locked = True
        finally:
            if not keep_locked:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
                    self._clear_lock_state()
        if keep_locked:
            raise ReviewArtifactError("could not safely release the review lock after metadata failure") from release_error
        if release_error is not None:
            raise ReviewArtifactError("could not durably release the review lock") from release_error

    def _clear_lock_state(self) -> None:
        self._lock_fd = None
        self._lock_identity = None
        self._lock_token = None
        self._locked = False

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
        self._after_publication_boundary("journal-removed")

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
        _validate_append_payload(append_bytes, task_ids, review_ids)
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
                self._after_publication_boundary(f"artifact-write:{name}")
            if name not in journal["published_artifacts"]:
                journal["published_artifacts"].append(name)
                self._write_journal(journal)
                self._after_publication_boundary(f"artifact-flag:{name}")

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
            self._after_publication_boundary("tasks-write")
        if not journal["tasks_published"]:
            journal["tasks_published"] = True
            self._write_journal(journal)
            self._after_publication_boundary("tasks-flag")
        self._validate_completed_journal(journal)
        journal["complete"] = True
        self._write_journal(journal)
        self._after_publication_boundary("complete-write")
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
        _validate_append_payload(_decode(journal["tasks_append"]["content"]), journal["task_ids"], journal["review_task_ids"])

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
    if set(journal) != _JOURNAL_FIELDS or journal.get("version") != 1 or journal.get("status") != "review_fix_queued":
        raise ReviewArtifactError("review publication journal has an invalid schema")
    list_fields = ("comment_ids", "artifact_names", "task_ids", "review_task_ids", "artifacts", "published_artifacts")
    if not all(isinstance(journal[key], list) for key in list_fields):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if not all(isinstance(journal[key], bool) for key in ("tasks_published", "complete", "consumed")):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    string_lists = ("comment_ids", "artifact_names", "task_ids", "review_task_ids", "published_artifacts")
    if not all(isinstance(journal[key], str) and journal[key] for key in ("attempt_id", "attempt_dir")) or not all(
        isinstance(value, str) and value for field in string_lists for value in journal[field]
    ):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if not journal["comment_ids"] or len(set(journal["comment_ids"])) != len(journal["comment_ids"]) or len(set(journal["artifact_names"])) != len(journal["artifact_names"]):
        raise ReviewArtifactError("review publication journal has duplicate ownership IDs")
    if len(journal["artifact_names"]) != len(journal["comment_ids"]):
        raise ReviewArtifactError("review publication journal allocation cardinality is invalid")
    allocated_suffixes: list[int] = []
    for name in journal["artifact_names"]:
        match = _ARTIFACT_RE.fullmatch(name)
        if match is None:
            raise ReviewArtifactError("review publication journal artifact allocation is invalid")
        allocated_suffixes.append(int(match.group(1)))
    if allocated_suffixes != list(range(allocated_suffixes[0], allocated_suffixes[0] + len(allocated_suffixes))):
        raise ReviewArtifactError("review publication journal artifact allocation is not contiguous")
    if not isinstance(journal["tasks_before"], dict) or not isinstance(journal["tasks_append"], dict):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if set(journal["tasks_before"]) != {"exists", "digest", "content"} or set(journal["tasks_append"]) != {"digest", "content"}:
        raise ReviewArtifactError("review publication journal has an invalid schema")
    for state in (journal["tasks_before"], journal["tasks_append"]):
        if not isinstance(state.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", state["digest"]) or not isinstance(state.get("content"), str):
            raise ReviewArtifactError("review publication journal has an invalid schema")
    if not isinstance(journal["tasks_before"].get("exists"), bool):
        raise ReviewArtifactError("review publication journal has an invalid schema")
    if _digest(_decode(journal["tasks_before"]["content"])) != journal["tasks_before"]["digest"] or _digest(_decode(journal["tasks_append"]["content"])) != journal["tasks_append"]["digest"]:
        raise ReviewArtifactError("review publication journal digest does not match its content")
    artifacts = journal["artifacts"]
    for artifact in journal["artifacts"]:
        if not isinstance(artifact, dict) or not all(isinstance(artifact.get(key), str) for key in ("name", "digest", "content")):
            raise ReviewArtifactError("review publication journal has an invalid schema")
        if _ARTIFACT_RE.fullmatch(artifact["name"]) is None or not re.fullmatch(r"[0-9a-f]{64}", artifact["digest"]):
            raise ReviewArtifactError("review publication journal has an invalid artifact name")
        if _digest(_decode(artifact["content"])) != artifact["digest"]:
            raise ReviewArtifactError("review publication journal artifact digest does not match its content")
    artifact_names = [artifact["name"] for artifact in artifacts]
    if not artifacts or len(set(artifact_names)) != len(artifact_names) or artifact_names != journal["artifact_names"][: len(artifacts)]:
        raise ReviewArtifactError("review publication journal artifact allocation is invalid")
    if len(journal["task_ids"]) != len(artifacts) * 3 or len(journal["review_task_ids"]) != len(artifacts) * 3:
        raise ReviewArtifactError("review publication journal task cardinality is invalid")
    if len(set(journal["task_ids"])) != len(journal["task_ids"]) or len(set(journal["review_task_ids"])) != len(journal["review_task_ids"]):
        raise ReviewArtifactError("review publication journal task IDs are not unique")
    all_task_numbers: list[int] = []
    for task_id in journal["task_ids"]:
        match = _NUMERIC_TASK_ID_RE.fullmatch(task_id)
        if match is None:
            raise ReviewArtifactError("review publication journal task ID is not canonical")
        all_task_numbers.append(int(match.group(1)))
    if all_task_numbers != list(range(all_task_numbers[0], all_task_numbers[0] + len(all_task_numbers))):
        raise ReviewArtifactError("review publication journal task IDs are not contiguous")
    for index, artifact in enumerate(artifacts):
        suffix = _ARTIFACT_RE.fullmatch(artifact["name"])
        if suffix is None:
            raise ReviewArtifactError("review publication journal artifact name is invalid")
        start = index * 3
        group_ids = journal["task_ids"][start : start + 3]
        group_labels = journal["review_task_ids"][start : start + 3]
        numbers = []
        for task_id in group_ids:
            match = _NUMERIC_TASK_ID_RE.fullmatch(task_id)
            if match is None:
                raise ReviewArtifactError("review publication journal task ID is not canonical")
            numbers.append(int(match.group(1)))
        if numbers != list(range(numbers[0], numbers[0] + 3)) or group_labels != [f"RF{suffix.group(1)}-T{ordinal}" for ordinal in (1, 2, 3)]:
            raise ReviewArtifactError("review publication journal task/artifact relationship is invalid")
    if journal["published_artifacts"] != artifact_names[: len(journal["published_artifacts"])]:
        raise ReviewArtifactError("review publication journal publication flags are invalid")
    all_artifacts_published = len(journal["published_artifacts"]) == len(artifact_names)
    if (journal["tasks_published"] and not all_artifacts_published) or (journal["complete"] and not (journal["tasks_published"] and all_artifacts_published)) or (journal["consumed"] and not journal["complete"]):
        raise ReviewArtifactError("review publication journal completion flags are invalid")
    _validate_append_payload(_decode(journal["tasks_append"]["content"]), journal["task_ids"], journal["review_task_ids"])


def _batch_from_journal(journal: dict[str, Any], spec_dir: Path) -> PublishedReviewBatch:
    return PublishedReviewBatch(
        attempt_id=journal["attempt_id"],
        status="review_fix_queued",
        artifact_paths=tuple(spec_dir / item["name"] for item in journal["artifacts"]),
        task_ids=tuple(journal["task_ids"]),
        comment_ids=tuple(journal["comment_ids"]),
    )


def _allocate_canonical_task_ids(path: Path, count: int) -> tuple[str, ...]:
    if not path.exists():
        return tuple(f"T-{number:03d}" for number in range(1, count + 1))
    if not _is_regular_file(path):
        raise ReviewArtifactError("canonical tasks.md is not a regular file")
    numbers: list[int] = []
    widths: list[int] = []
    for task in parse_task_rows(path.read_text(encoding="utf-8", errors="strict")):
        match = _NUMERIC_TASK_ID_RE.fullmatch(task.task_id)
        if match is not None:
            numbers.append(int(match.group(1)))
            widths.append(len(match.group(1)))
    first = max(numbers, default=0) + 1
    width = max([3, *widths, len(str(first + max(0, count - 1)))])
    if width > 4:
        raise ReviewArtifactError("cannot allocate canonical task IDs beyond T-9999")
    return tuple(f"T-{number:0{width}d}" for number in range(first, first + count))


def _staged_regular_file(root: Path, name: str) -> Path:
    path = root / name
    if path.parent != root or not _is_regular_file(path):
        raise ReviewArtifactError(f"staged output is missing or unsafe: {name}")
    return path


def _validate_append_payload(payload: bytes, task_ids: Sequence[str], review_ids: Sequence[str]) -> None:
    """Require the canonical rows and title detail blocks consumed by Phase 1."""
    try:
        markdown = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ReviewArtifactError("tasks append is not valid UTF-8") from exc
    rows = parse_task_rows(markdown)
    parsed_ids = [row.task_id for row in rows]
    if parsed_ids != list(task_ids) or len(set(parsed_ids)) != len(parsed_ids):
        raise ReviewArtifactError("tasks append must contain exactly the canonical manifest task rows")

    lines = markdown.splitlines()
    titles: list[str] = []
    row_positions = [index for index, line in enumerate(lines) if line.startswith("- [")]
    if len(row_positions) != len(rows):
        raise ReviewArtifactError("tasks append contains malformed task text")
    allowed = set(row_positions)
    for row_index, start in enumerate(row_positions):
        stop = row_positions[row_index + 1] if row_index + 1 < len(row_positions) else len(lines)
        details = [line for line in lines[start + 1 : stop] if line]
        if len(details) != 1 or (match := _TITLE_RE.fullmatch(details[0])) is None:
            raise ReviewArtifactError("tasks append requires exactly one review title detail per task")
        titles.append(match.group(1))
    if titles != list(review_ids):
        raise ReviewArtifactError("tasks append review labels do not match the manifest")
    for index, line in enumerate(lines):
        if not line or index in allowed or _TITLE_RE.fullmatch(line) or _SECTION_RE.fullmatch(line):
            continue
        raise ReviewArtifactError("tasks append contains output outside canonical review task blocks")


def _is_safe_relative_name(name: str) -> bool:
    path = Path(name)
    return bool(name) and not path.is_absolute() and len(path.parts) == 1 and path.name == name and name not in {".", ".."}


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


def _open_review_lock(path: Path) -> tuple[int, bool]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags, 0o600), True
    except FileExistsError:
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        return os.open(path, flags), False


def _fd_identity(fd: int) -> tuple[int, int]:
    metadata = os.fstat(fd)
    return metadata.st_dev, metadata.st_ino


def _path_has_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        metadata = path.stat()
    except OSError:
        return False
    return (metadata.st_dev, metadata.st_ino) == identity


def _read_fd_bytes(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_fd_bytes(fd: int, content: bytes) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        view = view[written:]
    os.fsync(fd)


def _lock_payload(strategy: str, token: str) -> bytes:
    return _render_lock_metadata(
        {
            "pid": str(os.getpid()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy,
            "token": token,
            "released": "false",
        }
    )


def _render_lock_metadata(metadata: dict[str, str]) -> bytes:
    return "".join(f"{name}={metadata[name]}\n" for name in ("pid", "created_at", "strategy", "token", "released")).encode("utf-8")


def _parse_lock_metadata(content: bytes) -> dict[str, str] | None:
    try:
        values = dict(line.split("=", 1) for line in content.decode("utf-8").splitlines() if "=" in line)
        if set(values) != _LOCK_FIELDS or values["released"] not in {"true", "false"}:
            return None
        int(values["pid"])
        if not values["strategy"] or not values["token"]:
            return None
        return values
    except (UnicodeDecodeError, ValueError):
        return None


def _lock_pid_from_bytes(content: bytes) -> int | None:
    try:
        for line in content.decode("utf-8").splitlines():
            if line.startswith("pid="):
                return int(line.removeprefix("pid="))
    except (ValueError, UnicodeDecodeError):
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
