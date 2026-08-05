"""Controller-owned retarget finalization contracts."""

from __future__ import annotations

import hashlib
import json
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


def _memory_receipt() -> dict[str, object]:
    return {
        "status": "not_applicable",
        "spec_id": "001-demo",
        "deleted_count": 0,
        "deleted_ids": [],
        "drawer_set_digest": "sha256:" + hashlib.sha256(b"[]").hexdigest(),
        "mine_status": "not_applicable",
        "audit_status": "not_applicable",
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


def _graph_receipt(*, terminal: bool) -> dict[str, object]:
    return {
        "spec_id": "001-demo",
        "spec_status": "pass" if terminal else "invalidated",
        "spec_graph_hash": "sha256:" + "b" * 64 if terminal else None,
        "workspace_status": "pass" if terminal else "not_applicable_empty_workspace",
        "workspace_graph_hash": "sha256:" + "c" * 64 if terminal else None,
        "workspace_finding_codes": [],
    }


def _mine_report(drawer_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "spec_id": "001-demo",
        "spec_dir": "specs/001-demo",
        "wing": "test",
        "palace_path": "test",
        "status": "complete",
        "expected_count": len(drawer_ids),
        "written_count": len(drawer_ids),
        "adopted_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "drifted_count": 0,
        "unavailable_count": 0,
        "drawer_ids": drawer_ids,
        "expected_drawer_ids": drawer_ids,
        "errors": [],
    }


def _memory_audit(drawer_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        spec_id="001-demo",
        status="pass",
        wing="test",
        palace_path="test",
        expected_count=len(drawer_ids),
        present_current_count=len(drawer_ids),
        missing=[],
        stale=[],
        wrong_wing=[],
        wrong_room=[],
        duplicate=[],
        non_canonical=[],
        lifecycle_excluded=[],
        errors=[],
    )


def _write_memory_manifest(
    finalization: object,
    spec_dir: Path,
    digest: str,
) -> None:
    (spec_dir / "mempalace-refresh-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spec_id": "001-demo",
                "files": finalization._current_memory_report_records(spec_dir),
                "report_set_digest": digest,
            }
        ),
        encoding="utf-8",
    )


def _retarget_state(status: str) -> dict[str, object]:
    memory = _memory_receipt()
    baseline_graph = _graph_receipt(terminal=False)
    final_graph = _graph_receipt(terminal=True)
    state: dict[str, object] = {
        "operation_id": "op-1",
        "revision_id": "rt-1",
        "status": status,
        "baseline_run_id": "baseline",
        "replacement_run_id": "replacement",
        "old_targets": ["services/api"],
        "replacement_targets": ["apps/web"],
        "artifact_invalidation": ["plan.md", "spec.md", "targets.yml", "tasks.md"],
        "checkpoint_id": "checkpoint-1",
        "checkpoint_commit": "a" * 40,
        "failure_code": "interrupted" if status == "failed" else None,
    }
    if status in {"invalidating", "rebuilding", "finalizing", "complete", "failed", "recovered"}:
        state.update(memory_excluded=True, memory_purge=memory)
    if status in {"rebuilding", "finalizing", "complete", "failed", "recovered"}:
        state["graph_invalidation"] = baseline_graph
    if status == "complete":
        state.update(
            replacement_commit="d" * 40,
            finalization_receipt={
                "revision_id": "rt-1",
                "completion_id": "e" * 32,
                "checkpoint_commit": "a" * 40,
                "replacement_targets": ["apps/web"],
                "memory": memory,
                "graph": final_graph,
                "replacement_commit": "d" * 40,
                "status": "complete",
            },
            comparison_pending_completion_id="e" * 32,
            comparison_event_id="retarget-comparison-" + "e" * 32,
            comparison_command="git diff a..b -- specs/001-demo",
        )
    return state


