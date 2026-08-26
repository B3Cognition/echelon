from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_deepen_routes_l3_semantic_authorization_without_provider_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_deepen", lambda args: calls.append(args))

    result = CliRunner().invoke(
        app,
        [
            "re",
            "deepen",
            "--to",
            "L3",
            "--source",
            "api",
            "--domain",
            "orders",
            "--from-run",
            "re-l2-parent",
            "--token-limit",
            "5000000",
            "--active-ms-limit",
            "7200000",
            "--semantic-token-limit",
            "1000000",
            "--semantic-active-ms-limit",
            "1800000",
            "--new-audit-epoch",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [[
        "--to",
        "L3",
        "--source",
        "api",
        "--domain",
        "orders",
        "--from-run",
        "re-l2-parent",
        "--token-limit",
        "5000000",
        "--active-ms-limit",
        "7200000",
        "--semantic-token-limit",
        "1000000",
        "--semantic-active-ms-limit",
        "1800000",
        "--new-audit-epoch",
    ]]


@pytest.mark.unit
def test_legacy_deepen_parser_keeps_runwide_and_semantic_limits_distinct() -> None:
    from echelon.cli import _parse_re_deepen_options

    options = _parse_re_deepen_options(
        [
            "--to",
            "L3",
            "--all",
            "--token-limit",
            "5000000",
            "--semantic-token-limit",
            "1000000",
            "--semantic-active-ms-limit",
            "1800000",
        ]
    )

    assert options.target_layer == "L3"
    assert options.token_limit == 5_000_000
    assert options.semantic_token_limit == 1_000_000
    assert options.semantic_active_ms_limit == 1_800_000
    assert options.new_audit_epoch is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    (
        ["--to", "L2", "--all", "--semantic-token-limit", "10"],
        ["--to", "L2", "--all", "--semantic-active-ms-limit", "10"],
        ["--to", "L2", "--all", "--new-audit-epoch"],
        ["--to", "L3", "--all", "--semantic-token-limit", "0"],
        ["--to", "L3", "--all", "--semantic-active-ms-limit", "0"],
    ),
)
def test_deepen_parser_rejects_cross_layer_or_nonpositive_semantic_flags(
    args: list[str],
) -> None:
    from echelon.cli import _parse_re_deepen_options

    with pytest.raises(ValueError):
        _parse_re_deepen_options(args)


@pytest.mark.unit
def test_legacy_deepen_dispatches_l3_only_to_protocol_25(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli,
        "_run_re_v24_deepen",
        lambda _root, options: calls.append(("2.4", options.target_layer)),
    )
    monkeypatch.setattr(
        cli,
        "_run_re_v25_deepen",
        lambda _root, options: calls.append(("2.5", options.target_layer)),
        raising=False,
    )

    cli._cmd_re_deepen(["--to", "L3", "--all"])

    assert calls == [("2.5", "L3")]


@pytest.mark.unit
def test_exact_protocol_25_child_lookup_reuses_manifest_in_every_state(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_25.inputs import create_protocol_25_run_store
    from harness.re_v2.protocol_25.lifecycle import find_exact_protocol_25_child
    from tests.unit.test_re_v2_protocol_25_inputs import _fixture

    inputs, manifest = _fixture()
    manifest = replace(manifest, run_id="re-existing-semantic-child")
    child = tmp_path / "runs" / manifest.run_id
    create_protocol_25_run_store(child, manifest, inputs)

    # Mutable run state is intentionally irrelevant to immutable request reuse.
    (child / "v2" / "state-marker").write_text("blocked_plateau\n")

    assert find_exact_protocol_25_child(
        tmp_path,
        manifest.semantic_request_id,
    ) == child
    assert find_exact_protocol_25_child(tmp_path, f"sha256:{'0' * 64}") is None
