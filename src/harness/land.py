"""Land — idempotent spec completion: merge PR, delete branch, clean worktrees, mark done."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import logging
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterator, Optional

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from echelon.ui import banner as _banner

from harness.errors import GitOpsError
from harness.gitops import _run_git
from harness.paths import build_dir, current_build_marker, runs_dir
from harness.spec_frontmatter import find_spec_dir, read_frontmatter, read_targets, write_status
from kernel.fulfillment import (
    blocking_statuses,
    fulfillment_report_is_current,
    fulfillment_has_blocking_gaps,
    latest_fulfillment_report,
    read_fulfillment_metadata,
    validate_deferred_scope_rows,
)
from kernel.spec_identity import spec_identity_aliases
from harness.deferred_scope import active_entries, ledger_path

logger = logging.getLogger(__name__)

_TEXT_SNAPSHOT_SUFFIXES = {".md", ".json", ".yml", ".yaml"}
_SPEC_INPUT_FILENAMES = {
    "spec.md",
    "plan.md",
    "tasks.md",
    "coverage-map.md",
    "user-clarifications.md",
}
_IMPLEMENTATION_INPUT_DIRS = (
    "src",
    "app",
    "apps",
    "lib",
    "packages",
    "tests",
    "test",
)
_IMPLEMENTATION_INPUT_FILES = {
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
}
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---(?:\n|$)", re.DOTALL)
_LAND_GENERATED_DRIFT_EXACT = {
    "docs/perf/perf-metrics.json",
    "docs/perf/perf-metrics-pty.json",
}


@dataclass(frozen=True)
class LandOptions:
    autoresolve: bool = True
    prepare_only: bool = False
    continue_existing: bool = False
    strategy: str = "merge"
    allow_fulfillment_gaps: bool = False


@dataclass(frozen=True)
class LandPrepareResult:
    status: str
    branch: str
    prepared_commit: str | None = None
    pushed: bool = False
    conflicted_files: list[str] = field(default_factory=list)
    autoresolved_files: list[str] = field(default_factory=list)
    message: str = ""


def prepare_feature_branch(
    *,
    spec_id: str,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> LandPrepareResult:
    """Prepare a feature branch by bringing it up to date with the default branch."""
    if options.strategy != "merge":
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message=f"unsupported land strategy: {options.strategy}",
        )

    if options.continue_existing:
        return _continue_feature_branch_preparation(
            feature_branch=feature_branch,
            project_dir=project_dir,
            gitops=gitops,
            options=options,
        )

    dirty = _run_git(
        ["status", "--porcelain", "--untracked-files=no"],
        cwd=str(project_dir),
        check=False,
    )
    if dirty.stdout.strip():
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message="working tree has tracked changes",
        )

    default_branch = gitops.get_default_branch()
    _run_git(["checkout", feature_branch], cwd=str(project_dir))

    result = _run_git(
        [
            "merge",
            "--no-ff",
            default_branch,
            "-m",
            build_echelon_commit_message(
                f"Merge {default_branch} into {feature_branch}",
                EchelonCommitMetadata(
                    origin="delivery",
                    action="land-prepare-merge",
                    spec_id=feature_branch,
                ),
            ),
        ],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode == 0:
        commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
        pushed = _push_prepared_branch_if_remote(gitops, project_dir, feature_branch)
        return LandPrepareResult(
            status="prepared",
            branch=feature_branch,
            prepared_commit=commit,
            pushed=pushed,
        )

    conflicted = _list_unmerged_files(project_dir)
    autoresolved: list[str] = []
    if options.autoresolve:
        autoresolved = _autoresolve_known_land_conflicts(project_dir, conflicted)
        conflicted = _list_unmerged_files(project_dir)
        if not conflicted:
            _run_git(["commit", "--no-edit"], cwd=str(project_dir))
            commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
            pushed = _push_prepared_branch_if_remote(gitops, project_dir, feature_branch)
            return LandPrepareResult(
                status="prepared",
                branch=feature_branch,
                prepared_commit=commit,
                pushed=pushed,
                autoresolved_files=autoresolved,
            )

    return LandPrepareResult(
        status="blocked",
        branch=feature_branch,
        conflicted_files=conflicted,
        autoresolved_files=autoresolved,
        message="merge conflicts remain",
    )


def _continue_feature_branch_preparation(
    *,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> LandPrepareResult:
    current_branch = _run_git(
        ["branch", "--show-current"],
        cwd=str(project_dir),
        check=False,
    ).stdout.strip()
    if current_branch != feature_branch:
        _run_git(["checkout", feature_branch], cwd=str(project_dir))

    conflicted = _list_unmerged_files(project_dir)
    autoresolved: list[str] = []
    if conflicted and options.autoresolve:
        autoresolved = _autoresolve_known_land_conflicts(project_dir, conflicted)
        conflicted = _list_unmerged_files(project_dir)
    if conflicted:
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            conflicted_files=conflicted,
            autoresolved_files=autoresolved,
            message="conflicts remain",
        )

    merge_head = _run_git(
        ["rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=str(project_dir),
        check=False,
    )
    if merge_head.returncode != 0:
        dirty = _tracked_dirty_files(project_dir)
        if dirty:
            generated, unsafe = _discard_known_generated_land_drift(project_dir)
            if generated and not unsafe:
                dirty = _tracked_dirty_files(project_dir)
        if not dirty and _branch_contains_default_branch(project_dir, gitops):
            commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
            pushed = _push_prepared_branch_if_remote(gitops, project_dir, feature_branch)
            return LandPrepareResult(
                status="prepared",
                branch=feature_branch,
                prepared_commit=commit,
                pushed=pushed,
                message="feature branch is already prepared",
            )
        if dirty:
            return LandPrepareResult(
                status="blocked",
                branch=feature_branch,
                message="working tree has tracked changes: " + ", ".join(dirty),
            )
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message="no merge in progress to continue",
        )

    _run_git(["commit", "--no-edit"], cwd=str(project_dir))
    commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
    pushed = _push_prepared_branch_if_remote(gitops, project_dir, feature_branch)
    return LandPrepareResult(
        status="prepared",
        branch=feature_branch,
        prepared_commit=commit,
        pushed=pushed,
        autoresolved_files=autoresolved,
    )


def _push_prepared_branch_if_remote(gitops: Any, project_dir: Path, feature_branch: str) -> bool:
    """Push prepared branches only when the project has a non-local origin.

    Local Echelon sandboxes and toy projects frequently have no remote. Land must
    still be able to finish there because the important invariant is the local
    default-branch merge, not publishing an unavailable feature branch.
    """
    origin_url = _origin_remote_url(project_dir)
    if not origin_url:
        logger.info("Skipping prepared branch push: no origin remote")
        return False
    if _is_local_remote_url(project_dir, origin_url):
        logger.info("Skipping prepared branch push: origin is local (%s)", origin_url)
        return False
    gitops.push_prepared_branch(str(project_dir), feature_branch, force_with_lease=False)
    return True


def _push_landed_default_branch_if_remote(
    gitops: Any,
    project_dir: Path,
    default_branch: str,
) -> bool:
    origin_url = _origin_remote_url(project_dir)
    if not origin_url:
        logger.info("Skipping landed default branch push: no origin remote")
        return True
    if _is_local_remote_url(project_dir, origin_url):
        logger.info("Skipping landed default branch push: origin is local (%s)", origin_url)
        return True
    return bool(gitops.push_landed_default_branch(str(project_dir), default_branch))


def _origin_remote_url(project_dir: Path) -> str | None:
    result = _run_git(
        ["remote", "get-url", "origin"],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def _is_local_remote_url(project_dir: Path, url: str) -> bool:
    if url.startswith("file://"):
        return True
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
        return False
    if re.match(r"^[^@/:]+@[^:]+:.+", url):
        return False
    remote_path = Path(url).expanduser()
    if not remote_path.is_absolute():
        remote_path = project_dir / remote_path
    return True


def _branch_contains_default_branch(project_dir: Path, gitops: Any) -> bool:
    default_branch = gitops.get_default_branch()
    result = _run_git(
        ["merge-base", "--is-ancestor", default_branch, "HEAD"],
        cwd=str(project_dir),
        check=False,
    )
    return result.returncode == 0


def _list_unmerged_files(project_dir: Path) -> list[str]:
    result = _run_git(
        ["diff", "--name-only", "--diff-filter=U"],
        cwd=str(project_dir),
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _autoresolve_known_land_conflicts(project_dir: Path, conflicted: list[str]) -> list[str]:
    """Resolve conflicts whose desired landing semantics are deterministic.

    This is deliberately narrow. It only handles generated/runtime state that
    Echelon owns, plus add/add .gitignore union conflicts. Source or spec
    artifact conflicts still block for human review.
    """
    unresolved = set(conflicted)
    autoresolved: list[str] = []

    if ".gitignore" in unresolved and _autoresolve_gitignore(project_dir):
        autoresolved.append(".gitignore")
        unresolved.discard(".gitignore")

    return autoresolved


def _autoresolve_gitignore(project_dir: Path) -> bool:
    base = _run_git(["show", ":1:.gitignore"], cwd=str(project_dir), check=False)
    if base.returncode == 0:
        return False

    ours = _run_git(["show", ":2:.gitignore"], cwd=str(project_dir), check=False)
    theirs = _run_git(["show", ":3:.gitignore"], cwd=str(project_dir), check=False)
    if ours.returncode != 0 or theirs.returncode != 0:
        return False

    lines: list[str] = []
    seen: set[str] = set()
    for content in (ours.stdout, theirs.stdout):
        for raw_line in content.splitlines():
            line = raw_line.rstrip()
            key = line.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(line)

    (project_dir / ".gitignore").write_text("\n".join(lines) + "\n", encoding="utf-8")
    add = _run_git(["add", ".gitignore"], cwd=str(project_dir), check=False)
    return add.returncode == 0


def find_pr_url(spec_id: str, state_dir: Path) -> Optional[str]:
    """Return the first PR URL found in any strategy state file for spec_id.

    When state_dir is given, scans it directly.
    When state_dir is the runs/ root (no spec_id subdir), delegates to
    _find_pr_url_all_builds which scans all build dirs.
    """
    # Direct scan: state files are at state_dir/*.json (no spec_id subdir)
    if state_dir.exists():
        for state_file in sorted(state_dir.glob("*.json")):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if data.get("pr_url") and _spec_id_matches(
                    str(data.get("spec_id") or ""),
                    spec_id,
                ):
                    return data["pr_url"]
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _find_pr_url_all_builds(spec_id: str, harness_root: Path) -> Optional[str]:
    """Scan all runs/build-*/state/ directories for a PR URL matching spec_id."""
    rd = runs_dir(harness_root)
    if not rd.exists():
        return None
    for build in sorted(rd.glob("build-*/"), reverse=True):
        state_dir = build / "state"
        url = find_pr_url(spec_id, state_dir)
        if url:
            return url
    return None


def resolve_land_repo(project_dir: Path, spec_dir: Path) -> Path:
    """Return the repo where git land operations should run for a spec."""
    targets = read_targets(spec_dir)
    if not targets:
        return project_dir.resolve()
    if len(targets) != 1:
        raise RuntimeError("land requires exactly one target repo for normal specs")
    target_rel = str(targets[0])
    target = (project_dir / target_rel).resolve()
    if not target.exists():
        raise RuntimeError(f"target repo not found: {target_rel}")
    return target


def _find_latest_harness_branch(spec_id: str, project_dir: Path) -> str | None:
    """Return the unambiguous newest legacy harness iteration for a spec.

    Legacy delivery runs commit to ``harness/<spec>/<strategy>/iter-N`` rather
    than a conventional feature branch.  Landing must either merge that branch
    or stop; treating it as absent would silently discard verified work.
    """
    candidates: list[tuple[int, str]] = []
    for alias in spec_identity_aliases(spec_id):
        result = _run_git(
            ["branch", "--list", f"harness/{alias}/*/iter-*"],
            cwd=str(project_dir),
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("could not list legacy harness branches")

        pattern = re.compile(
            rf"^harness/{re.escape(alias)}/[^/]+/iter-(?P<iteration>\d+)$"
        )
        for line in result.stdout.splitlines():
            branch = line.strip()
            match = pattern.fullmatch(branch)
            if match:
                candidates.append((int(match.group("iteration")), branch))
        if candidates:
            break

    if not candidates:
        return None

    latest_iteration = max(iteration for iteration, _ in candidates)
    latest = sorted(
        branch for iteration, branch in candidates if iteration == latest_iteration
    )
    if len(latest) != 1:
        raise RuntimeError(
            "ambiguous legacy harness branches at iteration "
            f"{latest_iteration}: {', '.join(latest)}"
        )

    logger.info("Found latest legacy harness branch for spec %s: %s", spec_id, latest[0])
    return latest[0]


def _validate_harness_branch_provenance(
    project_dir: Path,
    spec_dir: Path | None,
    branch: str,
    *,
    required: bool,
) -> None:
    """Require recorded fulfillment provenance to belong to a harness branch."""
    if spec_dir is None:
        if required:
            raise RuntimeError("current build has no canonical spec directory")
        return

    try:
        report = latest_fulfillment_report(spec_dir)
        metadata = read_fulfillment_metadata(report) if report is not None else {}
    except OSError as exc:
        raise RuntimeError("could not read fulfillment report metadata") from exc
    verified_commit = metadata.get("verified_commit")
    if not isinstance(verified_commit, str) or not verified_commit:
        if required:
            raise RuntimeError("current build lacks a verified fulfillment commit")
        return

    ancestry = _run_git(
        ["merge-base", "--is-ancestor", verified_commit, f"refs/heads/{branch}"],
        cwd=str(project_dir),
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("verified fulfillment commit is not on the selected harness branch")


def _find_current_build_harness_branch(
    spec_id: str,
    project_dir: Path,
    harness_root: Path,
    spec_dir: Path | None,
) -> str | None:
    """Return the current build's verified legacy harness branch, if present.

    A current-build marker is positive provenance for one converged strategy.
    Once present, incomplete or ambiguous provenance must block landing instead
    of falling back to the numerically latest legacy branch.
    """
    markers = [
        current_build_marker(harness_root, alias)
        for alias in spec_identity_aliases(spec_id)
        if current_build_marker(harness_root, alias).exists()
    ]
    if not markers:
        return None
    if len(markers) != 1:
        raise RuntimeError("multiple current-build markers match the spec")

    try:
        build_id = markers[0].read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("could not read current-build marker") from exc
    if not build_id:
        raise RuntimeError("current-build marker lacks a build identity")

    candidates: list[dict[str, Any]] = []
    state_root = build_dir(harness_root, build_id) / "state"
    try:
        state_files = sorted(state_root.glob("*.json"))
    except OSError as exc:
        raise RuntimeError("could not read current-build state") from exc
    for state_file in state_files:
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("current-build state is unreadable or invalid") from exc
        if not isinstance(state, dict):
            raise RuntimeError("current-build state is unreadable or invalid")
        if state.get("status") == "converged" and _spec_id_matches(
            str(state.get("spec_id") or ""), spec_id
        ):
            candidates.append(state)
    if len(candidates) != 1:
        raise RuntimeError("current build must contain exactly one converged strategy")

    state = candidates[0]
    strategy = str(state.get("strategy_id") or "")
    iteration = state.get("outer_iter")
    if not strategy or not isinstance(iteration, int) or iteration < 0:
        raise RuntimeError("converged current build lacks branch identity")

    branches: list[str] = []
    for alias in spec_identity_aliases(spec_id):
        branch = f"harness/{alias}/{strategy}/iter-{iteration}"
        branch_ref = f"refs/heads/{branch}"
        exists = _run_git(
            ["rev-parse", "--verify", "--quiet", branch_ref],
            cwd=str(project_dir),
            check=False,
        )
        if exists.returncode == 0:
            branches.append(branch)
    if len(branches) != 1:
        raise RuntimeError("current build must resolve exactly one local harness branch")

    branch = branches[0]
    _validate_harness_branch_provenance(
        project_dir,
        spec_dir,
        branch,
        required=True,
    )
    return branch


def _finish_branchless_landing(
    spec_id: str,
    *,
    wrapper_project_dir: Path,
    project_dir: Path,
    spec_dir: Path | None,
    gitops: Any,
    options: LandOptions,
    harness_root: Path | None = None,
) -> bool:
    """Finish an already-merged landing only when positive evidence proves it."""
    status = read_frontmatter(spec_dir).get("status") if spec_dir is not None else None
    report = latest_fulfillment_report(spec_dir) if spec_dir is not None else None
    metadata = read_fulfillment_metadata(report) if report is not None else {}
    verified_commit = metadata.get("verified_commit")

    if status == "landed" and not verified_commit:
        gitops.ensure_on_default_branch(str(project_dir))
        _post_land_topology_reconciliation(
            spec_id,
            wrapper_project_dir,
            project_dir,
        )
        logger.info("land: %s is already landed (legacy status evidence)", spec_id)
        return True

    problem: str
    if spec_dir is None:
        problem = (
            f"spec directory for {spec_id} was not found from orchestration root "
            f"{wrapper_project_dir.resolve()}"
        )
    elif status not in {"ready_to_land", "landed"}:
        problem = f"spec status is {status or '(missing)'}, not ready_to_land or landed"
    elif not isinstance(verified_commit, str) or not verified_commit:
        problem = "no verified commit is recorded in the fulfillment report"
    else:
        default_branch = _land_default_branch(gitops)
        if not _check_ready_before_land(
            spec_id,
            wrapper_project_dir,
            options,
            fulfillment_project_dir=project_dir,
            fulfillment_ref=default_branch,
        ):
            return False

        from harness.fulfillment_runner import (
            _implementation_input_hash,
            _spec_input_hash,
        )

        recorded_spec_hash = metadata.get("spec_input_hash")
        current_spec_hash = _spec_input_hash(spec_dir)
        recorded_implementation_hash = metadata.get("implementation_input_hash")
        if status == "ready_to_land" and (
            not isinstance(recorded_spec_hash, str)
            or not recorded_spec_hash
            or not isinstance(recorded_implementation_hash, str)
            or not recorded_implementation_hash
        ):
            _banner(
                "LAND - BRANCH NOT LANDED",
                [
                    ("spec", spec_id),
                    ("problem", "fulfillment report is missing input hashes"),
                    ("next step", f"rerun: echelon spec verify {spec_id}"),
                ],
                subtitle="Branchless status advancement requires complete provenance.",
            )
            return False
        if recorded_spec_hash and recorded_spec_hash != current_spec_hash:
            problem = "fulfillment report spec input hash is stale"
            _banner(
                "LAND - BRANCH NOT LANDED",
                [
                    ("spec", spec_id),
                    ("problem", problem),
                    ("next step", f"rerun: echelon spec verify {spec_id}"),
                ],
                subtitle="Branchless landing requires current fulfillment inputs.",
            )
            return False
        if (
            recorded_implementation_hash
            and recorded_implementation_hash != _implementation_input_hash(project_dir)
        ):
            problem = "fulfillment report implementation input hash is stale"
            _banner(
                "LAND - BRANCH NOT LANDED",
                [
                    ("spec", spec_id),
                    ("problem", problem),
                    ("next step", f"rerun: echelon spec verify {spec_id}"),
                ],
                subtitle="Branchless landing requires current fulfillment inputs.",
            )
            return False
        ancestor = _run_git(
            ["merge-base", "--is-ancestor", verified_commit, default_branch],
            cwd=str(project_dir),
            check=False,
        )
        if ancestor.returncode == 0:
            _cleanup_worktrees(
                spec_id,
                harness_root if harness_root is not None else wrapper_project_dir,
                gitops,
            )
            for alias in spec_identity_aliases(spec_id):
                _delete_harness_branches(alias, project_dir)
            if spec_dir is not None and status != "landed":
                write_status(spec_dir, "landed")
            _clear_landed_active_authoring_pointer(
                wrapper_project_dir,
                spec_id,
                "",
            )
            gitops.ensure_on_default_branch(str(project_dir))
            _post_land_topology_reconciliation(
                spec_id,
                wrapper_project_dir,
                project_dir,
            )
            logger.info(
                "land: %s has no feature branch, but verified commit %s is on %s",
                spec_id,
                verified_commit,
                default_branch,
            )
            return True
        problem = (
            f"verified commit {verified_commit} is not an ancestor of "
            f"the default branch {default_branch}"
        )

    _banner(
        "LAND - BRANCH NOT LANDED",
        [
            ("spec", spec_id),
            ("problem", problem),
            ("next step", "recover or merge the verified branch, then re-run land"),
        ],
        subtitle="Branch absence is not proof that verified work reached the default branch.",
    )
    return False


def _block_different_active_authoring_spec(
    project_root: Path,
    feature_branch: str,
    spec_id: str,
) -> bool:
    """Refuse landing before it changes a checkout owned by another Phase A run."""
    from echelon.spec_lifecycle import (
        SpecLifecycleError,
        SpecRunNotFound,
        resolve_active_spec_run,
    )

    try:
        active = resolve_active_spec_run(project_root)
    except SpecRunNotFound as exc:
        if not (project_root / "runs" / ".current").exists():
            return False
        _banner(
            "LAND — ACTIVE AUTHORING STATE BLOCKED",
            [
                ("problem", str(exc)),
                ("next step", "repair the active spec pointer before landing"),
            ],
            subtitle="Landing will not guess which Phase A checkout it may disturb.",
        )
        return True
    except SpecLifecycleError as exc:
        _banner(
            "LAND — ACTIVE AUTHORING STATE BLOCKED",
            [
                ("problem", str(exc)),
                ("next step", "repair the active spec state before landing"),
            ],
            subtitle="Landing will not guess which Phase A checkout it may disturb.",
        )
        return True

    if active.feature_branch == feature_branch:
        return False

    _banner(
        "LAND — ACTIVE AUTHORING SPEC",
        [
            ("active spec", active.spec_id),
            ("active branch", active.feature_branch),
            ("requested spec", spec_id),
            ("requested branch", feature_branch),
            (
                "next step",
                f"checkpoint/clean the active spec, then echelon spec switch {spec_id}",
            ),
        ],
        subtitle="Landing is refusing to disturb a different active Phase A checkout.",
    )
    return True


def land(
    spec_id: str,
    *,
    project_dir: Path,
    gitops: Any,
    state_dir: Optional[Path] = None,
    options: Optional[LandOptions] = None,
    harness_root: Path | None = None,
) -> bool:
    """Idempotent: merge PR, delete remote branch, clean worktrees, mark spec landed.

    ``project_dir`` owns canonical specs and lifecycle state. ``harness_root``
    owns delivery run state and worktrees, and defaults to ``project_dir`` for
    backwards-compatible single-repository callers. Target Git operations use
    the resolved spec target and the supplied ``gitops`` instance.

    Returns True if spec is now in landed state.
    Returns False only when PR merge is blocked — caller must retry or merge manually.
    """
    options = options or LandOptions()
    wrapper_project_dir = project_dir.resolve()
    project_dir = wrapper_project_dir
    runtime_root = (
        Path(harness_root).resolve()
        if harness_root is not None
        else wrapper_project_dir
    )
    spec_dir = find_spec_dir(spec_id, wrapper_project_dir)
    if spec_dir is not None:
        spec_id = spec_dir.name
        project_dir = resolve_land_repo(wrapper_project_dir, spec_dir)

    try:
        feature_branch = gitops.find_feature_branch(spec_id)
    except GitOpsError as exc:
        logger.error("land: could not resolve feature branch for %s: %s", spec_id, exc)
        _banner(
            "LAND — BRANCH RESOLUTION BLOCKED",
            [
                ("spec", spec_id),
                ("problem", str(exc)),
                (
                    "next step",
                    "repair repository or mirror access, then re-run land",
                ),
            ],
            subtitle="Echelon will not treat a branch lookup failure as an already-landed spec.",
        )
        return False

    if feature_branch is None:
        try:
            feature_branch = _find_current_build_harness_branch(
                spec_id,
                project_dir,
                runtime_root,
                spec_dir,
            )
            if feature_branch is None:
                feature_branch = _find_latest_harness_branch(spec_id, project_dir)
                if feature_branch is not None:
                    _validate_harness_branch_provenance(
                        project_dir,
                        spec_dir,
                        feature_branch,
                        required=False,
                    )
        except RuntimeError as exc:
            logger.error("land: could not resolve legacy harness branch for %s: %s", spec_id, exc)
            _banner(
                "LAND — BRANCH RESOLUTION BLOCKED",
                [
                    ("spec", spec_id),
                    ("problem", str(exc)),
                    ("next step", "resolve the legacy harness branch, then re-run land"),
                ],
                subtitle="Echelon will not mark a spec landed until its verified branch is resolved.",
            )
            return False

    if feature_branch is None:
        return _finish_branchless_landing(
            spec_id,
            wrapper_project_dir=wrapper_project_dir,
            project_dir=project_dir,
            spec_dir=spec_dir,
            gitops=gitops,
            options=options,
            harness_root=runtime_root,
        )

    if project_dir == wrapper_project_dir and _block_different_active_authoring_spec(
        wrapper_project_dir, feature_branch, spec_id
    ):
        return False

    if state_dir is not None:
        pr_url = find_pr_url(spec_id, state_dir)
    else:
        pr_url = _find_pr_url_all_builds(spec_id, runtime_root)

    readiness_ref = feature_branch if project_dir == wrapper_project_dir else None
    fulfillment_project_dir = None if project_dir == wrapper_project_dir else project_dir
    fulfillment_ref = feature_branch if project_dir != wrapper_project_dir else None
    if not options.prepare_only and not _check_ready_before_land(
        spec_id,
        wrapper_project_dir,
        options,
        ref=readiness_ref,
        fulfillment_project_dir=fulfillment_project_dir,
        fulfillment_ref=fulfillment_ref,
    ):
        return False

    if options.prepare_only:
        prepare_result = _prepare_for_land(
            spec_id=spec_id,
            feature_branch=feature_branch,
            project_dir=project_dir,
            gitops=gitops,
            options=options,
        )
        if prepare_result is None:
            return False
        _banner(
            "LAND — PREPARED",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                ("commit", prepare_result.prepared_commit or "(unchanged)"),
            ],
            subtitle="Feature branch is prepared; landing was not attempted.",
        )
        return True

    if pr_url:
        if not _verify_before_land(spec_id, project_dir, gitops, options):
            return False
        merged = gitops.merge_pr(pr_url)
        if merged:
            return _finish_landing(
                spec_id,
                feature_branch,
                project_dir,
                gitops,
                spec_project_dir=wrapper_project_dir,
                harness_root=runtime_root,
            )
        prepare_result = _prepare_for_land(
            spec_id=spec_id,
            feature_branch=feature_branch,
            project_dir=project_dir,
            gitops=gitops,
            options=options,
        )
        if prepare_result is None:
            return False
        if not _verify_before_land(spec_id, project_dir, gitops, options):
            return False
        _banner(
            "LAND — ACTION NEEDED",
            [
                ("spec", spec_id),
                ("problem", "PR merge blocked by branch protection, checks, or conflicts"),
                ("PR", pr_url),
                ("next step", f"re-run after checks/branch protection clear: echelon delivery land {spec_id}"),
            ],
            subtitle="Feature branch was prepared, but Echelon will not bypass the PR.",
        )
        return False

    if _default_branch_already_contains_feature(project_dir, gitops, feature_branch):
        if not _checkout_default_for_landing_cleanup(spec_id, project_dir, gitops):
            return False
        return _finish_landing(
            spec_id,
            feature_branch,
            project_dir,
            gitops,
            spec_project_dir=wrapper_project_dir,
            harness_root=runtime_root,
        )

    prepare_result = _prepare_for_land(
        spec_id=spec_id,
        feature_branch=feature_branch,
        project_dir=project_dir,
        gitops=gitops,
        options=options,
    )
    if prepare_result is None:
        return False
    if not _verify_before_land(spec_id, project_dir, gitops, options):
        return False
    if not _clean_generated_drift_before_direct_merge(spec_id, project_dir):
        return False

    # No PR URL — gh/glab not configured. Merge directly into the default branch.
    merged = gitops.merge_branch_into_default(feature_branch, str(project_dir))
    if not merged:
        _banner(
            "LAND — MERGE FAILED",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                ("problem", "direct merge into default branch failed (conflicts?)"),
                ("next step", f"git merge --no-ff {feature_branch}  # resolve conflicts, then re-run"),
            ],
            subtitle="Resolve conflicts manually, then re-run: echelon delivery land " + spec_id,
        )
        return False

    default_branch = _land_default_branch(gitops)
    if not _push_landed_default_branch_if_remote(gitops, project_dir, default_branch):
        _banner(
            "LAND — DEFAULT PUSH FAILED",
            [
                ("spec", spec_id),
                ("branch", default_branch),
                ("problem", "local merge succeeded, but pushing the default branch failed"),
                ("next step", f"git push origin {default_branch}  # then re-run: echelon delivery land {spec_id}"),
            ],
            subtitle="Echelon stopped before cleanup so the feature branch remains recoverable.",
        )
        return False

    return _finish_landing(
        spec_id,
        feature_branch,
        project_dir,
        gitops,
        spec_project_dir=wrapper_project_dir,
        harness_root=runtime_root,
    )


def _clean_generated_drift_before_direct_merge(spec_id: str, project_dir: Path) -> bool:
    """Discard known generated verification drift before checking out default.

    `land` verifies on the prepared feature branch, then directly checks out the
    default branch when no PR host is configured. Some project verify commands
    update tracked generated metrics. Those edits are not user source changes and
    should not make the final default-branch checkout unrecoverable.
    """
    generated, unsafe = _discard_known_generated_land_drift(project_dir)
    if unsafe:
        _banner(
            "LAND — DIRTY WORKTREE",
            [
                ("spec", spec_id),
                ("problem", "tracked changes remain after verification"),
                ("files", "\n".join(unsafe)),
                ("next step", f"commit or stash these files, then re-run: echelon delivery land {spec_id}"),
            ],
            subtitle="Echelon will only discard known generated verification drift.",
        )
        return False

    return True


def _discard_known_generated_land_drift(project_dir: Path) -> tuple[list[str], list[str]]:
    dirty = _tracked_dirty_files(project_dir)
    if not dirty:
        return [], []

    generated = [path for path in dirty if _is_known_land_generated_drift(path)]
    unsafe = [path for path in dirty if path not in generated]
    if unsafe or not generated:
        return generated, unsafe

    _run_git(["checkout", "--", *generated], cwd=str(project_dir))
    logger.info("Discarded generated land drift: %s", ", ".join(generated))
    return generated, []


def _tracked_dirty_files(project_dir: Path) -> list[str]:
    result = _run_git(
        ["diff", "--name-only", "HEAD", "--"],
        cwd=str(project_dir),
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_known_land_generated_drift(path: str) -> bool:
    return path in _LAND_GENERATED_DRIFT_EXACT


def _default_branch_already_contains_feature(
    project_dir: Path,
    gitops: Any,
    feature_branch: str,
) -> bool:
    default_branch = _land_default_branch(gitops)
    result = _run_git(
        ["merge-base", "--is-ancestor", feature_branch, default_branch],
        cwd=str(project_dir),
        check=False,
    )
    return result.returncode == 0


def _checkout_default_for_landing_cleanup(
    spec_id: str,
    project_dir: Path,
    gitops: Any,
) -> bool:
    if not _clean_generated_drift_before_direct_merge(spec_id, project_dir):
        return False
    default_branch = _land_default_branch(gitops)
    current_branch = _run_git(
        ["branch", "--show-current"],
        cwd=str(project_dir),
        check=False,
    ).stdout.strip()
    if current_branch == default_branch:
        return True
    checkout = _run_git(["checkout", default_branch], cwd=str(project_dir), check=False)
    if checkout.returncode == 0:
        return True
    _banner(
        "LAND — DEFAULT CHECKOUT FAILED",
        [
            ("spec", spec_id),
            ("branch", default_branch),
            ("problem", "feature branch is already merged, but Echelon could not switch to the default branch for cleanup"),
            ("next step", f"fix the checkout problem, then re-run: echelon delivery land {spec_id} --continue"),
        ],
        subtitle="Echelon stopped before deleting the local feature branch.",
    )
    return False


def _check_ready_before_land(
    spec_id: str,
    project_dir: Path,
    options: LandOptions,
    ref: str | None = None,
    fulfillment_project_dir: Path | None = None,
    fulfillment_ref: str | None = None,
) -> bool:
    status_warning = _land_status_warning(spec_id, project_dir)
    fulfillment_warning: str | None = None
    if status_warning is None:
        fulfillment_warning = _fulfillment_warning(
            spec_id,
            project_dir,
            strict=False,
            commit_project_dir=fulfillment_project_dir,
            commit_ref=fulfillment_ref,
        )

    if (
        (status_warning or fulfillment_warning)
        and ref is not None
        and _find_spec_dir_rel_in_ref(project_dir, spec_id, ref) is not None
    ):
        ref_status_warning = _land_status_warning(spec_id, project_dir, ref=ref)
        if ref_status_warning is None:
            ref_fulfillment_warning = _fulfillment_warning(
                spec_id,
                project_dir,
                strict=False,
                ref=ref,
            )
            if ref_fulfillment_warning is None:
                return True
            fulfillment_warning = ref_fulfillment_warning
        elif status_warning is None:
            status_warning = ref_status_warning

    if status_warning:
        _banner(
            "LAND — SPEC NOT READY",
            [
                ("spec", spec_id),
                ("problem", status_warning),
                ("next step", f"rerun delivery or spec verification, then: echelon delivery land {spec_id}"),
            ],
            subtitle="Echelon stopped before landing a spec that is not marked ready.",
        )
        return False

    return _check_fulfillment_before_land(
        spec_id,
        project_dir,
        options,
        warning=fulfillment_warning,
        commit_project_dir=fulfillment_project_dir,
        commit_ref=fulfillment_ref,
    )


def _land_status_warning(
    spec_id: str,
    project_dir: Path,
    ref: str | None = None,
) -> str | None:
    with _land_spec_dir(spec_id, project_dir, ref=ref) as spec_dir:
        if spec_dir is None or not (spec_dir / "spec.md").exists():
            return None

        status = read_frontmatter(spec_dir).get("status")
    if status in {"ready_to_land", "landed"}:
        return None
    return f"spec status must be ready_to_land before landing; current status is {status or '(missing)'}"


def _prepare_for_land(
    *,
    spec_id: str,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> LandPrepareResult | None:
    prepare_result = prepare_feature_branch(
        spec_id=spec_id,
        feature_branch=feature_branch,
        project_dir=project_dir,
        gitops=gitops,
        options=options,
    )
    if prepare_result.status == "blocked":
        has_conflicts = bool(prepare_result.conflicted_files)
        detail_label = "conflicts" if has_conflicts else "problem"
        detail_value = (
            "\n".join(prepare_result.conflicted_files)
            if has_conflicts
            else prepare_result.message or "(none)"
        )
        _banner(
            "LAND — FEATURE BRANCH NEEDS CONFLICT RESOLUTION"
            if has_conflicts
            else "LAND — FEATURE BRANCH NOT READY",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                (detail_label, detail_value),
                (
                    "next step",
                    f"resolve conflicts, then run: echelon delivery land {spec_id} --continue"
                    if has_conflicts
                    else f"resolve the reported problem, then run: echelon delivery land {spec_id} --continue",
                ),
            ],
            subtitle=(
                "Echelon stopped on semantic conflicts."
                if has_conflicts
                else "Echelon stopped before mutating the default branch."
            ),
        )
        return None
    return prepare_result


def _verify_before_land(
    spec_id: str,
    project_dir: Path,
    gitops: Any,
    options: LandOptions,
) -> bool:
    passed, output = _run_land_verify(project_dir, gitops)
    if passed:
        return True

    _banner(
        "LAND — VERIFY FAILED",
        [
            ("spec", spec_id),
            ("problem", "verification command failed"),
            ("output", output or "(no output)"),
            ("next step", f"fix verification failures, then re-run: echelon delivery land {spec_id}"),
        ],
        subtitle="Echelon stopped before merging or changing landing state.",
    )
    return False


def _check_fulfillment_before_land(
    spec_id: str,
    project_dir: Path,
    options: LandOptions,
    ref: str | None = None,
    warning: str | None = None,
    commit_project_dir: Path | None = None,
    commit_ref: str | None = None,
) -> bool:
    fulfillment_warning = warning
    if fulfillment_warning is None:
        fulfillment_warning = _fulfillment_warning(
            spec_id,
            project_dir,
            strict=False,
            ref=ref,
            commit_project_dir=commit_project_dir,
            commit_ref=commit_ref,
        )
    if not fulfillment_warning:
        spec_dir = find_spec_dir(spec_id, project_dir)
        entries = active_entries(spec_dir) if spec_dir is not None else ()
        if entries:
            _banner(
                "LAND — DEFERRED SCOPE",
                [
                    ("spec", spec_id),
                    ("ledger", str(ledger_path(spec_dir))),
                    (
                        "deferred",
                        "; ".join(
                            f"{', '.join(entry.selected_ids)} ({entry.reason})"
                            for entry in entries
                        ),
                    ),
                ],
                subtitle="Landing fulfilled scope with explicit owner deferrals.",
            )
        return True

    if not options.allow_fulfillment_gaps:
        _banner(
            "LAND — FULFILLMENT GAPS BLOCKED",
            [
                ("spec", spec_id),
                ("problem", fulfillment_warning),
                ("next step", f"echelon spec reopen {spec_id}  # then rerun delivery and land"),
                ("override", f"echelon delivery land {spec_id} --allow-fulfillment-gaps"),
            ],
            subtitle="Echelon stopped before landing incomplete spec coverage.",
        )
        return False

    _banner(
        "LAND — FULFILLMENT GAPS WARNING",
        [
            ("spec", spec_id),
            ("warning", fulfillment_warning),
        ],
        subtitle="Echelon will continue landing because --allow-fulfillment-gaps was set.",
    )
    return True


def _fulfillment_warning(
    spec_id: str,
    project_dir: Path,
    strict: bool = False,
    ref: str | None = None,
    commit_project_dir: Path | None = None,
    commit_ref: str | None = None,
) -> str | None:
    with _land_spec_dir(spec_id, project_dir, ref=ref) as spec_dir:
        if spec_dir is None:
            return None

        report = latest_fulfillment_report(spec_dir)
        if report is None:
            if (spec_dir / "spec.md").exists():
                return (
                    f"no fulfillment report found for {spec_dir}. "
                    f"Rerun `echelon spec verify {spec_id}` before landing."
                )
            return None

        freshness_project_dir = commit_project_dir or project_dir
        freshness_ref = commit_ref or ref
        if freshness_ref is None:
            current_commit = _current_git_commit(freshness_project_dir)
            current = bool(
                current_commit
                and fulfillment_report_is_current(report, current_commit=current_commit)
            )
        else:
            current_commit = _ref_git_commit(freshness_project_dir, freshness_ref)
            current = _fulfillment_report_covers_ref(
                report=report,
                project_dir=freshness_project_dir,
                spec_id=spec_id,
                ref=freshness_ref,
                current_commit=current_commit,
            )
        if current_commit and not current:
            metadata = read_fulfillment_metadata(report)
            verified_commit = metadata.get("verified_commit") or "(missing)"
            return (
                f"fulfillment report is stale for current HEAD {current_commit}: {report} "
                f"was verified at {verified_commit}. Rerun `echelon spec verify {spec_id}`."
            )

        metadata = read_fulfillment_metadata(report)
        if metadata.get("verify_scope") == "scoped":
            return (
                f"latest fulfillment report is a scoped fulfillment report: {report}. "
                f"Run full `echelon spec verify {spec_id}` before landing."
            )

        deferred_scope_issues = validate_deferred_scope_rows(report, spec_dir)
        if deferred_scope_issues:
            return "invalid deferred scope in fulfillment report: " + "; ".join(
                deferred_scope_issues
            )

        if not fulfillment_has_blocking_gaps(report, strict=strict):
            return None

    statuses = ", ".join(sorted(blocking_statuses(strict)))
    return (
        f"fulfillment report has unresolved statuses ({statuses}): {report}. "
        f"Run `echelon spec reopen {spec_id}` or rerun `echelon spec verify {spec_id}`."
    )


@contextmanager
def _land_spec_dir(
    spec_id: str,
    project_dir: Path,
    ref: str | None = None,
) -> Iterator[Path | None]:
    if ref is None:
        yield find_spec_dir(spec_id, project_dir)
        return

    spec_rel = _find_spec_dir_rel_in_ref(project_dir, spec_id, ref)
    if spec_rel is None:
        yield None
        return

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        for relpath in _list_ref_files(project_dir, ref, prefix=f"{spec_rel}/"):
            if Path(relpath).suffix not in _TEXT_SNAPSHOT_SUFFIXES:
                continue
            content = _show_ref_file(project_dir, ref, relpath)
            if content is None:
                continue
            target = tmp_root / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        yield tmp_root / spec_rel


def _find_spec_dir_rel_in_ref(project_dir: Path, spec_id: str, ref: str) -> str | None:
    candidates: list[str] = []
    for relpath in _list_ref_files(project_dir, ref, prefix="specs/"):
        path = Path(relpath)
        if path.name != "spec.md" or len(path.parts) < 3:
            continue
        spec_name = path.parts[1]
        if spec_name == spec_id or spec_name.startswith(f"{spec_id}-"):
            candidates.append(str(path.parent))
    return sorted(candidates)[0] if candidates else None


def _list_ref_files(project_dir: Path, ref: str, prefix: str = "") -> list[str]:
    args = ["ls-tree", "-r", "--name-only", ref]
    if prefix:
        args.extend(["--", prefix])
    result = _run_git(args, cwd=str(project_dir), check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _show_ref_file(project_dir: Path, ref: str, relpath: str) -> str | None:
    result = _run_git(["show", f"{ref}:{relpath}"], cwd=str(project_dir), check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def _ref_git_commit(project_dir: Path, ref: str) -> str | None:
    result = _run_git(["rev-parse", ref], cwd=str(project_dir), check=False)
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _fulfillment_report_covers_ref(
    *,
    report: Path,
    project_dir: Path,
    spec_id: str,
    ref: str,
    current_commit: str | None,
) -> bool:
    if not current_commit:
        return False

    metadata = read_fulfillment_metadata(report)
    verified_commit = metadata.get("verified_commit")
    if not isinstance(verified_commit, str) or not verified_commit:
        return False
    if verified_commit == current_commit:
        return True

    ancestor = _run_git(
        ["merge-base", "--is-ancestor", verified_commit, current_commit],
        cwd=str(project_dir),
        check=False,
    )
    if ancestor.returncode != 0:
        return False
    return not _ref_changes_fulfillment_inputs(
        project_dir=project_dir,
        spec_id=spec_id,
        ref=ref,
        verified_commit=verified_commit,
        current_commit=current_commit,
    )


def _ref_changes_fulfillment_inputs(
    *,
    project_dir: Path,
    spec_id: str,
    ref: str,
    verified_commit: str,
    current_commit: str,
) -> bool:
    spec_rel = _find_spec_dir_rel_in_ref(project_dir, spec_id, ref)
    result = _run_git(
        ["diff", "--name-only", verified_commit, current_commit],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode != 0:
        return True

    for relpath in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
        if _is_implementation_input_path(relpath):
            return True
        if spec_rel and _is_spec_input_path(relpath, spec_rel):
            if relpath == f"{spec_rel}/spec.md" and _spec_change_is_status_only(
                project_dir,
                verified_commit,
                current_commit,
                relpath,
            ):
                continue
            return True
    return False


def _is_implementation_input_path(relpath: str) -> bool:
    if relpath in _IMPLEMENTATION_INPUT_FILES:
        return True
    return any(relpath == dirname or relpath.startswith(f"{dirname}/") for dirname in _IMPLEMENTATION_INPUT_DIRS)


def _is_spec_input_path(relpath: str, spec_rel: str) -> bool:
    prefix = f"{spec_rel}/"
    if not relpath.startswith(prefix):
        return False
    return relpath.removeprefix(prefix) in _SPEC_INPUT_FILENAMES


def _spec_change_is_status_only(
    project_dir: Path,
    old_ref: str,
    new_ref: str,
    relpath: str,
) -> bool:
    old = _show_ref_file(project_dir, old_ref, relpath)
    new = _show_ref_file(project_dir, new_ref, relpath)
    if old is None or new is None:
        return False
    return _without_spec_status(old) == _without_spec_status(new)


def _without_spec_status(text: str) -> str:
    text = _FRONTMATTER_RE.sub("", text, count=1)
    return re.sub(r"^\*\*Status\*\*:\s*.*(?:\n|$)", "", text, count=1, flags=re.MULTILINE)


def _current_git_commit(project_dir: Path) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir), check=False)
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def _run_land_verify(project_dir: Path, gitops: Any) -> tuple[bool, str]:
    config = getattr(gitops, "_config", None)
    command = getattr(config, "verify_command", None) if config is not None else None
    if not isinstance(command, str) or not command.strip():
        return True, "no verify_command configured"

    try:
        args = shlex.split(command)
    except ValueError as e:
        return False, _trim_verify_output(f"invalid verify_command: {e}")

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            result = subprocess.run(
                args,
                cwd=str(project_dir),
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            output = _join_verify_output(
                _read_verify_tail(stdout_file),
                _read_verify_tail(stderr_file),
            )
            return False, _trim_verify_output(
                output or f"verify_command timed out after {e.timeout}s"
            )
        except FileNotFoundError as e:
            return False, _trim_verify_output(str(e))

        output = _join_verify_output(
            _read_verify_tail(stdout_file),
            _read_verify_tail(stderr_file),
        )

    if result.returncode != 0 and not output.strip():
        output = f"verify_command exited with status {result.returncode}"
    return result.returncode == 0, _trim_verify_output(output)


def _read_verify_tail(file: Any, limit: int = 4096) -> str:
    file.flush()
    size = file.seek(0, 2)
    file.seek(max(0, size - limit))
    return file.read().decode("utf-8", errors="replace")


def _join_verify_output(stdout: str, stderr: str) -> str:
    return "\n".join(part for part in [stdout, stderr] if part)


def _trim_verify_output(output: str) -> str:
    return output.strip()[-2000:]


def _finish_landing(
    spec_id: str,
    feature_branch: str,
    project_dir: Path,
    gitops: Any,
    *,
    spec_project_dir: Path | None = None,
    harness_root: Path | None = None,
) -> bool:
    """Clean up after a feature branch has merged."""
    spec_project_dir = spec_project_dir or project_dir
    default_branch = _land_default_branch(gitops)

    origin_url = _origin_remote_url(project_dir)
    remote_cleanup_required = bool(
        origin_url and not _is_local_remote_url(project_dir, origin_url)
    )

    remote_head = _remote_head_branch(project_dir) if remote_cleanup_required else None
    if remote_head == feature_branch:
        _banner(
            "LAND — REMOTE DEFAULT BRANCH BLOCKED",
            [
                ("branch", feature_branch),
                ("problem", f"origin/HEAD still points to {feature_branch}"),
                ("next step", f"change default branch to {default_branch}, then rerun: echelon delivery land {spec_id}"),
                ("manual cleanup", f"git push origin --delete {feature_branch}"),
            ],
            subtitle="Echelon stopped before deleting a branch that the remote still treats as default.",
        )
        return False

    if remote_cleanup_required and not gitops.delete_remote_branch(
        feature_branch,
        project_dir=str(project_dir),
    ):
        _banner(
            "LAND — REMOTE BRANCH CLEANUP BLOCKED",
            [
                ("branch", feature_branch),
                ("problem", "could not delete feature branch from origin"),
                ("state", "default branch merge is complete, but cleanup is not verified"),
                ("manual cleanup", f"git push origin --delete {feature_branch}"),
            ],
            subtitle="Echelon stopped before local cleanup and status mutation.",
        )
        return False
    if not remote_cleanup_required:
        logger.info("Skipping remote feature branch cleanup: no non-local origin remote")
    _delete_local_branch(feature_branch, str(project_dir))
    _cleanup_worktrees(
        spec_id,
        harness_root if harness_root is not None else project_dir,
        gitops,
    )
    _delete_harness_branches(spec_id, project_dir)
    gitops.ensure_on_default_branch(str(project_dir))

    spec_dir = find_spec_dir(spec_id, spec_project_dir)
    if spec_dir:
        write_status(spec_dir, "landed")
    _clear_landed_active_authoring_pointer(spec_project_dir, spec_id, feature_branch)
    _post_land_topology_reconciliation(
        spec_id,
        spec_project_dir,
        project_dir,
    )

    logger.info("land: %s — landed successfully", spec_id)
    return True


def _post_land_topology_reconciliation(
    spec_id: str,
    workspace_root: Path,
    target_root: Path,
) -> None:
    """Report independent topology and semantic freshness after successful landing."""
    source_id = _configured_source_id_for_target(workspace_root, target_root)
    default_head = _current_git_commit(target_root)
    reconciliation_detail = ""
    if default_head is None:
        reconciliation_detail = "could not resolve landed default HEAD"
    else:
        try:
            from harness.topology_promotion import reconcile_landed_topology

            result = reconcile_landed_topology(
                workspace_root,
                spec_id,
                target_root,
                default_head,
            )
            source_id = result.source_id or source_id
            if result.status != "current":
                reconciliation_detail = result.message
        except Exception as exc:  # noqa: BLE001 - landing must remain successful.
            reconciliation_detail = str(exc)

    topology_status = _landed_topology_status(workspace_root, source_id)
    semantic_status = _landed_semantic_re_status(workspace_root, source_id)
    _log_landed_freshness("topology", topology_status, reconciliation_detail)
    _log_landed_freshness("semantic RE", semantic_status)
    if source_id is not None and (
        topology_status != "current" or semantic_status != "current"
    ):
        logger.warning("next: echelon re refresh --source %s", source_id)


def _landed_topology_status(workspace_root: Path, source_id: str | None) -> str:
    if source_id is None:
        return "unavailable"
    try:
        from echelon.topology_audit import audit_topology

        status = audit_topology(workspace_root, source_id=source_id).status
    except Exception:  # noqa: BLE001 - landing reporting is deliberately nonfatal.
        return "unavailable"
    if status in {"current", "stale"}:
        return status
    return "unavailable"


def _landed_semantic_re_status(
    workspace_root: Path,
    source_id: str | None,
) -> str:
    if source_id is None:
        return "unavailable"
    try:
        from echelon.workspace_model import discover_workspace
        from harness.re_fingerprint import (
            fingerprint_source,
            resolve_re_fingerprint_profile,
        )
        from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
        from harness.re_registry import (
            load_published_index,
            published_source_is_current,
            published_source_is_usable,
        )

        root = Path(workspace_root).resolve()
        matches = [
            source
            for source in discover_workspace(root).sources
            if source.id == source_id
        ]
        if len(matches) != 1:
            return "unavailable"
        source = matches[0]
        source_path = Path(source.path)
        if not source_path.is_absolute():
            source_path = root / source_path
        if not source_path.exists():
            return "unavailable"
        index = load_published_index(root)
        if index is None or source_id not in index.sources:
            return "unavailable"
        profile = resolve_re_fingerprint_profile(root)
        fingerprint = fingerprint_source(source_path, profile)
        expect_empty = source.source_file_count <= 0
        if published_source_is_current(
            root,
            index,
            source_id,
            source_path=source.path,
            fingerprint=fingerprint.value,
            profile_hash=fingerprint.profile_hash,
            expect_empty=expect_empty,
            quality_contract_version=QUALITY_CONTRACT_VERSION,
        ):
            return "current"
        published = index.sources[source_id]
        if not published_source_is_usable(
            root,
            index,
            source_id,
            expect_empty=expect_empty,
        ):
            return "unavailable"
        if (
            expect_empty
            and published.status == "empty"
            and published.source_path == source.path
            and published.fingerprint == fingerprint.value
            and published.profile_hash == fingerprint.profile_hash
        ):
            return "current"
        return "stale"
    except Exception:  # noqa: BLE001 - landing reporting is deliberately nonfatal.
        return "unavailable"


def _log_landed_freshness(authority: str, status: str, detail: str = "") -> None:
    suffix = f" ({detail})" if detail and status != "current" else ""
    if status == "current":
        logger.info("%s: current", authority)
    else:
        logger.warning("%s: %s%s", authority, status, suffix)


def _configured_source_id_for_target(
    workspace_root: Path,
    target_root: Path,
) -> str | None:
    try:
        from echelon.workspace_model import discover_workspace

        workspace = Path(workspace_root).resolve()
        target = Path(target_root).resolve()
        matches = [
            source.id
            for source in discover_workspace(workspace).sources
            if (
                workspace
                if source.path == "."
                else workspace / source.path
            ).resolve()
            == target
        ]
    except (OSError, ValueError):
        return None
    return matches[0] if len(matches) == 1 else None


def _clear_landed_active_authoring_pointer(
    project_dir: Path,
    spec_id: str,
    feature_branch: str,
) -> None:
    """Clear runs/.current when it still names the spec that just landed."""

    root = Path(project_dir).resolve()
    current = root / "runs" / ".current"
    try:
        run_name = current.read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not run_name:
        return

    state_path = root / "runs" / run_name / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(state, dict):
        return

    active_branch = str(state.get("feature_branch") or "").strip()
    active_spec = str(state.get("spec_id") or "").strip()
    if feature_branch:
        if active_branch != feature_branch:
            return
    elif not _spec_id_matches(active_spec, spec_id):
        return
    try:
        current.unlink()
    except OSError as exc:
        logger.warning("Could not clear landed active spec pointer %s: %s", current, exc)


def _spec_id_matches(active_spec: str, requested_spec: str) -> bool:
    return bool(
        set(spec_identity_aliases(active_spec))
        & set(spec_identity_aliases(requested_spec))
    )


def _land_default_branch(gitops: Any) -> str:
    config = getattr(gitops, "_config", None)
    configured = getattr(config, "target_default_branch", None) if config is not None else None
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    try:
        branch = gitops.get_default_branch()
    except Exception:  # noqa: BLE001
        return "main"
    return str(branch or "main")


def _remote_head_branch(project_dir: Path, remote: str = "origin") -> str | None:
    """Return the branch that remote HEAD points at, if known."""
    result = _run_git(
        ["ls-remote", "--symref", remote, "HEAD"],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("ref:"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("refs/heads/"):
            return parts[1].removeprefix("refs/heads/")
    return None


def _cleanup_worktrees(spec_id: str, harness_root: Path, gitops: Any) -> None:
    """Remove all worktrees for this spec across all build dirs."""
    rd = runs_dir(harness_root)
    if not rd.exists():
        return
    for build in sorted(rd.glob("build-*/")):
        if not _build_state_matches_spec(build / "state", spec_id):
            continue
        worktree_base = build / "worktrees"
        if not worktree_base.exists():
            continue
        for strategy_dir in sorted(worktree_base.iterdir()):
            if not strategy_dir.is_dir():
                continue
            for iter_dir in sorted(strategy_dir.iterdir()):
                if iter_dir.is_dir():
                    try:
                        gitops.destroy_worktree(iter_dir, keep_branch=True)
                        logger.info("land: removed worktree %s", iter_dir)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("land: could not remove worktree %s: %s", iter_dir, e)


def _build_state_matches_spec(state_dir: Path, spec_id: str) -> bool:
    for state_file in sorted(state_dir.glob("*.json")):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _spec_id_matches(str(state.get("spec_id") or ""), spec_id):
            return True
    return False


def _delete_local_branch(branch: str, project_dir: str) -> None:
    """Delete the local feature branch after a successful merge.

    Uses -d (safe delete) so git refuses if the branch is somehow not merged —
    this is a second safety net on top of the merge-success gate in land().
    For PR-merged branches where local main hasn't been pulled yet, -d will
    refuse; we log a notice and leave the branch rather than force-deleting.
    """
    try:
        subprocess.run(
            ["git", "branch", "-d", branch],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            cwd=project_dir,
        )
        logger.info("land: deleted local branch %s", branch)
    except subprocess.CalledProcessError:
        # Most likely: PR was merged remotely but local main hasn't been pulled.
        # Branch is merged — just not visible to local git yet. Leave it.
        logger.info(
            "land: local branch %s not deleted (not yet in local history — run 'git pull' to clean up)",
            branch,
        )


def _delete_harness_branches(spec_id: str, project_dir: Path) -> None:
    """Safely delete merged local harness branches left over from delivery runs."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"harness/{spec_id}/*"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_dir),
        )
        branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]
        for branch in branches:
            try:
                subprocess.run(
                    ["git", "branch", "-d", branch],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                    cwd=str(project_dir),
                )
                logger.info("land: deleted legacy branch %s", branch)
            except subprocess.CalledProcessError as e:
                logger.warning(
                    "land: preserved unmerged legacy branch %s for review: %s",
                    branch,
                    e,
                )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("land: could not list harness branches for %s: %s", spec_id, e)
