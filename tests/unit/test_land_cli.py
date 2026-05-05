"""Tests for `echelon land <spec-id>` CLI command."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestCmdLand:
    """Verify _cmd_land wires arguments correctly and exits with proper codes."""

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_calls_land_with_correct_args(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """land() is called with spec_id, project_dir, and gitops."""
        from echelon.cli import _cmd_land

        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_gitops = MagicMock()
        mock_gitops_cls.return_value = mock_gitops
        mock_land.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 0
        mock_land.assert_called_once_with(
            "042",
            project_dir=Path.cwd(),
            gitops=mock_gitops,
        )

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_exit_code_0_on_success(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """Exit code 0 when land() returns True."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 0

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_exit_code_1_on_failure(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """Exit code 1 when land() returns False."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land(["042"])

        assert exc_info.value.code == 1

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_prints_success_message(
        self, mock_load_config, mock_gitops_cls, mock_land, capsys
    ):
        """A success message is printed when land() returns True."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["042"])

        captured = capsys.readouterr()
        assert "042" in captured.out
        assert "landed" in captured.out.lower()

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_prints_failure_message(
        self, mock_load_config, mock_gitops_cls, mock_land, capsys
    ):
        """A failure message is printed to stderr when land() returns False."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = False

        with pytest.raises(SystemExit):
            _cmd_land(["042"])

        captured = capsys.readouterr()
        assert "042" in captured.err

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_gitops_instantiated_with_config(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """GitOpsManager is instantiated with the loaded config."""
        from echelon.cli import _cmd_land

        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        mock_gitops_cls.return_value = MagicMock()
        mock_land.return_value = True

        with pytest.raises(SystemExit):
            _cmd_land(["099"])

        mock_gitops_cls.assert_called_once_with(mock_config)

    @patch("echelon.cli.land")
    @patch("echelon.cli.GitOpsManager")
    @patch("echelon.cli.load_config")
    def test_land_exception_propagates(
        self, mock_load_config, mock_gitops_cls, mock_land
    ):
        """If land() raises an exception, it propagates (not silently caught)."""
        from echelon.cli import _cmd_land

        mock_load_config.return_value = MagicMock()
        mock_gitops_cls.return_value = MagicMock()
        mock_land.side_effect = RuntimeError("unexpected")

        with pytest.raises(RuntimeError, match="unexpected"):
            _cmd_land(["042"])

    def test_no_args_shows_help(self, capsys):
        """Calling land with no arguments shows help and exits 0."""
        from echelon.cli import _cmd_land

        with pytest.raises(SystemExit) as exc_info:
            _cmd_land([])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Usage" in captured.out
