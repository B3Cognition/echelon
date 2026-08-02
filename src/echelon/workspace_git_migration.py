from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message
from harness.config import CANONICAL_CONFIG_PATH, LEGACY_CONFIG_PATH
from harness.re_registry import ensure_re_layout
from echelon.workspace_model import discover_workspace


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceGitMigrationPlan:
    workspace_root: Path
    canonical_config: Path
    legacy_config: Path
    canonical_config_needed: bool
    source_ignore_entries: tuple[str, ...]
    runtime_ignore_entries: tuple[str, ...]
    stage_paths: tuple[str, ...]
    already_git_backed: bool

    @property
    def gitignore_entries(self) -> tuple[str, ...]:
        return self.source_ignore_entries + self.runtime_ignore_entries


@dataclass(frozen=True)
class WorkspaceGitMigrationResult:
    plan: WorkspaceGitMigrationPlan
    write_requested: bool
    git_initialized: bool
    canonical_config_copied: bool
    source_roots_scaffolded: bool
    gitignore_updated: bool
    untracked_runtime_paths: tuple[str, ...]
    staged_paths: tuple[str, ...]
    committed: bool


@dataclass(frozen=True)
class WorkspaceDoctorFinding:
    severity: str
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class WorkspaceDoctorResult:
    workspace_root: Path
    buildable: bool
    findings: tuple[WorkspaceDoctorFinding, ...]

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _has_git_marker(root: Path) -> bool:
    marker = root / ".git"
    return marker.exists()


def _git_ignored(root: Path, path: str) -> bool:
    if not _has_git_marker(root):
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            return False
        normalized = path.strip("/")
        entries = {
            _normalize_gitignore_entry(line)
            for line in gitignore.read_text(encoding="utf-8").splitlines()
        }
        return normalized in entries
    return subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0


def _is_echelon_workspace(root: Path) -> bool:
    return (root / ".specify").exists() or (root / "specs").exists()


def _existing_stage_paths(root: Path) -> tuple[str, ...]:
    paths = [".gitignore"]
    paths.extend(path for path in (".echelon/config.yml",) if (root / path).exists())
    paths.extend(path for path in ("sources/README.md",) if (root / path).exists())
    paths.extend(path for path in ("re/.gitignore",) if (root / path).exists())
    paths.extend(path for path in ("specs",) if (root / path).exists())
    return tuple(paths)


def _source_ignore_entry(path: str) -> str:
    return f"/{path.strip('/')}/"


def build_migration_plan(workspace_root: Path) -> WorkspaceGitMigrationPlan:
    root = workspace_root.resolve()
    if not root.exists() or not root.is_dir():
        raise MigrationError(f"workspace root does not exist: {root}")
    if not _is_echelon_workspace(root):
        raise MigrationError(
            f"not an Echelon workspace: {root} (expected .specify/ or specs/)"
        )

    manifest = discover_workspace(root)
    canonical_config = root / CANONICAL_CONFIG_PATH
    legacy_config = root / LEGACY_CONFIG_PATH
    source_ignore_entries = tuple(
        _source_ignore_entry(source.path)
        for source in manifest.sources
        if source.path != "."
    )
    runtime_ignore_entries = (
        "/.specify/",
        "/runs/",
        "/.claude/",
        "/.claude-work/",
        "!/.echelon/",
        "!/.echelon/config.yml",
        "/.echelon/local.yml",
        "/.echelon/runtime/",
        "/.echelon/cache/",
        "/.echelon/recovery-backups/",
        ".DS_Store",
        "node_modules/",
        "/sources/*",
        "!/sources/README.md",
    )
    stage_paths = _existing_stage_paths(root)

    return WorkspaceGitMigrationPlan(
        workspace_root=root,
        canonical_config=canonical_config,
        legacy_config=legacy_config,
        canonical_config_needed=(not canonical_config.exists() and legacy_config.exists()),
        source_ignore_entries=source_ignore_entries,
        runtime_ignore_entries=runtime_ignore_entries,
        stage_paths=stage_paths,
        already_git_backed=_has_git_marker(root),
    )


def _append_missing_gitignore_entries(root: Path, entries: tuple[str, ...]) -> bool:
    gitignore = root / ".gitignore"
    existing_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    existing = set(existing_text.splitlines())
    existing_normalized = {_normalize_gitignore_entry(entry) for entry in existing}
    missing = [
        entry
        for entry in entries
        if entry not in existing
        and _normalize_gitignore_entry(entry) not in existing_normalized
    ]
    if not missing:
        return False

    prefix = "" if not existing_text or existing_text.endswith("\n") else "\n"
    gitignore.write_text(
        existing_text + prefix + "\n".join(missing) + "\n",
        encoding="utf-8",
    )
    return True


