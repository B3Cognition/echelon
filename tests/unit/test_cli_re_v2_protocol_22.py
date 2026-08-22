from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tests.support.re_v2_cli_workspace import create_cli_workspace


@pytest.mark.unit
def test_v2_defaults_to_baseline_and_inventory_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli
    from echelon.cli_app import app

    goals: list[str] = []

    def fake_create(
        project_root: Path,
        *,
        token_limit: int | None,
        time_limit_minutes: int | None,
        shadow: bool,
        goal: str,
    ) -> None:
        del project_root, token_limit, time_limit_minutes, shadow
        goals.append(goal)

    monkeypatch.setattr(legacy_cli, "_run_re_v2_create", fake_create)
    runner = CliRunner()

    default = runner.invoke(app, ["re", "run", "--engine", "v2", "--shadow"])
    inventory = runner.invoke(
        app,
        [
            "re",
            "run",
            "--engine",
            "v2",
            "--goal",
            "inventory",
            "--shadow",
        ],
    )

    assert default.exit_code == 0, default.output
    assert inventory.exit_code == 0, inventory.output
    assert goals == ["baseline", "inventory"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    (
        ["re", "run", "--goal", "baseline"],
        ["re", "run", "--engine", "v2", "--goal", "future"],
        [
            "re",
            "run",
            "--engine",
            "v2",
            "--goal",
            "baseline",
            "--goal",
            "inventory",
        ],
        ["re", "continue", "--goal", "baseline"],
    ),
)
def test_goal_is_closed_unique_creation_only_option(args: list[str]) -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 2


@pytest.mark.unit
def test_typer_routes_goal_without_changing_v1_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    calls: list[list[str]] = []
    monkeypatch.setattr("echelon.cli._cmd_re_run", lambda args: calls.append(args))
    runner = CliRunner()

    v1 = runner.invoke(app, ["re", "run"])
    v2 = runner.invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory"],
    )

    assert v1.exit_code == 0, v1.output
    assert v2.exit_code == 0, v2.output
    assert calls == [
        ["--re-policy", "changed"],
        [
            "--re-policy",
            "changed",
            "--engine",
            "v2",
            "--goal",
            "inventory",
        ],
    ]


@pytest.mark.unit
def test_ineligible_provider_changes_neither_run_nor_active_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    (probe.root / "runs").mkdir()
    pointer = probe.root / "runs" / ".current-re"
    pointer.write_text("re-existing\n", encoding="utf-8")
    before = probe.active_pointer_bytes()
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)

    result = CliRunner().invoke(app, ["re", "run", "--engine", "v2"])

    assert result.exit_code == 2
    assert "bounded-api-baseline-v1" in result.output
    assert probe.active_pointer_bytes() == before
    assert probe.run_directories() == ()


@pytest.mark.unit
def test_inventory_goal_needs_no_bounded_provider_and_pins_protocol_22(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.run_store import load_run_manifest

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)

    result = CliRunner().invoke(
        app,
        [
            "re",
            "run",
            "--engine",
            "v2",
            "--goal",
            "inventory",
            "--shadow",
        ],
    )

    assert result.exit_code == 0, result.output
    run_dir = probe.run_directories()[0]
    manifest = load_run_manifest(run_dir)
    assert manifest.schema_version == 2
    assert manifest.engine_protocol_version == "2.2"
    assert manifest.requested_goals == ("inventory",)
    assert probe.active_pointer_bytes() == (run_dir.name + "\n").encode()
    assert "provider initial dispatches: 0" in result.output


@pytest.mark.unit
def test_missing_agent_authority_fails_before_run_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    probe = create_cli_workspace(
        tmp_path,
        llm_cli="openai-compatible",
        include_agent=False,
    )
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--shadow"],
    )

    assert result.exit_code == 2
    assert "echelon.re-baseliner" in result.output
    assert probe.active_pointer_bytes() is None
    assert probe.run_directories() == ()


@pytest.mark.unit
def test_baseline_shadow_reports_closed_worst_case_without_provider_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    probe = create_cli_workspace(tmp_path, llm_cli="openai-compatible")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    monkeypatch.setattr(
        "harness.re_v2.protocol_22.provider.BoundedApiBaselineExecutor.execute",
        lambda *_args, **_kwargs: pytest.fail("shadow issued a provider request"),
    )

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--shadow"],
    )

    assert result.exit_code == 0, result.output
    run_dir = probe.run_directories()[0]
    manifest = load_run_manifest(run_dir)
    assert manifest.requested_goals == ("baseline",)
    output = result.output
    assert "provider initial dispatches:" in output
    assert "maximum shared-retry dispatches:" in output
    assert "context exact:" in output
    assert "context worst-case bound:" in output
    assert "per-dispatch hard limits:" in output
    assert "whole-run initial reservation:" in output
    assert "whole-run shared-retry reservation:" in output
    assert "authorized ceilings:" in output
    assert "provider requests issued: 0" in output
    assert EventStore(
        ReV2Paths.for_run(run_dir), protocol=PROTOCOL_22_EVENTS
    ).replay() == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    "v1_options",
    (
        ["--re-policy", "none"],
        ["--re-max-inner", "2"],
        ["--reset"],
        ["--no-reuse"],
        ["--profile", "fast"],
    ),
)
def test_v2_creation_rejects_v1_only_options_before_creation(
    monkeypatch: pytest.MonkeyPatch,
    v1_options: list[str],
) -> None:
    from echelon.cli_app import app

    monkeypatch.setattr(
        "echelon.cli._run_re_v2_create",
        lambda *_args, **_kwargs: pytest.fail("v2 creation started"),
    )

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory", *v1_options],
    )

    assert result.exit_code == 2


