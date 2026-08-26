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


@pytest.mark.unit
def test_reused_protocol_25_child_is_reported_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli

    context = object()
    calls: list[object] = []
    monkeypatch.setattr(cli, "_re_v2_context", lambda _workspace, _run: context)
    monkeypatch.setattr(cli, "_run_re_v2_live", calls.append)
    monkeypatch.setattr(
        "harness.re_v2.status.render_v2_status",
        lambda _run: "EXACT CHILD REUSED\n",
    )

    cli._run_or_report_re_v25_child(
        tmp_path,
        tmp_path / "runs" / "re-existing",
        execute=False,
    )

    assert calls == []
    assert capsys.readouterr().out == "EXACT CHILD REUSED\n"


@pytest.mark.unit
def test_shared_cli_executor_routes_semantic_contract_and_requests_audit_file(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from harness.prosaic_prompt_loader import ProsaicCommandArtifact
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_22.cli_provider import (
        calculate_shared_cli_dispatch_reservation,
    )
    from harness.re_v2.protocol_22.model import ExecutionInputV1
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_25.cli_provider import SquadCliSemanticRenderer
    from tests.re_v2_protocol_22_fixtures import digest
    from tests.unit.test_re_v2_protocol_22_cli_provider import _ProviderSpy, _result
    from tests.unit.test_re_v2_protocol_25_inputs import _executor_fixture
    from tests.unit.test_re_v2_protocol_25_runtime import _context

    catalog, objects = _executor_fixture()
    semantic = catalog.entry_for("semantic-audit")
    baseline = catalog.entry_for("compact-baseline")
    renderer = semantic.request_renderer
    assert renderer is not None
    agent = canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            body="Pinned semantic auditor. Write exactly `audit.json`.\n",
            frontmatter={
                "name": "echelon.re-validator",
                "model_tier": "strong",
                "effort": "high",
                "tools": "write",
            },
        )
    )
    semantic = replace(
        semantic,
        request_renderer=replace(
            renderer,
            agent_contract_hash=content_digest(agent),
        ),
    )
    renderer = semantic.request_renderer
    assert renderer is not None
    schema = objects[renderer.response_schemas[0].schema_hash]
    context = canonical_json_bytes(_context().to_json_dict())
    execution_input = ExecutionInputV1(
        schema_version=1,
        dispatch_id="semantic-dispatch-1",
        work_item_id=digest("semantic work"),
        attempt_kind="initial_generation",
        executor_contract_hash=semantic.executor_contract_hash,
        agent_contract_hash=content_digest(agent),
        context_bundle_hash=content_digest(context),
        provider_request_envelope_hash=digest("unused semantic envelope"),
        deterministic_invocation=None,
    )
    reservation = calculate_shared_cli_dispatch_reservation(
        agent,
        context,
        schema,
        semantic,
    )
    root = tmp_path / "candidate"
    root.mkdir()
    provider = _ProviderSpy(_result())

    result = SquadCliSemanticRenderer(
        (baseline, semantic),
        provider_factory=lambda: provider,  # type: ignore[return-value]
    ).execute(
        execution_input,
        agent,
        context,
        schema,
        reservation,
        root,
        10**12,
    )

    assert result.outcome == "candidate_ready"
    assert "audit.json" in provider.calls[0]["prompt"]
    assert "baseline.json" not in provider.calls[0]["prompt"]


@pytest.mark.unit
def test_continue_routes_distinct_runwide_and_semantic_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli

    run_dir = tmp_path / "runs" / "re-semantic"
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run",
        lambda _root: run_dir,
    )
    monkeypatch.setattr(cli, "_detect_re_engine_for_cli", lambda _run: "v2")
    monkeypatch.setattr(
        cli,
        "_run_re_v2_continue",
        lambda _run, **kwargs: calls.append(kwargs),
    )

    cli._cmd_re_continue(
        [
            "--re-token-limit",
            "5000000",
            "--re-semantic-token-limit",
            "1000000",
            "--re-semantic-time-limit-minutes",
            "30",
        ]
    )

    assert calls == [
        {
            "token_limit": 5_000_000,
            "time_limit_minutes": None,
            "semantic_token_limit": 1_000_000,
            "semantic_time_limit_minutes": 30,
        }
    ]


@pytest.mark.unit
def test_typer_continue_forwards_semantic_authorization_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_continue", calls.append)

    result = CliRunner().invoke(
        app,
        [
            "re",
            "continue",
            "--re-semantic-token-limit",
            "1000000",
            "--re-semantic-time-limit-minutes",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [[
        "--re-semantic-token-limit",
        "1000000",
        "--re-semantic-time-limit-minutes",
        "30",
    ]]


@pytest.mark.unit
def test_resume_routes_terminal_schema4_run_to_immutable_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch schema-4 resume falling through to the mutable v1 lifecycle."""
    from echelon import cli

    run_dir = tmp_path / "runs" / "re-blocked-l3"
    calls: list[tuple[Path, Path, str, int | None, int | None]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run",
        lambda _root: run_dir,
    )
    monkeypatch.setattr(cli, "_detect_re_engine_for_cli", lambda _run: "v2")
    from tests.re_v2_protocol_25_fixtures import manifest_v4

    monkeypatch.setattr(
        "harness.re_v2.run_store.load_run_manifest",
        lambda _run: manifest_v4(run_id="re-blocked-l3"),
    )
    monkeypatch.setattr(
        cli,
        "_run_re_v25_resume",
        lambda workspace, parent, answer, token_limit, time_limit_minutes: calls.append(
            (workspace, parent, answer, token_limit, time_limit_minutes)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "_re_lifecycle_controller",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("schema-4 resume must not use the v1 lifecycle")
        ),
    )

    cli._cmd_re_resume(
        ["Resolve only the retained timeout finding", "--re-token-limit", "7000000"]
    )

    assert calls == [
        (
            tmp_path,
            run_dir,
            "Resolve only the retained timeout finding",
            7_000_000,
            None,
        )
    ]
