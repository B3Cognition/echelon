from __future__ import annotations

import json
from contextlib import chdir
from pathlib import Path

import pytest
from typer.testing import CliRunner

from echelon.cli_app import app


def _invoke_stack(project_root: Path, args: list[str]):
    with chdir(project_root):
        return CliRunner().invoke(app, ["stack", *args])


@pytest.mark.unit
def test_stack_list_prints_bundled_stacks() -> None:
    result = _invoke_stack(Path(__file__).resolve().parents[2], ["list"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "statsperform-playbook" in out
    assert "statsperform-msa-service" in out
    assert "statsperform-stark-webapp" in out


@pytest.mark.unit
def test_stack_list_json_is_machine_readable() -> None:
    result = _invoke_stack(Path(__file__).resolve().parents[2], ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "statsperform-playbook" in [stack["id"] for stack in payload["stacks"]]
    playbook = next(stack for stack in payload["stacks"] if stack["id"] == "statsperform-playbook")
    assert "detection" in playbook
    assert "playbook" in playbook["detection"]["positive"]["technologies"]


@pytest.mark.unit
def test_stack_detect_json_reports_suggested_config(
    tmp_path: Path,
) -> None:
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

    result = _invoke_stack(tmp_path, ["detect", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["suggested_config"]["stacks"]["selected"] == ["statsperform-playbook"]


@pytest.mark.unit
def test_stack_detect_format_yaml_is_machine_readable(
    tmp_path: Path,
) -> None:
    import yaml

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

    result = _invoke_stack(tmp_path, ["detect", "--format", "yaml"])

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.output)
    assert payload["suggested_config"]["stacks"]["selected"] == ["statsperform-playbook"]


@pytest.mark.unit
def test_stack_detect_write_persists_under_runs(
    tmp_path: Path,
) -> None:
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

    result = _invoke_stack(tmp_path, ["detect", "--write"])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "runs/stack-detect/" in out
    assert list((tmp_path / "runs" / "stack-detect").glob("*/detected.yml"))
    assert list((tmp_path / "runs" / "stack-detect").glob("*/detected.md"))


@pytest.mark.unit
def test_stack_preflight_uses_explicit_stack_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.stack_service.run_stack_preflight",
        lambda resolved, **_kwargs: type(
            "Result",
            (),
            {"status": "pass", "findings": [], "has_errors": False},
        )(),
    )

    result = _invoke_stack(
        Path(__file__).resolve().parents[2],
        ["preflight", "--stack", "statsperform-playbook"],
    )

    assert result.exit_code == 0, result.output
    out = result.output
    assert "statsperform-playbook" in out
    assert "Status: pass" in out


@pytest.mark.unit
def test_stack_preflight_exits_nonzero_when_preflight_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "echelon.stack_service.run_stack_preflight",
        lambda resolved, **_kwargs: type(
            "Result",
            (),
            {"status": "fail", "findings": [], "has_errors": True},
        )(),
    )

    result = _invoke_stack(
        Path(__file__).resolve().parents[2],
        ["preflight", "--stack", "statsperform-playbook"],
    )

    assert result.exit_code == 1


@pytest.mark.unit
def test_stack_preflight_from_detect_uses_suggested_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "echelon.stack_service.run_stack_preflight",
        lambda resolved, **_kwargs: type(
            "Result",
            (),
            {"status": "pass", "findings": [], "has_errors": False},
        )(),
    )

    result = _invoke_stack(tmp_path, ["preflight", "--from-detect", str(report)])

    assert result.exit_code == 0, result.output
    out = result.output
    assert "statsperform-playbook" in out
    assert "Status: pass" in out


@pytest.mark.unit
def test_stack_preflight_without_selected_stacks_is_noop(
    tmp_path: Path,
) -> None:
    result = _invoke_stack(tmp_path, ["preflight"])

    assert result.exit_code == 0, result.output
    assert "No Echelon stacks selected" in result.output


@pytest.mark.unit
def test_stack_provision_writes_target_local_files(
    tmp_path: Path,
) -> None:
    result = _invoke_stack(
        tmp_path,
        [
            "provision",
            "--stack",
            "game-persistence-postgres",
            "--target",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "docker-compose.echelon-verify.yml").is_file()
    assert (tmp_path / ".env.echelon-verify.example").is_file()
    assert (
        "docker compose -f docker-compose.echelon-verify.yml up -d"
        in result.output
    )


@pytest.mark.unit
def test_stack_list_json_exposes_provisioners() -> None:
    result = _invoke_stack(Path(__file__).resolve().parents[2], ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    postgres = next(
        stack for stack in payload["stacks"] if stack["id"] == "game-persistence-postgres"
    )
    assert postgres["provisioners"][0]["id"] == "postgres-verify"


@pytest.mark.unit
def test_stack_list_bypasses_legacy_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_legacy_cli():
        raise AssertionError("stack list must not load echelon.cli")

    monkeypatch.setattr(
        "echelon.cli_app._legacy_cli",
        fail_legacy_cli,
        raising=False,
    )

    result = CliRunner().invoke(app, ["stack", "list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "statsperform-playbook" in [stack["id"] for stack in payload["stacks"]]


@pytest.mark.unit
def test_stack_detect_bypasses_legacy_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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

    def fail_legacy_cli():
        raise AssertionError("stack detect must not load echelon.cli")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli_app._legacy_cli",
        fail_legacy_cli,
        raising=False,
    )

    result = CliRunner().invoke(app, ["stack", "detect", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["suggested_config"]["stacks"]["selected"] == [
        "statsperform-playbook"
    ]


@pytest.mark.unit
def test_stack_preflight_bypasses_legacy_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_legacy_cli():
        raise AssertionError("stack preflight must not load echelon.cli")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli_app._legacy_cli",
        fail_legacy_cli,
        raising=False,
    )

    result = CliRunner().invoke(app, ["stack", "preflight", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "status": "pass",
        "message": (
            "No Echelon stacks selected. Use --stack <id> or configure "
            "stacks.selected."
        ),
        "selected": [],
    }


@pytest.mark.unit
def test_stack_provision_bypasses_legacy_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_legacy_cli():
        raise AssertionError("stack provision must not load echelon.cli")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli_app._legacy_cli",
        fail_legacy_cli,
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        [
            "stack",
            "provision",
            "--stack",
            "game-persistence-postgres",
            "--target",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "docker-compose.echelon-verify.yml").is_file()
    assert (tmp_path / ".env.echelon-verify.example").is_file()
    assert "Echelon did not start Docker" in result.output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("args", "initial_selection", "expected"),
    (
        (
            ["enable", "statsperform-playbook", "--dry-run"],
            [],
            "Dry run: Enabled stacks: statsperform-playbook",
        ),
        (
            ["disable", "statsperform-playbook", "--dry-run"],
            ["statsperform-playbook"],
            "Dry run: Disabled stacks: statsperform-playbook",
        ),
        (
            ["select", "statsperform-playbook", "--dry-run"],
            [],
            "Dry run: Selected stacks: statsperform-playbook",
        ),
        (
            ["selected"],
            [],
            "Explicit stacks: none",
        ),
    ),
)
def test_stack_selection_commands_bypass_legacy_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    args: list[str],
    initial_selection: list[str],
    expected: str,
) -> None:
    import yaml

    config_dir = tmp_path / ".echelon"
    config_dir.mkdir()
    (config_dir / "config.yml").write_text(
        yaml.safe_dump({"stacks": {"selected": initial_selection}}, sort_keys=False),
        encoding="utf-8",
    )

    def fail_legacy_cli():
        raise AssertionError("stack selection commands must not load echelon.cli")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.cli_app._legacy_cli",
        fail_legacy_cli,
        raising=False,
    )

    result = CliRunner().invoke(app, ["stack", *args])

    assert result.exit_code == 0, result.output
    assert expected in result.output