def _retarget_schema_errors(value: dict[str, object]) -> list[object]:
    schema = __import__("json").loads(
        (Path(__file__).parents[2] / "templates/state-schema.json").read_text()
    )
    state = {
        "run_id": "squad-001-1",
        "status": "running",
        "phase": "init",
        "iteration": 0,
        "created_at": "2026-08-05T00:00:00+00:00",
        "retarget": value,
    }
    return list(Draft7Validator(schema).iter_errors(state))


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
def test_state_schema_retarget_completion_receipt_closes_nested_evidence() -> None:
    value = {
        "operation_id": "op-1", "revision_id": "rt-1", "status": "complete",
        "baseline_run_id": "baseline", "replacement_run_id": "replacement",
        "old_targets": ["services/api"], "replacement_targets": ["apps/web"],
        "checkpoint_id": "checkpoint-1", "checkpoint_commit": "a" * 40,
        "replacement_commit": "b" * 40, "failure_code": None,
        "finalization_receipt": {
            "revision_id": "rt-1", "completion_id": "c" * 32,
            "checkpoint_commit": "a" * 40, "replacement_targets": ["apps/web"],
            "memory": {"forged": True}, "graph": {"forged": True},
            "replacement_commit": "b" * 40, "status": "complete",
        },
    }
    assert _retarget_schema_errors(value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,field",
    [
        ("checkpointed", "memory_purge"),
        ("invalidating", "memory_purge"),
        ("rebuilding", "graph_invalidation"),
        ("finalizing", "memory_purge"),
        ("complete", "finalization_receipt"),
        ("failed", "memory_purge"),
        ("recovered", "graph_invalidation"),
    ],
)
def test_state_schema_retarget_receipt_matrix_rejects_forged_nested_evidence(
    status: str,
    field: str,
) -> None:
    value = _retarget_state(status)
    value[field] = {"forged": True}

    assert _retarget_schema_errors(value)


@pytest.mark.unit
@pytest.mark.parametrize(
    "status",
    ["checkpointed", "invalidating", "rebuilding", "finalizing", "complete", "failed", "recovered"],
)
def test_state_schema_retarget_receipt_matrix_accepts_valid_status_examples(
    status: str,
) -> None:
    assert not _retarget_schema_errors(_retarget_state(status))


@pytest.mark.unit
def test_state_schema_accepts_exact_controller_adopted_complete_state() -> None:
    value = _retarget_state("complete")

    assert not _retarget_schema_errors(value)
    assert "memory_finalization" not in value
    assert "graph_finalization" not in value

    incomplete = __import__("copy").deepcopy(value)
    del incomplete["finalization_receipt"]["memory"]
    assert _retarget_schema_errors(incomplete)

    extended = __import__("copy").deepcopy(value)
    extended["finalization_receipt"]["extra"] = True
    assert _retarget_schema_errors(extended)


