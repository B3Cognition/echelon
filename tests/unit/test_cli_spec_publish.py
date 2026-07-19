"""CLI contract for local spec catalog publication."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.cli_app import app
from echelon.spec_publish import PublishedSpec, SpecPublishResult


def _result_fixture(*, created_commit: bool = True) -> SpecPublishResult:
    return SpecPublishResult(
        default_branch="main",
        previous_default_commit="a" * 40,
        default_commit="b" * 40 if created_commit else "a" * 40,
        created_commit=created_commit,
        destination_worktree=Path("/tmp/echelon-main"),
        caller_on_default=False,
        published=(
            PublishedSpec(
                spec_id="003-add-feature-opta-search",
                source_branch="003-add-feature-opta-search",
                source_commit="c" * 40,
                changed=created_commit,
            ),
        ),
    )


@pytest.mark.unit
def test_publish_help_explains_spec_only_local_behavior() -> None:
    result = CliRunner().invoke(app, ["spec", "publish", "--help"])

    assert result.exit_code == 0
    assert "committed spec snapshots" in result.output
    assert "does not merge implementation history" in result.output
    assert "local branches only" in result.output
    assert "does not fetch, push, or delete" in result.output
    assert "--all" in result.output


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    [["spec", "publish"], ["spec", "publish", "003", "--all"]],
)
def test_publish_requires_exactly_one_command_form(args: list[str]) -> None:
    result = CliRunner().invoke(app, args)

    assert result.exit_code != 0
    assert "exactly one" in result.output


@pytest.mark.unit
def test_publish_success_reports_commit_retained_branches_and_no_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.spec_publish.publish_specs",
        lambda *_args, **_kwargs: _result_fixture(),
    )

    result = CliRunner().invoke(app, ["spec", "publish", "003"])

    assert result.exit_code == 0
    assert "003-add-feature-opta-search" in result.output
    assert "Source branches retained" in result.output
    assert "Nothing was pushed" in result.output
    assert "git push origin main" in result.output
    assert "echelon wiki build" in result.output


@pytest.mark.unit
def test_publish_noop_is_reported_without_claiming_a_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.spec_publish.publish_specs",
        lambda *_args, **_kwargs: _result_fixture(created_commit=False),
    )

    result = CliRunner().invoke(app, ["spec", "publish", "003"])

    assert result.exit_code == 0
    assert "No publication commit was needed" in result.output


@pytest.mark.unit
def test_publish_service_error_has_operator_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.spec_publish import SpecPublishError

    def fail(*_args: object, **_kwargs: object) -> SpecPublishResult:
        raise SpecPublishError("source branch 003-search has uncommitted changes")

    monkeypatch.setattr("echelon.spec_publish.publish_specs", fail)

    result = CliRunner().invoke(app, ["spec", "publish", "003"])

    assert result.exit_code == 1
    assert "Spec publish failed:" in result.output
    assert "uncommitted changes" in result.output
