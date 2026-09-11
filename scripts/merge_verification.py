#!/usr/bin/env python3
"""Conservative, Git-bound verification planning for local merges.

This helper deliberately selects a focused suite only for the small, curated
CLI surface.  Every other source, runtime, dependency, or unknown change uses
the repository's existing full-unit command.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Iterable
from uuid import uuid4


FULL_UNIT_COMMAND = ("pytest", "-q", "-m", "unit")
FOCUSED_CLI_COMMAND = (
    "pytest",
    "-q",
    "tests/unit/test_cli_delivery.py",
    "tests/unit/test_cli_delivery_status.py",
    "tests/unit/test_cli_typer_app.py",
)

_FOCUSED_CLI_PATHS = frozenset(
    {
        "src/echelon/cli.py",
        "src/echelon/cli_app.py",
        "src/echelon/delivery_status.py",
    }
)
_FOCUSED_CLI_COMPANION_PATHS = frozenset(
    {
        "CHANGELOG.md",
        "tests/unit/test_cli_delivery.py",
        "tests/unit/test_cli_delivery_status.py",
        "tests/unit/test_cli_typer_app.py",
    }
)


@dataclass(frozen=True)
class VerificationPlan:
    """A deterministic command plan tied to one candidate Git tree."""

    base_commit: str
    candidate_commit: str
    candidate_tree: str
    changed_paths: tuple[str, ...]
    scope: str
    commands: tuple[tuple[str, ...], ...]
    requires_full_suite: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CommandResult:
    """Minimal command evidence suitable for a local merge receipt."""

    command: tuple[str, ...]
    exit_code: int
    duration_ms: int


@dataclass(frozen=True)
class ReceiptValidation:
    valid: bool
    reason: str = ""


def plan_for_changed_paths(
    *,
    base_commit: str,
    candidate_commit: str,
    candidate_tree: str,
    changed_paths: Iterable[str],
) -> VerificationPlan:
    """Classify changed paths without guessing dependency relationships."""
    paths = tuple(sorted({path.strip().lstrip("./") for path in changed_paths if path.strip()}))
    path_set = set(paths)
    focused_cli = (
        bool(path_set & _FOCUSED_CLI_PATHS)
        and path_set.issubset(_FOCUSED_CLI_PATHS | _FOCUSED_CLI_COMPANION_PATHS)
    )
    if focused_cli:
        return VerificationPlan(
            base_commit=base_commit,
            candidate_commit=candidate_commit,
            candidate_tree=candidate_tree,
            changed_paths=paths,
            scope="focused-cli",
            commands=(FOCUSED_CLI_COMMAND,),
            requires_full_suite=False,
        )
    return VerificationPlan(
        base_commit=base_commit,
        candidate_commit=candidate_commit,
        candidate_tree=candidate_tree,
        changed_paths=paths,
        scope="full-unit",
        commands=(FULL_UNIT_COMMAND,),
        requires_full_suite=True,
    )


def write_receipt(
    *,
    reports_dir: Path,
    plan: VerificationPlan,
    results: Iterable[CommandResult],
) -> Path:
    """Write one immutable local receipt for a completed verification plan."""
    root = Path(reports_dir) / "merge-verification"
    if root.is_symlink():
        raise OSError("merge verification receipt directory must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    collected = tuple(results)
    payload = {
        "schema_version": 1,
        "status": "passed" if collected and all(result.exit_code == 0 for result in collected) else "failed",
        "plan": plan.as_dict(),
        "results": [asdict(result) for result in collected],
    }
    receipt = root / f"receipt-{plan.candidate_commit[:12]}-{uuid4().hex}.json"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=root, prefix=".receipt-", suffix=".tmp", delete=False
    ) as temporary:
        json.dump(payload, temporary, sort_keys=True, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, receipt)
    return receipt


def confirm_fast_forward(
    *,
    receipt_path: Path,
    current_commit: str,
    current_tree: str,
) -> ReceiptValidation:
    """Accept only a passing receipt for this exact checked-out Git tree."""
    try:
        payload = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return ReceiptValidation(False, f"receipt is unavailable or malformed: {error}")
    if payload.get("schema_version") != 1:
        return ReceiptValidation(False, "receipt schema is unsupported")
    if payload.get("status") != "passed":
        return ReceiptValidation(False, "receipt did not record a passing verification")
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return ReceiptValidation(False, "receipt plan is unavailable")
    if plan.get("candidate_commit") != current_commit:
        return ReceiptValidation(False, "receipt candidate commit does not match HEAD")
    if plan.get("candidate_tree") != current_tree:
        return ReceiptValidation(False, "receipt candidate tree does not match HEAD")
    return ReceiptValidation(True)


def run_plan(*, repo_root: Path, reports_dir: Path, plan: VerificationPlan) -> Path:
    """Execute a plan in order and persist its compact, Git-bound result."""
    results: list[CommandResult] = []
    for command in plan.commands:
        started = time.monotonic()
        completed = subprocess.run(command, cwd=repo_root, check=False)
        duration_ms = int((time.monotonic() - started) * 1000)
        results.append(
            CommandResult(
                command=command,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
            )
        )
        if completed.returncode != 0:
            break
    return write_receipt(reports_dir=reports_dir, plan=plan, results=results)


def validate_candidate_checkout(
    *, candidate_commit: str, current_commit: str, porcelain_status: str
) -> None:
    """Reject evidence when execution would differ from the recorded candidate."""
    if current_commit != candidate_commit:
        raise RuntimeError("candidate ref is not the checked-out HEAD")
    if porcelain_status.strip():
        raise RuntimeError("working tree is dirty; commit or stash changes before verification")


def build_plan_from_git(
    *, repo_root: Path, base_ref: str, head_ref: str = "HEAD"
) -> VerificationPlan:
    """Build a plan from a Git range while resolving immutable identifiers."""
    base_commit = _git_output(repo_root, "rev-parse", base_ref)
    candidate_commit = _git_output(repo_root, "rev-parse", head_ref)
    candidate_tree = _git_output(repo_root, "rev-parse", f"{candidate_commit}^{{tree}}")
    changed = _git_output(repo_root, "diff", "--name-only", f"{base_commit}...{candidate_commit}")
    return plan_for_changed_paths(
        base_commit=base_commit,
        candidate_commit=candidate_commit,
        candidate_tree=candidate_tree,
        changed_paths=changed.splitlines(),
    )


def _git_output(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        command = subcommands.add_parser(name)
        command.add_argument("--base", required=True, help="tested base Git ref")
        command.add_argument("--head", default="HEAD", help="candidate Git ref")
        command.add_argument("--repo", type=Path, default=Path.cwd())
    confirm = subcommands.add_parser("confirm-fast-forward")
    confirm.add_argument("--receipt", type=Path, required=True)
    confirm.add_argument("--repo", type=Path, default=Path.cwd())
    return parser


def main(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    repo_root = args.repo.resolve()
    try:
        if args.command in {"plan", "run"}:
            plan = build_plan_from_git(
                repo_root=repo_root,
                base_ref=args.base,
                head_ref=args.head,
            )
            if args.command == "plan":
                print(json.dumps(plan.as_dict(), indent=2, sort_keys=True))
                return 0
            validate_candidate_checkout(
                candidate_commit=plan.candidate_commit,
                current_commit=_git_output(repo_root, "rev-parse", "HEAD"),
                porcelain_status=_git_output(repo_root, "status", "--porcelain"),
            )
            receipt = run_plan(
                repo_root=repo_root,
                reports_dir=repo_root / "tests" / "reports",
                plan=plan,
            )
            validation = confirm_fast_forward(
                receipt_path=receipt,
                current_commit=plan.candidate_commit,
                current_tree=plan.candidate_tree,
            )
            print(f"receipt: {receipt}")
            print(f"scope: {plan.scope}")
            return 0 if validation.valid else 1
        current_commit = _git_output(repo_root, "rev-parse", "HEAD")
        current_tree = _git_output(repo_root, "rev-parse", "HEAD^{tree}")
        validation = confirm_fast_forward(
            receipt_path=args.receipt,
            current_commit=current_commit,
            current_tree=current_tree,
        )
        if validation.valid:
            print("fast-forward verification evidence matches HEAD")
            return 0
        print(f"fast-forward verification evidence rejected: {validation.reason}")
        return 1
    except RuntimeError as error:
        print(f"merge verification failed: {error}")
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
