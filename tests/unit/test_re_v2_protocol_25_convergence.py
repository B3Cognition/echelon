from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_25.convergence import (
    BanzaiConvergenceError,
    run_banzai_resume,
)
from harness.re_v2.protocol_25.guidance import (
    GuidanceDirectiveV1,
    banzai_guidance_policy,
    custom_guidance_policy,
)
from tests.re_v2_protocol_22_fixtures import digest


def _document(status: str, *, unresolved: int = 1, calls: int = 0) -> dict[str, object]:
    return {
        "status": status,
        "semantic": {"unresolved_findings": unresolved},
        "guidance": {
            "banzai_eligible": status == "blocked_plateau",
        },
        "telemetry": {
            "calls_by_operation": {"semantic-resolution": calls},
        },
        **(
            {"debt_manifest_hash": digest("debt-manifest")}
            if status == "complete_with_debt"
            else {}
        ),
    }


def _authority(*, manifest_hash: str, guidance: GuidanceDirectiveV1 | None = None):
    payload = None if guidance is None else canonical_json_bytes(guidance.to_json_dict())
    return SimpleNamespace(
        manifest=SimpleNamespace(
            run_manifest_id=manifest_hash,
            human_guidance=(
                None
                if payload is None
                else SimpleNamespace(object_hash=content_digest(payload))
            ),
        ),
        inputs=SimpleNamespace(human_guidance=payload),
    )


def _directive(root: str) -> GuidanceDirectiveV1:
    policy = banzai_guidance_policy(root)
    return GuidanceDirectiveV1(
        schema_version=1,
        kind=policy.kind,
        answer=policy.answer,
        parent_manifest_hash=root,
        parent_terminal_event_hash=digest("parent-terminal"),
        accepted_audit_candidate_hashes=(digest("candidate"),),
        unresolved_audit_target_ids=(),
        audit_epoch_id=digest("epoch"),
        closure_root_hash=digest("closure"),
        unresolved_finding_ids=(digest("finding"),),
        accept_residual_debt=True,
        automatic_successor_limit=1,
        automation_root_manifest_hash=root,
        successor_index=1,
    )


def _custom_directive(root: str) -> GuidanceDirectiveV1:
    policy = custom_guidance_policy("Use the accepted evidence and preserve uncertainty.")
    return GuidanceDirectiveV1(
        schema_version=1,
        kind=policy.kind,
        answer=policy.answer,
        parent_manifest_hash=digest("earlier-parent"),
        parent_terminal_event_hash=digest("earlier-terminal"),
        accepted_audit_candidate_hashes=(digest("earlier-candidate"),),
        unresolved_audit_target_ids=(),
        audit_epoch_id=digest("epoch"),
        closure_root_hash=digest("earlier-closure"),
        unresolved_finding_ids=(digest("finding"),),
        accept_residual_debt=False,
        automatic_successor_limit=0,
        automation_root_manifest_hash=None,
        successor_index=0,
    )


@pytest.mark.unit
def test_banzai_creates_and_executes_exactly_one_successor_then_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "parent"
    child = tmp_path / "child"
    parent.mkdir()
    child.mkdir()
    root = digest("parent-manifest")
    authorities = {
        # Recommended/custom guidance may itself plateau and remains eligible
        # for one explicit Banzai successor.
        parent: _authority(manifest_hash=root, guidance=_custom_directive(root)),
        child: _authority(manifest_hash=digest("child-manifest"), guidance=_directive(root)),
    }
    documents = {
        parent: _document("blocked_plateau", calls=9),
        child: _document("in_progress", calls=0),
    }
    created: list[Path] = []
    executed: list[Path] = []
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_authority",
        lambda path: authorities[path],
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_status",
        lambda path: documents[path],
    )

    def create(path: Path):
        created.append(path)
        return child, True

    def execute(path: Path):
        executed.append(path)
        documents[path] = _document("complete", unresolved=0, calls=2)

    result = run_banzai_resume(
        project_root=tmp_path,
        blocked_run_dir=parent,
        create_or_reuse_successor=create,
        execute_successor=execute,
    )

    assert result.public_status == "complete"
    assert result.semantic_status == "complete"
    assert result.successor_created is True
    assert result.provider_call_count == 2
    assert result.debt_manifest_hash is None
    assert result.to_json_dict()["automatic_successor_count"] == 1
    assert result.to_json_dict()["automatic_successor_limit"] == 1
    assert created == [parent]
    assert executed == [child]


