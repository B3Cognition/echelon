from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Mapping

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    ContextBundleV1,
    DepthDebtV1,
    DeterministicAssessmentInputV2,
    EvidenceReferenceV1,
)
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationReceiptV2,
    CompactCandidateInputV1,
    CompactCertificationResultV2,
    CoverageAssessmentV1,
    Protocol22CertificationError,
    certify_compact_candidate,
    certify_deterministic_artifact,
    parse_authorial_candidate,
    render_baseline_markdown,
)
from harness.re_v2.protocol_22.context import build_source_overview_context_bundle
from harness.re_v2.protocol_22.graph import AcceptedArtifactV2, instantiate_ready_item
from harness.re_v2.protocol_22.inventory import InventoryArtifactV1
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.partition import FileRecordV1, WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.policies import (
    DOMAIN_SURFACES,
    SOURCE_OVERVIEW_SURFACES,
    policy_for,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_baseline import _candidate, _reference, _surface
from tests.unit.test_re_v2_protocol_22_context import (
    _domain_baseline_bytes,
    _domain_fixture,
    _source_fixture,
    _template,
)


@dataclass
class _SnapshotReader:
    partition: WorkspacePartitionCatalogV1
    blobs: Mapping[str, bytes]

    def read_file(
        self,
        source_id: str,
        source_relative_path: str,
        expected: FileRecordV1,
    ) -> bytes:
        source = next(item for item in self.partition.sources if item.source_id == source_id)
        assert expected == next(
            item for item in source.files if item.source_relative_path == source_relative_path
        )
        payload = self.blobs[source_relative_path]
        assert content_digest(payload) == expected.content_hash
        return payload


def _candidate_input(
    raw: dict[str, object],
    kind: str,
    context: ContextBundleV1,
    *,
    candidate: str = "candidate-a",
    capture: str = "capture-a",
) -> CompactCandidateInputV1:
    return CompactCandidateInputV1(
        candidate_id=digest(candidate),
        execution_capture_hash=digest(capture),
        authorial_payload=parse_authorial_candidate(
            canonical_json_bytes(raw),
            kind,
            context.target_artifact_policy,
        ),
    )


def _domain_certification_fixture(
    raw: dict[str, object],
    *,
    candidate: str = "candidate-a",
    capture: str = "capture-a",
) -> tuple[CompactCertificationResultV2, WorkItemV2, ContextBundleV1, _SnapshotReader]:
    fixture = _domain_fixture()
    item, _unused = _domain_baseline_bytes(fixture, {})
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    source = fixture.inputs.workspace_partition.sources[0]
    domain = source.domains[0]
    reader = _SnapshotReader(
        fixture.inputs.workspace_partition,
        {f"{domain.source_relative_root}/main.py": b"api:orders\n"},
    )
    verifier = fixture.inputs.executor_contract.entry_for(
        "compact-baseline"
    ).verifier
    result = certify_compact_candidate(
        _candidate_input(
            raw,
            "domain-baseline",
            context,
            candidate=candidate,
            capture=capture,
        ),
        item,
        context,
        reader,
        verifier,
    )
    return result, item, context, reader


def _valid_domain_candidate(context: ContextBundleV1) -> dict[str, object]:
    excerpt = context.evidence[0]
    reference = {
        "evidence_authority_id": excerpt.evidence_authority_id,
        "path": excerpt.source_relative_path,
        "start_line": excerpt.start_line,
        "end_line": excerpt.end_line,
    }
    raw = _candidate()
    raw["surfaces"]["responsibilities"] = _surface(
        "Owns order behavior", evidence=[reference]
    )
    raw["surfaces"]["entry_points"] = _surface(
        "Exposes the order entry point", evidence=[reference]
    )
    return raw


@pytest.mark.unit
def test_all_not_established_domain_fails_minimum_utility() -> None:
    result, _item, _context, _reader = _domain_certification_fixture(_candidate())

    assert result.certification.verdict == "rejected"
    assert result.certification.assessment.minimum_utility.diagnostic_codes == (
        "responsibilities_not_observed",
        "entry_or_behavior_not_observed",
        "no_regular_file_cited",
    )
    assert result.certification.assessment.normalized_diagnostics == (
        "minimum_utility_not_met",
    )
    assert result.candidate_assessment.outcome == "rejected_after_artifact"


@pytest.mark.unit
def test_valid_domain_candidate_has_exact_direct_and_combined_coverage() -> None:
    fixture = _domain_fixture()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    result, _item, _context, _reader = _domain_certification_fixture(
        _valid_domain_candidate(context)
    )
    coverage = result.certification.assessment.coverage

    assert result.certification.verdict == "accepted"
    assert coverage.projected_domains is None
    assert coverage.direct.universe == "direct_read_set"
    assert coverage.combined.universe == "combined_evidence_authority"
    for field in (
        "inventory_file_count",
        "selected_file_count",
        "referenced_file_count",
        "fully_selected_file_count",
        "partially_selected_file_count",
        "omitted_file_count",
        "omitted_range_count",
    ):
        assert getattr(coverage.direct, field) == getattr(coverage.combined, field)
    assert (
        coverage.direct.inventory_file_count,
        coverage.direct.selected_file_count,
        coverage.direct.referenced_file_count,
    ) == (1, 1, 1)
    assert coverage.direct.selected_over_inventory.to_json_dict() == {
        "numerator": 1,
        "denominator": 1,
    }


@pytest.mark.unit
def test_two_candidates_share_artifact_certification_but_keep_provenance() -> None:
    fixture = _domain_fixture()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    raw = _valid_domain_candidate(context)
    first, _item, _context, _reader = _domain_certification_fixture(
        raw,
        candidate="candidate-one",
        capture="capture-one",
    )
    second, _item, _context, _reader = _domain_certification_fixture(
        json.loads(json.dumps(raw, indent=2)),
        candidate="candidate-two",
        capture="capture-two",
    )

    assert first.artifact_bytes == second.artifact_bytes
    assert first.certification.identity == second.certification.identity
    assert first.candidate_assessment.identity != second.candidate_assessment.identity
    assert first.candidate_assessment.candidate_id != (
        second.candidate_assessment.candidate_id
    )


@pytest.mark.unit
@pytest.mark.parametrize("violation", ("path", "range", "authority"))
def test_evidence_mismatch_rejects_after_artifact(violation: str) -> None:
    fixture = _domain_fixture()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    raw = _valid_domain_candidate(context)
    reference = raw["surfaces"]["responsibilities"]["items"][0]["evidence"][0]
    if violation == "path":
        reference["path"] = "orders/other.py"
    elif violation == "range":
        reference["end_line"] = 2
    else:
        reference["evidence_authority_id"] = digest("unknown authority")

    result, _item, _context, _reader = _domain_certification_fixture(raw)

    assert result.certification.verdict == "rejected"
    assert "evidence_contract_invalid" in (
        result.certification.assessment.normalized_diagnostics
    )
    assert result.candidate_assessment.outcome == "rejected_after_artifact"


def _source_certification_fixture(
    *,
    presentation: str | None = None,
) -> tuple[
    object,
    WorkItemV2,
    ContextBundleV1,
    _SnapshotReader,
    object,
]:
    source = _source_fixture(
        {"orders": {"responsibilities": ("Domain owns orders",)}},
        presentation_ids=(
            None
            if presentation is None
            else {("api", "orders"): presentation}
        ),
    )
    context_bytes = build_source_overview_context_bundle(
        source.item,
        source.dependencies,
        source.inputs.artifact_policy,
    )
    context = load_canonical_object(context_bytes, ContextBundleV1.from_json_dict)
    template = _template(source.graph, "api", "source-overview")
    accepted = AcceptedArtifactV2(
        artifact_key_id=digest("source-context-key"),
        artifact_hash=content_digest(context_bytes),
    )
    item = instantiate_ready_item(
        template,
        {template.required_template_ids[0]: accepted},
        source.inputs,
    )
    blobs = {
        record.source_relative_path: (
            f"api:{next(domain.source_relative_root for domain in source.inputs.workspace_partition.sources[0].domains if record.source_relative_path.startswith(f'{domain.source_relative_root}/'))}\n".encode()
        )
        for record in source.inputs.workspace_partition.sources[0].files
    }
    reader = _SnapshotReader(source.inputs.workspace_partition, blobs)
    verifier = source.inputs.executor_contract.entry_for("compact-baseline").verifier
    return source, item, context, reader, verifier


def _valid_source_candidate(context: ContextBundleV1) -> dict[str, object]:
    direct = context.evidence[0]
    direct_ref = {
        "evidence_authority_id": direct.evidence_authority_id,
        "path": direct.source_relative_path,
        "start_line": direct.start_line,
        "end_line": direct.end_line,
    }
    raw = _candidate("source-overview")
    raw["surfaces"]["purpose"] = _surface(
        "Coordinates the source", evidence=[direct_ref]
    )
    raw["surfaces"]["runtime_shape"] = _surface(
        "Runs through the source entry", evidence=[direct_ref]
    )
    if context.domain_projections:
        projected = context.domain_projections[0].evidence[0]
        projected_ref = {
            "evidence_authority_id": projected.evidence_authority_id,
            "path": projected.source_relative_path,
            "start_line": projected.start_line,
            "end_line": projected.end_line,
        }
        raw["surfaces"]["domain_relationships"] = _surface(
            "Relates the domain to source runtime", evidence=[projected_ref]
        )
    return raw


@pytest.mark.unit
def test_source_coverage_adds_disjoint_direct_and_projected_authorities() -> None:
    _source, item, context, reader, verifier = _source_certification_fixture()
    result = certify_compact_candidate(
        _candidate_input(
            _valid_source_candidate(context),
            "source-overview",
            context,
        ),
        item,
        context,
        reader,
        verifier,
    )
    coverage = result.certification.assessment.coverage

    assert result.certification.verdict == "accepted"
    assert coverage.projected_domains is not None
    assert (
        coverage.direct.inventory_file_count,
        coverage.projected_domains.inventory_file_count,
        coverage.combined.inventory_file_count,
    ) == (1, 1, 2)
    assert (
        coverage.direct.selected_file_count,
        coverage.projected_domains.selected_file_count,
        coverage.combined.selected_file_count,
    ) == (1, 1, 2)
    assert (
        coverage.direct.referenced_file_count,
        coverage.projected_domains.referenced_file_count,
        coverage.combined.referenced_file_count,
    ) == (1, 1, 2)


@pytest.mark.unit
def test_projected_evidence_cannot_be_smuggled_into_direct_context() -> None:
    source, _item, context, reader, verifier = _source_certification_fixture()
    projection = context.domain_projections[0]
    projected = projection.evidence[0]
    raw = _valid_source_candidate(context)
    misplaced = replace(
        context,
        evidence=tuple(
            sorted((*context.evidence, projected), key=lambda item: item.sort_key)
        ),
        domain_projections=(replace(projection, evidence=()),),
    )
    template = _template(source.graph, "api", "source-overview")
    item = instantiate_ready_item(
        template,
        {
            template.required_template_ids[0]: AcceptedArtifactV2(
                digest("misplaced-context-key"),
                content_digest(canonical_json_bytes(misplaced.to_json_dict())),
            )
        },
        source.inputs,
    )
    reference = {
        "evidence_authority_id": projected.evidence_authority_id,
        "path": projected.source_relative_path,
        "start_line": projected.start_line,
        "end_line": projected.end_line,
    }
    raw["surfaces"]["purpose"] = _surface(
        "Claims projected evidence as direct context",
        evidence=[reference],
    )

    result = certify_compact_candidate(
        _candidate_input(raw, "source-overview", misplaced),
        item,
        misplaced,
        reader,
        verifier,
    )

    assert result.certification.verdict == "rejected"
    assert "evidence_contract_invalid" in (
        result.certification.assessment.normalized_diagnostics
    )


@pytest.mark.unit
def test_wholly_omitted_domain_counts_inventory_but_zero_projection_selection() -> None:
    _source, item, context, reader, verifier = _source_certification_fixture(
        presentation="domain-" + "x" * 3_000
    )
    result = certify_compact_candidate(
        _candidate_input(
            _valid_source_candidate(context),
            "source-overview",
            context,
        ),
        item,
        context,
        reader,
        verifier,
    )
    projected = result.certification.assessment.coverage.projected_domains

    assert projected is not None
    assert projected.inventory_file_count == 1
    assert projected.selected_file_count == 0
    assert projected.referenced_file_count == 0
    assert projected.omitted_file_count == 1
    assert projected.referenced_over_selected.to_json_dict() == {
        "numerator": 0,
        "denominator": 0,
    }


@pytest.mark.unit
def test_multi_domain_source_requires_boundary_or_relationship_claim() -> None:
    source = _source_fixture(
        {
            "orders": {"responsibilities": ("Orders",)},
            "users": {"responsibilities": ("Users",)},
        }
    )
    context_bytes = build_source_overview_context_bundle(
        source.item, source.dependencies, source.inputs.artifact_policy
    )
    context = load_canonical_object(context_bytes, ContextBundleV1.from_json_dict)
    template = _template(source.graph, "api", "source-overview")
    item = instantiate_ready_item(
        template,
        {
            template.required_template_ids[0]: AcceptedArtifactV2(
                digest("context-key"), content_digest(context_bytes)
            )
        },
        source.inputs,
    )
    raw = _valid_source_candidate(context)
    raw["surfaces"]["domain_relationships"] = _surface()
    reader = _SnapshotReader(
        source.inputs.workspace_partition,
        {
            record.source_relative_path: f"api:{record.source_relative_path.split('/')[0]}\n".encode()
            for record in source.inputs.workspace_partition.sources[0].files
        },
    )
    result = certify_compact_candidate(
        _candidate_input(raw, "source-overview", context),
        item,
        context,
        reader,
        source.inputs.executor_contract.entry_for("compact-baseline").verifier,
    )

    assert result.certification.verdict == "rejected"
    assert (
        "boundary_or_relationship_not_observed"
        in result.certification.assessment.minimum_utility.diagnostic_codes
    )


@pytest.mark.unit
def test_markdown_is_byte_stable_ordered_and_explicitly_unaudited() -> None:
    fixture = _domain_fixture()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    result, _item, _context, _reader = _domain_certification_fixture(
        _valid_domain_candidate(context)
    )

    first = render_baseline_markdown(result.artifact_bytes)
    second = render_baseline_markdown(result.artifact_bytes)
    text = first.decode("utf-8")

    assert first == second
    assert text.index("Responsibilities") < text.index("Entry Points")
    assert "Semantic audit: not run" in text
    assert "Depth debt" in text
    assert len(first) <= 96 * 1024


@pytest.mark.unit
def test_deterministic_certification_uses_null_compact_coverage() -> None:
    fixture = _domain_fixture()
    graph = fixture.graph
    inputs = fixture.inputs
    source = inputs.workspace_partition.sources[0]
    template = _template(graph, source.source_id, "domain-inventory", domain_key_value=source.domains[0].domain_key)
    item = instantiate_ready_item(template, {}, inputs)
    inventory = InventoryArtifactV1.from_json_dict(
        json.loads(fixture.inventory_bytes)
    )
    artifact_hash = content_digest(canonical_json_bytes(inventory.to_json_dict()))
    assessment = DeterministicAssessmentInputV2(
        canonical_schema_valid=True,
        dependency_closure_valid=True,
        policy_conformance_valid=True,
        depth_debt=None,
        normalized_diagnostics=(),
    )
    verifier = inputs.executor_contract.entry_for("inventory").verifier

    receipt = certify_deterministic_artifact(
        item,
        artifact_hash,
        assessment,
        verifier,
    )

    assert receipt.verdict == "accepted"
    assert receipt.assessment.assessment_kind == "deterministic_artifact"
    assert not hasattr(receipt.assessment, "coverage")
    assert receipt.assessment.semantic_status == "not_applicable"


@pytest.mark.unit
def test_deterministic_evidence_certification_requires_depth_debt() -> None:
    fixture = _domain_fixture()
    source = fixture.inputs.workspace_partition.sources[0]
    template = _template(
        fixture.graph,
        source.source_id,
        "domain-evidence-pack",
        domain_key_value=source.domains[0].domain_key,
    )
    dependency = next(
        value
        for role, value in fixture.dependencies.by_role.items()
        if role == "domain_inventory"
    )
    item = instantiate_ready_item(
        template,
        {template.required_template_ids[0]: dependency},
        fixture.inputs,
    )
    assessment = DeterministicAssessmentInputV2(
        canonical_schema_valid=True,
        dependency_closure_valid=True,
        policy_conformance_valid=True,
        depth_debt=None,
        normalized_diagnostics=(),
    )

    with pytest.raises(Protocol22CertificationError, match="depth debt"):
        certify_deterministic_artifact(
            item,
            digest("evidence artifact"),
            assessment,
            fixture.inputs.executor_contract.entry_for("evidence-pack").verifier,
        )


@pytest.mark.unit
def test_acceptance_receipt_contains_no_candidate_or_timestamp() -> None:
    fixture = _domain_fixture()
    context = load_canonical_object(
        fixture.context_bytes,
        ContextBundleV1.from_json_dict,
    )
    result, item, _context, _reader = _domain_certification_fixture(
        _valid_domain_candidate(context)
    )
    artifact_hash = content_digest(result.artifact_bytes)
    receipt = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=item.output_key,
        artifact_hash=artifact_hash,
        certification_receipt_id=result.certification.identity,
    )
    raw = receipt.to_json_dict()

    assert "candidate_id" not in raw
    assert "work_item_id" not in raw
    assert "accepted_at" not in raw
    assert ArtifactAcceptanceReceiptV2.from_json_dict(raw) == receipt
    assert CertificationReceiptV2.from_json_dict(
        result.certification.to_json_dict()
    ) == result.certification
    assert CandidateAssessmentReceiptV1.from_json_dict(
        result.candidate_assessment.to_json_dict()
    ) == result.candidate_assessment
