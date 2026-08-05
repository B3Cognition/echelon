"""Controller-owned retarget finalization contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from jsonschema import Draft7Validator


def _receipt(*, memory: dict[str, object]) -> dict[str, object]:
    return {
        "revision_id": "retarget-1",
        "completion_id": "a" * 32,
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
def test_retarget_completion_trailers_reject_unknown_or_duplicate_identity() -> None:
    from echelon.spec_retarget_finalization import _exact_trailers_match

    identity = {"Echelon-Action": "retarget-complete"}

    assert not _exact_trailers_match(
        "Echelon-Action: retarget-complete\nEchelon-Action: retarget-complete\n",
        identity,
    )
    assert not _exact_trailers_match(
        "Echelon-Action: retarget-complete\nEchelon-Injected: forged\n",
        identity,
    )


@pytest.mark.unit
def test_terminal_graph_verifier_rejects_nonterminal_receipt_before_reading_files(
    tmp_path: Path,
) -> None:
    from echelon.spec_retarget_finalization import (
        RetargetFinalizationError,
        verify_retarget_graph_postimage,
    )
    from echelon.spec_retarget_graph import RetargetGraphReceipt

    receipt = RetargetGraphReceipt(
        spec_id="001-demo",
        spec_status="invalidated",
        spec_graph_hash=None,
        workspace_status="not_applicable_empty_workspace",
        workspace_graph_hash=None,
        workspace_finding_codes=(),
    )

    with pytest.raises(RetargetFinalizationError, match="terminal"):
        verify_retarget_graph_postimage(tmp_path, tmp_path / "specs" / "001-demo", receipt)


@pytest.mark.unit
def test_state_schema_retarget_contract_is_closed_and_requires_identity() -> None:
    schema = __import__("json").loads(
        (Path(__file__).parents[2] / "templates/state-schema.json").read_text()
    )["properties"]["retarget"]
    validator = Draft7Validator(schema)

    assert list(validator.iter_errors({}))
    assert list(
        validator.iter_errors(
            {
                "status": "finalizing",
                "revision_id": "rt-1",
                "unknown": True,
            }
        )
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "status",
    ["checkpointed", "invalidating", "rebuilding", "finalizing", "failed", "recovered"],
)
def test_state_schema_retarget_nonterminal_variants_forbid_completion_receipt(status: str) -> None:
    schema = __import__("json").loads(
        (Path(__file__).parents[2] / "templates/state-schema.json").read_text()
    )["properties"]["retarget"]
    value = {
        "operation_id": "op-1",
        "revision_id": "rt-1",
        "status": status,
        "baseline_run_id": "baseline",
        "replacement_run_id": "replacement",
        "old_targets": ["services/api"],
        "replacement_targets": ["apps/web"],
        "checkpoint_id": "checkpoint-1",
        "checkpoint_commit": "a" * 40,
        "failure_code": None,
        "replacement_commit": "b" * 40,
    }
    assert list(Draft7Validator(schema).iter_errors(value))


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
    calls = {"memory": 0, "graph": 0, "memory_verify": 0, "graph_verify": 0}

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
    def refresh(*_args):
        calls["memory"] += 1
        return finalization.RetargetMemoryReceipt(**{
            **memory,
            "deleted_ids": (),
            "remaining_owned_ids": (),
            "unrelated_missing_ids": (),
            "unrelated_changed_ids": (),
            "unexpected_added_ids": (),
        })

    def finalize(*_args):
        calls["graph"] += 1
        return finalization.RetargetGraphReceipt.from_dict(graph)

    monkeypatch.setattr(finalization, "refresh_retarget_spec_memory", refresh)
    monkeypatch.setattr(finalization, "finalize_retarget_graphs", finalize)
    monkeypatch.setattr(
        finalization,
        "verify_retarget_memory_postimage",
        lambda *_args: calls.__setitem__("memory_verify", calls["memory_verify"] + 1),
    )
    monkeypatch.setattr(
        finalization,
        "verify_retarget_graph_postimage",
        lambda *_args: calls.__setitem__("graph_verify", calls["graph_verify"] + 1),
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
    assert finalization.apply_or_verify_retarget_finalization(
        prepared,
        project_root=project_root,
        state=state,
        expected_receipt=None,
    ) == first
    assert calls == {"memory": 1, "graph": 1, "memory_verify": 1, "graph_verify": 1}


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
Echelon-Origin: phase-a
Echelon-Spec: 001-demo
Echelon-Run: run-replacement
Echelon-Checkpoint: dddddddddddddddddddddddddddddddddddddddd
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
            "checkpoint_commit": "d" * 40,
        },
        "a" * 32,
    ) == commit
