from __future__ import annotations

import pytest

from echelon.cli import _consume_mode_arg


def test_consume_mode_arg_accepts_split_form() -> None:
    mode, next_index = _consume_mode_arg(
        ["--mode", "banzai", "build notes"],
        0,
        command_name="echelon run",
    )

    assert mode == "banzai"
    assert next_index == 2


def test_consume_mode_arg_accepts_equals_form() -> None:
    mode, next_index = _consume_mode_arg(
        ["--mode=banzai", "build notes"],
        0,
        command_name="echelon run",
    )

    assert mode == "banzai"
    assert next_index == 1


def test_consume_mode_arg_ignores_non_mode_token() -> None:
    mode, next_index = _consume_mode_arg(
        ["build notes"],
        0,
        command_name="echelon run",
    )

    assert mode is None
    assert next_index == 0


def test_consume_mode_arg_rejects_missing_mode(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _consume_mode_arg(["--mode"], 0, command_name="echelon run")

    assert exc.value.code == 1
    assert "--mode requires" in capsys.readouterr().err


def test_consume_mode_arg_rejects_invalid_mode(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _consume_mode_arg(["--mode=turbo"], 0, command_name="echelon run")

    assert exc.value.code == 1
    assert "invalid mode 'turbo'" in capsys.readouterr().err