@pytest.mark.unit
@pytest.mark.parametrize("replay_path", ["persisted_progress", "expected_receipt"])
@pytest.mark.parametrize(
    "invalid_part",
    [
        "memory_fail",
        "memory_warn",
        "memory_invalid",
        "memory_spec_id",
        "graph_invalidated",
        "graph_workspace_fail",
        "graph_invalid",
        "graph_spec_id",
    ],
)
def test_replay_paths_reject_nonterminal_or_cross_spec_receipts_before_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_path: str,
    invalid_part: str,
) -> None:
    import echelon.spec_retarget_finalization as finalization

    project_root = tmp_path / "project"
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    prepared = SimpleNamespace(
        _transaction_root=tmp_path / "completion",
        intent=SimpleNamespace(completion_id="e" * 32),
    )
    prepared._transaction_root.mkdir()
    memory = _memory_receipt()
    graph = _graph_receipt(terminal=True)
    if invalid_part == "memory_fail":
        memory["status"] = "fail"
        memory["failure_code"] = "mine_failed"
    elif invalid_part in {"memory_warn", "memory_invalid"}:
        memory["status"] = invalid_part.removeprefix("memory_")
    elif invalid_part == "memory_spec_id":
        memory["spec_id"] = "002-other"
    elif invalid_part == "graph_invalidated":
        graph["spec_status"] = "invalidated"
        graph["spec_graph_hash"] = None
    elif invalid_part == "graph_workspace_fail":
        graph["workspace_status"] = "fail"
    elif invalid_part == "graph_invalid":
        graph["spec_status"] = "invalid"
    elif invalid_part == "graph_spec_id":
        graph["spec_id"] = "002-other"
    state = {
        "spec_id": "001-demo",
        "published_spec_dir": "specs/001-demo",
        "retarget": {
            "status": "finalizing",
            "revision_id": "rt-1",
            "checkpoint_commit": "a" * 40,
            "replacement_targets": ["apps/web"],
            "replacement_run_id": "replacement",
            "baseline_run_id": "baseline",
            "graph_invalidation": _graph_receipt(terminal=False),
        },
    }
    if replay_path == "persisted_progress":
        (prepared._transaction_root / "retarget-progress.json").write_text(
            json.dumps(
                {"completion_id": "e" * 32, "memory": memory, "graph": graph}
            ),
            encoding="utf-8",
        )
        expected: object = None
    else:
        expected = {
            "revision_id": "rt-1",
            "completion_id": "e" * 32,
            "checkpoint_commit": "a" * 40,
            "replacement_targets": ["apps/web"],
            "memory": memory,
            "graph": graph,
            "replacement_commit": "d" * 40,
            "status": "complete",
        }
    monkeypatch.setattr(
        finalization,
        "load_retarget_history",
        lambda *_args: pytest.fail("advanced to history"),
    )

    with pytest.raises(finalization.RetargetFinalizationError):
        finalization.apply_or_verify_retarget_finalization(
            prepared,
            project_root=project_root,
            state=state,
            expected_receipt=expected,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    ["missing_report", "corrupt_mine", "corrupt_manifest", "audit_error"],
)
def test_memory_postimage_normalizes_evidence_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import echelon.spec_retarget_finalization as finalization

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    drawer_ids = ["drawer-1"]
    for name, payload in {
        "mempalace-audit.json": b'{"audit":"pass"}\n',
        "mempalace-audit.md": b"# audit\n",
        "mempalace-mine.json": json.dumps(_mine_report(drawer_ids)).encode(),
    }.items():
        (spec_dir / name).write_bytes(payload)
    report_digest = finalization._current_memory_report_set_digest(spec_dir)
    _write_memory_manifest(finalization, spec_dir, report_digest)
    drawer_digest = "sha256:" + hashlib.sha256(
        json.dumps(drawer_ids, separators=(",", ":")).encode()
    ).hexdigest()
    values = {
        **_memory_receipt(),
        "status": "pass",
        "drawer_set_digest": drawer_digest,
        "mine_status": "complete",
        "audit_status": "pass",
        "adapter": "test",
        "wing": "test",
        "palace_path": "test",
        "report_set_digest": report_digest,
    }
    for field in (
        "deleted_ids",
        "remaining_owned_ids",
        "unrelated_missing_ids",
        "unrelated_changed_ids",
        "unexpected_added_ids",
    ):
        values[field] = tuple(values[field])
    receipt = finalization.RetargetMemoryReceipt(**values)
    monkeypatch.setattr(
        finalization, "_configured_mempalace_wing", lambda *_args: "test"
    )
    if failure == "audit_error":
        monkeypatch.setattr(
            finalization,
            "audit_spec_memory",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("adapter audit failed")
            ),
        )
    else:
        monkeypatch.setattr(
            finalization,
            "audit_spec_memory",
            lambda *_args, **_kwargs: _memory_audit(drawer_ids),
        )
    if failure == "missing_report":
        (spec_dir / "mempalace-audit.md").unlink()
    elif failure == "corrupt_mine":
        (spec_dir / "mempalace-mine.json").write_text("{bad json\n")
    elif failure == "corrupt_manifest":
        (spec_dir / "mempalace-refresh-manifest.json").write_text("[]\n")

    with pytest.raises(
        finalization.RetargetFinalizationError,
        match="^retarget finalization memory postimage drifted$",
    ):
        finalization.verify_retarget_memory_postimage(tmp_path, spec_dir, receipt)


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure",
    ["missing_graph", "graph_read_error", "audit_error", "corrupt_member"],
)
def test_graph_postimage_normalizes_evidence_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    import echelon.spec_retarget_finalization as finalization

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    spec_graph = spec_dir / "spec-artifact-graph.json"
    workspace_graph = finalization.workspace_graph_path(tmp_path)
    workspace_graph.parent.mkdir(parents=True, exist_ok=True)
    spec_graph.write_bytes(b"spec graph")
    workspace_graph.write_bytes(b"workspace graph")
    spec_hash = "sha256:" + hashlib.sha256(b"spec graph").hexdigest()
    workspace_hash = "sha256:" + hashlib.sha256(b"workspace graph").hexdigest()
    receipt = finalization.RetargetGraphReceipt(
        "001-demo", "pass", spec_hash, "pass", workspace_hash, ()
    )
    monkeypatch.setattr(
        finalization,
        "audit_spec_graph",
        lambda *_args: SimpleNamespace(
            spec_id="001-demo", graph_hash=spec_hash, status="pass"
        ),
    )
    member = (
        SimpleNamespace(spec_id="001-demo")
        if failure == "corrupt_member"
        else SimpleNamespace(
            spec_id="001-demo",
            included=True,
            graph_hash=spec_hash,
            audit_status="pass",
        )
    )
    if failure == "audit_error":
        monkeypatch.setattr(
            finalization,
            "audit_workspace_graph",
            lambda *_args: (_ for _ in ()).throw(RuntimeError("audit failed")),
        )
    else:
        monkeypatch.setattr(
            finalization,
            "audit_workspace_graph",
            lambda *_args: SimpleNamespace(
                graph_hash=workspace_hash,
                status="pass",
                findings=(),
                members=(member,),
            ),
        )
    if failure == "missing_graph":
        spec_graph.unlink()
    elif failure == "graph_read_error":
        monkeypatch.setattr(
            finalization,
            "_sha256_file",
            lambda *_args: (_ for _ in ()).throw(OSError("read failed")),
        )

    with pytest.raises(
        finalization.RetargetFinalizationError,
        match="^retarget finalization graph postimage drifted$",
    ):
        finalization.verify_retarget_graph_postimage(tmp_path, spec_dir, receipt)


