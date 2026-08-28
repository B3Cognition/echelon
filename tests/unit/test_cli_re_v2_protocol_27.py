from __future__ import annotations

import pytest


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