def _normalize_gitignore_entry(entry: str) -> str:
    stripped = entry.strip()
    if not stripped or stripped.startswith("#"):
        return stripped
    return stripped.strip("/")


def _stage_workspace_files(root: Path, stage_paths: tuple[str, ...]) -> tuple[str, ...]:
    existing = [path for path in stage_paths if (root / path).exists()]
    if not existing:
        return ()
    _run_git(root, "add", "--", *existing)
    return tuple(existing)


def _copy_legacy_config_to_canonical(plan: WorkspaceGitMigrationPlan) -> bool:
    if not plan.canonical_config_needed:
        return False
    plan.canonical_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plan.legacy_config, plan.canonical_config)
    return True


def _scaffold_source_roots_directory(root: Path) -> bool:
    sources_dir = root / "sources"
    readme = sources_dir / "README.md"
    sources_dir.mkdir(exist_ok=True)
    if readme.exists():
        return False
    readme.write_text(
        "# Workspace Source Roots\n\n"
        "Put implementation repositories for this Echelon workspace here.\n\n"
        "Examples:\n\n"
        "```bash\n"
        "git clone git@github.com:example/app.git sources/app\n"
        "git clone git@github.com:example/api.git sources/api\n"
        "```\n\n"
        "After adding sources, declare them in `.echelon/config.yml`:\n\n"
        "```yaml\n"
        "sources:\n"
        "  - id: app\n"
        "    path: sources/app\n"
        "```\n\n"
        "Child repositories under this directory are ignored by workspace Git; "
        "this README is tracked so the location is visible in new workspaces.\n",
        encoding="utf-8",
    )
    return True


def _tracked_paths(root: Path, pathspec: str) -> tuple[str, ...]:
    try:
        result = _run_git(root, "ls-files", pathspec)
    except subprocess.CalledProcessError:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line)


def _is_tracked(root: Path, pathspec: str) -> bool:
    return bool(_tracked_paths(root, pathspec))


