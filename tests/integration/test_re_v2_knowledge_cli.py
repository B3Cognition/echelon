"""Ordinary depth-based CLI routing for the reviewed knowledge workflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.integration
def test_normal_run_uses_current_reviewed_analysis_and_configured_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import echelon.cli as cli
    import harness.re_v2.knowledge_workflow as workflow

    run_dir = tmp_path / "runs" / "re-reviewed"
    run_dir.mkdir(parents=True)
    config = object()
    provider = object()
    calls: list[tuple[Path, str, object, int | None, int | None]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run", lambda _root: run_dir
    )
    monkeypatch.setattr("harness.config.load_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda actual: provider if actual is config else pytest.fail("wrong config"),
    )

    def execute(root, run_id, provider_factory, *, token_limit, active_ms_limit):
        calls.append((root, run_id, provider_factory(), token_limit, active_ms_limit))
        return workflow.KnowledgeWorkflowResultV1(
            run_id, "complete", "re-synthesis", 4, None
        )

    monkeypatch.setattr(workflow, "run_knowledge_workflow", execute)
    monkeypatch.setattr(cli, "_reviewed_run_depths", lambda _path: {"api": "deep"})

    cli._cmd_re_knowledge_run(["--depth", "deep"])

    assert calls == [(tmp_path.resolve(), "re-reviewed", provider, 5_000_000, 10_800_000)]
    output = capsys.readouterr().out
    assert "completed" in output
    assert "generation 4" in output
    assert "deep" in output


@pytest.mark.integration
def test_normal_run_reports_one_actionable_step_when_analysis_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import echelon.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run", lambda _root: None
    )

    with pytest.raises(SystemExit) as failure:
        cli._cmd_re_knowledge_run([])

    assert failure.value.code == 2
    error = capsys.readouterr().err
    assert "needs attention" in error
    assert "echelon re run --engine v2" not in error
    assert "repaired analysis" in error


@pytest.mark.integration
def test_normal_refresh_accepts_multiple_sources_and_preserves_absolute_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import echelon.cli as cli

    captured: list[tuple[tuple[str, ...], str | None, int, int]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "_run_re_knowledge_refresh_action",
        lambda _root, sources, depth, tokens, active: captured.append(
            (sources, depth, tokens, active)
        ),
        raising=False,
    )

    cli._cmd_re_knowledge_refresh(
        [
            "--source",
            "api",
            "--source=worker",
            "--depth",
            "standard",
            "--re-token-limit",
            "7000000",
            "--re-time-limit-minutes",
            "240",
        ]
    )

    assert captured == [(('api', 'worker'), 'standard', 7_000_000, 14_400_000)]


@pytest.mark.integration
def test_normal_refresh_rejects_duplicate_source_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import echelon.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "_run_re_knowledge_refresh_action",
        lambda *_a: pytest.fail("duplicate source reached execution"),
        raising=False,
    )

    with pytest.raises(SystemExit) as failure:
        cli._cmd_re_knowledge_refresh(
            ["--source", "api", "--source", "api"]
        )

    assert failure.value.code == 2
