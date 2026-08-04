from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

import echelon.spec_retarget_history as history_module
from echelon.spec_retarget_history import (
    RetargetRecoveryProjection,
    advance_retarget_revision,
    append_prepared_revision,
    load_retarget_history,
)


def _projection() -> RetargetRecoveryProjection:
    return RetargetRecoveryProjection(
        run_id="squad-base",
        status="done",
        phase="done",
        spec_status="planned",
        completed_phases=(
            "phase1-requirements",
            "phase3-plan",
            "phase4-document",
        ),
        implementation_targets=("services/api",),
        ready_to_build=True,
    )


def _prepared_revision(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    revision = append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=_projection(),
    )
    return spec_dir, revision


def test_retarget_revision_identity_is_append_only_and_status_advances(
    tmp_path: Path,
) -> None:
    spec_dir, prepared = _prepared_revision(tmp_path)

    invalidating = advance_retarget_revision(
        spec_dir,
        prepared.revision_id,
        expected_status="prepared",
        status="invalidating",
        updates={
            "checkpoint_id": "retarget-preflight-retarget-1",
            "checkpoint_commit": "b" * 40,
        },
    )
    rebuilding = advance_retarget_revision(
        spec_dir,
        prepared.revision_id,
        expected_status="invalidating",
        status="rebuilding",
        updates={"memory_purge": {"status": "complete"}},
    )
    finalizing = advance_retarget_revision(
        spec_dir,
        prepared.revision_id,
        expected_status="rebuilding",
        status="finalizing",
        updates={"graph_invalidation": {"status": "complete"}},
    )
    completed = advance_retarget_revision(
        spec_dir,
        prepared.revision_id,
        expected_status="finalizing",
        status="complete",
        updates={"replacement_commit": "c" * 40},
    )

    history = load_retarget_history(spec_dir)
    assert invalidating.revision_id == rebuilding.revision_id == prepared.revision_id
    assert finalizing.revision_id == completed.revision_id == prepared.revision_id
    assert len(history.revisions) == 1
    assert history.revisions[0].status == "complete"
    assert history.revisions[0].operation_id == "rt-abc"
    assert history.revisions[0].old_targets == ("services/api",)


@pytest.mark.parametrize(
    ("expected_status", "status"),
    [
        ("prepared", "recovered"),
        ("prepared", "complete"),
        ("invalidating", "complete"),
        ("complete", "failed"),
    ],
)
def test_retarget_history_rejects_skipped_or_terminal_transition(
    tmp_path: Path,
    expected_status: str,
    status: str,
) -> None:
    spec_dir, revision = _prepared_revision(tmp_path)
    if expected_status == "invalidating":
        revision = advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status="prepared",
            status="invalidating",
            updates={},
        )
    elif expected_status == "complete":
        for next_status in ("invalidating", "rebuilding", "finalizing"):
            revision = advance_retarget_revision(
                spec_dir,
                revision.revision_id,
                expected_status=revision.status,
                status=next_status,
                updates={},
            )
        revision = advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status="finalizing",
            status="complete",
            updates={"replacement_commit": "c" * 40},
        )

    with pytest.raises(ValueError, match="invalid retarget transition"):
        advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status=expected_status,
            status=status,
            updates={},
        )


def test_retarget_history_compare_and_swap_rejects_stale_status_and_old_revision(
    tmp_path: Path,
) -> None:
    spec_dir, first = _prepared_revision(tmp_path)
    for next_status in ("invalidating", "rebuilding", "finalizing"):
        first = advance_retarget_revision(
            spec_dir,
            first.revision_id,
            expected_status=first.status,
            status=next_status,
            updates={},
        )
    first = advance_retarget_revision(
        spec_dir,
        first.revision_id,
        expected_status="finalizing",
        status="complete",
        updates={"replacement_commit": "c" * 40},
    )
    second = append_prepared_revision(
        spec_dir,
        operation_id="rt-def",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget-2",
        old_targets=("services/api",),
        replacement_targets=("apps/mobile",),
        original_prompt_digest="sha256:" + "d" * 64,
        recovery=_projection(),
    )

    with pytest.raises(ValueError, match="precondition changed"):
        advance_retarget_revision(
            spec_dir,
            first.revision_id,
            expected_status="failed",
            status="recovered",
            updates={"recovery_commit": "e" * 40},
        )
    with pytest.raises(ValueError, match="precondition changed"):
        advance_retarget_revision(
            spec_dir,
            second.revision_id,
            expected_status="invalidating",
            status="rebuilding",
            updates={},
        )


