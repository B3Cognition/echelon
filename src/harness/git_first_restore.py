"""Build immutable candidate-restore commits without touching active Git state."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
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
    elif path.startswith(prefix) and path.removeprefix(prefix) in _ALLOWED_ARTIFACTS:
        name = path.removeprefix(prefix)
    else:
        raise GitFirstRestoreError("candidate owned artifact paths are unsafe")
    return name, prefix + name


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
        match = re.fullmatch(r"specs/([^/]+)/([^/]+)", entry.path)
        if match is None or match.group(2) not in _ALLOWED_ARTIFACTS:
            raise GitFirstRestoreError("restore plan owned artifact paths are unsafe")
        spec_ids.add(match.group(1))
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
    dirty = _git(root, "status", "--porcelain", "-z").stdout
    if dirty:
        raise GitFirstRestoreError("base worktree and index must be clean")
    base_tree = _stdout_text(_git(root, "rev-parse", f"{base}^{{tree}}"))
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
    if _git(root, "status", "--porcelain", "-z").stdout:
        raise GitFirstRestoreError("base authority changed while building restore commit")
    if _active_index_snapshot(root) != index_snapshot:
        raise GitFirstRestoreError("active index changed while building restore commit")
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
