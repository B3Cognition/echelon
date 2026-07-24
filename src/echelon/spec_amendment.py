"""Deterministic branch and worktree setup for pre-build spec amendments."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Sequence


class SpecAmendmentError(RuntimeError):
    """Raised when an amendment cannot be prepared safely."""


class SpecAmendmentConflict(SpecAmendmentError):
    """Raised when the canonical spec branch moved before promotion."""


class SpecAmendmentLocked(SpecAmendmentError):
    """Raised when another amendment process owns this spec's lock."""


_SAFE_SPEC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ControlBaseline:
    """The immutable control-repository baseline for one amendment."""

    spec_id: str
    branch: str
    commit: str
    used_default_branch: bool


@dataclass(frozen=True)
class AmendmentWorktree:
    """A temporary amendment branch checked out outside the caller worktree."""

    path: Path
    branch: str
    baseline: ControlBaseline
    revision: int


@dataclass(frozen=True)
class TargetBaseline:
    """The clean source-repository commit used as amendment context."""

    branch: str
    commit: str
    used_default_branch: bool


@dataclass(frozen=True)
class TargetSnapshot:
    """A detached target worktree used only as clean amendment context."""

    target_id: str
    source_root: Path
    path: Path
    branch: str
    commit: str
    used_default_branch: bool


@dataclass(frozen=True)
class AmendmentPreparation:
    """The deterministic result of creating or previewing an amendment."""

    amendment_id: str
    baseline: ControlBaseline
    revision: int
    dry_run: bool
    worktree: AmendmentWorktree | None
    state_path: Path | None
    target_snapshots: tuple[TargetSnapshot, ...] = ()


@dataclass
class AmendmentLock:
    """Per-spec lease stored in Git's shared directory across worktrees."""

    _lease: object

    @classmethod
    def acquire(
        cls,
        project_root: Path,
        spec_id: str,
        operation_id: str | None = None,
    ) -> "AmendmentLock":
        """Acquire a lock that permits amendments of other specs concurrently."""

        from echelon.spec_lifecycle import SpecLifecycleLock, SpecLifecycleLocked

        _validate_spec_id(spec_id)
        root = Path(project_root).resolve()
        common = _git_common_dir(root)
        owner = operation_id or f"amend-{spec_id}-{os.getpid()}"
        try:
            lease = SpecLifecycleLock._acquire_path(
                common / "echelon" / "locks" / f"amend-{spec_id}.lock",
                owner,
                owner_label="amendment lock owner",
            )
        except SpecLifecycleLocked as exc:
            raise SpecAmendmentLocked(exc.operation_id) from exc
        return cls(_lease=lease)

    def release(self) -> None:
        self._lease.release()  # type: ignore[attr-defined]

    def __enter__(self) -> "AmendmentLock":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def resolve_control_baseline(
    project_root: Path,
    spec_id: str,
    *,
    configured_default_branch: str = "",
) -> ControlBaseline:
    """Resolve a spec branch, or the default branch, without changing checkout."""

    root = Path(project_root).resolve()
    _validate_spec_id(spec_id)
    if _local_branch_exists(root, spec_id):
        branch = spec_id
        used_default_branch = False
    else:
        branch = _resolve_default_branch(root, configured_default_branch)
        used_default_branch = True

    commit = _git(root, "rev-parse", f"refs/heads/{branch}^{{commit}}")
    spec_path = f"specs/{spec_id}/spec.md"
    result = _git_result(root, "cat-file", "-e", f"{commit}:{spec_path}")
    if result.returncode:
        raise SpecAmendmentError(
            f"baseline branch {branch!r} does not contain spec {spec_id!r}"
        )
    return ControlBaseline(
        spec_id=spec_id,
        branch=branch,
        commit=commit,
        used_default_branch=used_default_branch,
    )


def create_amendment_worktree(
    project_root: Path,
    baseline: ControlBaseline,
    *,
    revision: int,
) -> AmendmentWorktree:
    """Create a temporary amendment branch without switching the caller root."""

    if revision < 1:
        raise SpecAmendmentError("amendment revision must be positive")
    root = Path(project_root).resolve()
    _validate_spec_id(baseline.spec_id)
    branch = f"amend/{baseline.spec_id}/{revision:03d}"
    if _local_branch_exists(root, branch):
        raise SpecAmendmentError(f"amendment branch already exists: {branch}")
    path = root / ".echelon" / "runtime" / "amend-worktrees" / baseline.spec_id / f"{revision:03d}"
    if path.exists():
        raise SpecAmendmentError(f"amendment worktree path already exists: {path}")

    result = _git_result(
        root,
        "worktree",
        "add",
        "-b",
        branch,
        str(path),
        baseline.commit,
    )
    if result.returncode:
        raise SpecAmendmentError(
            f"could not create amendment worktree: {result.stderr.strip()}"
        )
    return AmendmentWorktree(
        path=path,
        branch=branch,
        baseline=baseline,
        revision=revision,
    )