def _is_submodule_like(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_file()


def _inside_runtime_or_artifact(path: str) -> bool:
    normalized = path.strip("/")
    return (
        normalized == ".specify"
        or normalized.startswith(".specify/")
        or normalized == "runs"
        or normalized.startswith("runs/")
        or normalized == "specs"
        or normalized.startswith("specs/")
    )


def doctor_workspace(workspace_root: Path) -> WorkspaceDoctorResult:
    root = workspace_root.resolve()
    findings: list[WorkspaceDoctorFinding] = []

    if not root.exists() or not root.is_dir():
        return WorkspaceDoctorResult(
            workspace_root=root,
            buildable=False,
            findings=(
                WorkspaceDoctorFinding(
                    "error",
                    "workspace_missing",
                    f"workspace root does not exist: {root}",
                    str(root),
                ),
            ),
        )

    if not _has_git_marker(root):
        findings.append(
            WorkspaceDoctorFinding(
                "error",
                "workspace_not_git_backed",
                "workspace root must be a Git repository",
                str(root),
            )
        )

    canonical = root / CANONICAL_CONFIG_PATH
    legacy = root / LEGACY_CONFIG_PATH
    if not canonical.exists():
        severity = "error" if legacy.exists() else "warning"
        findings.append(
            WorkspaceDoctorFinding(
                severity,
                "canonical_config_missing",
                ".echelon/config.yml is missing"
                + ("; migrate legacy echelon-config.yml" if legacy.exists() else ""),
                str(canonical),
            )
        )
    elif _git_ignored(root, ".echelon/config.yml"):
        findings.append(
            WorkspaceDoctorFinding(
                "error",
                "canonical_config_ignored",
                ".echelon/config.yml exists but is ignored by workspace Git",
                ".echelon/config.yml",
            )
        )

    runtime_paths = (
        (".specify", ".specify/ must be ignored by workspace Git"),
        ("runs", "runs/ must be ignored by workspace Git"),
        (".claude", ".claude/ must be ignored by workspace Git"),
        (".echelon/local.yml", ".echelon/local.yml must be ignored by workspace Git"),
        (".echelon/runtime", ".echelon/runtime/ must be ignored by workspace Git"),
        (".echelon/cache", ".echelon/cache/ must be ignored by workspace Git"),
        (
            ".echelon/recovery-backups",
            ".echelon/recovery-backups/ must be ignored by workspace Git",
        ),
    )
    for runtime_path, message in runtime_paths:
        path_obj = root / runtime_path
        if path_obj.exists() and not _git_ignored(root, runtime_path):
            findings.append(
                WorkspaceDoctorFinding(
                    "error",
                    "runtime_not_ignored",
                    message,
                    runtime_path,
                )
            )
        tracked_runtime = _tracked_paths(root, runtime_path) if _has_git_marker(root) else ()
        if tracked_runtime:
            findings.append(
                WorkspaceDoctorFinding(
                    "error",
                    "runtime_tracked",
                    f"{runtime_path} contains tracked runtime files",
                    runtime_path,
                )
            )

    re_root = root / "re"
    if re_root.exists() and _git_ignored(root, "re/index.json"):
        findings.append(
            WorkspaceDoctorFinding(
                "error",
                "re_ignored",
                "re/ must be a tracked artifact surface, not ignored",
                "re",
            )
        )
    for runtime_path in ("re/.cache", "re/.staging", "re/.locks"):
        runtime_obj = root / runtime_path
        if runtime_obj.exists() and not _git_ignored(root, runtime_path):
            findings.append(
                WorkspaceDoctorFinding(
                    "error",
                    "re_runtime_not_ignored",
                    f"{runtime_path}/ must be ignored by workspace Git",
                    runtime_path,
                )
            )
        tracked_runtime = _tracked_paths(root, runtime_path) if _has_git_marker(root) else ()
        if tracked_runtime:
            findings.append(
                WorkspaceDoctorFinding(
                    "error",
                    "re_runtime_tracked",
                    f"{runtime_path} contains tracked runtime files",
                    runtime_path,
                )
            )

    specs = root / "specs"
    if not specs.exists():
        findings.append(
            WorkspaceDoctorFinding(
                "warning",
                "specs_missing",
                "specs/ does not exist yet",
                "specs",
            )
        )
    elif _git_ignored(root, "specs"):
        findings.append(
            WorkspaceDoctorFinding(
                "error",
                "specs_ignored",
                "specs/ must be tracked artifact surface, not ignored",
                "specs",
            )
        )

    manifest = discover_workspace(root)
    if not manifest.sources:
        findings.append(
            WorkspaceDoctorFinding(
                "warning",
                "planning_only_workspace",
                "no source roots configured; workspace is planning-only and not buildable",
                str(canonical if canonical.exists() else root),
            )
        )

    for source in manifest.sources:
        source_root = root if source.path == "." else (root / source.path).resolve()
        if _inside_runtime_or_artifact(source.path):
            findings.append(
                WorkspaceDoctorFinding(
                    "error",
                    "invalid_source_root",
                    "source root must not be inside .specify/, runs/, or specs/",
                    source.path,
                )
            )
            continue
        if not source_root.exists():
            findings.append(
                WorkspaceDoctorFinding(
                    "error",
                    "source_root_missing",
                    "configured source root does not exist",
                    source.path,
                )
            )
            continue
        if source.path != "." and manifest.workspace.git_role == "orchestration":
            ignored = _git_ignored(root, source.path)
            if not ignored and not _is_submodule_like(source_root):
                findings.append(
                    WorkspaceDoctorFinding(
                        "warning",
                        "source_root_not_ignored",
                        "child source root should be ignored by orchestration Git unless it is a submodule",
                        source.path,
                    )
                )

    return WorkspaceDoctorResult(
        workspace_root=root,
        buildable=bool(manifest.sources) and not any(
            finding.severity == "error" for finding in findings
        ),
        findings=tuple(findings),
    )


def _untrack_runtime_paths(root: Path) -> tuple[str, ...]:
    untracked: list[str] = []
    for pathspec in (
        ".specify",
        "runs",
        ".claude",
        ".echelon/local.yml",
        ".echelon/runtime",
        ".echelon/cache",
        ".echelon/recovery-backups",
    ):
        tracked = _tracked_paths(root, pathspec)
        if not tracked:
            continue
        _run_git(root, "rm", "-r", "--cached", "--ignore-unmatch", "--", pathspec)
        untracked.extend(tracked)
    return tuple(untracked)


def migrate_workspace(
    workspace_root: Path,
    *,
    write: bool,
    commit: bool,
    commit_message: str = "chore: initialize echelon workspace",
) -> WorkspaceGitMigrationResult:
    plan = build_migration_plan(workspace_root)
    if not write:
        return WorkspaceGitMigrationResult(
            plan=plan,
            write_requested=False,
            git_initialized=False,
            canonical_config_copied=False,
            source_roots_scaffolded=False,
            gitignore_updated=False,
            untracked_runtime_paths=(),
            staged_paths=(),
            committed=False,
        )

    git_initialized = False
    if not plan.already_git_backed:
        _run_git(plan.workspace_root, "init")
        git_initialized = True

    canonical_config_copied = _copy_legacy_config_to_canonical(plan)
    source_roots_scaffolded = _scaffold_source_roots_directory(plan.workspace_root)
    ensure_re_layout(plan.workspace_root)
    gitignore_updated = _append_missing_gitignore_entries(
        plan.workspace_root,
        plan.gitignore_entries,
    )
    untracked_runtime_paths = _untrack_runtime_paths(plan.workspace_root)
    if plan.already_git_backed:
        stage_paths_list: list[str] = []
        if gitignore_updated:
            stage_paths_list.append(".gitignore")
        if source_roots_scaffolded or not _is_tracked(plan.workspace_root, "sources/README.md"):
            stage_paths_list.append("sources/README.md")
        if not _is_tracked(plan.workspace_root, "re/.gitignore"):
            stage_paths_list.append("re/.gitignore")
        if canonical_config_copied or (
            plan.canonical_config.exists()
            and (gitignore_updated or not _is_tracked(plan.workspace_root, ".echelon/config.yml"))
        ):
            stage_paths_list.append(".echelon/config.yml")
        stage_paths = tuple(stage_paths_list)
    else:
        stage_paths = _existing_stage_paths(plan.workspace_root)
    staged_paths = _stage_workspace_files(plan.workspace_root, stage_paths)

    committed = False
    if commit:
        commit_message = build_echelon_commit_message(
            commit_message,
            EchelonCommitMetadata(origin="workspace", action="init"),
        )
        _run_git(
            plan.workspace_root,
            "-c",
            "user.name=Echelon",
            "-c",
            "user.email=echelon-workspace@example.invalid",
            "commit",
            "-m",
            commit_message,
        )
        committed = True

    return WorkspaceGitMigrationResult(
        plan=plan,
        write_requested=True,
        git_initialized=git_initialized,
        canonical_config_copied=canonical_config_copied,
        source_roots_scaffolded=source_roots_scaffolded,
        gitignore_updated=gitignore_updated,
        untracked_runtime_paths=untracked_runtime_paths,
        staged_paths=staged_paths,
        committed=committed,
    )


def _print_plan(result: WorkspaceGitMigrationResult) -> None:
    plan = result.plan
    print(f"Workspace: {plan.workspace_root}")
    print(f"Git-backed: {'yes' if plan.already_git_backed else 'no'}")
    print("Gitignore entries:")
    for entry in plan.gitignore_entries:
        print(f"  {entry}")
    print("Stage paths:")
    for path in plan.stage_paths:
        print(f"  {path}")
    if plan.canonical_config_needed:
        print(f"Canonical config: copy {plan.legacy_config} -> {plan.canonical_config}")
    if not result.write_requested:
        print("Dry-run only. Re-run with --write to apply.")
    elif (
        not result.git_initialized
        and not result.canonical_config_copied
        and not result.source_roots_scaffolded
        and not result.gitignore_updated
        and not result.untracked_runtime_paths
        and not result.staged_paths
    ):
        print("No changes needed.")
    else:
        print("Applied:")
        print(f"  git_initialized: {result.git_initialized}")
        print(f"  canonical_config_copied: {result.canonical_config_copied}")
        print(f"  source_roots_scaffolded: {result.source_roots_scaffolded}")
        print(f"  gitignore_updated: {result.gitignore_updated}")
        print(f"  untracked_runtime_paths: {', '.join(result.untracked_runtime_paths) or '(none)'}")
        print(f"  staged_paths: {', '.join(result.staged_paths) or '(none)'}")
        print(f"  committed: {result.committed}")
        if not result.committed:
            print("Next: echelon workspace migrate --commit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-time migration from branchless Echelon workspace to lightweight workspace Git."
    )
    parser.add_argument("workspace", nargs="?", default=".", help="Workspace root")
    parser.add_argument("--write", action="store_true", help="Apply migration")
    parser.add_argument("--commit", action="store_true", help="Commit staged workspace files")
    parser.add_argument(
        "--message",
        default="chore: initialize echelon workspace",
        help="Commit message for --commit",
    )
    args = parser.parse_args(argv)

    try:
        result = migrate_workspace(
            Path(args.workspace),
            write=bool(args.write or args.commit),
            commit=bool(args.commit),
            commit_message=args.message,
        )
    except (MigrationError, subprocess.CalledProcessError) as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1

    _print_plan(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
