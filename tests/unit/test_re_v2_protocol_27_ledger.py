from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ReV2LedgerError
from tests.re_v2_protocol_27_fixtures import digest
from tests.unit.test_re_v2_protocol_27_runtime import _runtime_case


def _certified_case(tmp_path: Path, source_id: str = "api"):
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    inputs, item, context, candidate, runtime = _runtime_case(tmp_path, source_id)
    result = runtime.certify_candidate(
        item,
        context,
        canonical_json_bytes(candidate.to_json_dict()),
    )
    return inputs, item, result, Protocol27Ledger(inputs)


@pytest.mark.unit
def test_ledger_requires_assessment_then_certification_then_acceptance(
    tmp_path: Path,
) -> None:
    inputs, item, result, ledger = _certified_case(tmp_path)

    with pytest.raises(ReV2LedgerError, match="certification"):
        ledger.record_synthesis_acceptance(result.acceptance)
    with pytest.raises(ReV2LedgerError, match="assessment"):
        ledger.record_synthesis_certification(result.certification)

    assessment_record = ledger.record_candidate_assessment(result.assessment)
    certification_record = ledger.record_synthesis_certification(result.certification)
    acceptance_record = ledger.record_synthesis_acceptance(result.acceptance)
    view = ledger.replay()

    assert view.candidate_assessments[item.work_item_id] == result.assessment
    assert view.certifications[item.output_key.artifact_key_id] == result.certification
    assert view.accepted_artifacts[item.output_key.artifact_key_id] == result.acceptance
    assert assessment_record.seq < certification_record.seq < acceptance_record.seq
    assert ledger.object_store.read_blob(result.acceptance.artifact_hash) == result.artifact_bytes


@pytest.mark.unit
def test_ledger_identical_append_is_idempotent_and_conflict_fails(
    tmp_path: Path,
) -> None:
    _inputs, item, result, ledger = _certified_case(tmp_path)
    first = ledger.record_candidate_assessment(result.assessment)

    assert ledger.record_candidate_assessment(result.assessment) == first
    conflict = replace(result.assessment, candidate_hash=digest("conflict"))
    with pytest.raises(ReV2LedgerError, match="conflicting.*assessment"):
        ledger.record_candidate_assessment(conflict)
    assert len(ledger.replay_with_history()[0]) == 1
    assert item.work_item_id in ledger.replay().candidate_assessments


@pytest.mark.unit
def test_ledger_rejects_downstream_acceptance_before_generated_dependencies(
    tmp_path: Path,
) -> None:
    _inputs, item, result, ledger = _certified_case(tmp_path)
    missing_key = digest("missing-generated-key")
    missing_hash = ledger.object_store.put_blob(b"missing-generated-artifact")
    downstream_key = replace(
        result.acceptance.artifact_key,
        artifact_dependencies=(
            *result.acceptance.artifact_key.artifact_dependencies,
            type(result.acceptance.artifact_key.artifact_dependencies[0])(
                missing_key,
                missing_hash,
            ),
        ),
    )
    downstream_item = replace(
        item,
        output_key=downstream_key,
        dependency_key_ids=tuple(
            sorted(
                dependency.artifact_key_id
                for dependency in downstream_key.artifact_dependencies
            )
        ),
    )
    downstream_assessment = replace(
        result.assessment,
        candidate_hash=digest("downstream-candidate"),
        work_item_id=downstream_item.work_item_id,
    )
    downstream_certification = replace(
        result.certification,
        artifact_key_id=downstream_key.artifact_key_id,
        candidate_hash=downstream_assessment.candidate_hash,
        work_item_id=downstream_item.work_item_id,
    )
    downstream = replace(
        result.acceptance,
        artifact_key=downstream_key,
        certification_id=downstream_certification.identity,
        work_item_id=downstream_item.work_item_id,
    )
    ledger.record_candidate_assessment(downstream_assessment)
    ledger.record_synthesis_certification(downstream_certification)

    with pytest.raises(ReV2LedgerError, match="graph authority"):
        ledger.record_synthesis_acceptance(downstream)


@pytest.mark.unit
def test_partial_acceptance_receipt_is_exact_and_source_keyed(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger
    from tests.unit.test_re_v2_protocol_27_context import _validated_inputs

    inputs = _validated_inputs(tmp_path)
    ledger = Protocol27Ledger(inputs)
    receipt = inputs.manifest.partial_acceptances[0]

    first = ledger.record_partial_acceptance(receipt)

    assert ledger.record_partial_acceptance(receipt) == first
    assert ledger.replay().partial_acceptances[receipt.source_id] == receipt


@pytest.mark.unit
def test_certification_must_use_frozen_graph_verifier_authority(tmp_path: Path) -> None:
    _inputs, _item, result, ledger = _certified_case(tmp_path)
    ledger.record_candidate_assessment(result.assessment)
    changed = replace(
        result.certification,
        verifier_authority_hash=digest("invented-verifier"),
    )

    with pytest.raises(ReV2LedgerError, match="verifier authority"):
        ledger.record_synthesis_certification(changed)


@pytest.mark.unit
def test_materialization_and_publication_records_require_prior_authority(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.ledger import (
        Protocol27Ledger,
        SynthesisMaterializationReceiptV1,
    )
    from tests.re_v2_protocol_27_fixtures import publication_descriptor_v1
    from tests.unit.test_re_v2_protocol_27_context import _validated_inputs

    inputs = _validated_inputs(tmp_path)
    ledger = Protocol27Ledger(inputs)

    with pytest.raises(ReV2LedgerError, match="synthesis root"):
        ledger.record_materialization(
            SynthesisMaterializationReceiptV1(
                1,
                digest("root"),
                digest("materialization"),
            )
        )
    with pytest.raises(ReV2LedgerError, match="materialization"):
        ledger.record_publication(
            replace(publication_descriptor_v1(), run_id=inputs.manifest.run_id)
        )
