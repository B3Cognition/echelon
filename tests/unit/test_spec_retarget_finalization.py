"""Controller-owned retarget finalization contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


def _receipt(*, memory: dict[str, object]) -> dict[str, object]:
    return {
        "revision_id": "retarget-1",
        "checkpoint_commit": "a" * 40,
        "replacement_targets": ["apps/web"],
        "memory": memory,
        "graph": {
            "spec_id": "001-demo",
            "spec_status": "pass",
            "spec_graph_hash": "sha256:" + "b" * 64,
            "workspace_status": "not_applicable_empty_workspace",
            "workspace_graph_hash": None,
            "workspace_finding_codes": [],
        },
        "replacement_commit": "c" * 40,
        "status": "complete",
    }


@pytest.mark.unit
def test_retarget_finalization_rejects_nonfinalizing_runtime_state(tmp_path: Path) -> None:
    from echelon.spec_retarget_finalization import RetargetFinalizationError
    from echelon.spec_retarget_finalization import require_finalizing_retarget

    with pytest.raises(RetargetFinalizationError, match="finalizing"):
        require_finalizing_retarget({"retarget": {"status": "rebuilding"}})


@pytest.mark.unit
def test_retarget_finalization_rejects_unsealed_receipt(tmp_path: Path) -> None:
    from echelon.spec_retarget_finalization import RetargetFinalizationError
    from echelon.spec_retarget_finalization import validate_finalization_receipt

    with pytest.raises(RetargetFinalizationError, match="receipt"):
        validate_finalization_receipt({})


@pytest.mark.unit
def test_retarget_finalization_rejects_unvalidated_memory_receipt() -> None:
    from echelon.spec_retarget_finalization import RetargetFinalizationError
    from echelon.spec_retarget_finalization import validate_finalization_receipt

    with pytest.raises(RetargetFinalizationError, match="memory"):
        validate_finalization_receipt(_receipt(memory={"forged": "receipt"}))


@pytest.mark.unit
def test_retarget_effect_progress_is_bound_to_the_completion_id(tmp_path: Path) -> None:
    from echelon.spec_retarget_finalization import (
        RetargetFinalizationError,
        persist_retarget_effect_progress,
    )

    prepared = SimpleNamespace(
        _transaction_root=tmp_path,
        intent=SimpleNamespace(completion_id="a" * 32),
    )
    persist_retarget_effect_progress(prepared, "memory", {"receipt": "one"})

    (tmp_path / "retarget-progress.json").write_text(
        '{"completion_id":"' + "b" * 32 + '","memory":{"receipt":"one"},"graph":null}\n',
        encoding="utf-8",
    )
    with pytest.raises(RetargetFinalizationError, match="progress"):
        persist_retarget_effect_progress(prepared, "graph", {"receipt": "two"})


@pytest.mark.unit
def test_retarget_effect_progress_can_be_replayed_only_for_its_completion(
    tmp_path: Path,
) -> None:
    from echelon.spec_retarget_finalization import (
        load_retarget_effect_progress,
        persist_retarget_effect_progress,
    )

    prepared = SimpleNamespace(
        _transaction_root=tmp_path,
        intent=SimpleNamespace(completion_id="a" * 32),
    )
    memory = {
        "status": "not_applicable",
        "spec_id": "001-demo",
        "deleted_count": 0,
        "deleted_ids": [],
        "drawer_set_digest": "sha256:" + "b" * 64,
        "mine_status": None,
        "audit_status": None,
        "adapter": None,
        "wing": None,
        "palace_path": None,
        "scanned_count": 0,
        "delete_acknowledged_count": None,
        "remaining_owned_ids": [],
        "unrelated_missing_ids": [],
        "unrelated_changed_ids": [],
        "unexpected_added_ids": [],
        "report_set_digest": None,
        "failure_code": None,
    }
    persist_retarget_effect_progress(prepared, "memory", memory)

    assert load_retarget_effect_progress(prepared) == {
        "memory": memory,
        "graph": None,
    }


@pytest.mark.unit
def test_retarget_effect_progress_recovers_from_an_unpublished_private_tempfile(
    tmp_path: Path,
) -> None:
    from echelon.spec_retarget_finalization import persist_retarget_effect_progress

    prepared = SimpleNamespace(
        _transaction_root=tmp_path,
        intent=SimpleNamespace(completion_id="a" * 32),
    )
    (tmp_path / (".retarget-progress.json." + "a" * 32 + ".tmp")).write_text(
        "partial",
        encoding="utf-8",
    )

    persist_retarget_effect_progress(prepared, "memory", {"receipt": "one"})

    assert (tmp_path / "retarget-progress.json").is_file()


@pytest.mark.unit
def test_retarget_finalization_replays_private_effect_progress_after_a_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.spec_retarget_finalization as finalization

    project_root = tmp_path / "project"
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    prepared = SimpleNamespace(
        _transaction_root=tmp_path / "completion",
        intent=SimpleNamespace(completion_id="a" * 32),
    )
    prepared._transaction_root.mkdir()
    memory = {
        "status": "not_applicable",
        "spec_id": "001-demo",
        "deleted_count": 0,
        "deleted_ids": [],
        "drawer_set_digest": "sha256:" + "b" * 64,
        "mine_status": None,
        "audit_status": None,
        "adapter": None,
        "wing": None,
        "palace_path": None,
        "scanned_count": 0,
        "delete_acknowledged_count": None,
        "remaining_owned_ids": [],
        "unrelated_missing_ids": [],
        "unrelated_changed_ids": [],
        "unexpected_added_ids": [],
        "report_set_digest": None,
        "failure_code": None,
    }
    graph = {
        "spec_id": "001-demo",
        "spec_status": "pass",
        "spec_graph_hash": "sha256:" + "c" * 64,
        "workspace_status": "not_applicable_empty_workspace",
        "workspace_graph_hash": None,
        "workspace_finding_codes": [],
    }
    state = {
        "spec_id": "001-demo",
        "published_spec_dir": "specs/001-demo",
        "retarget": {
            "status": "finalizing",
            "revision_id": "retarget-1",
            "checkpoint_commit": "d" * 40,
            "replacement_targets": ["apps/web"],
            "replacement_run_id": "run-replacement",
            "baseline_run_id": "run-baseline",
            "graph_invalidation": graph,
        },
    }
    history = {"status": "finalizing"}

    def revision() -> SimpleNamespace:
        return SimpleNamespace(
            revision_id="retarget-1",
            status=history["status"],
            memory_finalization=memory if history["status"] == "complete" else None,
            graph_finalization=graph if history["status"] == "complete" else None,
        )

    monkeypatch.setattr(
        finalization,
        "load_retarget_history",
        lambda *_args: SimpleNamespace(revisions=(revision(),)),
    )
    monkeypatch.setattr(
        finalization,
        "refresh_retarget_spec_memory",
        lambda *_args: finalization.RetargetMemoryReceipt(**{
            **memory,
            "deleted_ids": (),
            "remaining_owned_ids": (),
            "unrelated_missing_ids": (),
            "unrelated_changed_ids": (),
            "unexpected_added_ids": (),
        }),
    )
    monkeypatch.setattr(
        finalization,
        "finalize_retarget_graphs",
        lambda *_args: finalization.RetargetGraphReceipt.from_dict(graph),
    )
    monkeypatch.setattr(
        finalization,
        "advance_retarget_revision",
        lambda *_args, **_kwargs: (
            history.__setitem__("status", "complete") or revision()
        ),
    )
    monkeypatch.setattr(
        finalization,
        "_find_retarget_completion_commit",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        finalization,
        "_commit_retarget_completion",
        lambda *_args: "e" * 40,
    )

    first = finalization.apply_or_verify_retarget_finalization(
        prepared,
        project_root=project_root,
        state=state,
        expected_receipt=None,
    )
    monkeypatch.setattr(
        finalization,
        "refresh_retarget_spec_memory",
        lambda *_args: pytest.fail("memory effect must not rerun"),
    )
    monkeypatch.setattr(
        finalization,
        "finalize_retarget_graphs",
        lambda *_args: pytest.fail("graph effect must not rerun"),
    )

    assert finalization.apply_or_verify_retarget_finalization(
        prepared,
        project_root=project_root,
        state=state,
        expected_receipt=None,
    ) == first


@pytest.mark.unit
def test_retarget_finalization_recovers_the_unique_committed_effect(
    tmp_path: Path,
) -> None:
    from echelon.spec_retarget_finalization import _find_retarget_completion_commit

    project_root = tmp_path / "project"
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    for args in (
        ("init", "-b", "main"),
        ("config", "user.name", "Echelon Tests"),
        ("config", "user.email", "echelon@example.test"),
    ):
        subprocess.run(["git", *args], cwd=project_root, check=True, capture_output=True)
    history = spec_dir / "retarget-history.json"
    history.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=project_root, check=True, capture_output=True
    )
    history.write_text('{"complete":true}\n', encoding="utf-8")
    message = """chore: finalize retargeted spec

Echelon-Action: retarget-complete
Echelon-Completion: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Echelon-Retarget-Revision: retarget-1
Echelon-Baseline-Run: run-baseline
Echelon-Replacement-Run: run-replacement
"""
    subprocess.run(["git", "add", "."], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=project_root,
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_root, check=True, capture_output=True, text=True
    ).stdout.strip()

    assert _find_retarget_completion_commit(
        project_root,
        spec_dir,
        {
            "revision_id": "retarget-1",
            "baseline_run_id": "run-baseline",
            "replacement_run_id": "run-replacement",
        },
        "a" * 32,
    ) == commit