@pytest.mark.unit
def test_banzai_finalizes_exact_child_plateau_without_second_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    root = digest("automation-root")
    authority = _authority(
        manifest_hash=digest("child-manifest"),
        guidance=_directive(root),
    )
    documents = [
        _document("blocked_plateau", calls=4),
        _document("complete_with_debt", calls=4),
    ]
    finalized: list[Path] = []
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_authority",
        lambda _path: authority,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_status",
        lambda _path: documents.pop(0),
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._finalize_debt",
        lambda project_root, run_dir: (
            finalized.append(run_dir)
            or SimpleNamespace(identity=digest("debt-manifest"))
        ),
    )

    result = run_banzai_resume(
        project_root=tmp_path,
        blocked_run_dir=child,
        create_or_reuse_successor=lambda _path: pytest.fail("must not create index 2"),
        execute_successor=lambda _path: pytest.fail("terminal child must not execute"),
    )

    assert result.public_status == "complete_with_debt"
    assert result.semantic_status == "blocked_plateau"
    assert result.successor_created is False
    assert result.provider_call_count == 0
    assert result.debt_manifest_hash == digest("debt-manifest")
    assert finalized == [child]


@pytest.mark.unit
def test_repeated_banzai_on_finalized_child_is_zero_call_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    root = digest("automation-root")
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_authority",
        lambda _path: _authority(
            manifest_hash=digest("child-manifest"),
            guidance=_directive(root),
        ),
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_status",
        lambda _path: _document("complete_with_debt", calls=4),
    )

    result = run_banzai_resume(
        project_root=tmp_path,
        blocked_run_dir=child,
        create_or_reuse_successor=lambda _path: pytest.fail("must not create index 2"),
        execute_successor=lambda _path: pytest.fail("must not call provider"),
    )

    assert result.public_status == "complete_with_debt"
    assert result.provider_call_count == 0
    assert result.successor_created is False


@pytest.mark.unit
def test_banzai_rejects_successor_index_two_and_nonsemantic_blocker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    root = digest("automation-root")
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_status",
        lambda _path: _document("blocked_plateau"),
    )
    invalid = _directive(root).to_json_dict()
    invalid["successor_index"] = 2
    invalid_payload = canonical_json_bytes(invalid)
    invalid_authority = SimpleNamespace(
        manifest=SimpleNamespace(
            run_manifest_id=digest("child"),
            human_guidance=SimpleNamespace(
                object_hash=content_digest(invalid_payload)
            ),
        ),
        inputs=SimpleNamespace(human_guidance=invalid_payload),
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_authority",
        lambda _path: invalid_authority,
    )
    with pytest.raises(BanzaiConvergenceError, match="automatic successor"):
        run_banzai_resume(
            project_root=tmp_path,
            blocked_run_dir=run_dir,
            create_or_reuse_successor=lambda _path: pytest.fail("must not create"),
            execute_successor=lambda _path: pytest.fail("must not execute"),
        )

    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_authority",
        lambda _path: _authority(manifest_hash=root),
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.convergence._load_status",
        lambda _path: _document("blocked_incomplete"),
    )
    with pytest.raises(BanzaiConvergenceError, match="semantic plateau"):
        run_banzai_resume(
            project_root=tmp_path,
            blocked_run_dir=run_dir,
            create_or_reuse_successor=lambda _path: pytest.fail("must not create"),
            execute_successor=lambda _path: pytest.fail("must not execute"),
        )
