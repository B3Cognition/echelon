"""The public CLI exposes only the current namespaced command surface."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from echelon.cli_app import app


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "init",
        "cicd",
        "artifacts",
        "land",
        "status",
        "continue",
        "rewind",
        "resume",
        "run",
        "build",
        "review",
        "codegen",
        "verify-spec",
        "reopen",
        "bugfix",
        "change",
        "harness",
    ],
)
def test_legacy_command_alias_is_not_exposed(command: str) -> None:
    result = CliRunner().invoke(app, [command, "--help"])

    assert result.exit_code == 2
    assert f"No such command '{command}'" in result.output


@pytest.mark.unit
def test_delivery_namespace_remains_exposed() -> None:
    result = CliRunner().invoke(app, ["delivery", "--help"])

    assert result.exit_code == 0
    assert "run" in result.output
