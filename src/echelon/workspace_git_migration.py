from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from echelon.workspace_model import discover_workspace


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceGitMigrationPlan:
    workspace_root: Path
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
    git_initialized: bool
    gitignore_updated: bool
    staged_paths: tuple[str, ...]
    committed: bool


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


def _is_echelon_workspace(root: Path) -> bool:
    return (root / ".specify").exists() or (root / "specs").exists()


def _existing_stage_paths(root: Path) -> tuple[str, ...]:
    paths = [".gitignore"]
    paths.extend(path for path in (".specify", "specs") if (root / path).exists())
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
    source_ignore_entries = tuple(
        _source_ignore_entry(source.path)
        for source in manifest.sources
        if source.path != "."
    )
    runtime_ignore_entries = ("/runs/build-*/", "/runs/verify-*/")
    stage_paths = _existing_stage_paths(root)

    return WorkspaceGitMigrationPlan(
        workspace_root=root,
        source_ignore_entries=source_ignore_entries,
        runtime_ignore_entries=runtime_ignore_entries,
        stage_paths=stage_paths,
        already_git_backed=_has_git_marker(root),
    )


def _append_missing_gitignore_entries(root: Path, entries: tuple[str, ...]) -> bool:
    gitignore = root / ".gitignore"
    existing_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    existing = set(existing_text.splitlines())
    missing = [entry for entry in entries if entry not in existing]
    if not missing:
        return False

    prefix = "" if not existing_text or existing_text.endswith("\n") else "\n"
    gitignore.write_text(
        existing_text + prefix + "\n".join(missing) + "\n",
        encoding="utf-8",
    )
    return True


def _stage_workspace_files(root: Path, stage_paths: tuple[str, ...]) -> tuple[str, ...]:
    existing = [path for path in stage_paths if (root / path).exists()]
    if not existing:
        return ()
    _run_git(root, "add", "--", *existing)
    return tuple(existing)


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
            git_initialized=False,
            gitignore_updated=False,
            staged_paths=(),
            committed=False,
        )

    git_initialized = False
    if not plan.already_git_backed:
        _run_git(plan.workspace_root, "init")
        git_initialized = True

    gitignore_updated = _append_missing_gitignore_entries(
        plan.workspace_root,
        plan.gitignore_entries,
    )
    staged_paths = _stage_workspace_files(
        plan.workspace_root,
        _existing_stage_paths(plan.workspace_root),
    )

    committed = False
    if commit:
        _run_git(plan.workspace_root, "commit", "-m", commit_message)
        committed = True

    return WorkspaceGitMigrationResult(
        plan=plan,
        git_initialized=git_initialized,
        gitignore_updated=gitignore_updated,
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
    if not result.git_initialized and not result.gitignore_updated and not result.staged_paths:
        print("Dry-run only. Re-run with --write to apply.")
    else:
        print("Applied:")
        print(f"  git_initialized: {result.git_initialized}")
        print(f"  gitignore_updated: {result.gitignore_updated}")
        print(f"  staged_paths: {', '.join(result.staged_paths) or '(none)'}")
        print(f"  committed: {result.committed}")
        if not result.committed:
            print('Next: git commit -m "chore: initialize echelon workspace"')


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
