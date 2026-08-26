from __future__ import annotations

from dataclasses import replace
import importlib

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from tests.re_v2_protocol_25_fixtures import (
    lower_parent_authority_bundle_v1,
    parent_semantic_authority_v1,
    protocol_25_parent_candidate_v1,
)
from tests.re_v2_protocol_22_fixtures import digest


def _adoption():  # type: ignore[no-untyped-def]
    try:
        return importlib.import_module("harness.re_v2.protocol_25.adoption")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 successor adoption is not registered")


def _lower_bundle():  # type: ignore[no-untyped-def]
    return lower_parent_authority_bundle_v1()


def _semantic(
    *,
    epoch: bool = False,
    unresolved_targets: bool = False,
    unresolved_findings: bool = False,
    deferred: bool = False,
):  # type: ignore[no-untyped-def]
    return parent_semantic_authority_v1(
        epoch=epoch,
        unresolved_targets=unresolved_targets,
        unresolved_findings=unresolved_findings,
        deferred=deferred,
    )


def _parent(
    parent_state: str,
    *,
    layer: str = "L3",
    semantic=None,
    authentication_state: str = "authenticated",
    workspace_state: str = "clean_exact_commits",
    lineage_state: str = "acyclic",
    terminal: bool = True,
):  # type: ignore[no-untyped-def]
    return protocol_25_parent_candidate_v1(
        parent_state,
        layer=layer,
        semantic_authority=semantic,
        authentication_state=authentication_state,
        workspace_state=workspace_state,
        lineage_state=lineage_state,
        terminal=terminal,
    )


@pytest.mark.parametrize(
    ("mode", "parent"),
    (
        ("new-audit-epoch", lambda: _parent("complete", layer="L2")),
        (
            "audit-successor",
            lambda: _parent(
                "blocked_incomplete",
                semantic=_semantic(unresolved_targets=True),
            ),
        ),
        (
            "closure-successor",
            lambda: _parent(
                "blocked_plateau",
                semantic=_semantic(epoch=True, unresolved_findings=True),
            ),
        ),
        (
            "new-audit-epoch",
            lambda: _parent("complete", semantic=_semantic(epoch=True)),
        ),
        (
            "new-audit-epoch",
            lambda: _parent(
                "next_epoch_required",
                semantic=_semantic(epoch=True, deferred=True),
            ),
        ),
    ),
)
def test_mode_accepts_only_authenticated_terminal_parent(mode: str, parent) -> None:  # type: ignore[no-untyped-def]
    candidate = parent()

    validated = _adoption().validate_protocol_25_parent(candidate, mode=mode)

    assert validated.candidate is candidate
    assert validated.mode == mode


@pytest.mark.parametrize(
    ("mode", "parent"),
    (
        ("audit-successor", lambda: _parent("complete")),
        (
            "closure-successor",
            lambda: _parent(
                "blocked_incomplete",
                semantic=_semantic(unresolved_targets=True),
            ),
        ),
        (
            "new-audit-epoch",
            lambda: _parent(
                "blocked_plateau",
                semantic=_semantic(epoch=True, unresolved_findings=True),
            ),
        ),
    ),
)
def test_mode_rejects_wrong_parent_state(mode: str, parent) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(_adoption().Protocol25AdoptionError, match="parent state"):
        _adoption().validate_protocol_25_parent(parent(), mode=mode)


