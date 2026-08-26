from __future__ import annotations

from dataclasses import replace

from jsonschema import Draft202012Validator, ValidationError
import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.execution import (
    CandidateInventoryEntryV1,
    CandidateInventoryV1,
)
from harness.re_v2.protocol_22.model import ArtifactKeyV2
from harness.re_v2.protocol_22.partition import FileRecordV1
from harness.re_v2.protocol_25.runtime import (
    AuthorizedEvidenceRangeV1,
    Protocol25DeterministicRuntime,
    Protocol25RuntimeError,
    SemanticCandidateInputV1,
    semantic_response_schema,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import (
    audit_target_v1,
    finding_vocabulary_v1,
    l3_artifact_key_v2,
)


TARGET = audit_target_v1()
VOCABULARY = finding_vocabulary_v1()
VERIFIER_AUTHORITY = digest("semantic-verifier")
EVIDENCE_PAYLOAD = b"search branch\n" * 20


class _FixtureSnapshotReader:
    def read_file(
        self, source_id: str, path: str, expected: FileRecordV1
    ) -> bytes:
        assert (source_id, path) == ("api", "src/search.py")
        assert expected.content_hash == content_digest(EVIDENCE_PAYLOAD)
        return EVIDENCE_PAYLOAD


def _runtime() -> Protocol25DeterministicRuntime:
    return Protocol25DeterministicRuntime(
        verifier_authority_hash=VERIFIER_AUTHORITY,
        snapshot_reader=_FixtureSnapshotReader(),
    )


def _evidence() -> AuthorizedEvidenceRangeV1:
    record = FileRecordV1(
        source_relative_path="src/search.py",
        mode="100644",
        object_kind="regular",
        content_hash=content_digest(EVIDENCE_PAYLOAD),
        byte_count=len(EVIDENCE_PAYLOAD),
        line_count=20,
        text_status="eligible_utf8",
    )
    return AuthorizedEvidenceRangeV1(
        schema_version=1,
        canonical_anchor_id="evidence:retry-branch",
        aliases=("citation:client-42", "citation:client-43"),
        source_id="api",
        source_relative_path="src/search.py",
        start_line=10,
        end_line=20,
        source_blob_hash=content_digest(EVIDENCE_PAYLOAD),
        file_record=record,
    )


def _base_authority_payloads() -> dict[str, bytes]:
    return {
        digest(seed): seed.encode("utf-8")
        for seed in ("baseline", "lower-closure", "audit-context", "evidence-pack")
    }


def _context(
    *,
    unresolved=(),  # type: ignore[no-untyped-def]
    active_siblings=(),  # type: ignore[no-untyped-def]
    target=TARGET,  # type: ignore[no-untyped-def]
    vocabulary=VOCABULARY,  # type: ignore[no-untyped-def]
    mode: str | None = None,
    overlays=(),  # type: ignore[no-untyped-def]
    assessments=(),  # type: ignore[no-untyped-def]
    extra_authority=None,  # type: ignore[no-untyped-def]
):
    authority_payloads = _base_authority_payloads()
    authority_payloads.update(extra_authority or {})
    return _runtime().build_context(
        mode=mode or ("AUDIT_EPOCH_TARGET" if not unresolved else "SEMANTIC_RESOLUTION"),
        audit_target=target,
        vocabulary=vocabulary,
        authorized_evidence=(_evidence(),),
        authority_payloads=authority_payloads,
        lower_authority_hashes=tuple(sorted(_base_authority_payloads())),
        unresolved_findings=tuple(unresolved),
        overlay_hashes=tuple(overlays),
        target_assessment_hashes=tuple(assessments),
        active_sibling_authority_hashes=tuple(active_siblings),
    )


def _candidate(filename: str, payload: dict[str, object]) -> SemanticCandidateInputV1:
    body = canonical_json_bytes(payload)
    work_item_id = digest(f"work:{filename}:{content_digest(body)}")
    inventory = CandidateInventoryV1(
        schema_version=1,
        dispatch_id=f"dispatch-{filename.removesuffix('.json')}",
        work_item_id=work_item_id,
        entries=(
            CandidateInventoryEntryV1(
                relative_path=filename,
                object_kind="regular",
                mode=0o644,
                byte_count=len(body),
                content_hash=content_digest(body),
            ),
        ),
    )
    return SemanticCandidateInputV1(
        candidate_id=digest(f"candidate:{filename}:{content_digest(body)}"),
        execution_capture_hash=digest(f"capture:{filename}:{content_digest(body)}"),
        inventory=inventory,
        candidate_bytes=body,
    )


def _finding(*, title: str = "Missing retry") -> dict[str, object]:
    return {
        "rule_id": "behavior.missing",
        "finding_class": "missing_behavior",
        "subject_kind": "operation",
        "subject_ref": "operation:search",
        "claim_anchor_ids": [],
        "evidence": [
            {
                "reference": "citation:client-42",
                "path": "src/search.py",
                "start_line": 12,
                "end_line": 14,
            }
        ],
        "title": title,
        "explanation": "Retry exhaustion is not represented in the accepted claim.",
        "recommendation": "Describe retry exhaustion without changing lower evidence.",
        "repair_context": "Refine the search operation claim.",
    }


def _audit_payload(*, verdict: str = "REPAIR", findings=None):  # type: ignore[no-untyped-def]
    selected = [_finding()] if findings is None and verdict == "REPAIR" else findings or []
    return {
        "schema_version": 1,
        "audit_target_id": TARGET.identity,
        "verdict": verdict,
        "findings": selected,
    }


def _certified_audit(*, verdict: str = "REPAIR", findings=None):  # type: ignore[no-untyped-def]
    return _runtime().certify_audit(
        _candidate("audit.json", _audit_payload(verdict=verdict, findings=findings)),
        artifact_key=l3_artifact_key_v2(
            "semantic-audit-findings",
            dependency_hashes=(TARGET.identity,),
        ),
        context=_context(),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "valid"),
    (
        ("semantic-audit-findings", _audit_payload()),
        (
            "semantic-resolution-overlay",
            {
                "schema_version": 1,
                "audit_epoch_id": digest("epoch"),
                "audit_target_id": TARGET.identity,
                "semantic_round": 1,
                "entries": [
                    {
                        "finding_key_ids": [digest("finding")],
                        "disposition": "resolved",
                        "semantic_claims": ["A bounded corrected claim."],
                        "evidence": [
                            {
                                "reference": "evidence:retry-branch",
                                "path": "src/search.py",
                                "start_line": 12,
                                "end_line": 14,
                            }
                        ],
                        "supersedes_claim_anchor_ids": ["claim:search-success"],
                        "refines_subject_refs": [],
                        "unresolved": False,
                    }
                ],
            },
        ),
        (
            "semantic-closure-assessment",
            {
                "schema_version": 1,
                "assessment_kind": "target",
                "audit_epoch_id": digest("epoch"),
                "audit_target_id": TARGET.identity,
                "resolution_overlay_hash": digest("overlay"),
                "verdicts": [],
                "deferred_observations": [],
            },
        ),
    ),
)
def test_protocol_25_response_schemas_are_closed_and_deterministic(
    kind: str, valid: dict[str, object]
) -> None:
    schema = semantic_response_schema(kind)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(valid)
    first = canonical_json_bytes(schema)
    assert first == canonical_json_bytes(semantic_response_schema(kind))

    candidate = dict(valid)
    candidate["run_completed"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(candidate)


@pytest.mark.unit
def test_audit_schema_requires_pass_zero_or_repair_nonzero() -> None:
    validator = Draft202012Validator(
        semantic_response_schema("semantic-audit-findings")
    )
    validator.validate(_audit_payload(verdict="PASS", findings=[]))

    with pytest.raises(ValidationError):
        validator.validate(_audit_payload(verdict="PASS", findings=[_finding()]))
    with pytest.raises(ValidationError):
        validator.validate(_audit_payload(verdict="REPAIR", findings=[]))


@pytest.mark.unit
@pytest.mark.parametrize(
    "controller_field",
    (
        "candidate_id",
        "audit_epoch_id",
        "receipt_id",
        "route",
        "semantic_round",
        "counter",
        "run_completed",
        "terminal_state",
    ),
)
def test_audit_schema_rejects_controller_owned_fields(
    controller_field: str,
) -> None:
    payload = _audit_payload()
    payload[controller_field] = digest(controller_field)
    with pytest.raises(ValidationError):
        Draft202012Validator(
            semantic_response_schema("semantic-audit-findings")
        ).validate(payload)


@pytest.mark.unit
def test_candidate_output_is_bounded_before_normalization() -> None:
    candidate = _candidate("audit.json", _audit_payload())
    oversized = b" " * (128 * 1024) + candidate.candidate_bytes
    entry = replace(
        candidate.inventory.entries[0],
        byte_count=len(oversized),
        content_hash=content_digest(oversized),
    )
    candidate = replace(
        candidate,
        inventory=replace(candidate.inventory, entries=(entry,)),
        candidate_bytes=oversized,
    )

    with pytest.raises(Protocol25RuntimeError, match="byte ceiling"):
        _runtime().certify_audit(
            candidate,
            artifact_key=l3_artifact_key_v2(
                "semantic-audit-findings", dependency_hashes=(TARGET.identity,)
            ),
            context=_context(),
        )


@pytest.mark.unit
def test_context_reads_authorized_evidence_through_shared_snapshot_seam() -> None:
    payload = b"line\n" * 20
    record = FileRecordV1(
        source_relative_path="src/search.py",
        mode="100644",
        object_kind="regular",
        content_hash=content_digest(payload),
        byte_count=len(payload),
        line_count=20,
        text_status="eligible_utf8",
    )

    class Reader:
        calls: list[tuple[str, str, FileRecordV1]] = []

        def read_file(
            self, source_id: str, path: str, expected: FileRecordV1
        ) -> bytes:
            self.calls.append((source_id, path, expected))
            return payload

    reader = Reader()
    evidence = replace(
        _evidence(), source_blob_hash=content_digest(payload), file_record=record
    )
    runtime = Protocol25DeterministicRuntime(
        verifier_authority_hash=VERIFIER_AUTHORITY,
        snapshot_reader=reader,
    )
    runtime.build_context(
        mode="AUDIT_EPOCH_TARGET",
        audit_target=TARGET,
        vocabulary=VOCABULARY,
        authorized_evidence=(evidence,),
        authority_payloads=_base_authority_payloads(),
        lower_authority_hashes=tuple(sorted(_base_authority_payloads())),
        unresolved_findings=(),
        overlay_hashes=(),
        target_assessment_hashes=(),
        active_sibling_authority_hashes=(),
    )

    assert reader.calls == [("api", "src/search.py", record)]


@pytest.mark.unit
def test_context_requires_exact_authority_bytes_and_runtime_schema() -> None:
    incomplete = _base_authority_payloads()
    del incomplete[digest("evidence-pack")]
    with pytest.raises(Protocol25RuntimeError, match="authority bytes"):
        _runtime().build_context(
            mode="AUDIT_EPOCH_TARGET",
            audit_target=TARGET,
            vocabulary=VOCABULARY,
            authorized_evidence=(_evidence(),),
            authority_payloads=incomplete,
            lower_authority_hashes=tuple(sorted(_base_authority_payloads())),
            unresolved_findings=(),
            overlay_hashes=(),
            target_assessment_hashes=(),
            active_sibling_authority_hashes=(),
        )

    wrong_alias = replace(_evidence(), aliases=("citation:not-issued",))
    with pytest.raises(Protocol25RuntimeError, match="controller vocabulary"):
        _runtime().build_context(
            mode="AUDIT_EPOCH_TARGET",
            audit_target=TARGET,
            vocabulary=VOCABULARY,
            authorized_evidence=(wrong_alias,),
            authority_payloads=_base_authority_payloads(),
            lower_authority_hashes=tuple(sorted(_base_authority_payloads())),
            unresolved_findings=(),
            overlay_hashes=(),
            target_assessment_hashes=(),
            active_sibling_authority_hashes=(),
        )

    wrong_target = replace(TARGET, response_schema_hash=digest("wrong-schema"))
    wrong_vocabulary = replace(
        VOCABULARY, audit_target_id=wrong_target.identity
    )
    with pytest.raises(Protocol25RuntimeError, match="response schema"):
        _runtime().build_context(
            mode="AUDIT_EPOCH_TARGET",
            audit_target=wrong_target,
            vocabulary=wrong_vocabulary,
            authorized_evidence=(_evidence(),),
            authority_payloads=_base_authority_payloads(),
            lower_authority_hashes=tuple(sorted(_base_authority_payloads())),
            unresolved_findings=(),
            overlay_hashes=(),
            target_assessment_hashes=(),
            active_sibling_authority_hashes=(),
        )


@pytest.mark.unit
def test_candidate_inventory_requires_exactly_one_expected_regular_file() -> None:
    candidate = _candidate("audit.json", _audit_payload())
    extra = CandidateInventoryEntryV1(
        relative_path="notes.txt",
        object_kind="regular",
        mode=0o644,
        byte_count=1,
        content_hash=digest("notes"),
    )

    with pytest.raises(Protocol25RuntimeError, match="exactly one regular audit.json"):
        _runtime().certify_audit(
            replace(
                candidate,
                inventory=replace(
                    candidate.inventory,
                    entries=(candidate.inventory.entries[0], extra),
                ),
            ),
            artifact_key=l3_artifact_key_v2(
                "semantic-audit-findings", dependency_hashes=(TARGET.identity,)
            ),
            context=_context(),
        )


@pytest.mark.unit
def test_audit_rejects_wrong_target_and_unauthorized_evidence_range() -> None:
    wrong = _audit_payload()
    wrong["audit_target_id"] = digest("wrong-target")
    with pytest.raises(Protocol25RuntimeError, match="audit target"):
        _runtime().certify_audit(
            _candidate("audit.json", wrong),
            artifact_key=l3_artifact_key_v2(
                "semantic-audit-findings", dependency_hashes=(TARGET.identity,)
            ),
            context=_context(),
        )

    outside = _audit_payload()
    outside["findings"][0]["evidence"][0]["end_line"] = 21  # type: ignore[index]
    with pytest.raises(Protocol25RuntimeError, match="authorized evidence"):
        _runtime().certify_audit(
            _candidate("audit.json", outside),
            artifact_key=l3_artifact_key_v2(
                "semantic-audit-findings", dependency_hashes=(TARGET.identity,)
            ),
            context=_context(),
        )


@pytest.mark.unit
def test_duplicate_provider_findings_normalize_to_one() -> None:
    result = _certified_audit(
        findings=[_finding(title="Missing retry"), _finding(title="Retry is missing")]
    )

    assert len(result.normalized_findings) == 1
    assert result.certification.verdict == "accepted"
    assert result.candidate_assessment.outcome == "certified"
    assert result.acceptance.artifact_hash == result.certification.artifact_hash
    assert result.candidate_assessment.normalized_authorial_payload_hash == (
        content_digest(result.normalized_authorial_payload_bytes)
    )
    assert result.candidate_assessment.normalized_authorial_payload_hash != (
        result.candidate_assessment.artifact_hash
    )


def _epoch():  # type: ignore[no-untyped-def]
    result = _certified_audit()
    return _runtime().freeze_epoch(
        (result,),
        selection_id=digest("selection"),
        audit_policy_hash=digest("audit-policy"),
        auditor_authority_hash=TARGET.auditor_authority_hash,
        executor_authority_hash=digest("executor"),
        verifier_authority_hash=VERIFIER_AUTHORITY,
        audited_l2_root_hashes=(digest("l2-root"),),
    )


def _resolution_payload(epoch, finding_ids=None):  # type: ignore[no-untyped-def]
    selected = epoch.finding_key_ids if finding_ids is None else tuple(finding_ids)
    return {
        "schema_version": 1,
        "audit_epoch_id": epoch.identity,
        "audit_target_id": TARGET.identity,
        "semantic_round": 1,
        "entries": [
            {
                "finding_key_ids": list(selected),
                "disposition": "resolved",
                "semantic_claims": ["Retry exhaustion returns a bounded response."],
                "evidence": [
                    {
                        "reference": "evidence:retry-branch",
                        "path": "src/search.py",
                        "start_line": 12,
                        "end_line": 14,
                    }
                ],
                "supersedes_claim_anchor_ids": ["claim:search-success"],
                "refines_subject_refs": ["operation:search"],
                "unresolved": False,
            }
        ],
    }


def _certified_resolution():  # type: ignore[no-untyped-def]
    audit = _certified_audit()
    epoch = _runtime().freeze_epoch(
        (audit,),
        selection_id=digest("selection"),
        audit_policy_hash=digest("audit-policy"),
        auditor_authority_hash=TARGET.auditor_authority_hash,
        executor_authority_hash=digest("executor"),
        verifier_authority_hash=VERIFIER_AUTHORITY,
        audited_l2_root_hashes=(digest("l2-root"),),
    )
    context = _context(unresolved=audit.normalized_findings)
    result = _runtime().certify_resolution(
        _candidate("resolution.json", _resolution_payload(epoch)),
        artifact_key=l3_artifact_key_v2(
            "semantic-resolution-overlay",
            dependency_hashes=(epoch.identity, TARGET.identity),
        ),
        context=context,
        epoch=epoch,
        semantic_round=1,
        prior_overlay_hashes=(),
        guidance_hash=None,
    )
    return audit, epoch, context, result


def _closure_payload(
    audit, epoch, resolution, *, deferred=()  # type: ignore[no-untyped-def]
):
    return {
        "schema_version": 1,
        "assessment_kind": "target",
        "audit_epoch_id": epoch.identity,
        "audit_target_id": TARGET.identity,
        "resolution_overlay_hash": resolution.artifact.identity,
        "verdicts": [
            {
                "finding_key_id": audit.normalized_findings[0].finding_key_id,
                "verdict": "closed",
                "reason_code": "resolved_by_overlay",
            }
        ],
        "deferred_observations": list(deferred),
    }


def _certified_closure():  # type: ignore[no-untyped-def]
    audit, epoch, context, resolution = _certified_resolution()
    closure_context = _context(
        unresolved=audit.normalized_findings,
        mode="CLOSURE_RECHECK",
        overlays=(resolution.artifact.identity,),
        extra_authority={
            resolution.artifact.identity: resolution.artifact_bytes
        },
    )
    result = _runtime().certify_target_closure(
        _candidate("closure.json", _closure_payload(audit, epoch, resolution)),
        artifact_key=l3_artifact_key_v2(
            "target-closure-assessment",
            dependency_hashes=(epoch.identity, resolution.artifact.identity),
        ),
        context=closure_context,
        epoch=epoch,
        overlay=resolution.artifact,
    )
    return audit, epoch, context, resolution, result


def _source_artifact_key(
    source_target, artifact_kind: str, dependencies: tuple[str, ...]  # type: ignore[no-untyped-def]
) -> ArtifactKeyV2:
    return ArtifactKeyV2(
        identity_schema_version=2,
        scope=source_target.scope,
        partition_id=digest("partition"),
        artifact_kind=artifact_kind,
        layer="L3",
        producer_protocol_version="2.5",
        layer_policy_hash=digest(f"{artifact_kind}-policy"),
        dependency_hashes=tuple(sorted(dependencies)),
    )


@pytest.mark.unit
def test_resolution_covers_each_requested_unresolved_id_exactly_once() -> None:
    audit, epoch, context, _result = _certified_resolution()

    with pytest.raises(Protocol25RuntimeError, match="every unresolved finding"):
        _runtime().certify_resolution(
            _candidate("resolution.json", _resolution_payload(epoch, (digest("sibling"),))),
            artifact_key=l3_artifact_key_v2(
                "semantic-resolution-overlay",
                dependency_hashes=(epoch.identity, TARGET.identity),
            ),
            context=context,
            epoch=epoch,
            semantic_round=1,
            prior_overlay_hashes=(),
            guidance_hash=None,
        )
    assert audit.normalized_findings[0].finding_key_id in epoch.finding_key_ids

    unknown_anchor = _resolution_payload(epoch)
    unknown_anchor["entries"][0]["supersedes_claim_anchor_ids"] = [  # type: ignore[index]
        "claim:not-controller-issued"
    ]
    with pytest.raises(Protocol25RuntimeError, match="controller-issued"):
        _runtime().certify_resolution(
            _candidate("resolution.json", unknown_anchor),
            artifact_key=l3_artifact_key_v2(
                "semantic-resolution-overlay",
                dependency_hashes=(epoch.identity, TARGET.identity),
            ),
            context=context,
            epoch=epoch,
            semantic_round=1,
            prior_overlay_hashes=(),
            guidance_hash=None,
        )


@pytest.mark.unit
def test_target_closure_requires_every_input_id_and_exact_overlay_hash() -> None:
    audit, epoch, context, resolution = _certified_resolution()
    finding_id = audit.normalized_findings[0].finding_key_id
    closure = {
        "schema_version": 1,
        "assessment_kind": "target",
        "audit_epoch_id": epoch.identity,
        "audit_target_id": TARGET.identity,
        "resolution_overlay_hash": resolution.artifact.identity,
        "verdicts": [
            {
                "finding_key_id": finding_id,
                "verdict": "closed",
                "reason_code": "resolved_by_overlay",
            }
        ],
        "deferred_observations": [],
    }
    result = _runtime().certify_target_closure(
        _candidate("closure.json", closure),
        artifact_key=l3_artifact_key_v2(
            "target-closure-assessment",
            dependency_hashes=(epoch.identity, resolution.artifact.identity),
        ),
        context=_context(
            unresolved=audit.normalized_findings,
            mode="CLOSURE_RECHECK",
            overlays=(resolution.artifact.identity,),
            extra_authority={
                resolution.artifact.identity: resolution.artifact_bytes
            },
        ),
        epoch=epoch,
        overlay=resolution.artifact,
    )
    assert result.artifact.assessed_finding_ids == (finding_id,)

    closure["resolution_overlay_hash"] = digest("wrong-overlay")
    with pytest.raises(Protocol25RuntimeError, match="overlay hash"):
        _runtime().certify_target_closure(
            _candidate("closure.json", closure),
            artifact_key=l3_artifact_key_v2(
                "target-closure-assessment",
                dependency_hashes=(epoch.identity, resolution.artifact.identity),
            ),
            context=_context(
                unresolved=audit.normalized_findings,
                mode="CLOSURE_RECHECK",
                overlays=(resolution.artifact.identity,),
                extra_authority={
                    resolution.artifact.identity: resolution.artifact_bytes
                },
            ),
            epoch=epoch,
            overlay=resolution.artifact,
        )


@pytest.mark.unit
def test_deferred_observations_are_normalized_without_joining_frozen_findings() -> None:
    audit, epoch, context, resolution = _certified_resolution()
    deferred = {
        key: value
        for key, value in _finding().items()
        if key
        in {
            "rule_id",
            "finding_class",
            "subject_kind",
            "subject_ref",
            "claim_anchor_ids",
            "evidence",
        }
    }
    deferred["diagnostic"] = "A dynamic branch needs another audit epoch."
    reworded = dict(deferred)
    reworded["diagnostic"] = "Inspect the dynamic branch in a later epoch."
    closure_context = _context(
        unresolved=audit.normalized_findings,
        mode="CLOSURE_RECHECK",
        overlays=(resolution.artifact.identity,),
        extra_authority={
            resolution.artifact.identity: resolution.artifact_bytes
        },
    )
    result = _runtime().certify_target_closure(
        _candidate(
            "closure.json",
            _closure_payload(
                audit, epoch, resolution, deferred=(deferred, reworded)
            ),
        ),
        artifact_key=l3_artifact_key_v2(
            "target-closure-assessment",
            dependency_hashes=(epoch.identity, resolution.artifact.identity),
        ),
        context=closure_context,
        epoch=epoch,
        overlay=resolution.artifact,
    )

    assert len(result.artifact.deferred_observations) == 1
    assert result.artifact.assessed_finding_ids == epoch.finding_key_ids
    assert tuple(item.finding_key_id for item in result.artifact.verdicts) == (
        epoch.finding_key_ids
    )


@pytest.mark.unit
def test_failed_source_guard_binds_composed_view_and_retains_authorizing_id() -> None:
    audit, epoch, _context_value, resolution, closure = _certified_closure()
    sibling = digest("closed-sibling-root")
    source_target = audit_target_v1(target_kind="source")
    source_vocabulary = replace(
        VOCABULARY, audit_target_id=source_target.identity
    )
    guard_context = _context(
        mode="SOURCE_COMPOSITION_GUARD",
        target=source_target,
        vocabulary=source_vocabulary,
        unresolved=audit.normalized_findings,
        active_siblings=(sibling,),
        overlays=(resolution.artifact.identity,),
        assessments=(closure.artifact.identity,),
        extra_authority={
            resolution.artifact.identity: resolution.artifact_bytes,
            closure.artifact.identity: closure.artifact_bytes,
            sibling: b"closed-sibling-root",
        },
    )
    view = _runtime().build_composed_view(
        context=guard_context,
        epoch=epoch,
        source_id="api",
        overlays=(resolution.artifact,),
        target_assessments=(closure.artifact,),
    )
    finding_id = audit.normalized_findings[0].finding_key_id
    payload = {
        "schema_version": 1,
        "assessment_kind": "source-composition",
        "audit_epoch_id": epoch.identity,
        "source_id": "api",
        "overlay_hashes": [resolution.artifact.identity],
        "target_assessment_hashes": [closure.artifact.identity],
        "outcome": "failed",
        "implicated_finding_ids": [finding_id],
        "deferred_observations": [],
    }
    dependencies = (
        epoch.identity,
        resolution.artifact.identity,
        closure.artifact.identity,
    )
    result = _runtime().certify_source_guard(
        _candidate("closure.json", payload),
        artifact_key=_source_artifact_key(
            source_target, "source-composition-assessment", dependencies
        ),
        context=guard_context,
        epoch=epoch,
        source_id="api",
        overlays=(resolution.artifact,),
        target_assessments=(closure.artifact,),
        composed_view=view,
    )

    assert view.active_sibling_authority_hashes == (sibling,)
    assert view.overlay_hashes == (resolution.artifact.identity,)
    context_payloads = {
        item.object_hash: item.payload_bytes
        for item in guard_context.authority_objects
    }
    assert context_payloads[sibling] == b"closed-sibling-root"
    assert context_payloads[resolution.artifact.identity] == (
        resolution.artifact_bytes
    )
    assert view.target_assessments == (closure.artifact,)
    assert result.artifact.composed_authority_hash == view.identity
    assert result.artifact.implicated_finding_ids == (finding_id,)
    assert result.artifact.outcome == "failed"

    wrong_hashes = dict(payload)
    wrong_hashes["target_assessment_hashes"] = [digest("wrong-assessment")]
    with pytest.raises(Protocol25RuntimeError, match="input authority"):
        _runtime().certify_source_guard(
            _candidate("closure.json", wrong_hashes),
            artifact_key=_source_artifact_key(
                source_target, "source-composition-assessment", dependencies
            ),
            context=guard_context,
            epoch=epoch,
            source_id="api",
            overlays=(resolution.artifact,),
            target_assessments=(closure.artifact,),
            composed_view=view,
        )

    provider_finding = dict(payload)
    provider_finding["findings"] = [_finding()]
    with pytest.raises(Protocol25RuntimeError, match="closed response schema"):
        _runtime().certify_source_guard(
            _candidate("closure.json", provider_finding),
            artifact_key=_source_artifact_key(
                source_target, "source-composition-assessment", dependencies
            ),
            context=guard_context,
            epoch=epoch,
            source_id="api",
            overlays=(resolution.artifact,),
            target_assessments=(closure.artifact,),
            composed_view=view,
        )


@pytest.mark.unit
def test_zero_finding_audits_freeze_and_close_without_model_work() -> None:
    audit = _certified_audit(verdict="PASS", findings=[])
    epoch = _runtime().freeze_epoch(
        (audit,),
        selection_id=digest("selection"),
        audit_policy_hash=digest("audit-policy"),
        auditor_authority_hash=TARGET.auditor_authority_hash,
        executor_authority_hash=digest("executor"),
        verifier_authority_hash=VERIFIER_AUTHORITY,
        audited_l2_root_hashes=(digest("l2-root"),),
    )
    closure = _runtime().build_closure_root(
        epoch,
        latest_receipts=(),
        target_rounds=(),
        plateau_counts=(),
        deferred_observations=(),
    )

    assert epoch.finding_key_ids == ()
    assert closure.state == "closed"
