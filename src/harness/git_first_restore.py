"""Build immutable candidate-restore commits without touching active Git state."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from typing import Iterator, Mapping

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from harness.proportional_quality import CandidateCheckpointEntry


_OBJECT_ID_PATTERN = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SAFE_ID_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RESTORE_PHASE = "phase1-quality-candidate-restored"
_ALLOWED_ARTIFACTS = frozenset(
    {"spec.md", "requirements-overview.md", "quality-gates.md", "issues.md"}
)
_REQUIRED_ARTIFACTS = frozenset({"spec.md", "quality-gates.md", "issues.md"})
_ERROR_OUTPUT_LIMIT = 4096
_RESTORE_JOURNAL_DIRECTORY = "git-first-restores"
_RESTORE_TEMP_PREFIX = ".git-first-restore-"


class GitFirstRestoreError(RuntimeError):
    """Raised when immutable restore authority cannot be built or verified."""


@dataclass(frozen=True)
class RestoreCommitEntry:
    path: str
    base_mode: str
    base_blob_oid: str
    base_sha256: str
    target_mode: str
    target_blob_oid: str
    target_sha256: str


@dataclass(frozen=True)
class GitFirstRestorePlan:
    schema_version: int
    completion_id: str
    run_id: str
    spec_id: str
    next_phase: str
    ref_name: str
    base_commit: str
    base_tree: str
    target_commit: str
    target_tree: str
    selected_candidate_id: str
    selected_manifest_sha256: str
    entries: tuple[RestoreCommitEntry, ...]


@dataclass(frozen=True)
class JournalEntry:
    path: str
    base_mode: str
    base_sha256: str
    target_mode: str
    target_sha256: str
    temporary_name: str


@dataclass(frozen=True)
class GitFirstRestoreJournal:
    schema_version: int
    completion_id: str
    plan_sha256: str
    ref_name: str
    base_commit: str
    target_commit: str
    entries: tuple[JournalEntry, ...]


@dataclass(frozen=True)
class GitFirstRestoreReceipt:
    schema_version: int
    completion_id: str
    restore_protocol: str
    plan_sha256: str
    target_commit: str
    checkpoint: Mapping[str, object]


@dataclass(frozen=True)
class _RestoreEntrySnapshot:
    sha256: str
    content: bytes
    mode: int
    token: tuple[object, ...]


def _bounded_output(value: bytes) -> str:
    return value[:_ERROR_OUTPUT_LIMIT].decode("utf-8", errors="replace")


def _git(
    project_root: Path,
    *args: str,
    stdin: bytes | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    process_env = os.environ.copy()
    process_env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
        }
    )
    if env is not None:
        process_env.update(env)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            input=stdin,
            check=False,
            capture_output=True,
            timeout=120,
            env=process_env,
        )
    except FileNotFoundError as exc:
        raise GitFirstRestoreError("could not execute git") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitFirstRestoreError(
            f"git {' '.join(args)} timed out"
        ) from exc
    if check and result.returncode != 0:
        raise GitFirstRestoreError(
            f"git {' '.join(args)} failed: "
            f"{_bounded_output(result.stderr or result.stdout)}"
        )
    return result


def _stdout_text(result: subprocess.CompletedProcess[bytes]) -> str:
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise GitFirstRestoreError("git returned invalid text") from exc


def _validate_safe_id(value: object, *, field: str) -> str:
    if type(value) is not str or _SAFE_ID_PATTERN.fullmatch(value) is None:
        raise GitFirstRestoreError(f"invalid {field}")
    return value


def _validate_metadata(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 1024
        or value != " ".join(value.strip().split())
    ):
        raise GitFirstRestoreError(f"invalid {field}")
    return value


def _validate_oid(value: object, *, field: str) -> str:
    if type(value) is not str or _OBJECT_ID_PATTERN.fullmatch(value) is None:
        raise GitFirstRestoreError(f"invalid {field}")
    return value


def _validate_sha256(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or re.fullmatch(r"[0-9a-f]{64}", value) is None
    ):
        raise GitFirstRestoreError(f"invalid {field}")
    return value


def _tree_entries(
    project_root: Path,
    commit_or_tree: str,
) -> dict[bytes, tuple[str, str, str]]:
    output = _git(
        project_root,
        "ls-tree",
        "-r",
        "-t",
        "-z",
        commit_or_tree,
    ).stdout
    entries: dict[bytes, tuple[str, str, str]] = {}
    for row in (item for item in output.split(b"\0") if item):
        try:
            header, path = row.split(b"\t", 1)
            mode_raw, object_type_raw, oid_raw = header.split()
            mode = mode_raw.decode("ascii")
            object_type = object_type_raw.decode("ascii")
            oid = oid_raw.decode("ascii")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitFirstRestoreError("could not parse Git tree") from exc
        if not path or path in entries or _OBJECT_ID_PATTERN.fullmatch(oid) is None:
            raise GitFirstRestoreError("could not parse Git tree")
        entries[path] = (mode, object_type, oid)
    return entries


def _blob_bytes(project_root: Path, oid: str) -> bytes:
    kind = _stdout_text(_git(project_root, "cat-file", "-t", oid))
    if kind != "blob":
        raise GitFirstRestoreError("candidate owned artifact is not a regular blob")
    return _git(project_root, "cat-file", "blob", oid).stdout


def _blob_sha256(project_root: Path, oid: str) -> str:
    return hashlib.sha256(_blob_bytes(project_root, oid)).hexdigest()


def _normalize_selected_path(path: object, *, spec_id: str) -> tuple[str, str]:
    if type(path) is not str or not path or "\0" in path or "\\" in path:
        raise GitFirstRestoreError("candidate owned artifact paths are unsafe")
    prefix = f"specs/{spec_id}/"
    if path in _ALLOWED_ARTIFACTS:
        name = path
        normalized_path = prefix + name
    else:
        parsed = PurePosixPath(path)
        parts = parsed.parts
        if (
            parsed.is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
            or len(parts) < 3
            or parts[-3] != "specs"
            or parts[-2] != spec_id
            or parts[-1] not in _ALLOWED_ARTIFACTS
        ):
            raise GitFirstRestoreError(
                "candidate owned artifact paths are unsafe"
            )
        name = parts[-1]
        normalized_path = parsed.as_posix()
    return name, normalized_path


def _validated_selected_entries(
    project_root: Path,
    *,
    spec_id: str,
    selected_entries: object,
) -> tuple[tuple[str, CandidateCheckpointEntry], ...]:
    if type(selected_entries) is not tuple or any(
        not isinstance(entry, CandidateCheckpointEntry)
        for entry in selected_entries
    ):
        raise GitFirstRestoreError("candidate checkpoint entries are malformed")
    normalized: list[tuple[str, str, CandidateCheckpointEntry]] = []
    names: set[str] = set()
    for entry in selected_entries:
        name, path = _normalize_selected_path(entry.path, spec_id=spec_id)
        if name in names:
            raise GitFirstRestoreError("candidate owned artifact paths are duplicated")
        names.add(name)
        if entry.mode not in {"100644", "100755"}:
            raise GitFirstRestoreError(
                "candidate owned artifact is not a regular blob"
            )
        _validate_oid(entry.blob_oid, field="candidate blob object ID")
        _validate_sha256(entry.sha256, field="candidate artifact digest")
        if type(entry.content) is not bytes:
            raise GitFirstRestoreError("candidate artifact content is malformed")
        content_digest = hashlib.sha256(entry.content).hexdigest()
        if content_digest != entry.sha256:
            raise GitFirstRestoreError("candidate artifact digest mismatch")
        object_content = _blob_bytes(project_root, entry.blob_oid)
        if object_content != entry.content:
            raise GitFirstRestoreError("candidate blob content mismatch")
        normalized.append((name, path, entry))
    if not _REQUIRED_ARTIFACTS <= names or not names <= _ALLOWED_ARTIFACTS:
        raise GitFirstRestoreError("candidate owned artifact paths are unsafe")
    return tuple(
        (path, entry)
        for _name, path, entry in sorted(normalized, key=lambda item: item[1])
    )


@contextmanager
def _isolated_index(journal_root: Path, completion_id: str) -> Iterator[Path]:
    try:
        journal_root.stat()
    except OSError as exc:
        raise GitFirstRestoreError("restore journal root is unavailable") from exc
    if not journal_root.is_dir() or journal_root.is_symlink():
        raise GitFirstRestoreError("restore journal root is not a directory")
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".git-first-{completion_id}-",
        suffix=".index",
        dir=journal_root,
    )
    os.close(descriptor)
    path = Path(raw_path)
    try:
        path.unlink()
        yield path
    finally:
        for candidate in (path, Path(f"{path}.lock")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise GitFirstRestoreError(
                    "could not remove isolated restore index"
                ) from exc


def _restore_checkpoint_message(
    *,
    spec_id: str,
    run_id: str,
    next_phase: str,
    completion_id: str,
    selected_candidate_id: str,
    selected_manifest_sha256: str,
) -> str:
    checkpoint_message = build_echelon_commit_message(
        f"echelon-checkpoint: {spec_id} {_RESTORE_PHASE}",
        EchelonCommitMetadata(
            origin="phase-a",
            action="checkpoint",
            spec_id=spec_id,
            run_id=run_id,
            phase=_RESTORE_PHASE,
            checkpoint_id=_RESTORE_PHASE,
            next_phase=next_phase,
            completion_id=completion_id,
        ),
    )
    return (
        checkpoint_message
        + f"\nEchelon-Selected-Candidate: {selected_candidate_id}"
        + f"\nEchelon-Selected-Manifest-SHA256: {selected_manifest_sha256}"
    )


def _base_commit_date(project_root: Path, base_commit: str) -> str:
    raw = _git(project_root, "cat-file", "commit", base_commit).stdout
    try:
        header = raw.split(b"\n\n", 1)[0]
        committer_lines = tuple(
            line for line in header.splitlines() if line.startswith(b"committer ")
        )
        if len(committer_lines) != 1:
            raise ValueError
        match = re.search(rb" ([0-9]+) ([+-][0-9]{4})$", committer_lines[0])
        if match is None:
            raise ValueError
        epoch = match.group(1).decode("ascii")
        timezone = match.group(2).decode("ascii")
    except (ValueError, UnicodeDecodeError) as exc:
        raise GitFirstRestoreError("could not read base commit timestamp") from exc
    if not epoch.isdigit() or re.fullmatch(r"[+-][0-9]{4}", timezone) is None:
        raise GitFirstRestoreError("could not read base commit timestamp")
    return f"{epoch} {timezone}"


def _deterministic_commit_bytes(
    *,
    target_tree: str,
    parent: str,
    message: str,
    timestamp: str,
) -> bytes:
    identity = "Echelon <echelon@local>"
    return (
        f"tree {target_tree}\n"
        f"parent {parent}\n"
        f"author {identity} {timestamp}\n"
        f"committer {identity} {timestamp}\n"
        f"\n{message}\n"
    ).encode("utf-8")


def _commit_tree_deterministically(
    project_root: Path,
    *,
    target_tree: str,
    parent: str,
    message: str,
    timestamp: str,
) -> str:
    raw_commit = _deterministic_commit_bytes(
        target_tree=target_tree,
        parent=parent,
        message=message,
        timestamp=timestamp,
    )
    commit = _stdout_text(
        _git(
            project_root,
            "hash-object",
            "-t",
            "commit",
            "-w",
            "--stdin",
            stdin=raw_commit,
        )
    )
    return _validate_oid(commit, field="target commit")


def _active_ref(project_root: Path) -> str:
    result = _git(
        project_root,
        "symbolic-ref",
        "--quiet",
        "HEAD",
        check=False,
    )
    if result.returncode != 0:
        raise GitFirstRestoreError("restore requires an active branch ref")
    ref_name = _stdout_text(result)
    if not ref_name.startswith("refs/heads/"):
        raise GitFirstRestoreError("restore requires an active branch ref")
    return ref_name


def _active_index_snapshot(project_root: Path) -> tuple[int, int, int, int, int, str]:
    raw_path = _stdout_text(_git(project_root, "rev-parse", "--git-path", "index"))
    index_path = Path(raw_path)
    if not index_path.is_absolute():
        index_path = project_root / index_path
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(index_path, flags)
    except OSError as exc:
        raise GitFirstRestoreError("active index is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise GitFirstRestoreError("active index is not a regular file")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise GitFirstRestoreError("active index changed while reading")
        return (
            after.st_dev,
            after.st_ino,
            stat.S_IMODE(after.st_mode),
            after.st_size,
            after.st_mtime_ns,
            digest.hexdigest(),
        )
    except OSError as exc:
        raise GitFirstRestoreError("active index could not be read") from exc
    finally:
        os.close(descriptor)


def _plan_spec_id(plan: GitFirstRestorePlan) -> str:
    spec_ids: set[str] = set()
    for entry in plan.entries:
        parsed = PurePosixPath(entry.path)
        parts = parsed.parts
        if (
            parsed.is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
            or len(parts) < 3
            or parts[-3] != "specs"
            or parts[-1] not in _ALLOWED_ARTIFACTS
        ):
            raise GitFirstRestoreError("restore plan owned artifact paths are unsafe")
        spec_ids.add(parts[-2])
    if len(spec_ids) != 1:
        raise GitFirstRestoreError("restore plan owned artifact paths are unsafe")
    return _validate_safe_id(next(iter(spec_ids)), field="spec ID")


def build_git_first_restore_commit(
    project_root: Path,
    journal_root: Path,
    completion_id: str,
    base_commit: str,
    selected_candidate_id: str,
    selected_manifest_sha256: str,
    selected_entries: tuple[CandidateCheckpointEntry, ...],
    run_id: str,
    spec_id: str,
    next_phase: str,
) -> GitFirstRestorePlan:
    """Build and verify a deterministic restore commit using an isolated index."""
    root = Path(project_root).resolve()
    journals = Path(journal_root).resolve()
    completion = _validate_safe_id(completion_id, field="completion ID")
    candidate_id = _validate_safe_id(
        selected_candidate_id,
        field="selected candidate ID",
    )
    spec = _validate_safe_id(spec_id, field="spec ID")
    run = _validate_metadata(run_id, field="run ID")
    following_phase = _validate_metadata(next_phase, field="next phase")
    manifest_digest = _validate_sha256(
        selected_manifest_sha256,
        field="selected manifest digest",
    )
    base = _validate_oid(base_commit, field="base commit")
    if not root.is_dir():
        raise GitFirstRestoreError("project root is not a directory")
    resolved_base = _stdout_text(_git(root, "rev-parse", f"{base}^{{commit}}"))
    if resolved_base != base:
        raise GitFirstRestoreError("base commit is not canonical")
    current_head = _stdout_text(_git(root, "rev-parse", "HEAD^{commit}"))
    if current_head != base:
        raise GitFirstRestoreError("base commit does not match HEAD")
    ref_name = _active_ref(root)
    index_snapshot = _active_index_snapshot(root)
    base_tree = _stdout_text(_git(root, "rev-parse", f"{base}^{{tree}}"))
    index_diff = _git(
        root,
        "diff-index",
        "--cached",
        "--quiet",
        base,
        "--",
        check=False,
    )
    if index_diff.returncode != 0:
        raise GitFirstRestoreError("base worktree and index must be clean")
    if _active_index_snapshot(root) != index_snapshot:
        raise GitFirstRestoreError("active index changed while checking base")

    normalized = _validated_selected_entries(
        root,
        spec_id=spec,
        selected_entries=selected_entries,
    )
    base_entries = _tree_entries(root, base)
    plan_entries: list[RestoreCommitEntry] = []
    for path, selected in normalized:
        base_entry = base_entries.get(path.encode("utf-8"))
        if (
            base_entry is None
            or base_entry[0] not in {"100644", "100755"}
            or base_entry[1] != "blob"
        ):
            raise GitFirstRestoreError(
                f"base owned artifact is not a regular blob: {path}"
            )
        plan_entries.append(
            RestoreCommitEntry(
                path=path,
                base_mode=base_entry[0],
                base_blob_oid=base_entry[2],
                base_sha256=_blob_sha256(root, base_entry[2]),
                target_mode=selected.mode,
                target_blob_oid=selected.blob_oid,
                target_sha256=selected.sha256,
            )
        )
    owned_status = _git(
        root,
        "status",
        "--porcelain",
        "-z",
        "--",
        *(entry.path for entry in plan_entries),
    ).stdout
    if owned_status:
        raise GitFirstRestoreError("base worktree and index must be clean")

    index_env: dict[str, str]
    with _isolated_index(journals, completion) as index_path:
        index_env = {"GIT_INDEX_FILE": str(index_path)}
        _git(root, "read-tree", base, env=index_env)
        for entry in plan_entries:
            _git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                entry.target_mode,
                entry.target_blob_oid,
                entry.path,
                env=index_env,
            )
        target_tree = _stdout_text(_git(root, "write-tree", env=index_env))

    message = _restore_checkpoint_message(
        spec_id=spec,
        run_id=run,
        next_phase=following_phase,
        completion_id=completion,
        selected_candidate_id=candidate_id,
        selected_manifest_sha256=manifest_digest,
    )
    target_commit = _commit_tree_deterministically(
        root,
        target_tree=target_tree,
        parent=base,
        message=message,
        timestamp=_base_commit_date(root, base),
    )
    plan = GitFirstRestorePlan(
        schema_version=1,
        completion_id=completion,
        run_id=run,
        spec_id=spec,
        next_phase=following_phase,
        ref_name=ref_name,
        base_commit=base,
        base_tree=base_tree,
        target_commit=target_commit,
        target_tree=target_tree,
        selected_candidate_id=candidate_id,
        selected_manifest_sha256=manifest_digest,
        entries=tuple(plan_entries),
    )
    verify_git_first_restore_commit(root, plan)
    if _active_ref(root) != ref_name:
        raise GitFirstRestoreError("active ref changed while building restore commit")
    if _stdout_text(_git(root, "rev-parse", "HEAD^{commit}")) != base:
        raise GitFirstRestoreError("base authority changed while building restore commit")
    if _active_index_snapshot(root) != index_snapshot:
        raise GitFirstRestoreError("active index changed while building restore commit")
    if _git(
        root,
        "status",
        "--porcelain",
        "-z",
        "--",
        *(entry.path for entry in plan.entries),
    ).stdout:
        raise GitFirstRestoreError("base authority changed while building restore commit")
    if _active_index_snapshot(root) != index_snapshot:
        raise GitFirstRestoreError("active index changed while building restore commit")
    return plan


def recover_git_first_restore_plan(
    project_root: Path,
    journal_root: Path,
    completion_id: str,
    base_commit: str,
    selected_candidate_id: str,
    selected_manifest_sha256: str,
    selected_entries: tuple[CandidateCheckpointEntry, ...],
    run_id: str,
    spec_id: str,
    next_phase: str,
) -> GitFirstRestorePlan:
    """Reconstruct immutable plan authority after Git-first side effects began."""

    root = Path(project_root).resolve()
    journals = Path(journal_root).resolve()
    completion = _validate_safe_id(completion_id, field="completion ID")
    candidate_id = _validate_safe_id(
        selected_candidate_id,
        field="selected candidate ID",
    )
    spec = _validate_safe_id(spec_id, field="spec ID")
    run = _validate_metadata(run_id, field="run ID")
    following_phase = _validate_metadata(next_phase, field="next phase")
    manifest_digest = _validate_sha256(
        selected_manifest_sha256,
        field="selected manifest digest",
    )
    base = _validate_oid(base_commit, field="base commit")
    if not root.is_dir():
        raise GitFirstRestoreError("project root is not a directory")
    resolved_base = _stdout_text(_git(root, "rev-parse", f"{base}^{{commit}}"))
    if resolved_base != base:
        raise GitFirstRestoreError("base commit is not canonical")
    ref_name = _active_ref(root)
    base_tree = _stdout_text(_git(root, "rev-parse", f"{base}^{{tree}}"))
    normalized = _validated_selected_entries(
        root,
        spec_id=spec,
        selected_entries=selected_entries,
    )
    base_entries = _tree_entries(root, base)
    plan_entries: list[RestoreCommitEntry] = []
    for path, selected in normalized:
        base_entry = base_entries.get(path.encode("utf-8"))
        if (
            base_entry is None
            or base_entry[0] not in {"100644", "100755"}
            or base_entry[1] != "blob"
        ):
            raise GitFirstRestoreError(
                f"base owned artifact is not a regular blob: {path}"
            )
        plan_entries.append(
            RestoreCommitEntry(
                path=path,
                base_mode=base_entry[0],
                base_blob_oid=base_entry[2],
                base_sha256=_blob_sha256(root, base_entry[2]),
                target_mode=selected.mode,
                target_blob_oid=selected.blob_oid,
                target_sha256=selected.sha256,
            )
        )
    with _isolated_index(journals, completion) as index_path:
        index_env = {"GIT_INDEX_FILE": str(index_path)}
        _git(root, "read-tree", base, env=index_env)
        for entry in plan_entries:
            _git(
                root,
                "update-index",
                "--add",
                "--cacheinfo",
                entry.target_mode,
                entry.target_blob_oid,
                entry.path,
                env=index_env,
            )
        target_tree = _stdout_text(_git(root, "write-tree", env=index_env))
    message = _restore_checkpoint_message(
        spec_id=spec,
        run_id=run,
        next_phase=following_phase,
        completion_id=completion,
        selected_candidate_id=candidate_id,
        selected_manifest_sha256=manifest_digest,
    )
    target_commit = _commit_tree_deterministically(
        root,
        target_tree=target_tree,
        parent=base,
        message=message,
        timestamp=_base_commit_date(root, base),
    )
    plan = GitFirstRestorePlan(
        schema_version=1,
        completion_id=completion,
        run_id=run,
        spec_id=spec,
        next_phase=following_phase,
        ref_name=ref_name,
        base_commit=base,
        base_tree=base_tree,
        target_commit=target_commit,
        target_tree=target_tree,
        selected_candidate_id=candidate_id,
        selected_manifest_sha256=manifest_digest,
        entries=tuple(plan_entries),
    )
    verify_git_first_restore_commit(root, plan)
    return plan


def verify_git_first_restore_commit(
    project_root: Path,
    plan: GitFirstRestorePlan,
) -> None:
    """Verify the complete target commit using only immutable Git objects."""
    root = Path(project_root).resolve()
    if not isinstance(plan, GitFirstRestorePlan) or plan.schema_version != 1:
        raise GitFirstRestoreError("invalid restore plan")
    _validate_safe_id(plan.completion_id, field="completion ID")
    run_id = _validate_metadata(plan.run_id, field="run ID")
    spec_id = _validate_safe_id(plan.spec_id, field="spec ID")
    next_phase = _validate_metadata(plan.next_phase, field="next phase")
    _validate_safe_id(plan.selected_candidate_id, field="selected candidate ID")
    _validate_sha256(
        plan.selected_manifest_sha256,
        field="selected manifest digest",
    )
    for field, oid in (
        ("base commit", plan.base_commit),
        ("base tree", plan.base_tree),
        ("target commit", plan.target_commit),
        ("target tree", plan.target_tree),
    ):
        _validate_oid(oid, field=field)
    if (
        type(plan.ref_name) is not str
        or not plan.ref_name.startswith("refs/heads/")
        or _git(root, "check-ref-format", plan.ref_name, check=False).returncode != 0
    ):
        raise GitFirstRestoreError("invalid restore ref")
    if type(plan.entries) is not tuple or not plan.entries or any(
        not isinstance(entry, RestoreCommitEntry) for entry in plan.entries
    ):
        raise GitFirstRestoreError("invalid restore plan entries")

    if _plan_spec_id(plan) != spec_id:
        raise GitFirstRestoreError("restore plan spec ID mismatch")
    names = {Path(entry.path).name for entry in plan.entries}
    if (
        len(names) != len(plan.entries)
        or not _REQUIRED_ARTIFACTS <= names
        or not names <= _ALLOWED_ARTIFACTS
    ):
        raise GitFirstRestoreError("restore plan owned artifact paths are unsafe")
    base_tree = _stdout_text(_git(root, "rev-parse", f"{plan.base_commit}^{{tree}}"))
    if base_tree != plan.base_tree:
        raise GitFirstRestoreError("restore plan base tree mismatch")
    expected_message = _restore_checkpoint_message(
        spec_id=spec_id,
        run_id=run_id,
        next_phase=next_phase,
        completion_id=plan.completion_id,
        selected_candidate_id=plan.selected_candidate_id,
        selected_manifest_sha256=plan.selected_manifest_sha256,
    )
    expected_commit = _deterministic_commit_bytes(
        target_tree=plan.target_tree,
        parent=plan.base_commit,
        message=expected_message,
        timestamp=_base_commit_date(root, plan.base_commit),
    )
    actual_commit = _git(root, "cat-file", "commit", plan.target_commit).stdout
    if actual_commit != expected_commit:
        raise GitFirstRestoreError(
            "target restore commit exact authority or message mismatch"
        )

    base_entries = _tree_entries(root, plan.base_tree)
    target_entries = _tree_entries(root, plan.target_tree)
    owned: set[bytes] = set()
    owned_ancestors: set[bytes] = set()
    for entry in plan.entries:
        path = entry.path.encode("utf-8")
        if path in owned:
            raise GitFirstRestoreError("duplicate restore plan entry")
        owned.add(path)
        parts = path.split(b"/")
        owned_ancestors.update(
            b"/".join(parts[:offset]) for offset in range(1, len(parts))
        )
        for field, oid in (
            ("base blob object ID", entry.base_blob_oid),
            ("target blob object ID", entry.target_blob_oid),
        ):
            _validate_oid(oid, field=field)
        for field, digest in (
            ("base artifact digest", entry.base_sha256),
            ("target artifact digest", entry.target_sha256),
        ):
            _validate_sha256(digest, field=field)
        if entry.base_mode not in {"100644", "100755"} or entry.target_mode not in {
            "100644",
            "100755",
        }:
            raise GitFirstRestoreError("restore plan entry is not a regular blob")
        if base_entries.get(path) != (
            entry.base_mode,
            "blob",
            entry.base_blob_oid,
        ):
            raise GitFirstRestoreError("base owned tree entry mismatch")
        if target_entries.get(path) != (
            entry.target_mode,
            "blob",
            entry.target_blob_oid,
        ):
            raise GitFirstRestoreError("target owned tree entry mismatch")
        if _blob_sha256(root, entry.base_blob_oid) != entry.base_sha256:
            raise GitFirstRestoreError("base owned artifact digest mismatch")
        if _blob_sha256(root, entry.target_blob_oid) != entry.target_sha256:
            raise GitFirstRestoreError("target owned artifact digest mismatch")
    if (
        {
            path: value
            for path, value in base_entries.items()
            if path not in owned and path not in owned_ancestors
        }
        != {
            path: value
            for path, value in target_entries.items()
            if path not in owned and path not in owned_ancestors
        }
    ):
        raise GitFirstRestoreError("target restore commit has an unowned tree change")


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GitFirstRestoreError("restore authority is not canonical JSON") from exc


def _restore_plan_sha256(plan: GitFirstRestorePlan) -> str:
    return hashlib.sha256(_canonical_json_bytes(asdict(plan))).hexdigest()


def _restore_temporary_name(completion_id: str, path: str) -> str:
    token = hashlib.sha256(
        f"{completion_id}:{path}".encode("utf-8")
    ).hexdigest()[:32]
    return f"{_RESTORE_TEMP_PREFIX}{token}.tmp"


def _restore_journal(plan: GitFirstRestorePlan) -> GitFirstRestoreJournal:
    plan_sha256 = _restore_plan_sha256(plan)
    return GitFirstRestoreJournal(
        schema_version=1,
        completion_id=plan.completion_id,
        plan_sha256=plan_sha256,
        ref_name=plan.ref_name,
        base_commit=plan.base_commit,
        target_commit=plan.target_commit,
        entries=tuple(
            JournalEntry(
                path=entry.path,
                base_mode=entry.base_mode,
                base_sha256=entry.base_sha256,
                target_mode=entry.target_mode,
                target_sha256=entry.target_sha256,
                temporary_name=_restore_temporary_name(
                    plan.completion_id,
                    entry.path,
                ),
            )
            for entry in plan.entries
        ),
    )


def _restore_fault(_point: str) -> None:
    """Test seam for simulating process death at durable boundaries."""


def _restore_entry_token(metadata: os.stat_result) -> tuple[object, ...]:
    return (
        stat.S_IFMT(metadata.st_mode),
        stat.S_IMODE(metadata.st_mode),
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        getattr(metadata, "st_flags", None),
        getattr(metadata, "st_gen", None),
    )


def _restore_entry_snapshot(
    directory_fd: int,
    name: str,
    *,
    missing_ok: bool = False,
) -> _RestoreEntrySnapshot | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise GitFirstRestoreError("restore worktree entry is missing")
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise GitFirstRestoreError("restore entry is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(
        os,
        "O_NONBLOCK",
        0,
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise GitFirstRestoreError("restore entry could not be opened") from exc
    try:
        opened = os.fstat(descriptor)
        token = _restore_entry_token(opened)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ) != (metadata.st_dev, metadata.st_ino, metadata.st_size):
            raise GitFirstRestoreError("restore entry identity changed")
        remaining = opened.st_size
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        while remaining:
            try:
                chunk = os.read(descriptor, min(1_048_576, remaining))
            except OSError as exc:
                raise GitFirstRestoreError("restore entry could not be read") from exc
            if not chunk:
                raise GitFirstRestoreError("restore entry changed while reading")
            remaining -= len(chunk)
            digest.update(chunk)
            chunks.append(chunk)
        after = os.fstat(descriptor)
        try:
            current = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise GitFirstRestoreError("restore entry identity changed") from exc
        if _restore_entry_token(after) != token or _restore_entry_token(current) != token:
            raise GitFirstRestoreError("restore entry identity changed")
        return _RestoreEntrySnapshot(
            sha256=digest.hexdigest(),
            content=b"".join(chunks),
            mode=stat.S_IMODE(opened.st_mode),
            token=token,
        )
    finally:
        os.close(descriptor)


def _open_restore_directory(path: Path, *, field: str) -> int:
    lexical = Path(os.path.abspath(path))
    try:
        metadata = os.lstat(lexical)
        if lexical.resolve(strict=True) != lexical:
            raise OSError(f"{field} contains a symlink")
    except OSError as exc:
        raise GitFirstRestoreError(f"{field} is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise GitFirstRestoreError(f"{field} is not a directory")
    try:
        descriptor = os.open(
            lexical,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise GitFirstRestoreError(f"{field} could not be opened") from exc
    if not stat.S_ISDIR(opened.st_mode) or (
        opened.st_dev,
        opened.st_ino,
    ) != (metadata.st_dev, metadata.st_ino):
        os.close(descriptor)
        raise GitFirstRestoreError(f"{field} identity changed")
    return descriptor


def _ensure_restore_journal_directory(journal_root: Path) -> Path:
    root_fd = _open_restore_directory(journal_root, field="restore journal root")
    try:
        directory = Path(journal_root) / _RESTORE_JOURNAL_DIRECTORY
        try:
            os.mkdir(_RESTORE_JOURNAL_DIRECTORY, mode=0o700, dir_fd=root_fd)
            os.fsync(root_fd)
        except FileExistsError:
            pass
        metadata = os.stat(
            _RESTORE_JOURNAL_DIRECTORY,
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise GitFirstRestoreError("restore journal directory is not a directory")
        return directory
    except OSError as exc:
        raise GitFirstRestoreError("restore journal directory is unavailable") from exc
    finally:
        os.close(root_fd)


def _write_restore_file(
    directory_fd: int,
    name: str,
    content: bytes,
    *,
    mode: int,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, mode, dir_fd=directory_fd)
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short restore write")
                view = view[written:]
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory_fd)
    except OSError as exc:
        raise GitFirstRestoreError("restore durable file write failed") from exc


def _atomic_exchange_restore_entries(
    first_directory_fd: int,
    first_name: str,
    second_directory_fd: int,
    second_name: str,
) -> None:
    import ctypes
    import ctypes.util
    import sys

    library_name = ctypes.util.find_library("c")
    if library_name is None:
        raise GitFirstRestoreError("atomic restore exchange is unavailable")
    libc = ctypes.CDLL(library_name, use_errno=True)
    first = os.fsencode(first_name)
    second = os.fsencode(second_name)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        flag = 0x00000002  # RENAME_SWAP
    elif hasattr(libc, "renameat2"):
        function = libc.renameat2
        flag = 0x00000002  # RENAME_EXCHANGE
    else:
        raise GitFirstRestoreError("atomic restore exchange is unavailable")
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        first_directory_fd,
        first,
        second_directory_fd,
        second,
        flag,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise GitFirstRestoreError(
            f"atomic restore exchange failed: {os.strerror(error_number)}"
        )


def _snapshot_matches(
    snapshot: _RestoreEntrySnapshot,
    *,
    mode: str,
    sha256: str,
) -> bool:
    return snapshot.mode == int(mode[-3:], 8) and snapshot.sha256 == sha256


def _persist_restore_journal(
    journal_fd: int,
    *,
    name: str,
    content: bytes,
) -> bool:
    existing = _restore_entry_snapshot(journal_fd, name, missing_ok=True)
    if existing is not None:
        if existing.mode != 0o600 or existing.content != content:
            raise GitFirstRestoreError("restore journal authority changed")
        return False
    _write_restore_file(journal_fd, name, content, mode=0o600)
    existing = _restore_entry_snapshot(journal_fd, name)
    if existing is None or existing.mode != 0o600 or existing.content != content:
        raise GitFirstRestoreError("restore journal authority changed")
    return True


def _preflight_restore_temporaries(
    journal_fd: int,
    *,
    entries: tuple[RestoreCommitEntry, ...],
    journal_entries: tuple[JournalEntry, ...],
    current_snapshots: tuple[_RestoreEntrySnapshot, ...],
) -> None:
    for entry, journal_entry, current in zip(
        entries,
        journal_entries,
        current_snapshots,
        strict=True,
    ):
        temporary = _restore_entry_snapshot(
            journal_fd,
            journal_entry.temporary_name,
            missing_ok=True,
        )
        if temporary is None:
            continue
        current_is_base = _snapshot_matches(
            current,
            mode=entry.base_mode,
            sha256=entry.base_sha256,
        )
        current_is_target = _snapshot_matches(
            current,
            mode=entry.target_mode,
            sha256=entry.target_sha256,
        )
        temporary_is_base = _snapshot_matches(
            temporary,
            mode=entry.base_mode,
            sha256=entry.base_sha256,
        )
        temporary_is_target = _snapshot_matches(
            temporary,
            mode=entry.target_mode,
            sha256=entry.target_sha256,
        )
        if current_is_base and not current_is_target and not temporary_is_target:
            raise GitFirstRestoreError("restore target temporary changed")
        if current_is_target and not current_is_base and not temporary_is_base:
            raise GitFirstRestoreError("restore exchange residue changed")
        if current_is_base and current_is_target and not (
            temporary_is_base or temporary_is_target
        ):
            raise GitFirstRestoreError("restore target temporary changed")


def _reconcile_restore_entry(
    worktree_fd: int,
    journal_fd: int,
    *,
    entry: RestoreCommitEntry,
    journal_entry: JournalEntry,
    target_content: bytes,
    expected_current: _RestoreEntrySnapshot,
) -> bool:
    destination = Path(entry.path).name
    current = _restore_entry_snapshot(worktree_fd, destination)
    if current is None:  # pragma: no cover - missing_ok is false
        raise GitFirstRestoreError("restore worktree entry is missing")
    if current != expected_current:
        raise GitFirstRestoreError("restore entry identity changed")
    temporary = _restore_entry_snapshot(
        journal_fd,
        journal_entry.temporary_name,
        missing_ok=True,
    )
    if _snapshot_matches(
        current,
        mode=entry.target_mode,
        sha256=entry.target_sha256,
    ):
        if temporary is None:
            return False
        if not _snapshot_matches(
            temporary,
            mode=entry.base_mode,
            sha256=entry.base_sha256,
        ):
            raise GitFirstRestoreError("restore exchange residue changed")
        try:
            os.unlink(journal_entry.temporary_name, dir_fd=journal_fd)
            os.fsync(journal_fd)
        except OSError as exc:
            raise GitFirstRestoreError("restore exchange cleanup failed") from exc
        return False
    if not _snapshot_matches(
        current,
        mode=entry.base_mode,
        sha256=entry.base_sha256,
    ):
        raise GitFirstRestoreError("restore worktree authority changed")
    if temporary is None:
        _write_restore_file(
            journal_fd,
            journal_entry.temporary_name,
            target_content,
            mode=int(entry.target_mode[-3:], 8),
        )
        temporary = _restore_entry_snapshot(
            journal_fd,
            journal_entry.temporary_name,
        )
    if temporary is None or not _snapshot_matches(
        temporary,
        mode=entry.target_mode,
        sha256=entry.target_sha256,
    ):
        raise GitFirstRestoreError("restore target temporary changed")
    if (
        _restore_entry_snapshot(worktree_fd, destination) != current
        or _restore_entry_snapshot(
            journal_fd,
            journal_entry.temporary_name,
        )
        != temporary
    ):
        raise GitFirstRestoreError("restore entry identity changed")
    _atomic_exchange_restore_entries(
        journal_fd,
        journal_entry.temporary_name,
        worktree_fd,
        destination,
    )
    os.fsync(worktree_fd)
    os.fsync(journal_fd)
    restored = _restore_entry_snapshot(worktree_fd, destination)
    displaced = _restore_entry_snapshot(
        journal_fd,
        journal_entry.temporary_name,
    )
    if (
        restored is None
        or not _snapshot_matches(
            restored,
            mode=entry.target_mode,
            sha256=entry.target_sha256,
        )
        or displaced is None
        or not _snapshot_matches(
            displaced,
            mode=entry.base_mode,
            sha256=entry.base_sha256,
        )
        or displaced.token[2:4] != current.token[2:4]
    ):
        raise GitFirstRestoreError("restore atomic exchange changed")
    return True


def _remove_displaced_restore_entry(journal_fd: int, temporary_name: str) -> None:
    try:
        os.unlink(temporary_name, dir_fd=journal_fd)
        os.fsync(journal_fd)
    except OSError as exc:
        raise GitFirstRestoreError("restore exchange cleanup failed") from exc


def _current_ref_commit(project_root: Path, ref_name: str) -> str:
    if _active_ref(project_root) != ref_name:
        raise GitFirstRestoreError("restore ref authority changed")
    result = _git(
        project_root,
        "show-ref",
        "--verify",
        "--hash",
        ref_name,
        check=False,
    )
    if result.returncode != 0:
        raise GitFirstRestoreError("restore ref authority changed")
    return _stdout_text(result)


def _current_index_tree(project_root: Path) -> str:
    return _stdout_text(_git(project_root, "write-tree"))


def _verify_restore_paths(
    worktree_fd: int,
    entries: tuple[RestoreCommitEntry, ...],
    *,
    target: bool,
) -> tuple[_RestoreEntrySnapshot, ...]:
    snapshots: list[_RestoreEntrySnapshot] = []
    for entry in entries:
        snapshot = _restore_entry_snapshot(worktree_fd, Path(entry.path).name)
        if snapshot is None:  # pragma: no cover - missing_ok is false
            raise GitFirstRestoreError("restore worktree entry is missing")
        mode = entry.target_mode if target else entry.base_mode
        digest = entry.target_sha256 if target else entry.base_sha256
        if not _snapshot_matches(snapshot, mode=mode, sha256=digest):
            raise GitFirstRestoreError("restore worktree authority changed")
        snapshots.append(snapshot)
    return tuple(snapshots)


def _validate_restore_receipt(
    value: object,
    *,
    plan: GitFirstRestorePlan,
    plan_sha256: str,
) -> dict[str, object] | None:
    if value is None:
        return None
    if type(value) is not dict or frozenset(value) != frozenset(
        {
            "schema_version",
            "completion_id",
            "restore_protocol",
            "plan_sha256",
            "target_commit",
            "checkpoint",
        }
    ):
        raise GitFirstRestoreError("restore receipt mismatch")
    if (
        value.get("schema_version") != 1
        or value.get("completion_id") != plan.completion_id
        or value.get("restore_protocol") != "git_first_v1"
        or value.get("plan_sha256") != plan_sha256
        or value.get("target_commit") != plan.target_commit
        or type(value.get("checkpoint")) is not dict
    ):
        raise GitFirstRestoreError("restore receipt mismatch")
    return dict(value)


def apply_or_recover_git_first_restore(
    project_root: Path,
    spec_dir: Path,
    journal_root: Path,
    plan: GitFirstRestorePlan,
    run_id: str,
    spec_id: str,
    next_phase: str,
    expected_receipt: object | None = None,
) -> GitFirstRestoreReceipt:
    """Converge worktree, ref, index, and ledger to immutable restore authority."""

    root = Path(project_root).resolve()
    lexical_spec = Path(os.path.abspath(spec_dir))
    lexical_journal_root = Path(os.path.abspath(journal_root))
    verify_git_first_restore_commit(root, plan)
    if (
        run_id != plan.run_id
        or spec_id != plan.spec_id
        or next_phase != plan.next_phase
    ):
        raise GitFirstRestoreError("restore plan identity changed")
    _validate_metadata(run_id, field="run ID")
    _validate_safe_id(spec_id, field="spec ID")
    _validate_metadata(next_phase, field="next phase")
    try:
        spec_relative = lexical_spec.relative_to(root).as_posix()
    except ValueError as exc:
        raise GitFirstRestoreError("restore spec directory escapes project") from exc
    expected_paths = tuple(
        f"{spec_relative}/{name}"
        for name in sorted(Path(entry.path).name for entry in plan.entries)
    )
    if tuple(entry.path for entry in plan.entries) != expected_paths:
        raise GitFirstRestoreError("restore plan does not match spec directory")
    journal = _restore_journal(plan)
    plan_sha256 = journal.plan_sha256
    expected = _validate_restore_receipt(
        expected_receipt,
        plan=plan,
        plan_sha256=plan_sha256,
    )
    from harness.phase_checkpoints import (
        PhaseCheckpointError,
        preflight_prebuilt_completion_checkpoint,
        record_prebuilt_completion_checkpoint,
    )

    checkpoint_expected = expected.get("checkpoint") if expected is not None else None
    try:
        preflight_prebuilt_completion_checkpoint(
            project_root=root,
            spec_dir=lexical_spec,
            phase=_RESTORE_PHASE,
            next_phase=next_phase,
            run_id=run_id,
            spec_id=spec_id,
            completion_id=plan.completion_id,
            expected_parent=plan.base_commit,
            commit=plan.target_commit,
            expected_entries=plan.entries,
            expected_receipt=checkpoint_expected,
        )
    except PhaseCheckpointError as exc:
        raise GitFirstRestoreError("restore checkpoint preflight failed") from exc
    current_ref = _current_ref_commit(root, plan.ref_name)
    if current_ref not in {plan.base_commit, plan.target_commit}:
        raise GitFirstRestoreError("restore ref authority changed")
    index_tree = _current_index_tree(root)
    if index_tree not in {plan.base_tree, plan.target_tree}:
        raise GitFirstRestoreError("restore index authority changed")

    worktree_fd = _open_restore_directory(
        lexical_spec,
        field="restore spec directory",
    )
    journal_root_fd: int | None = None
    journal_fd: int | None = None
    try:
        try:
            lexical_journal_root.relative_to(lexical_spec)
        except ValueError:
            pass
        else:
            raise GitFirstRestoreError(
                "restore journal root overlaps checkpoint-owned paths"
            )
        journal_root_fd = _open_restore_directory(
            lexical_journal_root,
            field="restore journal root",
        )
        if os.fstat(worktree_fd).st_dev != os.fstat(journal_root_fd).st_dev:
            raise GitFirstRestoreError(
                "restore temporaries must share the destination filesystem"
            )
        initial: list[str] = []
        initial_snapshots: list[_RestoreEntrySnapshot] = []
        for entry in plan.entries:
            snapshot = _restore_entry_snapshot(worktree_fd, Path(entry.path).name)
            if snapshot is None:  # pragma: no cover - missing_ok is false
                raise GitFirstRestoreError("restore worktree entry is missing")
            matches_base = _snapshot_matches(
                snapshot,
                mode=entry.base_mode,
                sha256=entry.base_sha256,
            )
            matches_target = _snapshot_matches(
                snapshot,
                mode=entry.target_mode,
                sha256=entry.target_sha256,
            )
            if matches_base and matches_target:
                initial.append("both")
            elif matches_base:
                initial.append("base")
            elif matches_target:
                initial.append("target")
            else:
                raise GitFirstRestoreError("restore worktree authority changed")
            initial_snapshots.append(snapshot)

        journal_dir = lexical_journal_root / _RESTORE_JOURNAL_DIRECTORY
        journal_name = f"{plan.completion_id}.json"
        journal_exists = False
        if journal_dir.exists():
            journal_fd = _open_restore_directory(
                journal_dir,
                field="restore journal directory",
            )
            journal_exists = (
                _restore_entry_snapshot(
                    journal_fd,
                    journal_name,
                    missing_ok=True,
                )
                is not None
            )
            expected_temps = {entry.temporary_name for entry in journal.entries}
            present_temps = {
                name
                for name in os.listdir(journal_fd)
                if name.startswith(_RESTORE_TEMP_PREFIX)
            }
            if present_temps and not journal_exists:
                raise GitFirstRestoreError("restore journal is missing")
            if not present_temps <= expected_temps:
                raise GitFirstRestoreError("unexplained restore temporary exists")
        if not journal_exists:
            base_state = (
                current_ref == plan.base_commit
                and index_tree == plan.base_tree
                and all(state in {"base", "both"} for state in initial)
            )
            target_state = (
                current_ref == plan.target_commit
                and index_tree == plan.target_tree
                and all(state in {"target", "both"} for state in initial)
            )
            if not base_state and not target_state:
                raise GitFirstRestoreError("restore journal is missing")
            if base_state and expected is not None:
                raise GitFirstRestoreError("restore receipt mismatch")

        if journal_exists or current_ref == plan.base_commit:
            if journal_fd is None:
                journal_dir = _ensure_restore_journal_directory(
                    lexical_journal_root
                )
                journal_fd = _open_restore_directory(
                    journal_dir,
                    field="restore journal directory",
                )
            if os.fstat(worktree_fd).st_dev != os.fstat(journal_fd).st_dev:
                raise GitFirstRestoreError(
                    "restore temporaries must share the destination filesystem"
                )
            journal_content = _canonical_json_bytes(asdict(journal))
            created = _persist_restore_journal(
                journal_fd,
                name=journal_name,
                content=journal_content,
            )
            if created:
                _restore_fault("after_journal")
            _preflight_restore_temporaries(
                journal_fd,
                entries=plan.entries,
                journal_entries=journal.entries,
                current_snapshots=tuple(initial_snapshots),
            )
            for offset, (entry, journal_entry, initial_snapshot) in enumerate(
                zip(
                    plan.entries,
                    journal.entries,
                    initial_snapshots,
                    strict=True,
                )
            ):
                exchanged = _reconcile_restore_entry(
                    worktree_fd,
                    journal_fd,
                    entry=entry,
                    journal_entry=journal_entry,
                    target_content=_blob_bytes(root, entry.target_blob_oid),
                    expected_current=initial_snapshot,
                )
                if exchanged and offset == 0:
                    _restore_fault("after_first_exchange")
                if exchanged:
                    _remove_displaced_restore_entry(
                        journal_fd,
                        journal_entry.temporary_name,
                    )
            _verify_restore_paths(worktree_fd, plan.entries, target=True)
            _restore_fault("after_all_exchanges")

            current_ref = _current_ref_commit(root, plan.ref_name)
            if current_ref == plan.base_commit:
                _git(
                    root,
                    "update-ref",
                    plan.ref_name,
                    plan.target_commit,
                    plan.base_commit,
                )
            elif current_ref != plan.target_commit:
                raise GitFirstRestoreError("restore ref authority changed")
            _restore_fault("after_ref_update")

            index_tree = _current_index_tree(root)
            if index_tree == plan.base_tree:
                _git(root, "read-tree", plan.target_commit)
            elif index_tree != plan.target_tree:
                raise GitFirstRestoreError("restore index authority changed")
            _restore_fault("after_index_update")

            try:
                os.unlink(journal_name, dir_fd=journal_fd)
                os.fsync(journal_fd)
            except OSError as exc:
                raise GitFirstRestoreError("restore journal cleanup failed") from exc

        verify_git_first_restore_commit(root, plan)
        if _current_ref_commit(root, plan.ref_name) != plan.target_commit:
            raise GitFirstRestoreError("restore ref authority changed")
        if _current_index_tree(root) != plan.target_tree:
            raise GitFirstRestoreError("restore index authority changed")
        _verify_restore_paths(worktree_fd, plan.entries, target=True)
        if journal_fd is not None:
            if _restore_entry_snapshot(
                journal_fd,
                journal_name,
                missing_ok=True,
            ) is not None or any(
                _restore_entry_snapshot(
                    journal_fd,
                    entry.temporary_name,
                    missing_ok=True,
                )
                is not None
                for entry in journal.entries
            ):
                raise GitFirstRestoreError("restore journal residue remains")
    finally:
        os.close(worktree_fd)
        if journal_root_fd is not None:
            os.close(journal_root_fd)
        if journal_fd is not None:
            os.close(journal_fd)

    try:
        checkpoint = record_prebuilt_completion_checkpoint(
            project_root=root,
            spec_dir=lexical_spec,
            phase=_RESTORE_PHASE,
            next_phase=next_phase,
            run_id=run_id,
            spec_id=spec_id,
            completion_id=plan.completion_id,
            expected_parent=plan.base_commit,
            commit=plan.target_commit,
            expected_entries=plan.entries,
            expected_receipt=checkpoint_expected,
        )
    except PhaseCheckpointError as exc:
        raise GitFirstRestoreError("restore checkpoint recording failed") from exc
    _restore_fault("before_receipt")
    receipt = GitFirstRestoreReceipt(
        schema_version=1,
        completion_id=plan.completion_id,
        restore_protocol="git_first_v1",
        plan_sha256=plan_sha256,
        target_commit=plan.target_commit,
        checkpoint=checkpoint,
    )
    if expected is not None and expected != asdict(receipt):
        raise GitFirstRestoreError("restore receipt mismatch")
    return receipt
