"""Publish committed spec snapshots from canonical local Phase A branches."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from pathlib import PurePosixPath
from typing import Iterator

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.git_helpers import (
    GitHelperError,
    run_git,
)
from echelon.phase_a_git import PhaseAGitError, resolve_phase_a_default_branch
from harness.config import get_full_resolved_config


CANONICAL_SPEC_BRANCH_RE = re.compile(
    r"^(?P<number>\d{3,})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)


class SpecPublishError(RuntimeError):
    """Raised when spec catalog publication cannot proceed safely."""


@dataclass(frozen=True)
class SpecPublicationSource:
    spec_id: str
    spec_number: str
    branch: str
    commit: str
    source_path: str


@dataclass(frozen=True)
class PublishedSpec:
    spec_id: str
    source_branch: str
    source_commit: str
    changed: bool


@dataclass(frozen=True)
class SpecPublishResult:
    default_branch: str
    previous_default_commit: str
    default_commit: str
    created_commit: bool
    destination_worktree: Path
    caller_on_default: bool
    published: tuple[PublishedSpec, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GitWorktree:
    path: Path
    branch: str | None


def discover_publication_sources(
    project_root: Path,
    default_branch: str,
) -> tuple[SpecPublicationSource, ...]:
    """Return canonical local branches with a matching committed spec."""

    root = Path(project_root).resolve()
    try:
        output = run_git(
            root,
            "for-each-ref",
            "--format=%(refname:short)%00%(objectname)",
            "refs/heads",
        ).stdout
    except GitHelperError as exc:
        raise SpecPublishError(str(exc)) from exc

    sources: list[SpecPublicationSource] = []
    for line in output.splitlines():
        branch, separator, commit = line.partition("\0")
        if not separator or branch == default_branch:
            continue
        match = CANONICAL_SPEC_BRANCH_RE.fullmatch(branch)
        if match is None:
            continue
        source_path = f"specs/{branch}"
        exists = run_git(
            root,
            "cat-file",
            "-e",
            f"{commit}:{source_path}/spec.md",
            check=False,
        )
        if exists.returncode != 0:
            continue
        sources.append(
            SpecPublicationSource(
                spec_id=branch,
                spec_number=match.group("number"),
                branch=branch,
                commit=commit,
                source_path=source_path,
            )
        )
    return tuple(sorted(sources, key=lambda source: source.branch))


def resolve_publication_sources(
    project_root: Path,
    *,
    identity: str | None,
    publish_all: bool,
    default_branch: str,
) -> tuple[SpecPublicationSource, ...]:
    """Resolve one command form against canonical local branch sources."""

    cleaned_identity = str(identity or "").strip()
    if bool(cleaned_identity) == publish_all:
        raise SpecPublishError("choose exactly one spec identity or --all")

    sources = discover_publication_sources(project_root, default_branch)
    by_number: dict[int, list[SpecPublicationSource]] = {}
    for source in sources:
        by_number.setdefault(int(source.spec_number), []).append(source)

    duplicate_numbers = {
        number: matches for number, matches in by_number.items() if len(matches) > 1
    }
    if publish_all:
        if duplicate_numbers:
            number = sorted(duplicate_numbers)[0]
            candidates = ", ".join(
                source.branch for source in duplicate_numbers[number]
            )
            raise SpecPublishError(
                f"ambiguous spec identity {number:03d}: {candidates}"
            )
        if not sources:
            raise SpecPublishError("no canonical local spec branches are publishable")
        return sources

    if cleaned_identity.isdigit():
        matches = by_number.get(int(cleaned_identity), [])
    else:
        matches = [source for source in sources if source.branch == cleaned_identity]
    if not matches:
        raise SpecPublishError(
            f"no canonical local spec branch matches {cleaned_identity!r}"
        )
    if len(matches) > 1:
        candidates = ", ".join(source.branch for source in matches)
        raise SpecPublishError(
            f"ambiguous spec identity {cleaned_identity!r}: {candidates}"
        )
    return tuple(matches)


def _git_bytes(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise SpecPublishError("could not execute git: git is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise SpecPublishError(f"git {' '.join(args)} timed out in {repo}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise SpecPublishError(
            f"git {' '.join(args)} failed in {repo}: {stderr.strip()}"
        )
    return result.stdout


def _configured_default_branch(project_root: Path) -> str:
    resolved = get_full_resolved_config(project_root)
    configured = resolved.get("target_default_branch", "")
    if not configured and isinstance(resolved.get("harness"), dict):
        configured = resolved["harness"].get("target_default_branch", "")
    return str(configured or "")


def _materialize_source(
    project_root: Path,
    source: SpecPublicationSource,
    staging_root: Path,
) -> Path:
    """Extract one exact committed spec subtree into an isolated directory."""

    archive = _git_bytes(
        project_root,
        "archive",
        "--format=tar",
        source.commit,
        "--",
        source.source_path,
    )
    expected = PurePosixPath(source.source_path)
    destination = staging_root / source.spec_id
    destination.mkdir(parents=True)

    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as payload:
            for member in payload.getmembers():
                member_path = PurePosixPath(member.name)
                if member.isdir() and member_path in expected.parents:
                    continue
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or member_path != expected
                    and expected not in member_path.parents
                ):
                    raise SpecPublishError(
                        f"unsafe archive path {member.name!r} for {source.branch}"
                    )
                relative = member_path.relative_to(expected)
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(member.mode & 0o777)
                    continue
                if not member.isfile():
                    raise SpecPublishError(
                        f"unsupported archive entry {member.name!r} for "
                        f"{source.branch}; links are not publishable"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = payload.extractfile(member)
                if extracted is None:
                    raise SpecPublishError(
                        f"could not read archive entry {member.name!r}"
                    )
                with target.open("wb") as output:
                    shutil.copyfileobj(extracted, output)
                target.chmod(member.mode & 0o777)
    except tarfile.TarError as exc:
        raise SpecPublishError(
            f"invalid Git archive for {source.branch}: {exc}"
        ) from exc

    manifest = {
        "schema_version": 1,
        "source_branch": source.branch,
        "source_commit": source.commit,
        "spec_id": source.spec_id,
    }
    (destination / ".echelon-publication.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _destination_collisions(
    destination_worktree: Path,
    sources: tuple[SpecPublicationSource, ...],
) -> None:
    specs_root = destination_worktree / "specs"
    if not specs_root.is_dir():
        return
    selected = {source.spec_id for source in sources}
    selected_numbers = {int(source.spec_number): source.spec_id for source in sources}
    for path in specs_root.iterdir():
        if not path.is_dir() or path.name in selected:
            continue
        match = re.match(r"^(\d{3,})-", path.name)
        if match is None:
            continue
        number = int(match.group(1))
        if number in selected_numbers:
            raise SpecPublishError(
                "destination identity collision: "
                f"specs/{path.name} already exists but publication selected "
                f"{selected_numbers[number]}"
            )


def _validated_specs_root(
    destination_worktree: Path,
    sources: tuple[SpecPublicationSource, ...],
) -> Path:
    worktree_root = destination_worktree.resolve()
    specs_root = worktree_root / "specs"
    if specs_root.is_symlink():
        raise SpecPublishError(
            f"publication path {specs_root} is a symlink; replace it with a "
            "worktree-local directory first"
        )
    if specs_root.exists() and not specs_root.is_dir():
        raise SpecPublishError(
            f"publication path {specs_root} is not a directory"
        )
    if specs_root.resolve() != worktree_root / "specs":
        raise SpecPublishError(
            f"publication path {specs_root} escapes the destination worktree"
        )
    for source in sources:
        destination = specs_root / source.spec_id
        if destination.is_symlink():
            raise SpecPublishError(
                f"publication destination {destination} is a symlink; remove it first"
            )
        if destination.exists() and not destination.is_dir():
            raise SpecPublishError(
                f"publication destination {destination} is not a directory"
            )
        if destination.resolve() != specs_root / source.spec_id:
            raise SpecPublishError(
                f"publication destination {destination} escapes {specs_root}"
            )
    return specs_root


def _list_worktrees(project_root: Path) -> tuple[GitWorktree, ...]:
    output = run_git(project_root, "worktree", "list", "--porcelain").stdout
    worktrees: list[GitWorktree] = []
    path: Path | None = None
    branch: str | None = None
    for line in [*output.splitlines(), ""]:
        if not line:
            if path is not None:
                worktrees.append(GitWorktree(path=path.resolve(), branch=branch))
            path = None
            branch = None
        elif line.startswith("worktree "):
            path = Path(line.removeprefix("worktree "))
        elif line.startswith("branch "):
            branch = line.removeprefix("branch ").removeprefix("refs/heads/")
    return tuple(worktrees)


def _validate_source_worktrees(
    sources: tuple[SpecPublicationSource, ...],
    worktrees: tuple[GitWorktree, ...],
) -> None:
    for source in sources:
        for worktree in worktrees:
            if worktree.branch != source.branch:
                continue
            dirty = run_git(
                worktree.path,
                "status",
                "--porcelain",
                "--",
                source.source_path,
            ).stdout.strip()
            if dirty:
                raise SpecPublishError(
                    f"source branch {source.branch} has uncommitted changes in "
                    f"{source.source_path} at {worktree.path}; "
                    "commit or clean them first"
                )


@contextmanager
def _publication_worktree(
    project_root: Path,
    default_branch: str,
    worktrees: tuple[GitWorktree, ...],
    cleanup_warnings: list[str],
) -> Iterator[tuple[Path, bool]]:
    """Yield a clean checked-out default worktree or a removable temporary one."""

    root = project_root.resolve()
    existing = next(
        (worktree for worktree in worktrees if worktree.branch == default_branch),
        None,
    )
    if existing is not None:
        dirty = run_git(existing.path, "status", "--porcelain").stdout.strip()
        if dirty:
            raise SpecPublishError(
                f"default-branch worktree {existing.path} is dirty; "
                "commit or clean it first"
            )
        yield existing.path, existing.path == root
        return

    temporary_root = Path(tempfile.mkdtemp(prefix="echelon-spec-publish-worktree-"))
    destination = temporary_root / "default"
    added = False
    try:
        run_git(
            root,
            "worktree",
            "add",
            "--quiet",
            str(destination),
            default_branch,
        )
        added = True
        yield destination.resolve(), False
    finally:
        if not added:
            shutil.rmtree(temporary_root, ignore_errors=True)
        else:
            try:
                removal = run_git(
                    root,
                    "worktree",
                    "remove",
                    "--force",
                    str(destination),
                    check=False,
                )
            except GitHelperError as exc:
                cleanup_warnings.append(
                    f"temporary worktree cleanup failure at {destination}: {exc}"
                )
            else:
                if removal.returncode != 0:
                    cleanup_warnings.append(
                        f"temporary worktree cleanup failure at {destination}: "
                        f"{removal.stderr.strip()}"
                    )
                else:
                    try:
                        prune = run_git(root, "worktree", "prune", check=False)
                    except GitHelperError as exc:
                        cleanup_warnings.append(
                            f"temporary worktree prune exception: {exc}"
                        )
                    else:
                        if prune.returncode != 0:
                            cleanup_warnings.append(
                                "temporary worktree prune failure: "
                                f"{prune.stderr.strip()}"
                            )
                    shutil.rmtree(temporary_root, ignore_errors=True)


def _assert_default_ref_unchanged(
    project_root: Path,
    default_branch: str,
    expected_commit: str,
) -> None:
    current = run_git(
        project_root,
        "rev-parse",
        f"refs/heads/{default_branch}^{{commit}}",
    ).stdout.strip()
    if current != expected_commit:
        raise SpecPublishError(
            f"default branch {default_branch} changed during publication; retry"
        )


def _restore_destinations(
    destination_worktree: Path,
    destinations: tuple[str, ...],
    backup_root: Path,
    captured_commit: str,
) -> None:
    for spec_id in destinations:
        destination = destination_worktree / "specs" / spec_id
        if destination.exists():
            shutil.rmtree(destination)
        backup = backup_root / spec_id
        if backup.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(backup, destination, symlinks=True)
    run_git(
        destination_worktree,
        "reset",
        "--quiet",
        captured_commit,
        "--",
        *(f"specs/{spec_id}" for spec_id in destinations),
    )


def _publish_into_worktree(
    project_root: Path,
    destination_worktree: Path,
    *,
    caller_on_default: bool,
    default_branch: str,
    default_commit: str,
    sources: tuple[SpecPublicationSource, ...],
) -> SpecPublishResult:
    spec_ids = tuple(source.spec_id for source in sources)
    paths = tuple(f"specs/{spec_id}" for spec_id in spec_ids)
    _validated_specs_root(destination_worktree, sources)
    _destination_collisions(destination_worktree, sources)
    with tempfile.TemporaryDirectory(prefix="echelon-spec-publish-") as temporary:
        temporary_root = Path(temporary)
        materialized_root = temporary_root / "materialized"
        backup_root = temporary_root / "backup"
        materialized_root.mkdir()
        backup_root.mkdir()
        staged_sources = {
            source.spec_id: _materialize_source(
                project_root, source, materialized_root
            )
            for source in sources
        }
        for spec_id in spec_ids:
            destination = destination_worktree / "specs" / spec_id
            if destination.exists():
                shutil.copytree(
                    destination,
                    backup_root / spec_id,
                    symlinks=True,
                )

        try:
            for spec_id in spec_ids:
                destination = destination_worktree / "specs" / spec_id
                if destination.exists():
                    shutil.rmtree(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(staged_sources[spec_id], destination)

            run_git(destination_worktree, "add", "-A", "--", *paths)
            staged_output = run_git(
                destination_worktree,
                "diff",
                "--cached",
                "--name-only",
                "-z",
                "--",
                *paths,
            ).stdout
            staged_paths = tuple(path for path in staged_output.split("\0") if path)
            allowed = tuple(path + "/" for path in paths)
            unexpected = [
                path
                for path in staged_paths
                if not any(
                    path == root_path or path.startswith(prefix)
                    for root_path, prefix in zip(paths, allowed)
                )
            ]
            if unexpected:
                raise SpecPublishError(
                    "publication staged paths outside the selected specs: "
                    + ", ".join(unexpected)
                )

            changed_ids = {
                spec_id
                for spec_id, path in zip(spec_ids, paths)
                if any(
                    item == path or item.startswith(path + "/")
                    for item in staged_paths
                )
            }
            _assert_default_ref_unchanged(
                project_root, default_branch, default_commit
            )
            if not staged_paths:
                published = tuple(
                    PublishedSpec(
                        spec_id=source.spec_id,
                        source_branch=source.branch,
                        source_commit=source.commit,
                        changed=False,
                    )
                    for source in sources
                )
                return SpecPublishResult(
                    default_branch=default_branch,
                    previous_default_commit=default_commit,
                    default_commit=default_commit,
                    created_commit=False,
                    destination_worktree=destination_worktree,
                    caller_on_default=caller_on_default,
                    published=published,
                )

            message = build_echelon_commit_message(
                f"docs: publish specs {', '.join(spec_ids)}",
                EchelonCommitMetadata(
                    origin="workspace",
                    action="spec-publish",
                    spec_id=",".join(spec_ids),
                ),
            )
            run_git(destination_worktree, "commit", "-m", message, "--", *paths)
            new_commit = run_git(
                destination_worktree, "rev-parse", "HEAD^{commit}"
            ).stdout.strip()
        except Exception as exc:
            try:
                _restore_destinations(
                    destination_worktree,
                    spec_ids,
                    backup_root,
                    default_commit,
                )
                residual = run_git(
                    destination_worktree,
                    "status",
                    "--porcelain",
                ).stdout.strip()
            except Exception as rollback_exc:
                raise SpecPublishError(
                    f"publication failed and rollback failed in "
                    f"{destination_worktree}: {rollback_exc}"
                ) from exc
            if residual:
                raise SpecPublishError(
                    f"publication failed and rollback left changes in "
                    f"{destination_worktree}: {residual}"
                ) from exc
            if isinstance(exc, SpecPublishError):
                raise
            if isinstance(exc, GitHelperError):
                raise SpecPublishError(str(exc)) from exc
            raise

    published = tuple(
        PublishedSpec(
            spec_id=source.spec_id,
            source_branch=source.branch,
            source_commit=source.commit,
            changed=source.spec_id in changed_ids,
        )
        for source in sources
    )
    return SpecPublishResult(
        default_branch=default_branch,
        previous_default_commit=default_commit,
        default_commit=new_commit,
        created_commit=True,
        destination_worktree=destination_worktree,
        caller_on_default=caller_on_default,
        published=published,
    )


def publish_specs(
    project_root: Path,
    *,
    identity: str | None = None,
    publish_all: bool = False,
) -> SpecPublishResult:
    """Publish committed canonical spec snapshots in one local default commit."""

    root = Path(project_root).resolve()
    try:
        default_branch, default_commit = resolve_phase_a_default_branch(
            root,
            _configured_default_branch(root),
        )
        sources = resolve_publication_sources(
            root,
            identity=identity,
            publish_all=publish_all,
            default_branch=default_branch,
        )
        worktrees = _list_worktrees(root)
        _validate_source_worktrees(sources, worktrees)
        cleanup_warnings: list[str] = []
        with _publication_worktree(
            root, default_branch, worktrees, cleanup_warnings
        ) as (
            destination_worktree,
            caller_on_default,
        ):
            result = _publish_into_worktree(
                root,
                destination_worktree,
                caller_on_default=caller_on_default,
                default_branch=default_branch,
                default_commit=default_commit,
                sources=sources,
            )
        return replace(result, warnings=tuple(cleanup_warnings))
    except SpecPublishError:
        raise
    except (GitHelperError, PhaseAGitError) as exc:
        raise SpecPublishError(str(exc)) from exc
