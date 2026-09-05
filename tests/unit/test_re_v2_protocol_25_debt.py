from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventRecord
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_25.artifacts import AuditClosureRootV1, L3SourceRootV1
from harness.re_v2.protocol_25.controller import (
    Protocol25ControllerStateV1,
    SemanticTargetControllerStateV1,
)
from harness.re_v2.protocol_25.debt import (
    Protocol25DebtError,
    finalize_protocol_25_debt,
    load_residual_debt_acceptance,
)
from harness.re_v2.protocol_25.guidance import (
    GuidanceDirectiveV1,
    banzai_guidance_policy,
)
from harness.re_v2.protocol_25.status import _apply_debt_status
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_25_runtime import _certified_audit


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_dir = tmp_path / "re-debt"
    (run_dir / "v2" / "inputs").mkdir(parents=True)
    objects = ObjectStore(run_dir / "v2" / "objects")
    certified = _certified_audit()
    candidate = certified.artifact
    finding = certified.normalized_findings[0]
    target_id = candidate.audit_target_id
    epoch_id = digest("debt-epoch")
    closure = AuditClosureRootV1(
        schema_version=1,
        audit_epoch_id=epoch_id,
        frozen_finding_ids=(finding.finding_key_id,),
        latest_closure_receipts=(),
        unresolved_finding_ids=(finding.finding_key_id,),
        target_rounds=((target_id, 3),),
        plateau_counts=((target_id, 2),),
        deferred_observations=(),
    )
    source_root = L3SourceRootV1(
        schema_version=1,
        source_id="api",
        selected_domain_keys=(digest("domain"),),
        full_source_coverage=True,
        audit_target_ids=(target_id,),
        closure_root_hashes=(closure.identity,),
        adopted_l2_root_hash=digest("l2-root"),
        unresolved_finding_ids=(finding.finding_key_id,),
        deferred_observation_ids=(),
        state="blocked",
    )
    policy = banzai_guidance_policy(digest("automation-root"))
    guidance = GuidanceDirectiveV1(
        schema_version=1,
        kind=policy.kind,
        answer=policy.answer,
        parent_manifest_hash=digest("parent-manifest"),
        parent_terminal_event_hash=digest("parent-terminal"),
        accepted_audit_candidate_hashes=(candidate.identity,),
        unresolved_audit_target_ids=(),
        audit_epoch_id=epoch_id,
        closure_root_hash=digest("parent-closure-root"),
        unresolved_finding_ids=(finding.finding_key_id,),
        accept_residual_debt=policy.accept_residual_debt,
        automatic_successor_limit=policy.automatic_successor_limit,
        automation_root_manifest_hash=policy.automation_root_manifest_hash,
        successor_index=policy.successor_index,
    )
    guidance_payload = canonical_json_bytes(guidance.to_json_dict())
    guidance_hash = content_digest(guidance_payload)
    objects.put_blob(canonical_json_bytes(candidate.to_json_dict()))
    terminal = EventRecord(
        schema_version=1,
        seq=9,
        previous_event_hash=digest("previous-event"),
        occurred_at="2026-09-05T00:00:00Z",
        type="run_failed",
        payload={"reason": "semantic closure reached plateau"},
        event_hash=digest("terminal-event"),
    )
    shared = SimpleNamespace(
        terminal=True,
        last_type="run_failed",
        active=None,
        lease_dispatch_id=None,
        indeterminate_work_items=set(),
    )
    replay = SimpleNamespace(
        shared=SimpleNamespace(shared=shared),
        plateau_targets={target_id},
        audit_closure_roots={closure.identity},
        audit_candidates={target_id: candidate.identity},
        audit_context_preflight_failure_id=None,
        semantic_context_projection_failure=None,
    )
    target = SemanticTargetControllerStateV1(
        audit_target_id=target_id,
        source_id="api",
        audit_state="accepted",
        frozen_finding_ids=(finding.finding_key_id,),
        unresolved_finding_ids=(finding.finding_key_id,),
        semantic_round=3,
        no_reduction_rounds=2,
        stage="plateau_recorded",
    )
    state = Protocol25ControllerStateV1(
        prerequisites_complete=True,
        prerequisites_failed=False,
        paused_resource=False,
        audit_epoch_id=epoch_id,
        targets=(target,),
        rooted_source_ids=("api",),
        terminal_state="blocked_plateau",
    )
    manifest = SimpleNamespace(
        run_id="re-debt",
        run_manifest_id=digest("run-manifest"),
        source_snapshot_id=digest("source-snapshot"),
        source_snapshot_kind="workspace-git-composite",
        selection=SimpleNamespace(identity=digest("selection")),
        human_guidance=SimpleNamespace(object_hash=guidance_hash),
    )
    authority = SimpleNamespace(
        manifest=manifest,
        inputs=SimpleNamespace(human_guidance=guidance_payload),
        graph=SimpleNamespace(
            selected_source_ids=("api",),
            audit_target_plans=(SimpleNamespace(audit_target_id=target_id),),
        ),
        events=(terminal,),
        ledger=SimpleNamespace(
            audit_candidates={candidate.identity: candidate},
            audit_epochs={epoch_id: object()},
            audit_closure_roots={closure.identity: closure},
            l3_source_roots={"api": source_root},
        ),
        objects=objects,
        state=state,
        replay=replay,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.debt._reconstruct_authority",
        lambda _run_dir: authority,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.debt._validate_clean_workspace",
        lambda **_kwargs: None,
    )
    return run_dir, authority, guidance


