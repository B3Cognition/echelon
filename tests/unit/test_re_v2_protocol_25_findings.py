from __future__ import annotations

import importlib
from dataclasses import replace

import pytest

from harness.re_v2.protocol_22.model import ArtifactScope
from tests.re_v2_protocol_22_fixtures import digest


def _findings():  # type: ignore[no-untyped-def]
    try:
        return importlib.import_module("harness.re_v2.protocol_25.findings")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 finding authority is not registered")


def _audited_artifact(seed: str = "baseline"):  # type: ignore[no-untyped-def]
    module = _findings()
    return module.AuditedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=digest(f"{seed}-key"),
        artifact_hash=digest(seed),
        dependency_hashes=(digest(f"{seed}-dependency"),),
    )


def _target(*, target_kind: str = "domain"):  # type: ignore[no-untyped-def]
    module = _findings()
    domain_key = digest("orders-domain") if target_kind == "domain" else None
    return module.AuditTargetV1(
        schema_version=1,
        target_kind=target_kind,
        scope=ArtifactScope("api", domain_key, digest("selected-content")),
        audited_artifacts=(_audited_artifact(),),
        lower_dependency_hashes=(digest("lower-closure"),),
        context_object_hashes=(digest("audit-context"),),
        evidence_object_hashes=(digest("evidence-pack"),),
        audit_policy_hash=digest("audit-policy"),
        auditor_authority_hash=digest("validator-agent"),
        response_schema_hash=digest("audit-schema"),
    )


def _vocabulary():  # type: ignore[no-untyped-def]
    module = _findings()
    target = _target()
    return module.FindingAuthorityVocabularyV1(
        schema_version=1,
        audit_target_id=target.identity,
        rule_ids=("behavior.missing", "behavior.unsupported"),
        subject_refs=("operation:search", "surface:search"),
        claim_anchor_ids=("claim:search-success",),
        evidence_anchors=(
            module.EvidenceAnchorAuthorityV1(
                schema_version=1,
                anchor_id="evidence:retry-branch",
                aliases=("citation:client-42", "citation:client-43"),
            ),
        ),
    )


def _key(  # type: ignore[no-untyped-def]
    *,
    subject_kind: str = "operation",
    subject_ref: str = "operation:search",
    evidence_refs: tuple[str, ...] = ("evidence:retry-branch",),
):
    module = _findings()
    vocabulary = _vocabulary()
    return module.normalize_finding_key(
        vocabulary=vocabulary,
        audit_target=_target(),
        rule_id="behavior.missing",
        finding_class="missing_behavior",
        subject_kind=subject_kind,
        subject_ref=subject_ref,
        claim_anchor_ids=(),
        evidence_refs=evidence_refs,
    )


def _semantic_finding(  # type: ignore[no-untyped-def]
    *,
    title: str,
    explanation: str,
):
    module = _findings()
    return module.SemanticFindingV1(
        schema_version=1,
        finding_key=_key(),
        title=title,
        explanation=explanation,
        recommendation="Describe the observed retry exhaustion behavior.",
        repair_context="Refine the search operation claim without editing L2.",
    )


def test_audit_target_identity_binds_exact_selected_authority() -> None:
    target = _target()

    assert target.identity != replace(
        target,
        context_object_hashes=(digest("different-context"),),
    ).identity
    assert target.identity != replace(
        target,
        audited_artifacts=(_audited_artifact("different-baseline"),),
    ).identity


def test_protocol_package_exports_finding_authorities() -> None:
    protocol = importlib.import_module("harness.re_v2.protocol_25")

    assert protocol.AuditTargetV1 is _findings().AuditTargetV1
    assert protocol.FindingKeyV1 is _findings().FindingKeyV1
    assert protocol.SemanticFindingV1 is _findings().SemanticFindingV1
    assert protocol.DeferredObservationV1 is _findings().DeferredObservationV1


def test_finding_authorities_round_trip_exactly() -> None:
    module = _findings()
    key = _key()
    values = (
        _audited_artifact(),
        _target(),
        _vocabulary(),
        key,
        _semantic_finding(
            title="Missing retry",
            explanation="No retry exhaustion behavior is described.",
        ),
        module.DeferredObservationV1(
            schema_version=1,
            audit_target_id=key.audit_target_id,
            authority_vocabulary_id=key.authority_vocabulary_id,
            rule_id=key.rule_id,
            finding_class="requires_deeper_evidence",
            subject_kind=key.subject_kind,
            subject_ref=key.subject_ref,
            claim_anchor_ids=key.claim_anchor_ids,
            evidence_anchor_ids=key.evidence_anchor_ids,
            audited_artifact_hashes=key.audited_artifact_hashes,
            diagnostic="A dynamic branch requires deeper evidence.",
        ),
    )

    for value in values:
        assert type(value).from_json_dict(value.to_json_dict()) == value


