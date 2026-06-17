from __future__ import annotations

import json
from pathlib import Path

from harness.harness_run_history import append_run, history_path, summarize_history
from harness.loop_result import LoopResult


def _result(
    *,
    status: str = "failed",
    reason: str = "outer_cap",
    tokens: int = 1234,
) -> LoopResult:
    return LoopResult(
        status=status,
        termination_reason=reason,
        outer_iterations=2,
        inner_iterations=1,
        pr_url="https://github.com/t/r/pull/1",
        tokens_used=tokens,
        final_verify=None,
        branch="001-demo",
    )


def test_append_run_creates_spec_local_history_file(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    append_run(
        spec_dir,
        spec_id="001-demo",
        build_id="build-20260617-000000-000001",
        mode="banzai",
        strategy_id="default",
        result=_result(),
        pr_url="https://github.com/t/r/pull/1",
    )

    data = json.loads(history_path(spec_dir).read_text(encoding="utf-8"))
    row = data["runs"][0]
    assert row["spec_id"] == "001-demo"
    assert row["build_id"] == "build-20260617-000000-000001"
    assert row["mode"] == "banzai"
    assert row["strategy_id"] == "default"
    assert row["status"] == "failed"
    assert row["termination_reason"] == "outer_cap"
    assert row["tokens_used"] == 1234


def test_summarize_history_returns_recent_runs_and_total_tokens(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    append_run(
        spec_dir,
        spec_id="001-demo",
        build_id="build-1",
        mode="semi",
        strategy_id="default",
        result=_result(tokens=100),
        pr_url=None,
    )
    append_run(
        spec_dir,
        spec_id="001-demo",
        build_id="build-2",
        mode="banzai",
        strategy_id="codegen",
        result=_result(tokens=250),
        pr_url=None,
    )

    summary = summarize_history(spec_dir, limit=1)

    assert summary["count"] == 2
    assert summary["total_tokens"] == 350
    assert len(summary["recent"]) == 1
    assert summary["recent"][0]["build_id"] == "build-2"
