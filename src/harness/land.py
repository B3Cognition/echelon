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

from echelon.ui import banner as _banner

from harness.gitops import _run_git
from harness.paths import runs_dir
from harness.spec_frontmatter import find_spec_dir, read_frontmatter, write_status
from kernel.fulfillment import (
    blocking_statuses,
    fulfillment_report_is_current,
    fulfillment_has_blocking_gaps,
    latest_fulfillment_report,
    read_fulfillment_metadata,
)

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
            f"Merge {default_branch} into {feature_branch}",
        ],
        cwd=str(project_dir),
        check=False,
    )
    if result.returncode == 0:
        commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
        gitops.push_prepared_branch(
            str(project_dir), feature_branch, force_with_lease=False
        )
        return LandPrepareResult(
            status="prepared",
            branch=feature_branch,
            prepared_commit=commit,
            pushed=True,
        )

    conflicted = _list_unmerged_files(project_dir)
    autoresolved: list[str] = []
    if options.autoresolve and conflicted == [".gitignore"] and _autoresolve_gitignore(project_dir):
        autoresolved.append(".gitignore")
        conflicted = _list_unmerged_files(project_dir)
        if not conflicted:
            _run_git(["commit", "--no-edit"], cwd=str(project_dir))
            commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
            gitops.push_prepared_branch(
                str(project_dir), feature_branch, force_with_lease=False
            )
            return LandPrepareResult(
                status="prepared",
                branch=feature_branch,
                prepared_commit=commit,
                pushed=True,
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
) -> LandPrepareResult:
    current_branch = _run_git(
        ["branch", "--show-current"],
        cwd=str(project_dir),
        check=False,
    ).stdout.strip()
    if current_branch != feature_branch:
        _run_git(["checkout", feature_branch], cwd=str(project_dir))

    conflicted = _list_unmerged_files(project_dir)
    if conflicted:
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            conflicted_files=conflicted,
            message="conflicts remain",
        )

    merge_head = _run_git(
        ["rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=str(project_dir),
        check=False,
    )
    if merge_head.returncode != 0:
        return LandPrepareResult(
            status="blocked",
            branch=feature_branch,
            message="no merge in progress to continue",
        )

    _run_git(["commit", "--no-edit"], cwd=str(project_dir))
    commit = _run_git(["rev-parse", "HEAD"], cwd=str(project_dir)).stdout.strip()
    gitops.push_prepared_branch(str(project_dir), feature_branch, force_with_lease=False)
    return LandPrepareResult(
        status="prepared",
        branch=feature_branch,
        prepared_commit=commit,
        pushed=True,
    )


def _list_unmerged_files(project_dir: Path) -> list[str]:
    result = _run_git(
        ["diff", "--name-only", "--diff-filter=U"],
        cwd=str(project_dir),
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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
                if data.get("pr_url") and data.get("spec_id") == spec_id:
                    return data["pr_url"]
            except (json.JSONDecodeError, OSError):
                continue
    return None


def _find_pr_url_all_builds(spec_id: str, project_dir: Path) -> Optional[str]:
    """Scan all runs/build-*/state/ directories for a PR URL matching spec_id."""
    rd = runs_dir(project_dir)
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
    frontmatter = read_frontmatter(spec_dir)
    targets = frontmatter.get("targets") or []
    if not targets:
        return project_dir.resolve()
    if len(targets) != 1:
        raise RuntimeError("land requires exactly one target repo for normal specs")
    target_rel = str(targets[0])
    target = (project_dir / target_rel).resolve()
    if not target.exists():
        raise RuntimeError(f"target repo not found: {target_rel}")
    return target


def land(
    spec_id: str,
    *,
    project_dir: Path,
    gitops: Any,
    state_dir: Optional[Path] = None,
    options: Optional[LandOptions] = None,
) -> bool:
    """Idempotent: merge PR, delete remote branch, clean worktrees, mark spec landed.

    Returns True if spec is now in landed state.
    Returns False only when PR merge is blocked — caller must retry or merge manually.
    """
    options = options or LandOptions()
    wrapper_project_dir = project_dir
    spec_dir = find_spec_dir(spec_id, wrapper_project_dir)
    if spec_dir is not None:
        project_dir = resolve_land_repo(wrapper_project_dir, spec_dir)

    feature_branch = gitops.find_feature_branch(spec_id)
    if feature_branch is None:
        logger.info("land: %s — feature branch not found, already landed", spec_id)
        _cleanup_worktrees(spec_id, wrapper_project_dir, gitops)
        _delete_harness_branches(spec_id, project_dir)
        return True

    if state_dir is not None:
        pr_url = find_pr_url(spec_id, state_dir)
    else:
        pr_url = _find_pr_url_all_builds(spec_id, wrapper_project_dir)

    if not options.prepare_only and not _check_ready_before_land(
        spec_id,
        wrapper_project_dir,
        options,
        ref=feature_branch,
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
                ("next step", f"re-run after checks/branch protection clear: echelon land {spec_id}"),
            ],
            subtitle="Feature branch was prepared, but Echelon will not bypass the PR.",
        )
        return False

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
            subtitle="Resolve conflicts manually, then re-run: echelon land " + spec_id,
        )
        return False

    default_branch = _land_default_branch(gitops)
    if not gitops.push_landed_default_branch(str(project_dir), default_branch):
        _banner(
            "LAND — DEFAULT PUSH FAILED",
            [
                ("spec", spec_id),
                ("branch", default_branch),
                ("problem", "local merge succeeded, but pushing the default branch failed"),
                ("next step", f"git push origin {default_branch}  # then re-run: echelon land {spec_id}"),
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
    )


def _check_ready_before_land(
    spec_id: str,
    project_dir: Path,
    options: LandOptions,
    ref: str | None = None,
) -> bool:
    status_warning = _land_status_warning(spec_id, project_dir)
    fulfillment_warning: str | None = None
    if status_warning is None:
        fulfillment_warning = _fulfillment_warning(
            spec_id,
            project_dir,
            strict=False,
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
                ("next step", f"rerun harness or verify-spec, then: echelon land {spec_id}"),
            ],
            subtitle="Echelon stopped before landing a spec that is not marked ready.",
        )
        return False

    return _check_fulfillment_before_land(
        spec_id,
        project_dir,
        options,
        warning=fulfillment_warning,
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
        _banner(
            "LAND — FEATURE BRANCH NEEDS CONFLICT RESOLUTION",
            [
                ("spec", spec_id),
                ("branch", feature_branch),
                ("conflicts", "\n".join(prepare_result.conflicted_files) or "(none)"),
                ("next step", f"resolve conflicts, then run: echelon land {spec_id} --continue"),
            ],
            subtitle="Echelon stopped on semantic conflicts.",
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
            ("next step", f"fix verification failures, then re-run: echelon land {spec_id}"),
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
) -> bool:
    fulfillment_warning = warning
    if fulfillment_warning is None:
        fulfillment_warning = _fulfillment_warning(
            spec_id,
            project_dir,
            strict=False,
            ref=ref,
        )
    if not fulfillment_warning:
        return True

    if not options.allow_fulfillment_gaps:
        _banner(
            "LAND — FULFILLMENT GAPS BLOCKED",
            [
                ("spec", spec_id),
                ("problem", fulfillment_warning),
                ("next step", f"echelon reopen {spec_id}  # then rerun harness and land"),
                ("override", f"echelon land {spec_id} --allow-fulfillment-gaps"),
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
) -> str | None:
    with _land_spec_dir(spec_id, project_dir, ref=ref) as spec_dir:
        if spec_dir is None:
            return None

        report = latest_fulfillment_report(spec_dir)
        if report is None:
            if (spec_dir / "spec.md").exists():
                return (
                    f"no fulfillment report found for {spec_dir}. "
                    f"Rerun `echelon verify-spec {spec_id}` before landing."
                )
            return None

        if ref is None:
            current_commit = _current_git_commit(project_dir)
            current = bool(
                current_commit
                and fulfillment_report_is_current(report, current_commit=current_commit)
            )
        else:
            current_commit = _ref_git_commit(project_dir, ref)
            current = _fulfillment_report_covers_ref(
                report=report,
                project_dir=project_dir,
                spec_id=spec_id,
                ref=ref,
                current_commit=current_commit,
            )
        if current_commit and not current:
            metadata = read_fulfillment_metadata(report)
            verified_commit = metadata.get("verified_commit") or "(missing)"
            return (
                f"fulfillment report is stale for current HEAD {current_commit}: {report} "
                f"was verified at {verified_commit}. Rerun `echelon verify-spec {spec_id}`."
            )

        metadata = read_fulfillment_metadata(report)
        if metadata.get("verify_scope") == "scoped":
            return (
                f"latest fulfillment report is a scoped fulfillment report: {report}. "
                f"Run full `echelon verify-spec {spec_id}` before landing."
            )

        if not fulfillment_has_blocking_gaps(report, strict=strict):
            return None

    statuses = ", ".join(sorted(blocking_statuses(strict)))
    return (
        f"fulfillment report has unresolved statuses ({statuses}): {report}. "
        f"Run `echelon reopen {spec_id}` or rerun `echelon verify-spec {spec_id}`."
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
) -> bool:
    """Clean up after a feature branch has merged."""
    spec_project_dir = spec_project_dir or project_dir
    default_branch = _land_default_branch(gitops)

    remote_head = _remote_head_branch(project_dir)
    if remote_head == feature_branch:
        _banner(
            "LAND — REMOTE DEFAULT BRANCH BLOCKED",
            [
                ("branch", feature_branch),
                ("problem", f"origin/HEAD still points to {feature_branch}"),
                ("next step", f"change default branch to {default_branch}, then rerun: echelon land {spec_id}"),
                ("manual cleanup", f"git push origin --delete {feature_branch}"),
            ],
            subtitle="Echelon stopped before deleting a branch that the remote still treats as default.",
        )
        return False

    if not gitops.delete_remote_branch(feature_branch, project_dir=str(project_dir)):
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
    _delete_local_branch(feature_branch, str(project_dir))
    _cleanup_worktrees(spec_id, project_dir, gitops)
    _delete_harness_branches(spec_id, project_dir)
    gitops.ensure_on_default_branch(str(project_dir))

    spec_dir = find_spec_dir(spec_id, spec_project_dir)
    if spec_dir:
        write_status(spec_dir, "landed")

    logger.info("land: %s — landed successfully", spec_id)
    return True


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


def _cleanup_worktrees(spec_id: str, project_dir: Path, gitops: Any) -> None:
    """Remove all worktrees for this spec across all build dirs."""
    rd = runs_dir(project_dir)
    if not rd.exists():
        return
    for build in sorted(rd.glob("build-*/")):
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
    """Delete local harness/{spec_id}-* branches left over from harness runs."""
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
                    ["git", "branch", "-D", branch],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                    cwd=str(project_dir),
                )
                logger.info("land: deleted legacy branch %s", branch)
            except subprocess.CalledProcessError as e:
                logger.warning("land: could not delete legacy branch %s: %s", branch, e)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("land: could not list harness branches for %s: %s", spec_id, e)
