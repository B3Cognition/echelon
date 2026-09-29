from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.paths import current_build_marker
from harness.skills.run_skill import (
    RunContextError,
    _fresh_delivery_baseline,
    _fresh_delivery_completed_tasks,
    _fresh_delivery_repair_task_id,
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
        "spec_id": "012",
        "status": status,
        "termination_reason": termination_reason,
    }
    if checkpoint is not None:
        payload["checkpoint_commits"] = [{"commit": checkpoint}]
    path = state_dir / "delivery.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _intent() -> SimpleNamespace:
    return SimpleNamespace(
        spec_id="012",
        reset=False,
        resume=False,
    )


@pytest.mark.parametrize("spec_id", ["999", "", None])
def test_recovery_ignores_foreign_or_unbound_spec(tmp_path, spec_id):
    path = _write_state(tmp_path, "build-other", status="blocked", checkpoint="a" * 40, termination_reason="build_blocked")
    payload = json.loads(path.read_text())
    payload["spec_id"] = spec_id
    path.write_text(json.dumps(payload))
    assert _fresh_delivery_baseline(tmp_path, _intent()) is None


def test_legacy_checkpoint_does_not_restore_unbound_task_completion(tmp_path):
    path = _write_state(tmp_path, "build-old", status="interrupted", checkpoint="a" * 40)
    payload = json.loads(path.read_text())
    payload["checkpoint_commits"][0]["task_ids"] = ["T-001"]
    path.write_text(json.dumps(payload))
    gitops = SimpleNamespace(commit_is_ancestor=lambda *args: True)
    assert _fresh_delivery_completed_tasks(tmp_path, _intent(), "a" * 40, gitops) == ()


def test_checkpoint_progress_requires_unchanged_definitions(tmp_path):
    from harness.task_progress import checkpoint_input_hash

    spec = tmp_path / "specs/012"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("Original requirement\n")
    (spec / "tasks.md").write_text("- [ ] T-001 implement original\n  **Status:** PENDING\n  - [ ] original acceptance\n")
    digest = checkpoint_input_hash(spec)
    path = _write_state(tmp_path, "build-old", status="interrupted", checkpoint="a" * 40)
    payload = json.loads(path.read_text())
    payload["checkpoint_commits"][0].update(task_ids=["T-001"], checkpoint_input_hash=digest)
    path.write_text(json.dumps(payload))
    gitops = SimpleNamespace(commit_is_ancestor=lambda *args: True)
    def recover():
        return _fresh_delivery_completed_tasks(tmp_path, _intent(), "a" * 40, gitops, spec_dir=spec)
    assert recover() == ("T-001",)
    (spec / "tasks.md").write_text("- [x] T-001 implement original\n  **Status:** DONE\n  - [x] original acceptance\n")
    assert recover() == ("T-001",)
    (spec / "spec.md").write_text("Changed requirement\n")
    assert recover() == ()
    (spec / "spec.md").write_text("Original requirement\n")
    (spec / "tasks.md").write_text("- [ ] T-001 implement original\n  **Status:** DEFERRED\n  - [ ] original acceptance\n")
    assert recover() == ()
    (spec / "tasks.md").write_text("- [ ] T-001 implement DIFFERENT\n  **Status:** PENDING\n")
    assert recover() == ()


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

    assert _fresh_delivery_baseline(tmp_path, _intent()) == newest


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
        _fresh_delivery_baseline(tmp_path, _intent())


@pytest.mark.unit
def test_new_budget_refuses_dirty_interrupted_candidate_without_retention(
    tmp_path: Path,
) -> None:
    """Do not silently replace a loose interrupted candidate with an older checkpoint."""
    _write_state(
        tmp_path, "build-older", status="blocked", checkpoint="a" * 40,
        termination_reason="outer_cap",
    )
    latest = _write_state(
        tmp_path, "build-newest", status="interrupted",
        termination_reason="user_cancel",
    )
    worktree = latest.parent.parent / "worktrees" / "iter-0"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    (worktree / "app.ts").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.ts"], cwd=worktree, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "initial"],
        cwd=worktree, check=True,
    )
    (worktree / "app.ts").write_text("unretained candidate\n", encoding="utf-8")
    state = json.loads(latest.read_text(encoding="utf-8"))
    state["delivery_slice_operation"] = {
        "id": "slice-1", "worktree_path": str(worktree), "progress_applied": False,
    }
    latest.write_text(json.dumps(state), encoding="utf-8")
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newest", encoding="utf-8")

    with pytest.raises(RunContextError, match="uncommitted candidate"):
        _fresh_delivery_baseline(tmp_path, _intent())