@pytest.mark.unit
@pytest.mark.parametrize("drift", ["report_bytes", "report_digest"])
def test_memory_postimage_rejects_live_report_drift_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    import hashlib
    import json
    import echelon.spec_retarget_finalization as finalization

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    drawer_ids = ["drawer-1"]
    drawer_digest = "sha256:" + hashlib.sha256(
        json.dumps(drawer_ids, separators=(",", ":")).encode()
    ).hexdigest()
    for name, payload in {
        "mempalace-audit.json": b'{"audit":"pass"}\n',
        "mempalace-audit.md": b"# audit\n",
        "mempalace-mine.json": json.dumps(_mine_report(drawer_ids)).encode(),
    }.items():
        (spec_dir / name).write_bytes(payload)
    digest = finalization._current_memory_report_set_digest(spec_dir)
    _write_memory_manifest(finalization, spec_dir, digest)
    memory_values = {
        **_memory_receipt(), "status": "pass", "drawer_set_digest": drawer_digest,
        "mine_status": "complete", "audit_status": "pass", "adapter": "test",
        "wing": "test", "palace_path": "test", "report_set_digest": digest,
    }
    for field in (
        "deleted_ids", "remaining_owned_ids", "unrelated_missing_ids",
        "unrelated_changed_ids", "unexpected_added_ids",
    ):
        memory_values[field] = tuple(memory_values[field])
    receipt = finalization.RetargetMemoryReceipt(**memory_values)
    monkeypatch.setattr(
        finalization, "_configured_mempalace_wing", lambda *_args: "test"
    )
    monkeypatch.setattr(
        finalization,
        "audit_spec_memory",
        lambda *_args, **_kwargs: _memory_audit(drawer_ids),
    )
    original = {path.name: path.read_bytes() for path in spec_dir.iterdir()}
    if drift == "report_bytes":
        (spec_dir / "mempalace-audit.md").write_bytes(b"tampered\n")
    else:
        receipt = finalization.RetargetMemoryReceipt(
            **{**receipt.to_dict(), "report_set_digest": "sha256:" + "f" * 64,
               "failure_code": None,
               "deleted_ids": (), "remaining_owned_ids": (),
               "unrelated_missing_ids": (), "unrelated_changed_ids": (),
               "unexpected_added_ids": ()}
        )

    with pytest.raises(finalization.RetargetFinalizationError, match="postimage drifted"):
        finalization.verify_retarget_memory_postimage(tmp_path, spec_dir, receipt)
    if drift == "report_bytes":
        assert (spec_dir / "mempalace-audit.md").read_bytes() == b"tampered\n"
    else:
        assert {path.name: path.read_bytes() for path in spec_dir.iterdir()} == original