def test_audit_target_kind_must_match_scope() -> None:
    module = _findings()

    with pytest.raises(module.Protocol25SchemaError, match="source target"):
        replace(_target(), target_kind="source")


def test_finding_identity_ignores_diagnostic_rewording() -> None:
    first = _semantic_finding(
        title="Missing retry",
        explanation="No retry exhaustion behavior is described.",
    )
    second = _semantic_finding(
        title="Retry behavior absent",
        explanation="The current claim omits what happens after retry exhaustion.",
    )

    assert first.finding_key.identity == second.finding_key.identity
    assert first.identity != second.identity


def test_finding_identity_changes_with_structured_authority() -> None:
    first = _key(subject_ref="operation:search")
    second = _key(subject_kind="surface", subject_ref="surface:search")

    assert first.identity != second.identity


def test_equivalent_evidence_aliases_normalize_to_one_finding_key() -> None:
    first = _key(evidence_refs=("citation:client-42",))
    second = _key(evidence_refs=("citation:client-43",))

    assert first.evidence_anchor_ids == ("evidence:retry-branch",)
    assert first.identity == second.identity


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("rule_id", "behavior.unknown"),
        ("subject_ref", "operation:unknown"),
        ("evidence_refs", ("citation:unknown",)),
    ),
)
def test_normalizer_rejects_non_controller_authority(field: str, value: object) -> None:
    module = _findings()
    arguments = {
        "vocabulary": _vocabulary(),
        "audit_target": _target(),
        "rule_id": "behavior.missing",
        "finding_class": "missing_behavior",
        "subject_kind": "operation",
        "subject_ref": "operation:search",
        "claim_anchor_ids": (),
        "evidence_refs": ("evidence:retry-branch",),
    }
    arguments[field] = value

    with pytest.raises(module.Protocol25SchemaError, match="controller-issued"):
        module.normalize_finding_key(**arguments)


def test_normalizer_rejects_duplicate_provider_anchors() -> None:
    module = _findings()

    with pytest.raises(module.Protocol25SchemaError, match="duplicate"):
        module.normalize_finding_key(
            vocabulary=_vocabulary(),
            audit_target=_target(),
            rule_id="behavior.unsupported",
            finding_class="unsupported_claim",
            subject_kind="operation",
            subject_ref="operation:search",
            claim_anchor_ids=("claim:search-success", "claim:search-success"),
            evidence_refs=("evidence:retry-branch",),
        )


def test_normalizer_requires_subject_kind_to_match_controller_reference() -> None:
    module = _findings()

    with pytest.raises(module.Protocol25SchemaError, match="subject_kind"):
        module.normalize_finding_key(
            vocabulary=_vocabulary(),
            audit_target=_target(),
            rule_id="behavior.missing",
            finding_class="missing_behavior",
            subject_kind="boundary",
            subject_ref="operation:search",
            claim_anchor_ids=(),
            evidence_refs=("evidence:retry-branch",),
        )


def test_finding_class_is_closed() -> None:
    module = _findings()

    with pytest.raises(module.Protocol25SchemaError, match="finding_class"):
        replace(_key(), finding_class="style_preference")


def test_diagnostic_text_is_normalized_and_bounded() -> None:
    module = _findings()

    with pytest.raises(module.Protocol25SchemaError, match="normalized"):
        _semantic_finding(title=" Missing retry", explanation="Valid explanation")
    with pytest.raises(module.Protocol25SchemaError, match="bounded"):
        _semantic_finding(title="Missing retry", explanation="x" * 4097)


def test_deferred_observation_identity_ignores_diagnostic_rewording() -> None:
    module = _findings()
    key = _key()
    first = module.DeferredObservationV1(
        schema_version=1,
        audit_target_id=key.audit_target_id,
        authority_vocabulary_id=key.authority_vocabulary_id,
        rule_id=key.rule_id,
        finding_class="requires_deeper_evidence",
        subject_kind=key.subject_kind,
        subject_ref=key.subject_ref,
        claim_anchor_ids=key.claim_anchor_ids,
        evidence_anchor_ids=key.evidence_anchor_ids,
        audited_artifact_hashes=key.audited_artifact_hashes,
        diagnostic="A dynamic branch requires deeper evidence.",
    )
    second = replace(
        first,
        diagnostic="Deeper evidence is required for the dynamic branch.",
    )

    assert first.observation_id == second.observation_id
    assert first.payload_hash != second.payload_hash
