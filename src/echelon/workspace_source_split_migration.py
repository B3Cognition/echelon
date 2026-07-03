from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class SplitMigrationError(RuntimeError):
    pass


WORKSPACE_KEEP_NAMES = {
    ".git",
    ".gitignore",
    ".specify",
    "runs",
    "specs",
}

LOCAL_KEEP_NAMES = {
    ".DS_Store",
    ".claude",
    ".superpowers",
}

SOURCE_DOT_NAMES = {
    ".github",
    ".gitattributes",
    ".swift-format",
    ".swiftlint.yml",
}

TRANSIENT_DROP_NAMES = {
    ".harness-build-status.json",
}


@dataclass(frozen=True)
class SourceSplitPlan:
    workspace_root: Path
    source_dir: Path
    keep_names: frozenset[str]
    move_names: tuple[str, ...]
    drop_names: tuple[str, ...]
    original_gitignore: str


@dataclass(frozen=True)
class SourceSplitResult:
    plan: SourceSplitPlan
    write_requested: bool
    moved_paths: tuple[str, ...]
    root_gitignore_updated: bool
    child_git_initialized: bool
    child_committed: bool
    root_staged: bool
    root_committed: bool


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_child_git_repo(root: Path) -> None:
    try:
        _run_git(root, "init", "-b", "main")
    except subprocess.CalledProcessError:
        _run_git(root, "init")
        _run_git(root, "branch", "-M", "main")


def _has_git_marker(root: Path) -> bool:
    marker = root / ".git"
    return marker.is_dir() or marker.is_file()


def _is_echelon_workspace(root: Path) -> bool:
    return (root / ".specify").exists() or (root / "specs").exists()


def _tracked_status_lines(root: Path) -> list[str]:
    output = _run_git(root, "status", "--porcelain").stdout.splitlines()
    return [line for line in output if not line.startswith("?? ")]


def _normalize_gitignore_entry(entry: str) -> str:
    stripped = entry.strip()
    if not stripped or stripped.startswith("#"):
        return stripped
    return stripped.strip("/")


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


def build_source_split_plan(
    workspace_root: Path,
    *,
    source_dir: str,
) -> SourceSplitPlan:
    root = workspace_root.resolve()
    if not root.exists() or not root.is_dir():
        raise SplitMigrationError(f"workspace root does not exist: {root}")
    if not _has_git_marker(root):
        raise SplitMigrationError(f"workspace root is not git-backed: {root}")
    if not _is_echelon_workspace(root):
        raise SplitMigrationError(
            f"not an Echelon workspace: {root} (expected .specify/ or specs/)"
        )

    source_name = source_dir.strip("/")
    if not source_name or "/" in source_name or source_name in {".", ".."}:
        raise SplitMigrationError(f"source dir must be one simple child name: {source_dir}")
    target = root / source_name
    if target.exists():
        raise SplitMigrationError(f"source dir already exists: {target}")

    if _tracked_status_lines(root):
        raise SplitMigrationError(
            "workspace has tracked changes; commit or stash them before splitting"
        )

    keep_names = frozenset(WORKSPACE_KEEP_NAMES | LOCAL_KEEP_NAMES | {source_name})
    move_names = tuple(
        child.name
        for child in sorted(root.iterdir(), key=lambda item: item.name)
        if child.name not in keep_names
        and child.name not in TRANSIENT_DROP_NAMES
        and (not child.name.startswith(".") or child.name in SOURCE_DOT_NAMES)
    )
    drop_names = tuple(
        child.name
        for child in sorted(root.iterdir(), key=lambda item: item.name)
        if child.name in TRANSIENT_DROP_NAMES
    )
    if not move_names and not drop_names:
        raise SplitMigrationError("no source files or directories found to move")

    original_gitignore = (
        (root / ".gitignore").read_text(encoding="utf-8")
        if (root / ".gitignore").exists()
        else ""
    )
    return SourceSplitPlan(
        workspace_root=root,
        source_dir=target,
        keep_names=keep_names,
        move_names=move_names,
        drop_names=drop_names,
        original_gitignore=original_gitignore,
    )


