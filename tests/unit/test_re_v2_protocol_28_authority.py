from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    L4ClosureParentBundleV1,
    Protocol28AuthorityError,
    ValidatedL3ParentV1,
    ValidatedL3ParentV2,
    ValidatedL3TargetV1,
    build_l3_target_projections,
    build_parent_authority_bundle_v3,
)
from tests.re_v2_protocol_28_fixtures import digest


def _selection(*domain_keys: str) -> SelectionScopeV1:
    return SelectionScopeV1(
        schema_version=1,
        all_sources=False,
        source_ids=("api",),
        domain_keys=tuple(sorted(domain_keys)),
    )


def _target(
    target_id: str,
    *,
    target_kind: str = "domain",
    frozen_epoch_id: str,
    unresolved: tuple[str, ...] = (),
) -> ValidatedL3TargetV1:
    return ValidatedL3TargetV1(
        schema_version=1,
        target_kind=target_kind,
        source_id="api",
        target_id=target_id,
        target_content_id=digest(f"{target_id}:content"),
        candidate_authority_hash=digest(f"{target_id}:candidate"),
        finding_ids=unresolved,
        unresolved_finding_ids=unresolved,
        resolution_overlay_ids=(),
        closure_receipt_ids=(),
        closure_state="deeper-evidence-blocked" if unresolved else "complete",
        relevant_l2_root_ids=(digest(f"{target_id}:l2-root"),),
        audit_policy_id=digest("audit-policy"),
        executor_policy_id=digest("executor-policy"),
        frozen_epoch_id=frozen_epoch_id,
        epoch_target_entry_hash=digest(f"{target_id}:epoch-entry"),
    )


def _parent(
    domain_keys: tuple[str, ...],
    *,
    epoch_seed: str,
    blocker_classes: tuple[str, ...] = (),
    unresolved_domain: str | None = None,
) -> ValidatedL3ParentV1:
    epoch_id = digest(epoch_seed)
    targets = [
        _target(
            domain_key,
            frozen_epoch_id=epoch_id,
            unresolved=(digest(f"{domain_key}:finding"),)
            if domain_key == unresolved_domain
            else (),
        )
        for domain_key in domain_keys
    ]
    targets.append(
        _target("api", target_kind="source", frozen_epoch_id=epoch_id)
    )
    selection = _selection(*domain_keys)
    return ValidatedL3ParentV1(
        schema_version=1,
        run_id=f"re-l3-{epoch_seed}",
        manifest_hash=digest(f"{epoch_seed}:manifest"),
        terminal_event_hash=digest(f"{epoch_seed}:terminal"),
        source_snapshot_id=digest("source-snapshot"),
        partition_manifest_id=digest("partition-manifest"),
        selection_id=selection.identity,
        frozen_epoch_id=epoch_id,
        terminal_state="blocked" if blocker_classes else "complete",
        blocker_classes=blocker_classes,
        workspace_partition_catalog_id=digest("partition-catalog"),
        inherited_artifact_policy_catalog_id=digest("artifact-policy-catalog"),
        lower_l0_l2_authority_ids=(digest("lower-authority"),),
        targets=tuple(sorted(targets, key=lambda item: item.sort_key)),
    )


@pytest.mark.unit
def test_target_projection_survives_unrelated_selection_expansion() -> None:
    """Adding an unrelated audit target must not invalidate accepted local work."""
    api_domain = digest("api-domain")
    search_domain = digest("search-domain")
    first_parent = _parent((api_domain,), epoch_seed="epoch-one")
    expanded_parent = _parent(
        (api_domain, search_domain),
        epoch_seed="epoch-two",
    )

    first = build_l3_target_projections(first_parent, _selection(api_domain))
    expanded = build_l3_target_projections(
        expanded_parent,
        _selection(api_domain),
    )

    assert first.for_domain(api_domain).identity == expanded.for_domain(api_domain).identity
    assert first.membership_for(first.for_domain(api_domain).identity).identity != (
        expanded.membership_for(expanded.for_domain(api_domain).identity).identity
    )


@pytest.mark.unit
def test_projection_rejects_mixed_epoch_authority() -> None:
    """One projection catalog may not splice targets from two semantic epochs."""
    api_domain = digest("api-domain")
    search_domain = digest("search-domain")
    parent = _parent((api_domain, search_domain), epoch_seed="epoch-one")
    mixed = replace(
        parent.targets[1],
        frozen_epoch_id=digest("other-epoch"),
    )
    parent = replace(
        parent,
        targets=tuple(
            sorted(
                (parent.targets[0], mixed, parent.targets[2]),
                key=lambda item: item.sort_key,
            )
        ),
    )

    with pytest.raises(Protocol28AuthorityError, match="mixed.*epoch"):
        build_l3_target_projections(
            parent,
            _selection(api_domain, search_domain),
        )