def resolve_target_baseline(
    target_root: Path,
    *,
    feature_branch: str,
    configured_default_branch: str = "",
) -> TargetBaseline:
    """Resolve a target feature branch or its default branch without checkout."""

    root = Path(target_root).resolve()
    if _local_branch_exists(root, feature_branch):
        branch = feature_branch
        used_default_branch = False
    else:
        branch = _resolve_default_branch(root, configured_default_branch)
        used_default_branch = True
    return TargetBaseline(
        branch=branch,
        commit=_git(root, "rev-parse", f"refs/heads/{branch}^{{commit}}"),
        used_default_branch=used_default_branch,
    )


def promote_amendment(
    project_root: Path,
    baseline: ControlBaseline,
    amended_commit: str,
) -> None:
    """Advance the canonical branch only if it still equals the baseline SHA."""

    root = Path(project_root).resolve()
    _validate_spec_id(baseline.spec_id)
    _git(root, "rev-parse", f"{amended_commit}^{{commit}}")
    result = _git_result(
        root,
        "update-ref",
        f"refs/heads/{baseline.spec_id}",
        amended_commit,
        baseline.commit,
    )
    if result.returncode:
        raise SpecAmendmentConflict(
            f"canonical spec branch {baseline.spec_id!r} advanced before promotion"
        )


def prepare_amendment(project_root: Path, args: Sequence[str]) -> AmendmentPreparation:
    """Prepare an isolated amendment and snapshot its declared product inputs."""

    root = Path(project_root).resolve()
    spec_id, description, input_values, dry_run = _parse_prepare_args(args)
    if dry_run:
        baseline = resolve_control_baseline(root, spec_id)
        revision = _next_revision(root, spec_id)
        amendment_id = f"{spec_id}/{revision:03d}"
        _preflight_inputs(root, input_values)
        return AmendmentPreparation(
            amendment_id=amendment_id,
            baseline=baseline,
            revision=revision,
            dry_run=True,
            worktree=None,
            state_path=None,
        )

    with AmendmentLock.acquire(root, spec_id):
        return _prepare_amendment_locked(root, spec_id, description, input_values)


def _prepare_amendment_locked(
    root: Path,
    spec_id: str,
    description: str,
    input_values: Sequence[str],
) -> AmendmentPreparation:
    """Create one revision while its per-spec amendment lock is held."""

    baseline = resolve_control_baseline(root, spec_id)
    revision = _next_revision(root, spec_id)
    amendment_id = f"{spec_id}/{revision:03d}"
    from echelon.product_inputs import parse_input_declaration, resolve_product_input_revision

    declarations = [parse_input_declaration(value) for value in input_values]
    worktree = create_amendment_worktree(root, baseline, revision=revision)
    target_snapshots: tuple[TargetSnapshot, ...] = ()
    try:
        target_snapshots = _create_target_snapshots(root, worktree, baseline)
        amendment_dir = (
            worktree.path / "specs" / spec_id / "amendments" / f"{revision:03d}"
        )
        inputs_dir = amendment_dir / "inputs"
        resolution = resolve_product_input_revision(root, inputs_dir, declarations)
        _write_amendment_proposal(
            amendment_dir,
            amendment_id=amendment_id,
            description=description,
            baseline=baseline,
            input_count=len(resolution.declarations),
        )
        state_path = _amendment_state_path(root, spec_id, revision)
        _write_json_atomic(state_path, {
            "schema_version": 1,
            "amendment_id": amendment_id,
            "spec_id": spec_id,
            "description": description,
            "status": "prepared",
            "baseline": {
                "branch": baseline.branch,
                "commit": baseline.commit,
                "used_default_branch": baseline.used_default_branch,
            },
            "worktree": {
                "path": str(worktree.path),
                "branch": worktree.branch,
            },
            "target_snapshots": [
                {
                    "id": item.target_id,
                    "source_root": str(item.source_root),
                    "path": str(item.path),
                    "branch": item.branch,
                    "commit": item.commit,
                    "used_default_branch": item.used_default_branch,
                }
                for item in target_snapshots
            ],
            "product_inputs": resolution.state_payload(root),
        })
    except Exception:
        for snapshot in reversed(target_snapshots):
            _git_result(snapshot.source_root, "worktree", "remove", "--force", str(snapshot.path))
        _git_result(root, "worktree", "remove", "--force", str(worktree.path))
        _git_result(root, "branch", "-D", worktree.branch)
        raise
    return AmendmentPreparation(
        amendment_id=amendment_id,
        baseline=baseline,
        revision=revision,
        dry_run=False,
        worktree=worktree,
        state_path=state_path,
        target_snapshots=target_snapshots,
    )