def split_workspace_source_repo(
    workspace_root: Path,
    *,
    source_dir: str,
    write: bool,
    commit: bool,
    child_commit_message: str = "chore: initialize source repo",
    root_commit_message: str = "chore: split source repo from workspace",
) -> SourceSplitResult:
    plan = build_source_split_plan(workspace_root, source_dir=source_dir)
    if not write:
        return SourceSplitResult(
            plan=plan,
            write_requested=False,
            moved_paths=(),
            root_gitignore_updated=False,
            child_git_initialized=False,
            child_committed=False,
            root_staged=False,
            root_committed=False,
        )

    plan.source_dir.mkdir()
    moved: list[str] = []
    for name in plan.move_names:
        shutil.move(str(plan.workspace_root / name), str(plan.source_dir / name))
        moved.append(name)
    for name in plan.drop_names:
        path = plan.workspace_root / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    if plan.original_gitignore and not (plan.source_dir / ".gitignore").exists():
        (plan.source_dir / ".gitignore").write_text(plan.original_gitignore, encoding="utf-8")

    _init_child_git_repo(plan.source_dir)
    _run_git(plan.source_dir, "add", ".")
    _run_git(
        plan.source_dir,
        "-c",
        "user.name=Echelon Migration",
        "-c",
        "user.email=echelon-migration@example.invalid",
        "commit",
        "-m",
        child_commit_message,
    )

    root_gitignore_updated = _append_missing_gitignore_entries(
        plan.workspace_root,
        (f"/{plan.source_dir.name}/", "/runs/", ".harness-build-status.json"),
    )
    _run_git(plan.workspace_root, "add", "-u")
    if root_gitignore_updated:
        _run_git(plan.workspace_root, "add", ".gitignore")

    root_committed = False
    if commit:
        _run_git(plan.workspace_root, "commit", "-m", root_commit_message)
        root_committed = True

    return SourceSplitResult(
        plan=plan,
        write_requested=True,
        moved_paths=tuple(moved),
        root_gitignore_updated=root_gitignore_updated,
        child_git_initialized=True,
        child_committed=True,
        root_staged=True,
        root_committed=root_committed,
    )


def _print_result(result: SourceSplitResult) -> None:
    plan = result.plan
    print(f"Workspace: {plan.workspace_root}")
    print(f"Source dir: {plan.source_dir}")
    print("Keep at workspace root:")
    for name in sorted(plan.keep_names):
        if name != plan.source_dir.name:
            print(f"  {name}")
    print("Move into source dir:")
    for name in plan.move_names:
        print(f"  {name}")
    if plan.drop_names:
        print("Drop transient workspace files:")
        for name in plan.drop_names:
            print(f"  {name}")
    if not result.write_requested:
        print("Dry-run only. Re-run with --write to apply.")
        return
    print("Applied:")
    print(f"  moved_paths: {', '.join(result.moved_paths) or '(none)'}")
    print(f"  root_gitignore_updated: {result.root_gitignore_updated}")
    print(f"  child_git_initialized: {result.child_git_initialized}")
    print(f"  child_committed: {result.child_committed}")
    print(f"  root_staged: {result.root_staged}")
    print(f"  root_committed: {result.root_committed}")
    if not result.root_committed:
        print('Next: git commit -m "chore: split source repo from workspace"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Split an existing single-repo Echelon workspace into a lightweight workspace Git repo and child source Git repo."
    )
    parser.add_argument("workspace", nargs="?", default=".", help="Workspace root")
    parser.add_argument(
        "--source-dir",
        default="app",
        help="Child directory name for implementation source repo",
    )
    parser.add_argument("--write", action="store_true", help="Apply split")
    parser.add_argument("--commit", action="store_true", help="Commit root workspace split")
    parser.add_argument(
        "--child-message",
        default="chore: initialize source repo",
        help="Commit message for child source repo initialization",
    )
    parser.add_argument(
        "--root-message",
        default="chore: split source repo from workspace",
        help="Commit message for root workspace commit when --commit is used",
    )
    args = parser.parse_args(argv)

    try:
        result = split_workspace_source_repo(
            Path(args.workspace),
            source_dir=args.source_dir,
            write=bool(args.write or args.commit),
            commit=bool(args.commit),
            child_commit_message=args.child_message,
            root_commit_message=args.root_message,
        )
    except (SplitMigrationError, subprocess.CalledProcessError) as exc:
        print(f"split migration failed: {exc}", file=sys.stderr)
        return 1

    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
