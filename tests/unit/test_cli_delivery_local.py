"""Opt-in macOS local verification CLI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_delivery_verify_local_decline_never_starts_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Host lifecycle execution requires a fresh explicit confirmation."""
    from echelon.cli import LocalActionPlan
    from echelon.cli_app import app

    action_plan = LocalActionPlan(
        spec_id="001-demo",
        target_id="browser-game",
        engine="docker",
        candidate_fingerprint="a" * 64,
        planned_actions=("start isolated PostgreSQL",),
        digest="b" * 64,
    )
    calls: list[object] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("echelon.cli._build_local_action_plan", lambda *_args, **_kwargs: action_plan)
    monkeypatch.setattr(
        "echelon.cli._run_local_delivery_verification",
        lambda *_args, **_kwargs: calls.append("ran"),
    )

    result = CliRunner().invoke(
        app,
        ["delivery", "verify-local", "001-demo"],
        input="no\n",
    )

    assert result.exit_code == 1
    assert calls == []
    assert "No host-local resources were started" in result.output


@pytest.mark.unit
def test_delivery_verify_local_rejects_keep_on_failure_with_assume_yes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Retaining host resources may not bypass the interactive warning."""
    from echelon.cli_app import app

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["delivery", "verify-local", "001-demo", "--yes", "--keep-on-failure"],
    )

    assert result.exit_code == 1
    assert "--keep-on-failure cannot be combined with --yes" in result.output
