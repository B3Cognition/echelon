"""CLI entry point for python -m harness.

Subcommands:
  run     — run the ralph-loop for a spec (reads HARNESS_* env vars)
  resume  — resume a blocked loop with an answer (reads HARNESS_* env vars)
  gitops  — GitOps operations (find-branch, create-worktree, commit-push, open-pr, merge-pr, local-merge)
  validate-tasks — validate canonical tasks.md rows
  migrate-tasks — migrate legacy tasks.md markers to canonical rows
  validate-plan — validate canonical plan.md sections
  migrate-plan — migrate legacy plan.md files to canonical sections

Environment variables for `run`:
  HARNESS_SPEC          required  spec ID (e.g., "012")
  HARNESS_MODE          optional  banzai | semi | guided  (default: semi)
  HARNESS_MAX_OUTER     optional  integer  (default: 5)
  HARNESS_MAX_INNER     optional  integer  (default: 3)
  HARNESS_STRATEGIES    optional  comma-separated strategy IDs  (default: default)
  HARNESS_AUTO_MERGE    optional  true | false  (default: false)
  HARNESS_KILL_LOSERS   optional  true | false  (default: false)
  HARNESS_TOKEN_BUDGET  optional  integer token cap  (default: unlimited)

Environment variables for `resume`:
  HARNESS_SPEC      required  spec ID
  HARNESS_STRATEGY  optional  strategy ID  (default: default)
  HARNESS_ANSWER    required  answer text for the escalation question
"""

from __future__ import annotations

import os
import sys


def _bool_env(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


def _run() -> None:
    spec_id = os.environ.get("HARNESS_SPEC", "").strip()
    if not spec_id:
        print("HARNESS_SPEC is required.", file=sys.stderr)
        sys.exit(1)

    mode = os.environ.get("HARNESS_MODE", "semi").strip()
    max_outer = int(os.environ.get("HARNESS_MAX_OUTER", "5"))
    max_inner = int(os.environ.get("HARNESS_MAX_INNER", "3"))
    strategies_csv = os.environ.get("HARNESS_STRATEGIES", "default").strip()
    auto_merge = _bool_env("HARNESS_AUTO_MERGE")
    kill_losers = _bool_env("HARNESS_KILL_LOSERS")
    token_budget_raw = os.environ.get("HARNESS_TOKEN_BUDGET", "").strip()

    # Build a message string that parse_intent can consume.
    parts = [f"spec {spec_id}", f"{mode} mode",
             f"max {max_outer} outer iterations",
             f"max {max_inner} inner iterations"]
    if strategies_csv != "default":
        parts.append(f"strategies={strategies_csv}")
    if auto_merge:
        parts.append("auto_merge")
    if kill_losers:
        parts.append("kill_losers")
    if token_budget_raw:
        parts.append(f"token_budget={token_budget_raw}")
    user_message = " ".join(parts)

    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run

    config = load_config()
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(buffer_limit_bytes=config.buffer_limit_bytes)

    run(user_message, provider, gitops)


def _resume() -> None:
    spec_id = os.environ.get("HARNESS_SPEC", "").strip()
    strategy_id = os.environ.get("HARNESS_STRATEGY", "default").strip()
    answer = os.environ.get("HARNESS_ANSWER", "").strip()

    if not spec_id:
        print("HARNESS_SPEC is required.", file=sys.stderr)
        sys.exit(1)
    if not answer:
        print("HARNESS_ANSWER is required.", file=sys.stderr)
        sys.exit(1)

    user_message = f"spec {spec_id} strategy {strategy_id} answer: {answer}"

    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.resume_skill import resume

    config = load_config()
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(buffer_limit_bytes=config.buffer_limit_bytes)

    resume(user_message, provider, gitops)


def _validate_tasks() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness validate-tasks <tasks.md>", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.task_validation import TaskValidationError, validate_tasks_file

    tasks_path = Path(sys.argv[2])
    try:
        result = validate_tasks_file(tasks_path)
    except TaskValidationError as e:
        print(f"invalid tasks.md: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"OK: {result.task_count} canonical tasks")


def _migrate_tasks() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness migrate-tasks <tasks.md> [--write]", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.task_migration import migrate_tasks_markdown
    from kernel.task_contract import validate_tasks_markdown

    tasks_path = Path(sys.argv[2])
    write = "--write" in sys.argv[3:]
    unknown = [arg for arg in sys.argv[3:] if arg != "--write"]
    if unknown:
        print(f"Unknown migrate-tasks option: {unknown[0]!r}", file=sys.stderr)
        sys.exit(1)

    migrated = migrate_tasks_markdown(
        tasks_path.read_text(encoding="utf-8", errors="replace")
    )
    result = validate_tasks_markdown(migrated)
    if not result.valid:
        print(f"invalid migrated tasks.md: {'; '.join(result.errors)}", file=sys.stderr)
        sys.exit(1)

    if write:
        tasks_path.write_text(migrated, encoding="utf-8")
        print(f"OK: migrated {result.task_count} canonical tasks")
        return

    print(migrated, end="")


def _validate_plan() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness validate-plan <plan.md>", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.plan_validation import PlanValidationError, validate_plan_file

    plan_path = Path(sys.argv[2])
    try:
        validate_plan_file(plan_path)
    except PlanValidationError as e:
        print(f"invalid plan.md: {e}", file=sys.stderr)
        sys.exit(1)

    print("OK: canonical plan.md")


def _migrate_plan() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness migrate-plan <plan.md> [--write]", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.plan_migration import migrate_plan_markdown
    from kernel.plan_contract import validate_plan_markdown

    plan_path = Path(sys.argv[2])
    write = "--write" in sys.argv[3:]
    unknown = [arg for arg in sys.argv[3:] if arg != "--write"]
    if unknown:
        print(f"Unknown migrate-plan option: {unknown[0]!r}", file=sys.stderr)
        sys.exit(1)

    migrated = migrate_plan_markdown(
        plan_path.read_text(encoding="utf-8", errors="replace")
    )
    result = validate_plan_markdown(migrated)
    if not result.valid:
        print(f"invalid migrated plan.md: {'; '.join(result.errors)}", file=sys.stderr)
        sys.exit(1)

    if write:
        plan_path.write_text(migrated, encoding="utf-8")
        print("OK: migrated canonical plan.md")
        return

    print(migrated, end="")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]

    if subcommand == "run":
        _run()
    elif subcommand == "resume":
        _resume()
    elif subcommand == "gitops":
        from harness.skills.gitops_skill import main as gitops_main
        sys.exit(gitops_main(sys.argv[2:]))
    elif subcommand == "validate-tasks":
        _validate_tasks()
    elif subcommand == "migrate-tasks":
        _migrate_tasks()
    elif subcommand == "validate-plan":
        _validate_plan()
    elif subcommand == "migrate-plan":
        _migrate_plan()
    else:
        print(
            f"Unknown subcommand: {subcommand!r}. Use 'run', 'resume', 'gitops', 'validate-tasks', 'migrate-tasks', 'validate-plan', or 'migrate-plan'.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
