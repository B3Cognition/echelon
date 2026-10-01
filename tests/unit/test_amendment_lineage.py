"""Only target-local, checkpoint-proven work survives an amended Spec plan."""

from __future__ import annotations

import pytest

from harness.amendment_lineage import AmendmentLineageError, proven_amended_task_ids


OLD_HASH = "a" * 64
NEW_HASH = "b" * 64
WEB_CANDIDATE = "c" * 40
API_CANDIDATE = "d" * 40
WEB_CHECKPOINT = "e" * 40
API_CHECKPOINT = "f" * 40


def _manifest() -> dict[str, object]:
    return {
        "status": "promoted",
        "spec_id": "004-demo",
        "pre_amendment_working_hash": OLD_HASH,
        "projected_working_hash": NEW_HASH,
        "old_task_ids": ["T-001", "T-002"],
        "new_task_ids": ["T-003"],
        "target_paths": ["apps/web", "apps/api"],
        "targets": {
            "apps/web": {
                "candidate_commit": WEB_CANDIDATE,
                "source_git_root": "/repo/web",
                "checkpoint_refs": [{
                    "build_id": "build-web", "commit": WEB_CHECKPOINT,
                    "checkpoint_input_hash": OLD_HASH, "task_ids": ["T-001"],
                }],
            },
            "apps/api": {
                "candidate_commit": API_CANDIDATE,
                "source_git_root": "/repo/api",
                "checkpoint_refs": [{
                    "build_id": "build-api", "commit": API_CHECKPOINT,
                    "checkpoint_input_hash": OLD_HASH, "task_ids": ["T-002"],
                }],
            },
        },
    }


def _state(target: str, build: str, checkpoint: str, task: str) -> dict[str, object]:
    return {
        "spec_id": "004-demo", "target_id": target, "build_id": build,
        "status": "blocked",
        "checkpoint_commits": [{
            "commit": checkpoint, "checkpoint_input_hash": OLD_HASH,
            "task_ids": [task],
        }],
        "build": {"task_results": {"T-099": {"status": "DONE"}}},
    }


def _prove(manifest: dict[str, object], states: tuple[dict[str, object], ...],
           *, candidate: str | None = WEB_CANDIDATE,
           current_hash: str = NEW_HASH,
           ancestry=lambda commit, branch: commit == WEB_CHECKPOINT and branch == WEB_CANDIDATE,
           target: str = "apps/web") -> tuple[str, ...]:
    return proven_amended_task_ids(
        manifest, target_id=target, candidate=candidate,
        current_input_hash=current_hash, states=states,
        commit_is_ancestor=ancestry,
    )


def test_carries_only_recorded_target_local_ancestor_checkpoint() -> None:
    web = _state("apps/web", "build-web", WEB_CHECKPOINT, "T-001")
    api = _state("apps/api", "build-api", API_CHECKPOINT, "T-002")
    assert _prove(_manifest(), (web, api)) == ("T-001",)
    assert _prove(
        _manifest(), (web, api), target="apps/api", candidate=API_CANDIDATE,
        ancestry=lambda commit, branch: commit == API_CHECKPOINT and branch == API_CANDIDATE,
    ) == ("T-002",)


@pytest.mark.parametrize("change", [
    "wrong_hash", "nonancestor", "unrecorded_commit", "provider_only", "checkbox_only",
])
def test_unproven_old_work_never_carries(change: str) -> None:
    manifest = _manifest()
    state = _state("apps/web", "build-web", WEB_CHECKPOINT, "T-001")
    ancestry = lambda commit, branch: commit == WEB_CHECKPOINT and branch == WEB_CANDIDATE
    if change == "wrong_hash":
        state["checkpoint_commits"][0]["checkpoint_input_hash"] = "0" * 64
    elif change == "nonancestor":
        ancestry = lambda _commit, _branch: False
    elif change == "unrecorded_commit":
        state["checkpoint_commits"][0]["commit"] = "0" * 40
    elif change == "provider_only":
        state["checkpoint_commits"] = []
    else:
        state["checkpoint_commits"] = []
        state["tasks_markdown"] = "- [x] T-001"
    assert _prove(manifest, (state,), ancestry=ancestry) == ()


@pytest.mark.parametrize("change", [
    "unsettled", "changed_current_hash", "wrong_candidate", "unknown_target",
    "pending_dispatch",
])
def test_changed_or_unsettled_lineage_blocks_before_dispatch(change: str) -> None:
    manifest = _manifest()
    state = _state("apps/web", "build-web", WEB_CHECKPOINT, "T-001")
    candidate = WEB_CANDIDATE
    current_hash = NEW_HASH
    target = "apps/web"
    if change == "unsettled":
        manifest["status"] = "promoting"
    elif change == "changed_current_hash":
        current_hash = "0" * 64
    elif change == "wrong_candidate":
        candidate = "0" * 40
    elif change == "unknown_target":
        target = "apps/other"
    else:
        state["delivery_slice_operation"] = {"id": "sealed", "progress_applied": False}
    with pytest.raises(AmendmentLineageError):
        _prove(manifest, (state,), candidate=candidate, current_hash=current_hash,
               target=target)


def test_no_candidate_never_inherits_progress() -> None:
    manifest = _manifest()
    manifest["targets"]["apps/web"]["candidate_commit"] = None
    manifest["targets"]["apps/web"]["checkpoint_refs"] = []
    assert _prove(manifest, (), candidate=None) == ()


def test_malformed_recorded_task_ids_fail_closed() -> None:
    manifest = _manifest()
    manifest["targets"]["apps/web"]["checkpoint_refs"][0]["task_ids"] = [{"bad": "shape"}]
    with pytest.raises(AmendmentLineageError, match="checkpoint reference"):
        _prove(manifest, ())


def test_newer_uncheckpointed_pending_dispatch_blocks_carry_forward() -> None:
    old = _state("apps/web", "build-web", WEB_CHECKPOINT, "T-001")
    newer = {
        "spec_id": "004-demo", "target_id": "apps/web", "build_id": "build-zzzz",
        "checkpoint_commits": [],
        "delivery_slice_operation": {"id": "sealed-newer", "progress_applied": False},
    }
    with pytest.raises(AmendmentLineageError, match="pending original Delivery operation"):
        _prove(_manifest(), (old, newer))