@pytest.mark.unit
def test_newer_retained_salvage_supersedes_older_dirty_interruption(
    tmp_path: Path,
) -> None:
    """Historical loose work cannot veto a newer retained delivery lineage."""
    older = _write_state(
        tmp_path, "build-older", status="interrupted",
        termination_reason="user_cancel",
    )
    worktree = older.parent.parent / "worktrees" / "iter-0"
    worktree.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    (worktree / "loose.txt").write_text("old candidate\n", encoding="utf-8")
    state = json.loads(older.read_text(encoding="utf-8"))
    state["delivery_slice_operation"] = {
        "id": "old-slice", "worktree_path": str(worktree), "progress_applied": False,
    }
    older.write_text(json.dumps(state), encoding="utf-8")
    older_state = json.loads(older.read_text(encoding="utf-8"))
    older_state["checkpoint_commits"] = [{"commit": "a" * 40}]
    older.write_text(json.dumps(older_state), encoding="utf-8")
    newer = _write_state(
        tmp_path, "build-newer", status="interrupted",
        termination_reason="user_cancel",
    )
    newer_state = json.loads(newer.read_text(encoding="utf-8"))
    newer_state["salvage_commit"] = "b" * 40
    newer.write_text(json.dumps(newer_state), encoding="utf-8")
    marker = current_build_marker(tmp_path, "012")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("build-newer", encoding="utf-8")

    gitops = SimpleNamespace(
        get_clean_worktree_head=lambda *args, **kwargs: "b" * 40,
        commit_is_ancestor=lambda parent, child: (parent, child) in {
            ("a" * 40, "b" * 40), ("b" * 40, "b" * 40),
        },
        commit_is_ancestor_of_default=lambda commit: False,
    )
    assert _fresh_delivery_baseline(tmp_path, _intent(), gitops) == "b" * 40


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
    latest_payload.update({"spec_id": "012"})
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
    other_payload.update({"spec_id": "012"})
    other_payload["checkpoint_commits"][0]["task_ids"] = ["T-004"]
    other.write_text(json.dumps(other_payload), encoding="utf-8")

    from harness.task_progress import checkpoint_input_hash

    spec = tmp_path / "specs/012"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text("- [ ] T-001 original task\n")
    for path in (first, latest, other):
        payload = json.loads(path.read_text())
        payload["checkpoint_commits"][0]["checkpoint_input_hash"] = checkpoint_input_hash(spec)
        path.write_text(json.dumps(payload))

    class GitOps:
        @staticmethod
        def commit_is_ancestor(commit: str, descendant: str) -> bool:
            return descendant == baseline and commit in {ancestor, baseline}

    recovered = _fresh_delivery_completed_tasks(
        tmp_path,
        _intent(),
        baseline,
        GitOps(),
        spec_dir=spec,
    )

    assert recovered == ("T-001", "T-002")


@pytest.mark.unit
def test_fresh_delivery_repair_target_comes_from_latest_retained_task_checkpoint(
    tmp_path: Path,
) -> None:
    from harness.task_progress import checkpoint_input_hash

    spec = tmp_path / "specs/012"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text("- [ ] T-001 first\n- [ ] T-002 second\n")
    digest = checkpoint_input_hash(spec)
    older = "a" * 40
    latest = "b" * 40
    baseline = "c" * 40
    unrelated = "d" * 40
    for build_id, commit, task_id in (
        ("build-001", older, "T-002"),
        ("build-002", latest, "T-001"),
        ("build-003", unrelated, "T-099"),
    ):
        state_path = _write_state(tmp_path, build_id, status="blocked", checkpoint=commit)
        payload = json.loads(state_path.read_text())
        payload["checkpoint_commits"][0].update(
            task_ids=[task_id], checkpoint_input_hash=digest,
        )
        state_path.write_text(json.dumps(payload))

    class GitOps:
        @staticmethod
        def commit_is_ancestor(commit: str, descendant: str) -> bool:
            return descendant == baseline and commit in {older, latest}

    assert _fresh_delivery_repair_task_id(
        tmp_path, _intent(), baseline, GitOps(), spec_dir=spec,
        completed_task_ids=("T-001", "T-002"),
    ) == "T-001"

    (spec / "tasks.md").write_text("- [ ] T-001 changed\n- [ ] T-002 second\n")
    assert _fresh_delivery_repair_task_id(
        tmp_path, _intent(), baseline, GitOps(), spec_dir=spec,
        completed_task_ids=("T-001", "T-002"),
    ) is None