@pytest.mark.unit
@pytest.mark.parametrize(
    "drift",
    ["missing_spec", "missing_workspace", "bytes", "spec_audit", "workspace_audit", "findings"],
)
def test_graph_postimage_rejects_each_live_drift_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    import hashlib
    import echelon.spec_retarget_finalization as finalization

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    spec_graph = spec_dir / "spec-artifact-graph.json"
    workspace_graph = finalization.workspace_graph_path(tmp_path)
    workspace_graph.parent.mkdir(parents=True, exist_ok=True)
    if drift != "missing_spec":
        spec_graph.write_bytes(b"spec graph")
    if drift not in {"missing_workspace", "missing_spec"}:
        workspace_graph.write_bytes(b"workspace graph")
    spec_hash = "sha256:" + hashlib.sha256(b"spec graph").hexdigest()
    workspace_hash = "sha256:" + hashlib.sha256(b"workspace graph").hexdigest()
    receipt = finalization.RetargetGraphReceipt(
        "001-demo", "pass", spec_hash, "pass", workspace_hash, ()
    )
    monkeypatch.setattr(
        finalization,
        "audit_spec_graph",
        lambda *_args: SimpleNamespace(
            graph_hash=spec_hash, status="fail" if drift == "spec_audit" else "pass"
        ),
    )
    monkeypatch.setattr(
        finalization,
        "audit_workspace_graph",
        lambda *_args: SimpleNamespace(
            graph_hash=workspace_hash,
            status="fail" if drift == "workspace_audit" else "pass",
            findings=(SimpleNamespace(code="unexpected", subject_id="001-demo"),)
            if drift == "findings" else (),
            members=(SimpleNamespace(spec_id="001-demo", included=True,
                                     graph_hash=spec_hash, audit_status="pass"),),
        ),
    )
    if drift == "bytes":
        spec_graph.write_bytes(b"tampered graph")
    original = {
        path.name: path.read_bytes()
        for path in (spec_graph, workspace_graph)
        if path.exists()
    }

    with pytest.raises(finalization.RetargetFinalizationError, match="postimage drifted"):
        finalization.verify_retarget_graph_postimage(tmp_path, spec_dir, receipt)
    assert {
        path.name: path.read_bytes()
        for path in (spec_graph, workspace_graph)
        if path.exists()
    } == original


@pytest.mark.unit
def test_live_postimage_verifiers_reuse_exact_memory_and_graph_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import json
    import echelon.spec_retarget_finalization as finalization

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    drawer_ids = ["drawer-1"]
    for name, payload in {
        "mempalace-audit.json": b'{"audit":"pass"}\n',
        "mempalace-audit.md": b"# audit\n",
        "mempalace-mine.json": json.dumps(_mine_report(drawer_ids)).encode(),
        "spec-artifact-graph.json": b"spec graph",
    }.items():
        (spec_dir / name).write_bytes(payload)
    workspace_graph = finalization.workspace_graph_path(tmp_path)
    workspace_graph.parent.mkdir(parents=True, exist_ok=True)
    workspace_graph.write_bytes(b"workspace graph")
    report_digest = finalization._current_memory_report_set_digest(spec_dir)
    _write_memory_manifest(finalization, spec_dir, report_digest)
    drawer_digest = "sha256:" + hashlib.sha256(
        json.dumps(drawer_ids, separators=(",", ":")).encode()
    ).hexdigest()
    memory_values = {
        **_memory_receipt(), "status": "pass", "drawer_set_digest": drawer_digest,
        "mine_status": "complete", "audit_status": "pass", "adapter": "test",
        "wing": "test", "palace_path": "test", "report_set_digest": report_digest,
    }
    for field in (
        "deleted_ids", "remaining_owned_ids", "unrelated_missing_ids",
        "unrelated_changed_ids", "unexpected_added_ids",
    ):
        memory_values[field] = tuple(memory_values[field])
    memory = finalization.RetargetMemoryReceipt(**memory_values)
    spec_hash = "sha256:" + hashlib.sha256(b"spec graph").hexdigest()
    workspace_hash = "sha256:" + hashlib.sha256(b"workspace graph").hexdigest()
    graph = finalization.RetargetGraphReceipt(
        "001-demo", "pass", spec_hash, "pass", workspace_hash, ()
    )
    monkeypatch.setattr(
        finalization, "_configured_mempalace_wing", lambda *_args: "test"
    )
    monkeypatch.setattr(
        finalization, "audit_spec_memory",
        lambda *_args, **_kwargs: _memory_audit(drawer_ids),
    )
    monkeypatch.setattr(
        finalization, "audit_spec_graph",
        lambda *_args: SimpleNamespace(
            spec_id="001-demo", graph_hash=spec_hash, status="pass"
        ),
    )
    monkeypatch.setattr(
        finalization, "audit_workspace_graph",
        lambda *_args: SimpleNamespace(
            graph_hash=workspace_hash, status="pass", findings=(),
            members=(SimpleNamespace(spec_id="001-demo", included=True,
                                     graph_hash=spec_hash, audit_status="pass"),),
        ),
    )
    original = {path: path.read_bytes() for path in spec_dir.iterdir()}
    original[workspace_graph] = workspace_graph.read_bytes()

    finalization.verify_retarget_memory_postimage(tmp_path, spec_dir, memory)
    finalization.verify_retarget_graph_postimage(tmp_path, spec_dir, graph)

    assert {path: path.read_bytes() for path in original} == original


