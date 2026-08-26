from __future__ import annotations

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