def load_amendment_state(project_root: Path, amendment_or_spec_id: str) -> dict[str, object]:
    """Load an amendment by exact ID or select the newest revision for a spec."""

    root = Path(project_root).resolve()
    spec_id, revision = _parse_amendment_reference(amendment_or_spec_id)
    amendment_root = _amendment_root(root, spec_id)
    if revision is None:
        revisions = sorted(
            (path for path in amendment_root.iterdir() if path.is_dir() and path.name.isdigit()),
            key=lambda path: int(path.name),
        ) if amendment_root.exists() else []
        if not revisions:
            raise SpecAmendmentError(f"no amendment exists for spec {spec_id!r}")
        state_path = revisions[-1] / "state.json"
    else:
        state_path = amendment_root / f"{revision:03d}" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecAmendmentError(f"could not read amendment state: {state_path}") from exc
    if not isinstance(state, dict):
        raise SpecAmendmentError(f"amendment state is not an object: {state_path}")
    return state


def abandon_amendment(project_root: Path, amendment_or_spec_id: str) -> dict[str, object]:
    """Record that an amendment was declined without touching its spec branch."""

    root = Path(project_root).resolve()
    state = load_amendment_state(root, amendment_or_spec_id)
    amendment_id = str(state.get("amendment_id") or "")
    spec_id, revision = _parse_amendment_reference(amendment_id)
    if revision is None:
        raise SpecAmendmentError("amendment state has an invalid amendment_id")
    if str(state.get("status") or "") not in {"prepared", "awaiting_approval"}:
        raise SpecAmendmentError(
            f"cannot abandon amendment in state {state.get('status')!r}"
        )
    state["status"] = "abandoned"
    _write_json_atomic(_amendment_state_path(root, spec_id, revision), state)
    return state


def _resolve_default_branch(project_root: Path, configured_default_branch: str) -> str:
    configured = configured_default_branch.strip()
    if configured:
        if _local_branch_exists(project_root, configured):
            return configured
        raise SpecAmendmentError(
            f"configured default branch does not exist locally: {configured!r}"
        )

    remote_head = _git_result(
        project_root,
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
    )
    if not remote_head.returncode:
        remote_branch = remote_head.stdout.strip().partition("/")[2]
        if remote_branch and _local_branch_exists(project_root, remote_branch):
            return remote_branch

    for candidate in ("main", "master"):
        if _local_branch_exists(project_root, candidate):
            return candidate
    raise SpecAmendmentError("could not determine a default branch")


def _parse_prepare_args(args: Sequence[str]) -> tuple[str, str, list[str], bool]:
    if len(args) < 2:
        raise SpecAmendmentError("amendment requires a spec id and change description")
    spec_id = str(args[0]).strip()
    description = str(args[1]).strip()
    if not description:
        raise SpecAmendmentError("amendment change description must not be empty")
    _validate_spec_id(spec_id)
    input_values: list[str] = []
    dry_run = False
    index = 2
    while index < len(args):
        value = str(args[index])
        if value == "--dry-run":
            dry_run = True
            index += 1
        elif value == "--input":
            if index + 1 >= len(args):
                raise SpecAmendmentError("--input requires requirement:<path> or reference:<path>")
            input_values.append(str(args[index + 1]))
            index += 2
        elif value.startswith("--input="):
            input_values.append(value.split("=", 1)[1])
            index += 1
        else:
            raise SpecAmendmentError(f"unknown amendment option: {value}")
    return spec_id, description, input_values, dry_run


def _parse_amendment_reference(value: str) -> tuple[str, int | None]:
    raw = value.strip()
    spec_id, separator, revision_text = raw.rpartition("/")
    if separator and revision_text.isdigit():
        _validate_spec_id(spec_id)
        return spec_id, int(revision_text)
    _validate_spec_id(raw)
    return raw, None


def _preflight_inputs(project_root: Path, input_values: Sequence[str]) -> None:
    from echelon.product_inputs import ProductInputError, parse_input_declaration

    for value in input_values:
        declaration = parse_input_declaration(value)
        if "://" in declaration.location:
            continue
        path = Path(declaration.location).expanduser()
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            raise ProductInputError(f"input path does not exist: {declaration.location}")


