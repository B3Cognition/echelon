"""Tests for conservative, Git-bound merge verification selection."""

from __future__ import annotations

from dataclasses import replace
import sys

from scripts.merge_verification import (
    FULL_UNIT_COMMAND,
    FOCUSED_CLI_COMMAND,
    CommandResult,
    confirm_fast_forward,
    plan_for_changed_paths,
    run_plan,
    validate_candidate_checkout,
    write_receipt,
)


def test_cli_only_changes_select_the_curated_cli_suite() -> None:
    plan = plan_for_changed_paths(
        base_commit="base",
        candidate_commit="candidate",
        candidate_tree="tree",
        changed_paths=("src/echelon/delivery_status.py", "src/echelon/cli_app.py"),
    )

    assert plan.scope == "focused-cli"
    assert plan.commands == (FOCUSED_CLI_COMMAND,)
    assert plan.requires_full_suite is False


def test_cli_changes_allow_only_their_curated_test_and_changelog_companions() -> None:
    plan = plan_for_changed_paths(
        base_commit="base",
        candidate_commit="candidate",
        candidate_tree="tree",
        changed_paths=(
            "CHANGELOG.md",
            "src/echelon/delivery_status.py",
            "tests/unit/test_cli_delivery_status.py",
        ),
    )

    assert plan.scope == "focused-cli"
    assert plan.commands == (FOCUSED_CLI_COMMAND,)


def test_unknown_or_shared_changes_fail_closed_to_the_full_unit_suite() -> None:
    plan = plan_for_changed_paths(
        base_commit="base",
        candidate_commit="candidate",
        candidate_tree="tree",
        changed_paths=("src/harness/state.py",),
    )

    assert plan.scope == "full-unit"
    assert plan.commands == (FULL_UNIT_COMMAND,)
    assert plan.requires_full_suite is True


def test_fast_forward_confirmation_accepts_only_the_tested_commit_and_tree(
    tmp_path,
) -> None:
    plan = plan_for_changed_paths(
        base_commit="base",
        candidate_commit="candidate",
        candidate_tree="tree",
        changed_paths=("src/echelon/delivery_status.py",),
    )
    receipt = write_receipt(
        reports_dir=tmp_path,
        plan=plan,
        results=(CommandResult(command=FOCUSED_CLI_COMMAND, exit_code=0, duration_ms=12),),
    )

    assert confirm_fast_forward(
        receipt_path=receipt,
        current_commit="candidate",
        current_tree="tree",
    ).valid is True
    assert confirm_fast_forward(
        receipt_path=receipt,
        current_commit="merge-commit",
        current_tree="tree",
    ).valid is False
    assert confirm_fast_forward(
        receipt_path=receipt,
        current_commit="candidate",
        current_tree="changed-tree",
    ).valid is False


def test_run_plan_executes_commands_and_records_a_passing_receipt(tmp_path) -> None:
    plan = replace(
        plan_for_changed_paths(
            base_commit="base",
            candidate_commit="candidate",
            candidate_tree="tree",
            changed_paths=("src/echelon/delivery_status.py",),
        ),
        commands=((sys.executable, "-c", "raise SystemExit(0)"),),
    )

    receipt = run_plan(repo_root=tmp_path, reports_dir=tmp_path, plan=plan)

    assert confirm_fast_forward(
        receipt_path=receipt,
        current_commit="candidate",
        current_tree="tree",
    ).valid is True


def test_candidate_checkout_validation_refuses_dirty_or_non_head_candidates() -> None:
    assert validate_candidate_checkout(
        candidate_commit="candidate",
        current_commit="candidate",
        porcelain_status="",
    ) is None

    for current_commit, porcelain_status in (
        ("other", ""),
        ("candidate", " M src/echelon/cli.py\n"),
    ):
        try:
            validate_candidate_checkout(
                candidate_commit="candidate",
                current_commit=current_commit,
                porcelain_status=porcelain_status,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected candidate checkout validation to fail")