@pytest.mark.unit
@pytest.mark.parametrize("replay_path", ["persisted_progress", "expected_receipt"])
@pytest.mark.parametrize("drift_step", ["memory", "graph"])
def test_replay_paths_reject_live_drift_before_history_or_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replay_path: str,
    drift_step: str,
) -> None:
    import json
    import echelon.spec_retarget_finalization as finalization

    project_root = tmp_path / "project"
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    prepared = SimpleNamespace(
        _transaction_root=tmp_path / "completion",
        intent=SimpleNamespace(completion_id="e" * 32),
    )
    prepared._transaction_root.mkdir()
    memory = _memory_receipt()
    graph = _graph_receipt(terminal=True)
    state = {
        "spec_id": "001-demo", "published_spec_dir": "specs/001-demo",
        "retarget": {
            "status": "finalizing", "revision_id": "rt-1",
            "checkpoint_commit": "a" * 40, "replacement_targets": ["apps/web"],
            "replacement_run_id": "replacement", "baseline_run_id": "baseline",
            "graph_invalidation": _graph_receipt(terminal=False),
        },
    }
    if replay_path == "persisted_progress":
        (prepared._transaction_root / "retarget-progress.json").write_text(
            json.dumps({"completion_id": "e" * 32, "memory": memory, "graph": graph}),
            encoding="utf-8",
        )
        expected: object = None
    else:
        expected = {
            "revision_id": "rt-1", "completion_id": "e" * 32,
            "checkpoint_commit": "a" * 40, "replacement_targets": ["apps/web"],
            "memory": memory, "graph": graph, "replacement_commit": "d" * 40,
            "status": "complete",
        }
    verifier = (
        "verify_retarget_memory_postimage" if drift_step == "memory"
        else "verify_retarget_graph_postimage"
    )
    monkeypatch.setattr(
        finalization, verifier,
        lambda *_args: (_ for _ in ()).throw(
            finalization.RetargetFinalizationError("retarget finalization postimage drifted")
        ),
    )
    monkeypatch.setattr(finalization, "refresh_retarget_spec_memory", lambda *_args: pytest.fail("mutated memory"))
    monkeypatch.setattr(finalization, "finalize_retarget_graphs", lambda *_args: pytest.fail("mutated graph"))
    monkeypatch.setattr(finalization, "load_retarget_history", lambda *_args: pytest.fail("advanced history"))
    monkeypatch.setattr(finalization, "advance_retarget_revision", lambda *_args, **_kwargs: pytest.fail("advanced history"))

    with pytest.raises(finalization.RetargetFinalizationError, match="postimage drifted"):
        finalization.apply_or_verify_retarget_finalization(
            prepared, project_root=project_root, state=state, expected_receipt=expected
        )
    assert state["retarget"]["status"] == "finalizing"


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