@pytest.mark.unit
def test_parent_bundle_accepts_only_deeper_evidence_blockers() -> None:
    """L4 must not route around human-decision or lower-artifact blockers."""
    domain = digest("api-domain")
    parent = _parent(
        (domain,),
        epoch_seed="epoch-one",
        blocker_classes=("requires_human_decision",),
        unresolved_domain=domain,
    )
    projections = build_l3_target_projections(parent, _selection(domain))

    with pytest.raises(Protocol28AuthorityError, match="requires_human_decision"):
        build_parent_authority_bundle_v3(parent, projections)


@pytest.mark.unit
def test_exact_partial_parent_accepts_every_authenticated_blocker_class() -> None:
    domain = digest("api-domain")
    finding = digest(f"{domain}:finding")
    raw = _parent(
        (domain,),
        epoch_seed="accepted-debt",
        blocker_classes=("requires_human_decision",),
        unresolved_domain=domain,
    )
    partial = ValidatedL3ParentV2(
        parent=raw,
        input_quality="partial",
        residual_debt_acceptance_hash=digest("residual-debt-acceptance"),
        unresolved_finding_ids=(finding,),
        deferred_observation_ids=(),
    )

    projections = build_l3_target_projections(partial, _selection(domain))
    bundle = build_parent_authority_bundle_v3(partial, projections)

    # Accepted debt remains in L3 authority, not in L4's mandatory closure queue.
    assert bundle.unresolved_deeper_finding_ids == ()
    assert projections.projections[0].unresolved_finding_ids == (finding,)
    assert partial.parent.to_json_dict() == raw.to_json_dict()


@pytest.mark.unit
def test_partial_parent_rejects_missing_or_mismatched_debt_authority() -> None:
    domain = digest("api-domain")
    finding = digest(f"{domain}:finding")
    raw = _parent(
        (domain,),
        epoch_seed="invalid-debt",
        blocker_classes=("requires_human_decision",),
        unresolved_domain=domain,
    )

    with pytest.raises(Protocol28AuthorityError, match="debt acceptance"):
        ValidatedL3ParentV2(raw, "partial", None, (finding,), ())
    with pytest.raises(Protocol28AuthorityError, match="unresolved"):
        ValidatedL3ParentV2(
            raw,
            "partial",
            digest("residual-debt-acceptance"),
            (digest("different-finding"),),
            (),
        )
    complete = _parent((domain,), epoch_seed="complete-not-partial")
    with pytest.raises(Protocol28AuthorityError, match="unresolved blocked"):
        ValidatedL3ParentV2(
            complete,
            "partial",
            digest("residual-debt-acceptance"),
            (),
            (),
        )


@pytest.mark.unit
def test_parent_bundle_round_trip_keeps_selected_deeper_findings() -> None:
    """The L4 child must carry exact inherited deeper-evidence debt."""
    domain = digest("api-domain")
    finding = digest(f"{domain}:finding")
    parent = _parent(
        (domain,),
        epoch_seed="epoch-one",
        blocker_classes=("requires_deeper_evidence",),
        unresolved_domain=domain,
    )
    projections = build_l3_target_projections(parent, _selection(domain))

    bundle = build_parent_authority_bundle_v3(parent, projections)
    rebuilt = type(bundle).from_json_dict(bundle.to_json_dict())

    assert rebuilt == bundle
    assert rebuilt.selection_id == _selection(domain).identity
    assert rebuilt.unresolved_deeper_finding_ids == (finding,)
    assert rebuilt.selected_projection_ids == tuple(
        item.identity for item in projections.projections
    )


def _closure_bundle() -> L4ClosureParentBundleV1:
    return L4ClosureParentBundleV1(
        schema_version=1,
        selection_id=digest("selection"),
        source_snapshot_id=digest("source-snapshot"),
        partition_manifest_id=digest("partition-manifest"),
        l3_run_id="re-l3-parent",
        l3_manifest_hash=digest("l3-manifest"),
        l3_terminal_event_hash=digest("l3-terminal"),
        frozen_epoch_id=digest("frozen-epoch"),
        l4_run_id="re-l4-evidence",
        l4_manifest_hash=digest("l4-manifest"),
        l4_terminal_event_hash=digest("l4-terminal"),
        l4_run_root_id=digest("l4-run-root"),
        l4_run_root_state="complete",
        assigned_target_projection_ids=(digest("target-projection"),),
        accepted_slice_ids=(digest("accepted-slice"),),
        verification_receipt_ids=(digest("verification-receipt"),),
        target_root_ids=(digest("target-root"),),
        immutable_object_ids=(digest("immutable-object"),),
    )


@pytest.mark.unit
def test_closure_bundle_rejects_incomplete_l4_root() -> None:
    """A closure successor cannot authenticate a merely partial evidence run."""
    with pytest.raises(Protocol28AuthorityError, match="complete"):
        replace(_closure_bundle(), l4_run_root_state="blocked")


@pytest.mark.unit
def test_closure_bundle_closed_schema_rejects_budget_or_checkpoint_fields() -> None:
    """Zero-provider closure authority must stay free of dormant execution state."""
    raw = _closure_bundle().to_json_dict()
    raw["budget_policy"] = {"token_limit": 1}

    with pytest.raises(Protocol28AuthorityError, match="unknown fields"):
        L4ClosureParentBundleV1.from_json_dict(raw)
