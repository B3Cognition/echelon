from __future__ import annotations

import pytest
from typer.testing import CliRunner

from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture


@pytest.mark.unit
def test_deepen_routes_closed_l2_selection_and_resource_authority(
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
            "L2",
            "--source",
            "api",
            "--domain",
            "010-orders",
            "--from-run",
            "re-parent",
            "--token-limit",
            "2000000",
            "--active-ms-limit",
            "3600000",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [[
        "--to",
        "L2",
        "--source",
        "api",
        "--domain",
        "010-orders",
        "--from-run",
        "re-parent",
        "--token-limit",
        "2000000",
        "--active-ms-limit",
        "3600000",
    ]]


@pytest.mark.unit
def test_deepen_routes_all_sources_without_provider_specific_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_deepen", lambda args: calls.append(args))

    result = CliRunner().invoke(app, ["re", "deepen", "--to", "L2", "--all"])

    assert result.exit_code == 0, result.output
    assert calls == [["--to", "L2", "--all"]]


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    (
        ["re", "deepen", "--all"],
        ["re", "deepen", "--to", "L2"],
        ["re", "deepen", "--to", "L2", "--all", "--source", "api"],
        ["re", "deepen", "--to", "L2", "--all", "--domain", "orders"],
        ["re", "deepen", "--to", "L2", "--domain", "orders"],
        ["re", "deepen", "--to", "L2", "--source", "api", "--engine", "v2"],
        ["re", "deepen", "--to", "L2", "--all", "--token-limit", "0"],
        ["re", "deepen", "--to", "L2", "--all", "--active-ms-limit", "0"],
    ),
)
def test_deepen_parser_rejects_invalid_or_v1_style_contract(args: list[str]) -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 2


@pytest.mark.unit
def test_deepen_legacy_parser_rejects_duplicate_selectors() -> None:
    from echelon import cli as legacy_cli

    with pytest.raises(SystemExit) as exc:
        legacy_cli._cmd_re_deepen(
            ["--to", "L2", "--source", "api", "--source", "api"]
        )

    assert exc.value.code == 2


@pytest.mark.unit
@pytest.mark.parametrize("selector", ("001-re-src",))
def test_selection_resolves_presentation_domain_id_to_stable_key(
    selector: str,
) -> None:
    from echelon import cli as legacy_cli

    inputs, _manifest = _input_fixture()
    options = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--source", "api", "--domain", selector]
    )

    selection = legacy_cli._resolve_re_v24_selection(
        inputs.workspace_partition,
        options,
    )

    assert selection.source_ids == ("api",)
    assert selection.domain_keys == (
        inputs.workspace_partition.sources[0].domains[0].domain_key,
    )


@pytest.mark.unit
def test_selection_accepts_stable_domain_key_and_rejects_unknown_values() -> None:
    from echelon import cli as legacy_cli

    inputs, _manifest = _input_fixture()
    domain = inputs.workspace_partition.sources[0].domains[0]
    selected = legacy_cli._resolve_re_v24_selection(
        inputs.workspace_partition,
        legacy_cli._parse_re_deepen_options(
            ["--to", "L2", "--source", "api", "--domain", domain.domain_key]
        ),
    )
    assert selected.domain_keys == (domain.domain_key,)

    with pytest.raises(ValueError, match="unknown source"):
        legacy_cli._resolve_re_v24_selection(
            inputs.workspace_partition,
            legacy_cli._parse_re_deepen_options(
                ["--to", "L2", "--source", "missing"]
            ),
        )
    with pytest.raises(ValueError, match="unknown domain"):
        legacy_cli._resolve_re_v24_selection(
            inputs.workspace_partition,
            legacy_cli._parse_re_deepen_options(
                ["--to", "L2", "--source", "api", "--domain", "missing"]
            ),
        )


@pytest.mark.unit
def test_all_selection_is_canonical_and_semantic_identity_excludes_budget() -> None:
    from echelon import cli as legacy_cli

    inputs, _manifest = _input_fixture()
    low = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--all", "--token-limit", "100"]
    )
    high = legacy_cli._parse_re_deepen_options(
        ["--to", "L2", "--all", "--token-limit", "1000000"]
    )
    low_selection = legacy_cli._resolve_re_v24_selection(
        inputs.workspace_partition,
        low,
    )
    high_selection = legacy_cli._resolve_re_v24_selection(
        inputs.workspace_partition,
        high,
    )

    assert low_selection == high_selection
    assert low_selection.all_sources is True
    assert low_selection.source_ids == ()
    assert low_selection.domain_keys == ()
    assert legacy_cli.semantic_request_id_for(
        "re-root",
        "sha256:" + "a" * 64,
        inputs.workspace_partition.snapshot_id,
        low_selection,
        "L2",
        "sha256:" + "b" * 64,
    ) == legacy_cli.semantic_request_id_for(
        "re-root",
        "sha256:" + "a" * 64,
        inputs.workspace_partition.snapshot_id,
        high_selection,
        "L2",
        "sha256:" + "b" * 64,
    )