def test_retarget_history_rejects_updates_to_immutable_revision_content(
    tmp_path: Path,
) -> None:
    spec_dir, revision = _prepared_revision(tmp_path)

    with pytest.raises(ValueError, match="immutable retarget revision field"):
        advance_retarget_revision(
            spec_dir,
            revision.revision_id,
            expected_status="prepared",
            status="invalidating",
            updates={"replacement_run_id": "changed"},
        )


def test_retarget_append_rejects_same_baseline_and_replacement_run(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    with pytest.raises(ValueError, match="replacement_run_id"):
        append_prepared_revision(
            spec_dir,
            operation_id="rt-abc",
            baseline_run_id="squad-base",
            replacement_run_id="squad-base",
            old_targets=("services/api",),
            replacement_targets=("apps/web",),
            original_prompt_digest="sha256:" + "a" * 64,
            recovery=_projection(),
        )


def test_retarget_append_rejects_recovery_targets_different_from_old_targets(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    mismatched = replace(
        _projection(),
        implementation_targets=("services/other",),
    )

    with pytest.raises(ValueError, match="recovery implementation_targets"):
        append_prepared_revision(
            spec_dir,
            operation_id="rt-abc",
            baseline_run_id="squad-base",
            replacement_run_id="squad-retarget",
            old_targets=("services/api",),
            replacement_targets=("apps/web",),
            original_prompt_digest="sha256:" + "a" * 64,
            recovery=mismatched,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(replacement_run_id=row["baseline_run_id"]),
        lambda row: row["recovery"].update(
            implementation_targets=["services/other"]
        ),
        lambda row: row.update(replacement_targets=row["old_targets"]),
    ],
)
def test_retarget_history_load_enforces_revision_cross_invariants(
    tmp_path: Path,
    mutation,
) -> None:
    spec_dir, _revision = _prepared_revision(tmp_path)
    path = spec_dir / "retarget-history.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload["revisions"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_retarget_history(spec_dir)


def test_retarget_history_writer_revalidates_directly_constructed_revision(
    tmp_path: Path,
) -> None:
    spec_dir, revision = _prepared_revision(tmp_path)
    history = load_retarget_history(spec_dir)
    invalid = replace(
        revision,
        replacement_run_id=revision.baseline_run_id,
    )

    with pytest.raises(ValueError, match="replacement_run_id"):
        history_module._write_history_atomic(
            spec_dir,
            replace(history, revisions=(invalid,)),
        )


@pytest.mark.parametrize(
    "older_status",
    ["prepared", "invalidating", "rebuilding", "finalizing", "failed"],
)
def test_retarget_history_rejects_nonterminal_or_failed_historical_revision(
    tmp_path: Path,
    older_status: str,
) -> None:
    spec_dir, _revision = _prepared_revision(tmp_path)
    path = spec_dir / "retarget-history.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    older = payload["revisions"][0]
    older["status"] = older_status
    latest = json.loads(json.dumps(older))
    latest["revision_id"] = "retarget-" + "b" * 32
    latest["operation_id"] = "rt-next"
    latest["replacement_run_id"] = "squad-retarget-next"
    latest["replacement_targets"] = ["apps/mobile"]
    latest["status"] = "prepared"
    payload["revisions"].append(latest)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="historical retarget revision"):
        load_retarget_history(spec_dir)


