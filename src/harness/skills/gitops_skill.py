"""GitOps skill CLI entry point.

Exposes GitOpsManager operations as a CLI so harness.run.md can call them
as one-liners instead of embedding multi-line Python in bash -c strings.

Usage (via __main__.py):
  python -m harness gitops <subcommand> [args]

Subcommands:
  find-branch <spec_id>
  create-worktree <spec_id> <strategy> <outer_iter> [--base-branch <branch>]
  commit-push <worktree_path> <push_branch> <message>
  open-pr <push_branch> <spec_id> <strategy> <spec_name>
  merge-pr <pr_url>
  local-merge <push_branch> <spec_id> <spec_name>
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from harness.config import load_config
from harness.gitops import GitOpsManager


def _make_gitops() -> GitOpsManager:
    return GitOpsManager(load_config())


def cmd_find_branch(args: argparse.Namespace) -> int:
    gitops = _make_gitops()
    branch = gitops.find_feature_branch(args.spec_id)
    print(branch or "")
    return 0


def cmd_create_worktree(args: argparse.Namespace) -> int:
    gitops = _make_gitops()
    base_branch = args.base_branch if args.base_branch else None
    path = gitops.create_worktree(
        args.spec_id,
        args.strategy,
        args.outer_iter,
        base_branch=base_branch,
    )
    print(path)
    return 0


def cmd_commit_push(args: argparse.Namespace) -> int:
    gitops = _make_gitops()
    gitops.commit(args.worktree_path, args.message)
    gitops.push(args.worktree_path, args.push_branch)
    print("branch:", args.push_branch)
    return 0


def cmd_open_pr(args: argparse.Namespace) -> int:
    gitops = _make_gitops()
    pr_url = gitops.find_existing_pr(args.push_branch)
    if not pr_url:
        pr_url = gitops.create_draft_pr(
            args.push_branch, args.spec_id, args.strategy, args.spec_name,
        )
        gitops.promote_pr_ready(pr_url)
    print("pr_url:", pr_url)
    return 0


def cmd_merge_pr(args: argparse.Namespace) -> int:
    gitops = _make_gitops()
    merged = gitops.merge_pr(args.pr_url)
    print("merged:", merged)
    return 0


def cmd_local_merge(args: argparse.Namespace) -> int:
    gitops = _make_gitops()
    gitops.local_merge(args.push_branch, args.spec_id, args.spec_name)
    print("merged: True")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness gitops",
        description="GitOps operations for the harness.",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("find-branch", help="Find echelon feature branch for a spec")
    p.add_argument("spec_id")

    p = sub.add_parser("create-worktree", help="Create worktree from mirror")
    p.add_argument("spec_id")
    p.add_argument("strategy")
    p.add_argument("outer_iter", type=int)
    p.add_argument("--base-branch", default="")

    p = sub.add_parser("commit-push", help="Stage, commit, and push worktree")
    p.add_argument("worktree_path")
    p.add_argument("push_branch")
    p.add_argument("message")

    p = sub.add_parser("open-pr", help="Find or create and promote a PR")
    p.add_argument("push_branch")
    p.add_argument("spec_id")
    p.add_argument("strategy")
    p.add_argument("spec_name")

    p = sub.add_parser("merge-pr", help="Merge a PR")
    p.add_argument("pr_url")

    p = sub.add_parser("local-merge", help="Merge in mirror and push default branch (no PR tool)")
    p.add_argument("push_branch")
    p.add_argument("spec_id")
    p.add_argument("spec_name")

    args = parser.parse_args(argv)

    _handlers = {
        "find-branch": cmd_find_branch,
        "create-worktree": cmd_create_worktree,
        "commit-push": cmd_commit_push,
        "open-pr": cmd_open_pr,
        "merge-pr": cmd_merge_pr,
        "local-merge": cmd_local_merge,
    }

    try:
        return _handlers[args.subcommand](args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
