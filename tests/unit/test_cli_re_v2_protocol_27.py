from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_parse_v2_synthesis_uses_existing_resource_flag_names() -> None:
    from echelon.cli import _parse_re_synthesize_v2_options

    options = _parse_re_synthesize_v2_options(
        [
            "--from-run",
            "re-parent",
            "--accept-partial",
            "web",
            "--accept-partial=api",
            "--token-limit",
            "400000",
            "--active-ms-limit=600000",
        ]
    )

    assert options.from_run == "re-parent"
    assert options.accepted_partial_sources == ("api", "web")
    assert options.token_limit == 400000
    assert options.active_ms_limit == 600000


@pytest.mark.unit
@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "--from-run is required"),
        (["--from-run", "re-parent", "--token-limit", "0"], "positive integer"),
        (
            [
                "--from-run",
                "re-parent",
                "--accept-partial",
                "api",
                "--accept-partial",
                "api",
            ],
            "duplicate --accept-partial",
        ),
        (["--from-run", "re-parent", "--allow-partial"], "unknown option"),
    ],
)
def test_parse_v2_synthesis_rejects_ambiguous_or_legacy_options(
    args: list[str],
    message: str,
) -> None:
    from echelon.cli import _parse_re_synthesize_v2_options

    with pytest.raises(ValueError, match=message):
        _parse_re_synthesize_v2_options(args)


@pytest.mark.unit
def test_from_run_routes_to_v2_without_entering_legacy_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli

    observed: list[list[str]] = []
    monkeypatch.setattr(
        cli,
        "_cmd_re_synthesize_v2",
        lambda args: observed.append(list(args)),
    )

    cli._cmd_re_synthesize(["--from-run", "re-parent"])

    assert observed == [["--from-run", "re-parent"]]


@pytest.mark.unit
def test_status_accepts_explicit_protocol_27_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_re_status
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis
    from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
    from tests.unit.test_re_v2_protocol_27_publication import _completed_context

    context = _completed_context(tmp_path)
    run_protocol_27_synthesis(
        context.paths.root.parent,
        lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    )
    monkeypatch.chdir(tmp_path)

    _cmd_re_status(["re-synthesis-child", "--json"])

    assert '"engine_protocol_version": "2.7"' in capsys.readouterr().out


@pytest.mark.unit
def test_continue_accepts_explicit_protocol_27_run_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli
    from harness.re_v2.protocol_27.inputs import create_protocol_27_run_store
    from tests.unit.test_re_v2_protocol_27_inputs import _input_set

    run_dir = tmp_path / "runs/re-synthesis-child"
    create_protocol_27_run_store(run_dir, _input_set(run_dir.name))
    observed: list[Path] = []
    monkeypatch.setattr(
        cli,
        "_run_re_v2_continue",
        lambda selected, **_options: observed.append(selected),
    )
    monkeypatch.chdir(tmp_path)

    cli._cmd_re_continue([run_dir.name])

    assert observed == [run_dir]


@pytest.mark.unit
def test_public_cli_routes_protocol_27_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli
    from echelon.cli_app import app

    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        cli,
        "_cmd_re_status",
        lambda args: calls.append(("status", list(args))),
    )
    monkeypatch.setattr(
        cli,
        "_cmd_re_continue",
        lambda args: calls.append(("continue", list(args))),
    )
    monkeypatch.setattr(
        cli,
        "_cmd_re_synthesize",
        lambda args: calls.append(("synthesize", list(args))),
    )
    runner = CliRunner()

    assert runner.invoke(app, ["re", "status", "re-child", "--json"]).exit_code == 0
    assert runner.invoke(app, ["re", "continue", "re-child"]).exit_code == 0
    result = runner.invoke(
        app,
        [
            "re",
            "synthesize",
            "--from-run",
            "re-parent",
            "--accept-partial",
            "web",
            "--token-limit",
            "400000",
            "--active-ms-limit",
            "600000",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        ("status", ["re-child", "--json"]),
        ("continue", ["re-child"]),
        (
            "synthesize",
            [
                "--from-run",
                "re-parent",
                "--accept-partial",
                "web",
                "--token-limit",
                "400000",
                "--active-ms-limit",
                "600000",
            ],
        ),
    ]
