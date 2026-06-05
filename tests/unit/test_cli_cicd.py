"""Tests for the retired echelon cicd command."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_cicd_command_is_deprecated_and_does_not_start_llm(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_cicd

    with pytest.raises(SystemExit) as exc:
        _cmd_cicd(["001"])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "retired" in err
    assert "echelon harness init" in err
    assert "verify_command" in err
