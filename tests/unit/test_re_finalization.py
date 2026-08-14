from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_partial_run(root: Path) -> Path:
    run_dir = root / "runs/re-20260814-120000-000001"
    (root / "runs").mkdir(parents=True)
    (root / "runs/.current-re").write_text(run_dir.name + "\n", encoding="utf-8")
    summary = {
        "status": "partial",
        "finalized_at": "2026-08-14T10:00:00+00:00",
        "blocked_reason": "re_token_budget_exhausted",
        "workspace_synthesis_incomplete": True,
        "source_quality_debt": ["api"],
        "semantic_failure_count": 1,
        "semantic_failure_sources": ["api"],
    }
    _write_json(
        run_dir / "state.json",
        {
            "run_id": run_dir.name,
            "run_kind": "re",
            "status": "done",
            "golddigger_status": "partial",
            "finalized_partial": True,
            "extraction_complete": True,
            "publication_pending": False,
            "publication_complete": True,
            "generation": 3,
            "re_execution_profile": {
                "name": "high",
                "hard_token_limit": 100,
                "hard_active_minutes": 3600,
            },
            "re_partial_finalization": summary,
        },
    )
    _write_json(
        run_dir / "re/state.json",
        {
            "status": "done",
            "phase": "re-extract-2-specify",
            "publication_status": "partial",
            "re_token_usage": 100,
            "re_execution_profile": {
                "name": "high",
                "hard_token_limit": 100,
                "hard_active_minutes": 3600,
            },
            "re_source_states": {"api": {"status": "partial_quality_debt"}},
            "re_workspace_synthesis_complete": False,
            "re_specification_targets": [{"kind": "workspace-synthesis"}],
            "last_dispatch": {
                "phase_id": "re-extract-2-specify",
                "agent": "specifier",
                "post_dispatch_complete": True,
                "dispatched_at": "2026-08-14T09:00:00Z",
            },
            "re_partial_finalization": summary,
        },
    )
    _write_json(
        run_dir / "re/quality/partial-finalization.json",
        {
            "schema_version": 1,
            "run_id": run_dir.name,
            "status": "partial",
            "finalized_at": "2026-08-14T10:00:00+00:00",
            "finalized_from": {
                "outer_status": "blocked",
                "inner_status": "blocked",
                "blocked_reason": "re_token_budget_exhausted",
                "phase": "re-extract-2-specify",
            },
            "debt": {
                "controller_incomplete": True,
                "workspace_synthesis_incomplete": True,
                "source_quality_debt": ["api"],
                "semantic_failure_sources": {"api": ["001-re-domain"]},
            },
        },
    )
    return run_dir


@pytest.mark.unit
def test_synthesize_partial_run_executes_only_workspace_target_and_updates_debt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness import re_finalization

    run_dir = _write_partial_run(tmp_path)
    calls: list[dict[str, object]] = []

    class FakeController:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def run(self) -> SimpleNamespace:
            state_path = run_dir / "re/state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.update(
                {
                    "status": "done",
                    "re_workspace_synthesis_complete": True,
                    "re_specification_targets": [],
                    "re_token_usage": 123,
                }
            )
            _write_json(state_path, state)
            return SimpleNamespace(completed=True)

    monkeypatch.setattr(re_finalization, "ReExtractionController", FakeController)
    monkeypatch.setattr(re_finalization, "validate_re_run", lambda *_a, **_k: None)

    result = re_finalization.synthesize_partial_re_run(
        tmp_path,
        provider=object(),
        extension_root=tmp_path / "runtime",
        hard_token_limit=200_000,
    )

    assert result.completed
    assert result.token_usage == 123
    assert calls[0]["stop_after_workspace_synthesis"] is True
    outer = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    inner = json.loads((run_dir / "re/state.json").read_text(encoding="utf-8"))
    debt = json.loads(
        (run_dir / "re/quality/partial-finalization.json").read_text(encoding="utf-8")
    )
    assert outer["status"] == "done"
    assert outer["publication_pending"] is True
    assert outer["publication_complete"] is False
    assert inner["status"] == "done"
    assert inner["publication_status"] == "partial"
    assert inner["re_execution_profile"]["hard_token_limit"] == 200_000
    assert debt["debt"]["workspace_synthesis_incomplete"] is False
    assert outer["re_partial_finalization"]["workspace_synthesis_incomplete"] is False


@pytest.mark.unit
def test_synthesize_partial_run_requires_a_higher_exhausted_token_limit(
    tmp_path: Path,
) -> None:
    from harness.re_finalization import ReFinalizationError, synthesize_partial_re_run

    _write_partial_run(tmp_path)

    with pytest.raises(ReFinalizationError, match="--re-token-limit"):
        synthesize_partial_re_run(
            tmp_path,
            provider=object(),
            extension_root=tmp_path / "runtime",
        )