def _create_target_snapshots(
    project_root: Path,
    worktree: AmendmentWorktree,
    baseline: ControlBaseline,
) -> tuple[TargetSnapshot, ...]:
    from harness.spec_frontmatter import read_target_entries

    spec_dir = worktree.path / "specs" / baseline.spec_id
    snapshots: list[TargetSnapshot] = []
    try:
        for entry in read_target_entries(spec_dir):
            raw_path = str(entry.get("path") or "").strip()
            if not raw_path:
                continue
            source_root = (project_root / raw_path).resolve()
            try:
                source_root.relative_to(project_root)
            except ValueError as exc:
                raise SpecAmendmentError(f"target path escapes project root: {raw_path!r}") from exc
            if not source_root.is_dir():
                raise SpecAmendmentError(f"target repository does not exist: {raw_path}")
            feature_branch = str(entry.get("branch") or baseline.spec_id).strip()
            target_baseline = resolve_target_baseline(
                source_root,
                feature_branch=feature_branch,
            )
            target_path = worktree.path / raw_path
            if target_path.exists():
                raise SpecAmendmentError(f"target snapshot path already exists: {target_path}")
            result = _git_result(
                source_root,
                "worktree",
                "add",
                "--detach",
                str(target_path),
                target_baseline.commit,
            )
            if result.returncode:
                raise SpecAmendmentError(
                    f"could not create target snapshot for {raw_path}: {result.stderr.strip()}"
                )
            snapshots.append(TargetSnapshot(
                target_id=str(entry.get("id") or raw_path),
                source_root=source_root,
                path=target_path,
                branch=target_baseline.branch,
                commit=target_baseline.commit,
                used_default_branch=target_baseline.used_default_branch,
            ))
    except Exception:
        _remove_target_snapshots(snapshots)
        raise
    return tuple(snapshots)


def _remove_target_snapshots(snapshots: Sequence[TargetSnapshot]) -> None:
    """Best-effort cleanup for target worktrees created by this invocation."""

    for snapshot in reversed(snapshots):
        _git_result(snapshot.source_root, "worktree", "remove", "--force", str(snapshot.path))


def _next_revision(project_root: Path, spec_id: str) -> int:
    root = _amendment_root(project_root, spec_id)
    revisions = [
        int(path.name)
        for path in root.iterdir()
        if path.is_dir() and path.name.isdigit()
    ] if root.exists() else []
    return max(revisions, default=0) + 1


def _write_amendment_proposal(
    amendment_dir: Path,
    *,
    amendment_id: str,
    description: str,
    baseline: ControlBaseline,
    input_count: int,
) -> None:
    """Write deterministic hand-off artifacts before any model workflow runs."""

    amendment_dir.mkdir(parents=True, exist_ok=True)
    (amendment_dir / "change-request.md").write_text(
        "# Change request\n\n"
        f"- Amendment: `{amendment_id}`\n"
        f"- Baseline branch: `{baseline.branch}`\n"
        f"- Baseline commit: `{baseline.commit}`\n\n"
        "## Requested change\n\n"
        f"{description}\n",
        encoding="utf-8",
    )
    (amendment_dir / "impact.md").write_text(
        "# Amendment impact\n\n"
        "Status: pending impact analysis and explicit approval.\n\n"
        f"New input declarations: {input_count}\n\n"
        "No canonical spec, plan, or task artifact has been changed.\n",
        encoding="utf-8",
    )


def _amendment_state_path(project_root: Path, spec_id: str, revision: int) -> Path:
    return _amendment_root(project_root, spec_id) / f"{revision:03d}" / "state.json"


def _amendment_root(project_root: Path, spec_id: str) -> Path:
    return _git_common_dir(project_root) / "echelon" / "amendments" / spec_id


def _git_common_dir(project_root: Path) -> Path:
    common = Path(_git(project_root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = project_root / common
    return common.resolve()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=f".{path.name}-",
        suffix=".tmp",
        encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _local_branch_exists(project_root: Path, branch: str) -> bool:
    return not _git_result(
        project_root,
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{branch}",
    ).returncode


def _validate_spec_id(spec_id: str) -> None:
    if not _SAFE_SPEC_ID.fullmatch(spec_id):
        raise SpecAmendmentError(f"unsafe spec id: {spec_id!r}")


def _git(project_root: Path, *args: str) -> str:
    result = _git_result(project_root, *args)
    if result.returncode:
        raise SpecAmendmentError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _git_result(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
