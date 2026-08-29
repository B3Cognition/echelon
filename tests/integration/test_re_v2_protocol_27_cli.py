from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
from tests.unit.test_re_v2_protocol_27_publication import _completed_context


@pytest.mark.integration
def test_exact_successor_reuses_parent_without_provider_calls(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.lifecycle import execute_protocol_27_request
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis
    from harness.re_v2.protocol_27.status import protocol_27_status_document

    parent = _completed_context(tmp_path)
    assert run_protocol_27_synthesis(
        parent.paths.root.parent,
        lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    ).synthesis_closure_complete
    provider = _ScriptedProvider()

    result = execute_protocol_27_request(
        tmp_path,
        SimpleNamespace(
            from_run="re-synthesis-child",
            accepted_partial_sources=("web",),
            token_limit=400_000,
            active_ms_limit=600_000,
        ),
        lambda: provider,  # type: ignore[arg-type]
    )

    run_id = (tmp_path / "runs/.current-re").read_text(encoding="utf-8").strip()
    document = protocol_27_status_document(tmp_path / "runs" / run_id)
    assert result.synthesis_closure_complete
    assert provider.calls == []
    assert document["artifact_counts"]["adopted"] == document["artifact_counts"]["required"]
    assert document["publication_status"] == "published_partial"


@pytest.mark.integration
def test_exact_terminal_request_reuses_child_byte_stably(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.lifecycle import execute_protocol_27_request
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    parent = _completed_context(tmp_path)
    run_protocol_27_synthesis(
        parent.paths.root.parent,
        lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    )
    options = SimpleNamespace(
        from_run="re-synthesis-child",
        accepted_partial_sources=("web",),
        token_limit=400_000,
        active_ms_limit=600_000,
    )
    first_provider = _ScriptedProvider()
    execute_protocol_27_request(tmp_path, options, lambda: first_provider)  # type: ignore[arg-type]
    child_id = (tmp_path / "runs/.current-re").read_text(encoding="utf-8").strip()
    child = tmp_path / "runs" / child_id / "v2"
    before = {
        name: (child / name).read_bytes()
        for name in ("run.json", "events.jsonl", "ledger.jsonl")
    }
    second_provider = _ScriptedProvider()

    execute_protocol_27_request(tmp_path, options, lambda: second_provider)  # type: ignore[arg-type]

    assert (tmp_path / "runs/.current-re").read_text(encoding="utf-8").strip() == child_id
    assert second_provider.calls == []
    assert before == {
        name: (child / name).read_bytes()
        for name in ("run.json", "events.jsonl", "ledger.jsonl")
    }


@pytest.mark.integration
def test_terminal_cli_continuation_is_byte_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli
    import harness.config
    import harness.squad_provider
    from harness.re_v2.protocol_27.lifecycle import run_protocol_27_synthesis

    context = _completed_context(tmp_path)
    run_dir = context.paths.root.parent
    run_protocol_27_synthesis(
        run_dir,
        lambda: _ScriptedProvider(),  # type: ignore[arg-type]
    )
    before = {
        name: (run_dir / "v2" / name).read_bytes()
        for name in ("run.json", "events.jsonl", "ledger.jsonl")
    }
    provider = _ScriptedProvider()
    monkeypatch.setattr(cli, "_installed_re_runtime_or_exit", lambda _root: (tmp_path, tmp_path))
    monkeypatch.setattr(harness.config, "load_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(harness.squad_provider, "SquadCliProvider", lambda _config: provider)

    cli._run_re_v2_continue(
        run_dir,
        token_limit=None,
        time_limit_minutes=None,
    )

    assert provider.calls == []
    assert before == {
        name: (run_dir / "v2" / name).read_bytes()
        for name in ("run.json", "events.jsonl", "ledger.jsonl")
    }
    assert "RE WORKSPACE SYNTHESIS — COMPLETE OVER ACCEPTED PARTIAL INPUTS" in capsys.readouterr().out
