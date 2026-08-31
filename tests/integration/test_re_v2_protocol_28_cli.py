from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.integration
def test_l4_parser_accepts_public_limits_and_shadow() -> None:
    from echelon.cli import _parse_re_deepen_options

    live = _parse_re_deepen_options(
        [
            "--to",
            "L4",
            "--source",
            "api",
            "--token-limit",
            "2000000",
            "--active-ms-limit",
            "1200000",
        ]
    )
    shadow = _parse_re_deepen_options(
        ["--to", "L4", "--source", "api", "--shadow"]
    )

    assert live.target_layer == "L4"
    assert live.token_limit == 2_000_000
    assert live.active_ms_limit == 1_200_000
    assert live.shadow is False
    assert shadow.shadow is True


@pytest.mark.integration
@pytest.mark.parametrize(
    "args, message",
    (
        (["--to", "L4", "--all", "--semantic-token-limit", "1"], "only for L3"),
        (["--to", "L4", "--all", "--new-audit-epoch"], "only for L3"),
        (["--to", "L3", "--all", "--shadow"], "only for L4"),
        (
            ["--to", "L4", "--all", "--shadow", "--token-limit", "1"],
            "cannot be combined",
        ),
        (["--to", "L4", "--all", "--source", "api"], "cannot be combined"),
    ),
)
def test_l4_parser_rejects_cross_protocol_options(
    args: list[str], message: str
) -> None:
    from echelon.cli import _parse_re_deepen_options

    with pytest.raises(ValueError, match=message):
        _parse_re_deepen_options(args)


@pytest.mark.integration
def test_l4_typer_surface_is_truthful_and_has_no_hard_prefix() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "deepen", "--help"])

    assert result.exit_code == 0
    assert "L4" in result.output
    assert "--shadow" in result.output
    assert "--token-limit" in result.output
    assert "--active-ms-limit" in result.output
    assert "hard-token" not in result.output
    assert "hard_token" not in result.output


@pytest.mark.integration
def test_l4_dispatch_routes_only_to_protocol_28(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli

    calls: list[tuple[Path, object]] = []
    monkeypatch.setattr(cli, "_run_re_v28_deepen", lambda root, options: calls.append((root, options)))
    monkeypatch.setattr(cli, "_run_re_v24_deepen", lambda *_args: pytest.fail("L2 route used"))
    monkeypatch.setattr(cli, "_run_re_v25_deepen", lambda *_args: pytest.fail("L3 route used"))

    cli._cmd_re_deepen(["--to", "L4", "--all", "--shadow"])

    assert len(calls) == 1
    assert calls[0][1].target_layer == "L4"
    assert calls[0][1].shadow is True


@pytest.mark.integration
def test_schema7_context_and_exhaustive_continuation_dispatch_by_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli
    import harness.config
    import harness.squad_provider
    from harness.re_v2.protocol_28.context import Protocol28RunContext
    from harness.re_v2.protocol_28.lifecycle import create_or_reuse_protocol_28_child
    from tests.unit.test_re_v2_protocol_28_inputs import _fixture
    from tests.unit.test_re_v2_protocol_28_lifecycle import _PassingBackend

    _manifest, inputs = _fixture("re-l4-cli-continue")
    run_dir = create_or_reuse_protocol_28_child(tmp_path, inputs)
    backend = _PassingBackend()
    monkeypatch.setattr(cli, "_installed_re_runtime_or_exit", lambda _root: None)
    monkeypatch.setattr(harness.config, "load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(harness.squad_provider, "SquadCliProvider", lambda _config: backend)

    assert isinstance(cli._re_v2_context(tmp_path, run_dir), Protocol28RunContext)
    cli._run_re_v2_continue(
        run_dir,
        token_limit=None,
        time_limit_minutes=None,
    )

    output = capsys.readouterr().out
    assert backend.roles == ["producer", "verifier"]
    assert "PROTOCOL 2.8" in output
    assert "accepted=1" in output
    assert output.rstrip().endswith("L4 SELECTED SCOPE COMPLETE")
    assert (run_dir / "re" / "l4" / "materialization.json").is_file()


@pytest.mark.integration
def test_schema7_closure_continuation_rejects_resources_and_replays_zero_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli
    from harness.re_v2.protocol_28.closure import create_or_reuse_l4_closure_successor
    from harness.re_v2.protocol_28.context import Protocol28ClosureRunContext
    from tests.unit.test_re_v2_protocol_28_closure import _complete_closure_fixture

    run_dir = create_or_reuse_l4_closure_successor(
        tmp_path, _complete_closure_fixture("re-l4-cli-closure")
    )
    assert isinstance(
        cli._re_v2_context(tmp_path, run_dir), Protocol28ClosureRunContext
    )

    with pytest.raises(ValueError, match="rejects resource"):
        cli._run_re_v2_continue(
            run_dir,
            token_limit=1_000_000,
            time_limit_minutes=None,
        )
    cli._run_re_v2_continue(
        run_dir,
        token_limit=None,
        time_limit_minutes=None,
    )

    assert "mode: l4-closure-successor" in capsys.readouterr().out


@pytest.mark.integration
def test_continued_l3_child_auto_advances_its_unique_open_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_24.model import SelectionScopeV1
    from harness.re_v2.protocol_28.orchestration import (
        DeepenOrchestrationController,
        DeepenOrchestrationRequestV1,
        create_or_load_orchestration,
    )

    selection = SelectionScopeV1(1, False, ("api",), ())
    request = DeepenOrchestrationRequestV1(
        1,
        "re-input",
        content_digest(b"input-manifest"),
        content_digest(b"input-terminal"),
        content_digest(b"snapshot"),
        content_digest(b"partition"),
        selection,
        content_digest(b"policy"),
        content_digest(b"executors"),
        content_digest(b"l3-request"),
    )
    def clock() -> str:
        return "2026-08-31T12:00:00Z"
    intent = create_or_load_orchestration(tmp_path, request, clock=clock)
    DeepenOrchestrationController(intent, clock=clock).bind_l3_child(
        "re-l3-child", content_digest(b"l3-manifest")
    )
    calls: list[object] = []
    monkeypatch.setattr(
        cli,
        "_run_re_v28_deepen",
        lambda _root, options: calls.append(options),
    )

    assert cli._advance_re_v28_open_intent(tmp_path, "re-l3-child") is True

    assert len(calls) == 1
    assert calls[0].target_layer == "L4"
    assert calls[0].from_run == "re-input"
    assert calls[0].source_ids == ("api",)


@pytest.mark.integration
def test_shadow_checkpoint_preview_is_read_only_without_a_cache(
    tmp_path: Path,
) -> None:
    from echelon.cli import _re_v28_checkpoint_adoption, _render_re_v28_shadow
    from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    before = tuple(sorted(path.relative_to(workspace) for path in workspace.rglob("*")))

    adoption, conditional_ids, candidates = _re_v28_checkpoint_adoption(
        workspace, inputs
    )
    output = _render_re_v28_shadow(
        inputs,
        checkpoint_adoption=adoption,
        conditional_checkpoint_ids=conditional_ids,
        checkpoint_candidates=candidates,
    )

    assert tuple(sorted(path.relative_to(workspace) for path in workspace.rglob("*"))) == before
    assert "checkpoint reuse: realized=0 conditional=0 candidates=0" in output
    assert "mutation: none" in output