@pytest.mark.unit
def test_catalog_failure_precedes_run_and_pointer_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    monkeypatch.setattr(
        "harness.re_v2.protocol_22.policies.build_compact_v1_policy_catalog",
        lambda: (_ for _ in ()).throw(ValueError("catalog construction failed")),
    )

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory", "--shadow"],
    )

    assert result.exit_code == 2
    assert "catalog construction failed" in result.output
    assert probe.active_pointer_bytes() is None
    assert probe.run_directories() == ()


@pytest.mark.unit
def test_missing_response_schema_authority_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from echelon import cli as legacy_cli
    from echelon.cli_app import app

    probe = create_cli_workspace(tmp_path, llm_cli="openai-compatible")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    original = legacy_cli._re_v22_installed_registry

    def without_schemas(root: Path) -> tuple[object, bytes | None, dict[str, bytes]]:
        registry, agent, schemas = original(root)
        return replace(registry, response_schemas={}), agent, schemas

    monkeypatch.setattr(legacy_cli, "_re_v22_installed_registry", without_schemas)

    result = CliRunner().invoke(app, ["re", "run", "--engine", "v2", "--shadow"])

    assert result.exit_code == 2
    assert "response_schema" in result.output
    assert probe.active_pointer_bytes() is None
    assert probe.run_directories() == ()


@pytest.mark.unit
def test_storage_failure_leaves_incomplete_store_inactive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    (probe.root / "runs").mkdir()
    pointer = probe.root / "runs" / ".current-re"
    pointer.write_text("re-existing\n", encoding="utf-8")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)

    def fail_after_unique_store(run_dir: Path, *_args: object) -> None:
        (run_dir / "v2").mkdir(parents=True)
        raise RuntimeError("durable publication interrupted")

    monkeypatch.setattr(
        "harness.re_v2.protocol_22.inputs.create_protocol_22_run_store",
        fail_after_unique_store,
    )

    result = CliRunner().invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory", "--shadow"],
    )

    assert result.exit_code == 2
    assert "durable publication interrupted" in result.output
    assert probe.active_pointer_bytes() == b"re-existing\n"
    incomplete = probe.run_directories()
    assert len(incomplete) == 1
    assert (incomplete[0] / "v2").is_dir()
    assert not (incomplete[0] / "v2" / "run-manifest.json").exists()


@pytest.mark.unit
def test_installed_in_process_authority_closes_over_runtime_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli
    from harness.re_v2.canonical import content_digest

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    observed: list[tuple[str, ...]] = []

    def digest_modules(*modules: object) -> str:
        names = tuple(str(getattr(module, "__name__")) for module in modules)
        observed.append(names)
        return content_digest("\n".join(names).encode())

    monkeypatch.setattr(legacy_cli, "_re_v22_implementation_digest", digest_modules)

    legacy_cli._re_v22_installed_registry(probe.root)

    assert any(
        "harness.re_v2.protocol_22.runtime" in closure for closure in observed
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "continuation",
    (
        ["re", "continue"],
        ["re", "continue", "--re-time-limit-minutes", "1"],
        [
            "re",
            "continue",
            "--re-token-limit",
            "5000000",
            "--re-time-limit-minutes",
            "6",
        ],
    ),
)
def test_paused_continuation_requires_only_strictly_higher_ceilings_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation: list[str],
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.run_store import ReV2Paths

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            "re",
            "run",
            "--engine",
            "v2",
            "--goal",
            "inventory",
            "--re-time-limit-minutes",
            "1",
        ],
    )
    assert created.exit_code == 0, created.output
    paths = ReV2Paths.for_run(probe.run_directories()[0])
    before = paths.events.read_bytes()

    result = runner.invoke(app, continuation)

    assert result.exit_code == 2
    assert "strictly higher" in result.output
    assert paths.events.read_bytes() == before


@pytest.mark.unit
def test_terminal_protocol_22_run_rejects_budget_authorization_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app
    from harness.re_v2.run_store import ReV2Paths

    probe = create_cli_workspace(tmp_path, llm_cli="codex")
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "echelon-home"))
    monkeypatch.chdir(probe.root)
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["re", "run", "--engine", "v2", "--goal", "inventory"],
    )
    assert created.exit_code == 0, created.output
    paths = ReV2Paths.for_run(probe.run_directories()[0])
    before = paths.events.read_bytes()

    result = runner.invoke(
        app,
        ["re", "continue", "--re-token-limit", "6000000"],
    )

    assert result.exit_code == 2
    assert "terminal protocol-2.2" in result.output
    assert paths.events.read_bytes() == before