@pytest.mark.parametrize("parent_state", ("running_audit", "paused_resource"))
def test_nonterminal_parent_is_never_adoptable(parent_state: str) -> None:
    with pytest.raises(_adoption().Protocol25AdoptionError, match="terminal"):
        _adoption().validate_protocol_25_parent(
            _parent(parent_state, terminal=False),
            mode="new-audit-epoch",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("authentication_state", "corrupt", "authenticated"),
        ("lineage_state", "cyclic", "cycle"),
        ("workspace_state", "dirty", "Commit, stash, or revert"),
        ("workspace_state", "commit_drift", "commits do not match"),
    ),
)
def test_parent_integrity_and_clean_source_checks_fail_closed(
    field: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(_adoption().Protocol25AdoptionError, match=message):
        _adoption().validate_protocol_25_parent(
            _parent("complete", layer="L2", **{field: value}),
            mode="new-audit-epoch",
        )


def test_parent_snapshot_and_selection_must_match_request() -> None:
    parent = _parent("complete", layer="L2")

    with pytest.raises(_adoption().Protocol25AdoptionError, match="snapshot"):
        _adoption().validate_protocol_25_parent(
            parent,
            mode="new-audit-epoch",
            expected_source_snapshot_id=digest("different-snapshot"),
        )
    with pytest.raises(_adoption().Protocol25AdoptionError, match="selection"):
        _adoption().validate_protocol_25_parent(
            parent,
            mode="new-audit-epoch",
            expected_selection_id=digest("different-selection"),
        )


def test_audit_successor_retains_candidates_and_only_missing_targets() -> None:
    parent = _parent(
        "blocked_incomplete",
        semantic=_semantic(unresolved_targets=True),
    )

    validated = _adoption().validate_protocol_25_parent(
        parent,
        mode="audit-successor",
    )

    assert validated.adopted_audit_candidate_hashes == (
        digest("accepted-candidate"),
    )
    assert validated.remaining_audit_target_ids == (digest("missing-target"),)
    assert validated.unresolved_finding_ids == ()


def test_closure_successor_retains_epoch_progress_and_only_open_findings() -> None:
    semantic = _semantic(epoch=True, unresolved_findings=True)
    parent = _parent("blocked_plateau", semantic=semantic)

    validated = _adoption().validate_protocol_25_parent(
        parent,
        mode="closure-successor",
    )

    assert validated.audit_epoch_id == digest("audit-epoch")
    assert validated.closure_root_hash == digest("closure-root")
    assert validated.unresolved_finding_ids == (digest("open-finding"),)
    assert validated.adopted_semantic_object_ids == semantic.object_ids


def test_next_epoch_rejects_open_frozen_finding() -> None:
    with pytest.raises(_adoption().Protocol25AdoptionError, match="closed"):
        _adoption().validate_protocol_25_parent(
            _parent(
                "next_epoch_required",
                semantic=_semantic(
                    epoch=True,
                    unresolved_findings=True,
                    deferred=True,
                ),
            ),
            mode="new-audit-epoch",
        )


def test_parent_bundle_v2_embeds_v1_bytes_unchanged_and_round_trips() -> None:
    lower = _lower_bundle()
    before = canonical_json_bytes(lower.to_json_dict())
    validated = _adoption().validate_protocol_25_parent(
        _parent("blocked_plateau", semantic=_semantic(epoch=True, unresolved_findings=True)),
        mode="closure-successor",
    )

    bundle = _adoption().build_parent_authority_bundle_v2(validated)

    assert bundle.lower_authority_bundle is validated.candidate.lower_authority_bundle
    assert canonical_json_bytes(bundle.lower_authority_bundle.to_json_dict()) == before
    assert type(bundle).from_json_dict(bundle.to_json_dict()) == bundle


def test_parent_closure_import_requires_exact_self_contained_objects() -> None:
    payloads = {
        name: f"semantic-object:{name}".encode()
        for name in (
            "candidate",
            "epoch",
            "overlay",
            "target-assessment",
            "source-assessment",
            "closure-receipt",
            "closure-root",
            "l3-source-root",
        )
    }
    object_ids = {name: content_digest(payload) for name, payload in payloads.items()}
    semantic = _adoption().ParentSemanticAuthorityV1(
        schema_version=1,
        accepted_audit_target_ids=(digest("accepted-target"),),
        accepted_audit_candidate_hashes=(object_ids["candidate"],),
        unresolved_audit_target_ids=(),
        audit_epoch_id=object_ids["epoch"],
        resolution_overlay_hashes=(object_ids["overlay"],),
        target_assessment_hashes=(object_ids["target-assessment"],),
        source_assessment_hashes=(object_ids["source-assessment"],),
        closure_receipt_ids=(object_ids["closure-receipt"],),
        closure_root_hash=object_ids["closure-root"],
        unresolved_finding_ids=(digest("open-finding"),),
        deferred_observation_ids=(),
        l3_source_root_hashes=(object_ids["l3-source-root"],),
    )
    validated = _adoption().validate_protocol_25_parent(
        _parent("blocked_plateau", semantic=semantic),
        mode="closure-successor",
    )
    objects = {object_ids[name]: payload for name, payload in payloads.items()}

    imported = _adoption().import_protocol_25_parent_closure(validated, objects)

    assert imported == tuple(sorted(objects))
    missing = dict(objects)
    missing.pop(next(iter(missing)))
    with pytest.raises(_adoption().Protocol25AdoptionError, match="incomplete"):
        _adoption().import_protocol_25_parent_closure(validated, missing)
    tampered = dict(objects)
    first = next(iter(tampered))
    tampered[first] = b"tampered"
    with pytest.raises(_adoption().Protocol25AdoptionError, match="hash mismatch"):
        _adoption().import_protocol_25_parent_closure(validated, tampered)


def test_semantic_authority_rejects_partial_or_incoherent_closure() -> None:
    module = _adoption()

    with pytest.raises(module.Protocol25AdoptionError, match="candidate"):
        replace(
            _semantic(unresolved_targets=True),
            accepted_audit_candidate_hashes=(),
        )
    with pytest.raises(module.Protocol25AdoptionError, match="epoch"):
        replace(_semantic(epoch=True), audit_epoch_id=None)
    with pytest.raises(module.Protocol25AdoptionError, match="unresolved audit target"):
        replace(
            _semantic(epoch=True),
            unresolved_audit_target_ids=(digest("late-target"),),
        )


def test_protocol_package_exports_adoption_contract() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")
    module = _adoption()

    assert protocol.ParentAuthorityBundleV2 is module.ParentAuthorityBundleV2
    assert protocol.validate_protocol_25_parent is module.validate_protocol_25_parent
