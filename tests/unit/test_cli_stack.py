from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.unit
def test_stack_list_prints_bundled_stacks(capsys: pytest.CaptureFixture[str]) -> None:
    from echelon.cli import _cmd_stack

    _cmd_stack(["list"], project_root=Path(__file__).resolve().parents[2])

    out = capsys.readouterr().out
    assert "statsperform-playbook" in out
    assert "statsperform-msa-service" in out
    assert "statsperform-stark-webapp" in out


@pytest.mark.unit
def test_stack_list_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    from echelon.cli import _cmd_stack

    _cmd_stack(["list", "--json"], project_root=Path(__file__).resolve().parents[2])

    payload = json.loads(capsys.readouterr().out)
    assert "statsperform-playbook" in [stack["id"] for stack in payload["stacks"]]


@pytest.mark.unit
def test_stack_preflight_uses_explicit_stack_selection(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_stack

    monkeypatch.setattr(
        "echelon.cli.run_stack_preflight",
        lambda resolved, **_kwargs: type(
            "Result",
            (),
            {"status": "pass", "findings": [], "has_errors": False},
        )(),
    )

    _cmd_stack(
        ["preflight", "--stack", "statsperform-playbook"],
        project_root=Path(__file__).resolve().parents[2],
    )

    out = capsys.readouterr().out
    assert "statsperform-playbook" in out
    assert "Status: pass" in out


@pytest.mark.unit
def test_stack_preflight_exits_nonzero_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_stack

    monkeypatch.setattr(
        "echelon.cli.run_stack_preflight",
        lambda resolved, **_kwargs: type(
            "Result",
            (),
            {"status": "fail", "findings": [], "has_errors": True},
        )(),
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_stack(
            ["preflight", "--stack", "statsperform-playbook"],
            project_root=Path(__file__).resolve().parents[2],
        )

    assert exc.value.code == 1


@pytest.mark.unit
def test_stack_preflight_without_selected_stacks_is_noop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_stack

    _cmd_stack(["preflight"], project_root=tmp_path)

    assert "No Echelon stacks selected" in capsys.readouterr().out
