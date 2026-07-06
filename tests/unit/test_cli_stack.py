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
    playbook = next(stack for stack in payload["stacks"] if stack["id"] == "statsperform-playbook")
    assert "detection" in playbook
    assert "playbook" in playbook["detection"]["positive"]["technologies"]


@pytest.mark.unit
def test_stack_detect_json_reports_suggested_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_stack

    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "react": "latest",
                    "@statsperform/react-playbook": "latest",
                }
            }
        ),
        encoding="utf-8",
    )

    _cmd_stack(["detect", "--json"], project_root=tmp_path)

    payload = json.loads(capsys.readouterr().out)
    assert payload["suggested_config"]["stacks"]["selected"] == ["statsperform-playbook"]


@pytest.mark.unit
def test_stack_detect_format_yaml_is_machine_readable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "react": "latest",
                    "@statsperform/react-playbook": "latest",
                }
            }
        ),
        encoding="utf-8",
    )

    _cmd_stack(["detect", "--format", "yaml"], project_root=tmp_path)

    payload = yaml.safe_load(capsys.readouterr().out)
    assert payload["suggested_config"]["stacks"]["selected"] == ["statsperform-playbook"]


@pytest.mark.unit
def test_stack_detect_write_persists_under_runs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_stack

    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "react": "latest",
                    "@statsperform/react-playbook": "latest",
                }
            }
        ),
        encoding="utf-8",
    )

    _cmd_stack(["detect", "--write"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "runs/stack-detect/" in out
    assert list((tmp_path / "runs" / "stack-detect").glob("*/detected.yml"))
    assert list((tmp_path / "runs" / "stack-detect").glob("*/detected.md"))


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
def test_stack_preflight_from_detect_uses_suggested_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_stack

    report = tmp_path / "detected.yml"
    report.write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                'target: "."',
                "observed_stacks: []",
                "matching_echelon_stacks: []",
                "modernization_candidates: []",
                "decisions_required: []",
                "suggested_config:",
                "  stacks:",
                "    selected:",
                "      - statsperform-playbook",
                "    target_archetypes:",
                "      - web_app",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "echelon.cli.run_stack_preflight",
        lambda resolved, **_kwargs: type(
            "Result",
            (),
            {"status": "pass", "findings": [], "has_errors": False},
        )(),
    )

    _cmd_stack(["preflight", "--from-detect", str(report)], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "statsperform-playbook" in out
    assert "Status: pass" in out


@pytest.mark.unit
def test_stack_preflight_without_selected_stacks_is_noop(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_stack

    _cmd_stack(["preflight"], project_root=tmp_path)

    assert "No Echelon stacks selected" in capsys.readouterr().out