@pytest.mark.unit
def test_banzai_plateau_finalization_is_exact_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir, authority, guidance = _fixture(tmp_path, monkeypatch)

    first = finalize_protocol_25_debt(
        project_root=tmp_path,
        run_dir=run_dir,
        require_banzai=True,
    )
    second = finalize_protocol_25_debt(
        project_root=tmp_path,
        run_dir=run_dir,
        require_banzai=True,
    )

    assert first == second == load_residual_debt_acceptance(run_dir)
    assert first.run_manifest_hash == authority.manifest.run_manifest_id
    assert first.terminal_event_hash == authority.events[-1].event_hash
    assert first.guidance_directive_hash == guidance.identity
    assert first.unresolved_by_source_and_class[0].source_id == "api"
    assert first.unresolved_by_source_and_class[0].finding_ids == (
        guidance.unresolved_finding_ids[0],
    )
    assert first.acceptance_policy_id == "re-v2-banzai-residual-debt-v1"

    document = _apply_debt_status(
        {
            "status": "blocked_plateau",
            "guidance": {
                "recommended_eligible": True,
                "banzai_eligible": True,
                "actions": [{"action_id": "banzai", "enabled": True}],
            },
        },
        first,
    )
    assert document["status"] == "complete_with_debt"
    assert document["semantic_status"] == "blocked_plateau"
    assert document["quality"] == "partial"
    assert document["accepted_residual_findings"] == 1
    assert document["debt_manifest_hash"] == first.identity
    assert document["next_action"].startswith("none")
    assert document["guidance"]["actions"][0]["enabled"] is False


@pytest.mark.unit
def test_banzai_accepts_materialized_targets_when_plan_ids_differ(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir, authority, _guidance = _fixture(tmp_path, monkeypatch)
    authority.graph.audit_target_plans = (
        SimpleNamespace(audit_target_id=digest("audit-target-plan")),
    )

    acceptance = finalize_protocol_25_debt(
        project_root=tmp_path,
        run_dir=run_dir,
        require_banzai=True,
    )

    assert acceptance.unresolved_finding_ids == (
        authority.state.targets[0].unresolved_finding_ids
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation,match",
    (
        ("missing_audit", "selected audit"),
        ("missing_epoch", "audit epoch"),
        ("missing_closure", "closure root"),
        ("missing_source_root", "source root"),
        ("active", "active dispatch"),
        ("indeterminate", "indeterminate"),
        ("projection_failure", "projection failure"),
        ("non_banzai", "Banzai"),
        ("altered_unresolved", "unresolved"),
    ),
)
def test_debt_finalization_rejects_incomplete_or_changed_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    match: str,
) -> None:
    run_dir, authority, _guidance = _fixture(tmp_path, monkeypatch)
    if mutation == "missing_audit":
        authority.graph.audit_target_plans = (
            *authority.graph.audit_target_plans,
            SimpleNamespace(audit_target_id=digest("missing-target")),
        )
    elif mutation == "missing_epoch":
        authority.ledger.audit_epochs = {}
    elif mutation == "missing_closure":
        authority.ledger.audit_closure_roots = {}
    elif mutation == "missing_source_root":
        authority.ledger.l3_source_roots = {}
    elif mutation == "active":
        authority.replay.shared.shared.active = object()
    elif mutation == "indeterminate":
        authority.replay.shared.shared.indeterminate_work_items = {digest("work")}
    elif mutation == "projection_failure":
        authority.replay.semantic_context_projection_failure = {"reason": "too large"}
    elif mutation == "non_banzai":
        raw = guidance = GuidanceDirectiveV1.from_json_dict(
            __import__("json").loads(authority.inputs.human_guidance)
        ).to_json_dict()
        raw.update(
            kind="custom",
            accept_residual_debt=False,
            automatic_successor_limit=0,
            automation_root_manifest_hash=None,
            successor_index=0,
        )
        raw["answer"] = "Keep working."
        authority.inputs.human_guidance = canonical_json_bytes(raw)
        authority.manifest.human_guidance = SimpleNamespace(
            object_hash=content_digest(authority.inputs.human_guidance)
        )
    elif mutation == "altered_unresolved":
        authority.state = replace(
            authority.state,
            targets=(replace(authority.state.targets[0], unresolved_finding_ids=()),),
        )

    with pytest.raises(Protocol25DebtError, match=match):
        finalize_protocol_25_debt(
            project_root=tmp_path,
            run_dir=run_dir,
            require_banzai=True,
        )


@pytest.mark.unit
def test_debt_finalization_rejects_dirty_sources_and_altered_persisted_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir, _authority, _guidance = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.debt._validate_clean_workspace",
        lambda **_kwargs: (_ for _ in ()).throw(Protocol25DebtError("sources must be clean")),
    )
    with pytest.raises(Protocol25DebtError, match="sources must be clean"):
        finalize_protocol_25_debt(project_root=tmp_path, run_dir=run_dir, require_banzai=True)

    monkeypatch.setattr(
        "harness.re_v2.protocol_25.debt._validate_clean_workspace",
        lambda **_kwargs: None,
    )
    finalize_protocol_25_debt(project_root=tmp_path, run_dir=run_dir, require_banzai=True)
    pointer = run_dir / "v2" / "inputs" / "residual-debt-acceptance.json"
    pointer.write_bytes(b'{"object_hash":"sha256:' + b"0" * 64 + b'","schema_version":1}\n')

    with pytest.raises(Protocol25DebtError, match="persisted residual-debt acceptance"):
        finalize_protocol_25_debt(project_root=tmp_path, run_dir=run_dir, require_banzai=True)