def test_retarget_append_cannot_supersede_failed_revision(tmp_path: Path) -> None:
    spec_dir, revision = _prepared_revision(tmp_path)
    advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="prepared",
        status="failed",
        updates={"failure_code": "retarget_checkpoint_failed"},
    )

    with pytest.raises(ValueError, match="not terminal"):
        append_prepared_revision(
            spec_dir,
            operation_id="rt-next",
            baseline_run_id="squad-base",
            replacement_run_id="squad-retarget-next",
            old_targets=("services/api",),
            replacement_targets=("apps/mobile",),
            original_prompt_digest="sha256:" + "b" * 64,
            recovery=_projection(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update(extra=True), "invalid retarget history keys"),
        (
            lambda payload: payload["revisions"][0].update(extra=True),
            "invalid retarget revision keys",
        ),
        (
            lambda payload: payload["revisions"][0]["recovery"].update(extra=True),
            "invalid retarget recovery keys",
        ),
        (
            lambda payload: payload["revisions"][0].update(
                original_prompt_digest="sha256:not-a-digest"
            ),
            "original_prompt_digest",
        ),
        (
            lambda payload: payload["revisions"][0].update(
                checkpoint_commit="ABCDEF"
            ),
            "checkpoint_commit",
        ),
        (
            lambda payload: payload["revisions"].append(payload["revisions"][0].copy()),
            "duplicate retarget revision",
        ),
        (
            lambda payload: payload["revisions"][0].update(
                old_targets=["x" * 1025]
            ),
            "old_targets",
        ),
    ],
)
def test_retarget_history_rejects_malformed_persisted_schema(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    spec_dir, _revision = _prepared_revision(tmp_path)
    path = spec_dir / "retarget-history.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_retarget_history(spec_dir)


def test_retarget_history_rejects_nonregular_ledger(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "retarget-history.json").mkdir()

    with pytest.raises(ValueError, match="regular file"):
        load_retarget_history(spec_dir)


def test_retarget_history_validates_nested_artifact_digests(tmp_path: Path) -> None:
    spec_dir, revision = _prepared_revision(tmp_path)
    advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="prepared",
        status="invalidating",
        updates={
            "artifact_inventory": (
                {"path": "spec.md", "sha256": "sha256:" + "f" * 64},
            ),
        },
    )
    path = spec_dir / "retarget-history.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["revisions"][0]["artifact_inventory"][0]["sha256"] = "sha256:bad"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact_inventory"):
        load_retarget_history(spec_dir)


def test_retarget_history_atomic_replace_is_file_then_parent_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    events: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def observed_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        events.append("parent_fsync" if history_module.stat.S_ISDIR(mode) else "file_fsync")
        real_fsync(descriptor)

    def observed_replace(source, destination) -> None:
        assert Path(source).parent == spec_dir
        assert Path(source).is_file()
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(history_module.os, "fsync", observed_fsync)
    monkeypatch.setattr(history_module.os, "replace", observed_replace)

    append_prepared_revision(
        spec_dir,
        operation_id="rt-abc",
        baseline_run_id="squad-base",
        replacement_run_id="squad-retarget",
        old_targets=("services/api",),
        replacement_targets=("apps/web",),
        original_prompt_digest="sha256:" + "a" * 64,
        recovery=_projection(),
    )

    assert events[-3:] == ["file_fsync", "replace", "parent_fsync"]


def test_retarget_history_enforces_bounded_revision_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_dir, revision = _prepared_revision(tmp_path)
    failed = advance_retarget_revision(
        spec_dir,
        revision.revision_id,
        expected_status="prepared",
        status="failed",
        updates={"failure_code": "retarget_checkpoint_failed"},
    )
    history = load_retarget_history(spec_dir)
    monkeypatch.setattr(history_module, "_MAX_REVISIONS", 1)
    with pytest.raises(ValueError, match="too many retarget revisions"):
        history_module._write_history_atomic(
            spec_dir,
            replace(history, revisions=(failed, failed)),
        )
