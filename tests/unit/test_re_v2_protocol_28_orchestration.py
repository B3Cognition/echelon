from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.events import ReV2EventError
from harness.re_v2.protocol_28.orchestration import (
    DeepenOrchestrationController,
    DeepenOrchestrationError,
    DeepenOrchestrationRequestV1,
    create_or_load_orchestration,
    find_exact_orchestration,
    find_open_orchestrations_for_child,
    load_orchestration,
)
from tests.re_v2_protocol_28_fixtures import digest, selection_scope_v1


NOW = "2026-08-31T12:00:00Z"


def _request(**changes: object) -> DeepenOrchestrationRequestV1:
    value = DeepenOrchestrationRequestV1(
        schema_version=1,
        input_run_id="re-l2-input",
        input_manifest_hash=digest("input-manifest"),
        input_terminal_event_hash=digest("input-terminal"),
        source_snapshot_id=digest("snapshot"),
        partition_manifest_id=digest("partition"),
        selection=selection_scope_v1(),
        exhaustive_policy_catalog_id=digest("policy"),
        executor_catalog_id=digest("executors"),
        l3_prerequisite_request_id=digest("l3-request"),
    )
    return replace(value, **changes)


@pytest.mark.unit
def test_request_is_closed_and_resource_independent() -> None:
    request = _request()
    assert DeepenOrchestrationRequestV1.from_json_dict(request.to_json_dict()) == request
    with pytest.raises(DeepenOrchestrationError, match="unknown fields"):
        DeepenOrchestrationRequestV1.from_json_dict(
            {**request.to_json_dict(), "token_limit": 9}
        )
    assert "token" not in str(request.to_json_dict())


@pytest.mark.unit
def test_create_reuses_exact_intent_and_rejects_retarget(tmp_path: Path) -> None:
    first = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)
    second = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)

    assert second.paths.root == first.paths.root
    assert second.paths.root.parent == tmp_path / "runs" / ".re-v2-orchestrations"
    assert find_exact_orchestration(tmp_path, _request().request_id) == first.paths.root

    changed = _request(source_snapshot_id=digest("changed-snapshot"))
    assert changed.request_id != _request().request_id
    assert find_exact_orchestration(tmp_path, changed.request_id) is None


@pytest.mark.unit
def test_event_protocol_is_content_free_and_projection_rebuilds(tmp_path: Path) -> None:
    intent = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)
    controller = DeepenOrchestrationController(intent, clock=lambda: NOW)

    with pytest.raises(ReV2EventError, match="unknown fields"):
        intent.events.append(
            "l3_child_bound",
            {
                "run_id": "re-l3",
                "manifest_hash": digest("l3-manifest"),
                "source_excerpt": "secret",
            },
            occurred_at=NOW,
        )

    controller.bind_l3_child("re-l3", digest("l3-manifest"))
    controller.satisfy_l3("re-l3", digest("l3-terminal"))
    intent.paths.projection.unlink()
    projection = controller.rebuild_projection()

    assert projection.state == "awaiting_l4"
    assert projection.l3_run_id == "re-l3"
    assert "secret" not in intent.paths.events.read_text(encoding="utf-8")


@pytest.mark.unit
def test_transition_binds_at_most_one_child_and_exact_hashes(tmp_path: Path) -> None:
    intent = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)
    controller = DeepenOrchestrationController(intent, clock=lambda: NOW)
    controller.bind_l3_child("re-l3", digest("l3-manifest"))

    controller.bind_l3_child("re-l3", digest("l3-manifest"))
    with pytest.raises(DeepenOrchestrationError, match="already binds"):
        controller.bind_l3_child("re-other", digest("other-manifest"))
    with pytest.raises(DeepenOrchestrationError, match="does not match"):
        controller.satisfy_l3("re-l3", digest("wrong-terminal"), manifest_hash=digest("wrong"))


@pytest.mark.unit
def test_resource_raise_preserves_request_identity(tmp_path: Path) -> None:
    intent = create_or_load_orchestration(
        tmp_path,
        _request(),
        clock=lambda: NOW,
        token_limit=100,
        active_ms_limit=200,
    )
    controller = DeepenOrchestrationController(intent, clock=lambda: NOW)
    controller.authorize("tokens", 300, authorized_by="cli")
    projection = controller.rebuild_projection()

    assert projection.request_id == _request().request_id
    assert projection.token_limit == 300
    assert projection.active_ms_limit == 200
    with pytest.raises(DeepenOrchestrationError, match="increase"):
        controller.authorize("tokens", 300, authorized_by="cli")


@pytest.mark.unit
def test_reverse_lookup_authenticates_unique_open_intent(tmp_path: Path) -> None:
    first = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)
    DeepenOrchestrationController(first, clock=lambda: NOW).bind_l3_child(
        "re-l3", digest("l3-manifest")
    )
    assert find_open_orchestrations_for_child(tmp_path, "re-l3") == (first.paths.root,)

    other = create_or_load_orchestration(
        tmp_path,
        _request(selection=replace(selection_scope_v1(), source_ids=("worker",))),
        clock=lambda: NOW,
    )
    DeepenOrchestrationController(other, clock=lambda: NOW).bind_l3_child(
        "re-l3", digest("l3-manifest")
    )
    with pytest.raises(DeepenOrchestrationError, match="multiple open"):
        find_open_orchestrations_for_child(tmp_path, "re-l3", require_unique=True)


@pytest.mark.unit
def test_crash_after_event_recovers_without_duplicate_transition(tmp_path: Path) -> None:
    intent = create_or_load_orchestration(tmp_path, _request(), clock=lambda: NOW)

    def crash(seam: str) -> None:
        if seam == "after_event_before_projection":
            raise RuntimeError("crash")

    crashing = DeepenOrchestrationController(intent, clock=lambda: NOW, fault=crash)
    with pytest.raises(RuntimeError, match="crash"):
        crashing.bind_l3_child("re-l3", digest("l3-manifest"))

    recovered = load_orchestration(intent.paths.root)
    stable = DeepenOrchestrationController(recovered, clock=lambda: NOW)
    before = len(recovered.events.replay())
    stable.bind_l3_child("re-l3", digest("l3-manifest"))

    assert len(recovered.events.replay()) == before
    assert stable.rebuild_projection().l3_run_id == "re-l3"
