"""Unit tests for echelon init wing provisioning."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


def test_derive_wing_from_git_remote(tmp_path):
    with patch("echelon.cli.subprocess") as mock_subprocess:
        mock_subprocess.run.return_value = MagicMock(
            returncode=0, stdout="https://github.com/org/my-app.git\n"
        )
        from echelon.cli import _derive_wing_suggestion
        result = _derive_wing_suggestion(tmp_path)
    assert result == "my-app"


def test_derive_wing_fallback_when_no_remote(tmp_path):
    with patch("echelon.cli.subprocess") as mock_subprocess:
        mock_subprocess.run.return_value = MagicMock(returncode=1, stdout="")
        from echelon.cli import _derive_wing_suggestion
        result = _derive_wing_suggestion(tmp_path)
    # Fallback: dirname + hash
    assert result.startswith(tmp_path.name)
    assert len(result) > len(tmp_path.name)


def test_provision_wing_idempotent_when_already_set(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({
        "mempalace": {"wing": "existing-wing"},
        "deploy": {"type": "http", "blue_port": 3000, "green_port": 3001},
    }))

    from echelon.cli import _provision_wing
    with patch("builtins.print") as mock_print:
        result = _provision_wing(tmp_path, echelon_yml)

    assert result == "existing-wing"
    printed = " ".join(str(c) for c in mock_print.call_args_list)
    assert "already configured" in printed


def test_provision_wing_writes_to_echelon_yml(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({
        "deploy": {"type": "http", "blue_port": 3000, "green_port": 3001},
    }))

    with patch("echelon.cli._derive_wing_suggestion", return_value="my-app"):
        with patch("echelon.cli.check_wing_collision", return_value=[]):
            with patch("builtins.input", return_value=""):
                from echelon.cli import _provision_wing
                result = _provision_wing(tmp_path, echelon_yml)

    assert result == "my-app"
    config = yaml.safe_load(echelon_yml.read_text())
    assert config["mempalace"]["wing"] == "my-app"
    assert config["deploy"]["blue_port"] == 3000  # other keys preserved


def test_provision_wing_collision_reprompts(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"deploy": {"type": "http", "blue_port": 3000, "green_port": 3001}}))

    inputs = iter(["colliding-wing", "colliding-wing"])

    with patch("echelon.cli._derive_wing_suggestion", return_value="colliding-wing"):
        with patch("echelon.cli.check_wing_collision", side_effect=[
            ["/other/spec.md"],  # first: collision
            ["/other/spec.md"],  # second same name: force-accept
        ]):
            with patch("builtins.input", side_effect=inputs):
                from echelon.cli import _provision_wing
                result = _provision_wing(tmp_path, echelon_yml)

    assert result == "colliding-wing"
    config = yaml.safe_load(echelon_yml.read_text())
    assert config["mempalace"]["wing"] == "colliding-wing"
