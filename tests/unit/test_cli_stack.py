from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_workspace_config(root: Path, text: str = "stacks:\n  selected: []\n") -> Path:
    config_path = root / ".echelon" / "config.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(text, encoding="utf-8")
    return config_path


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


@pytest.mark.unit
def test_stack_enable_persists_an_explicit_selection_idempotently(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(tmp_path)

    _cmd_stack(["enable", "statsperform-playbook"], project_root=tmp_path)
    _cmd_stack(["enable", "statsperform-playbook"], project_root=tmp_path)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == {
        "stacks": {"selected": ["statsperform-playbook"]}
    }
    assert "Enabled stacks: statsperform-playbook" in capsys.readouterr().out


@pytest.mark.unit
def test_stack_select_replaces_then_clears_explicit_selection(tmp_path: Path) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(
        tmp_path,
        "stacks:\n  selected:\n    - statsperform-playbook\n",
    )

    _cmd_stack(["select", "statsperform-msa-service"], project_root=tmp_path)
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["stacks"]["selected"] == [
        "statsperform-msa-service"
    ]

    _cmd_stack(["select"], project_root=tmp_path)
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["stacks"]["selected"] == []


@pytest.mark.unit
def test_stack_disable_removes_only_explicitly_selected_stack(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(
        tmp_path,
        "stacks:\n  selected:\n    - statsperform-playbook\n    - statsperform-msa-service\n",
    )

    _cmd_stack(["disable", "statsperform-playbook"], project_root=tmp_path)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["stacks"]["selected"] == [
        "statsperform-msa-service"
    ]
    assert "Disabled stacks: statsperform-playbook" in capsys.readouterr().out


@pytest.mark.unit
def test_stack_enable_preserves_unrelated_config_comments(tmp_path: Path) -> None:
    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(
        tmp_path,
        "# Project-owned settings\nproject: example\nstacks:\n  # Keep this note\n  selected: []\n",
    )

    _cmd_stack(["enable", "statsperform-playbook"], project_root=tmp_path)

    written = config_path.read_text(encoding="utf-8")
    assert "# Project-owned settings" in written
    assert "  # Keep this note" in written
    assert "project: example" in written


@pytest.mark.unit
def test_stack_enable_accepts_null_stack_fields(tmp_path: Path) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(
        tmp_path,
        "stacks:\n  selected: null\n  target_archetypes: null\n",
    )

    _cmd_stack(["enable", "statsperform-playbook"], project_root=tmp_path)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["stacks"]["selected"] == [
        "statsperform-playbook"
    ]


@pytest.mark.unit
def test_stack_enable_does_not_modify_nested_selected_key(tmp_path: Path) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(
        tmp_path,
        "stacks:\n  metadata:\n    selected: keep\n",
    )

    _cmd_stack(["enable", "statsperform-playbook"], project_root=tmp_path)

    stacks = yaml.safe_load(config_path.read_text(encoding="utf-8"))["stacks"]
    assert stacks["metadata"]["selected"] == "keep"
    assert stacks["selected"] == ["statsperform-playbook"]


@pytest.mark.unit
def test_stack_enable_updates_flow_style_stacks_mapping(tmp_path: Path) -> None:
    import yaml

    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(
        tmp_path,
        "# Keep this comment\nstacks: {selected: []}\n",
    )

    _cmd_stack(["enable", "statsperform-playbook"], project_root=tmp_path)

    written = config_path.read_text(encoding="utf-8")
    assert yaml.safe_load(written)["stacks"]["selected"] == [
        "statsperform-playbook"
    ]
    assert written.count("stacks:") == 1
    assert "# Keep this comment" in written


@pytest.mark.unit
def test_stack_enable_rejects_unknown_stack_without_modifying_config(tmp_path: Path) -> None:
    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cmd_stack(["enable", "unknown-stack"], project_root=tmp_path)

    assert exc.value.code == 1
    assert config_path.read_text(encoding="utf-8") == before


@pytest.mark.unit
def test_stack_enable_dry_run_does_not_modify_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_stack

    config_path = _write_workspace_config(tmp_path)
    before = config_path.read_text(encoding="utf-8")

    _cmd_stack(
        ["enable", "statsperform-playbook", "--dry-run"],
        project_root=tmp_path,
    )

    assert config_path.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "stacks:\n  selected:\n  - statsperform-playbook" in out


@pytest.mark.unit
def test_stack_selected_reports_local_override(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_stack

    _write_workspace_config(
        tmp_path,
        "stacks:\n  selected:\n    - statsperform-playbook\n",
    )
    local_path = tmp_path / ".echelon" / "local.yml"
    local_path.write_text(
        "stacks:\n  selected:\n    - statsperform-msa-service\n",
        encoding="utf-8",
    )

    _cmd_stack(["selected", "--json"], project_root=tmp_path)

    payload = json.loads(capsys.readouterr().out)
    assert payload["explicit"] == ["statsperform-playbook"]
    assert payload["effective"] == ["statsperform-msa-service"]
    assert payload["local_override"] is True
