"""Unit tests for MemPalaceContext."""
from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from codegen.memory.context import MemPalaceContext


def test_from_project_reads_wing_from_echelon_yml(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"mempalace": {"wing": "my-app"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        ctx = MemPalaceContext.from_project(tmp_path, run_id="run-123")

    assert ctx.wing == "my-app"
    assert ctx.run_id == "run-123"
    assert ctx.palace_path == "/fake/palace"


def test_from_project_wing_override_takes_precedence(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"mempalace": {"wing": "my-app"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        ctx = MemPalaceContext.from_project(tmp_path, run_id="run-123", wing_override="override-wing")

    assert ctx.wing == "override-wing"


def test_from_project_hard_fails_if_no_echelon_yml(tmp_path):
    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        with pytest.raises(SystemExit, match="echelon.yml not found"):
            MemPalaceContext.from_project(tmp_path, run_id="run-123")


def test_from_project_hard_fails_if_wing_not_set(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"deploy": {"type": "http"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        with pytest.raises(SystemExit, match="wing not set"):
            MemPalaceContext.from_project(tmp_path, run_id="run-123")


def test_from_project_empty_string_override_is_accepted(tmp_path):
    echelon_yml = tmp_path / "echelon.yml"
    echelon_yml.write_text(yaml.dump({"mempalace": {"wing": "from-yaml"}}))

    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        ctx = MemPalaceContext.from_project(tmp_path, run_id="r1", wing_override="")

    assert ctx.wing == ""


def test_from_wing_constructs_without_project_dir():
    with patch("codegen.memory.context._get_palace_path", return_value="/fake/palace"):
        ctx = MemPalaceContext.from_wing(wing="my-app", run_id="gate-run")

    assert ctx.wing == "my-app"
    assert ctx.run_id == "gate-run"
    assert ctx.palace_path == "/fake/palace"
