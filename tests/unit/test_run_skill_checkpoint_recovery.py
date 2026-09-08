from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.paths import current_build_marker
from harness.skills.run_skill import (
    RunContextError,
    _fresh_delivery_baselines,
    _fresh_delivery_completed_tasks,
)


def _write_state(
    root: Path,
    build_id: str,
    *,
    status: str,
    checkpoint: str | None = None,
    termination_reason: str | None = None,
) -> Path:
    state_dir = root / "runs" / build_id / "state"
    state_dir.mkdir(parents=True)
    payload: dict[str, object] = {
        "status": status,
        "termination_reason": termination_reason,
    }
    if checkpoint is not None:
        payload["checkpoint_commits"] = [{"commit": checkpoint}]
    path = state_dir / "default.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _intent() -> SimpleNamespace:
    return SimpleNamespace(
        spec_id="012",
        strategies=["default"],
        reset=False,
        resume=False,
    )


@pytest.mark.unit
def test_new_budget_prefers_checkpoint_from_dead_running_delivery(tmp_path: Path) -> None:
    older = "a" * 40
    newest = "b" * 40
    _write_state(
        tmp_path,
        "build-older",
        status="blocked",
        checkpoint=older,
        termination_reason="outer_cap",
    )
    latest = _write_state(
        tmp_path,
        "build-newest",
        status="running",
        checkpoint=newest,
    )
    latest.with_suffix(".lock").write_text(
        "pid=999999999\ntimestamp=now\nrun_id=dead\n",
        encoding="utf-8",
    )
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newest", encoding="utf-8")

    assert _fresh_delivery_baselines(tmp_path, _intent()) == {"default": newest}


@pytest.mark.unit
def test_new_budget_refuses_to_compete_with_live_running_delivery(tmp_path: Path) -> None:
    latest = _write_state(
        tmp_path,
        "build-newest",
        status="running",
        checkpoint="b" * 40,
    )
    latest.with_suffix(".lock").write_text(
        f"pid={os.getpid()}\ntimestamp=now\nrun_id=live\n",
        encoding="utf-8",
    )
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newest", encoding="utf-8")

    with pytest.raises(RunContextError, match="already active"):
        _fresh_delivery_baselines(tmp_path, _intent())


@pytest.mark.unit
def test_fresh_delivery_recovers_only_checkpointed_tasks_on_baseline_ancestry(
    tmp_path: Path,
) -> None:
    ancestor = "a" * 40
    baseline = "b" * 40
    unrelated = "c" * 40
    first = _write_state(
        tmp_path,
        "build-first",
        status="running",
        checkpoint=ancestor,
    )
    first_payload = json.loads(first.read_text(encoding="utf-8"))
    first_payload.update(
        {
            "spec_id": "012",
            "strategy_id": "default",
            "build": {
                "task_results": {
                    "T-001": {"status": "DONE"},
                    "T-099": {"status": "DONE"},
                }
            },
        }
    )
    first_payload["checkpoint_commits"][0]["task_ids"] = ["T-001"]
    first.write_text(json.dumps(first_payload), encoding="utf-8")

    latest = _write_state(
        tmp_path,
        "build-latest",
        status="interrupted",
        checkpoint=baseline,
    )
    latest_payload = json.loads(latest.read_text(encoding="utf-8"))
    latest_payload.update({"spec_id": "012", "strategy_id": "default"})
    latest_payload["checkpoint_commits"][0]["task_ids"] = ["T-002"]
    latest_payload["build"] = {
        "task_results": {
            "T-002": {"status": "DONE"},
            # Provider-reported but never checkpointed: must not be inherited.
            "T-003": {"status": "DONE"},
        }
    }
    latest.write_text(json.dumps(latest_payload), encoding="utf-8")

    other = _write_state(
        tmp_path,
        "build-unrelated",
        status="interrupted",
        checkpoint=unrelated,
    )
    other_payload = json.loads(other.read_text(encoding="utf-8"))
    other_payload.update({"spec_id": "012", "strategy_id": "default"})
    other_payload["checkpoint_commits"][0]["task_ids"] = ["T-004"]
    other.write_text(json.dumps(other_payload), encoding="utf-8")

    class GitOps:
        @staticmethod
        def commit_is_ancestor(commit: str, descendant: str) -> bool:
            return descendant == baseline and commit in {ancestor, baseline}

    recovered = _fresh_delivery_completed_tasks(
        tmp_path,
        _intent(),
        {"default": baseline},
        GitOps(),
    )

    assert recovered == {"default": ("T-001", "T-002")}
