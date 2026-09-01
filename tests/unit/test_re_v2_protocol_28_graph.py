from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_28.graph import (
    AcceptedExhaustiveSliceV1,
    ExhaustiveVerificationReceiptV1,
    Protocol28ClosureIntegrityError,
    Protocol28GraphError,
    build_l4_semantic_closure,
    build_run_root,
    build_target_root,
)
from harness.re_v2.protocol_28.planning import realize_slice
from tests.re_v2_protocol_28_fixtures import digest
from tests.unit.test_re_v2_protocol_28_planning import _plan


def _accepted_fixture():  # type: ignore[no-untyped-def]
    plan, _, _ = _plan()
    target_plan = plan.target_plans[0]
    accepted: list[AcceptedExhaustiveSliceV1] = []
    verifiers: list[ExhaustiveVerificationReceiptV1] = []
    for index, entry in enumerate(target_plan.entries):
        spec = realize_slice(entry, {})
        item = AcceptedExhaustiveSliceV1(
            schema_version=1,
            plan_entry_id=entry.identity,
            slice_spec_id=spec.identity,
            output_artifact_key_id=spec.output_artifact_key_id,
            candidate_hash=digest(f"candidate-{index}"),
            producer_execution_capture_hash=digest(f"producer-{index}"),
            verifier_result_hash=digest(f"verifier-result-{index}"),
            verifier_execution_capture_hash=digest(f"verifier-capture-{index}"),
            certification_receipt_hash=digest(f"certification-{index}"),
            acceptance_receipt_hash=digest(f"acceptance-{index}"),
            addressed_finding_ids=entry.assigned_finding_ids,
            verdict="PASS",
        )
        accepted.append(item)
        verifiers.append(
            ExhaustiveVerificationReceiptV1(
                schema_version=1,
                accepted_slice_id=item.identity,
                plan_entry_id=entry.identity,
                verifier_result_hash=item.verifier_result_hash,
                verifier_execution_capture_hash=item.verifier_execution_capture_hash,
                assessed_finding_ids=item.addressed_finding_ids,
                verdict="PASS",
            )
        )
    return plan, target_plan, tuple(accepted), tuple(verifiers)


@pytest.mark.unit
def test_target_root_rejects_one_missing_plan_entry() -> None:
    """A percentage or near-complete accepted set can never create L4 authority."""
    _, target_plan, accepted, _ = _accepted_fixture()

    with pytest.raises(Protocol28GraphError, match="exact plan closure"):
        build_target_root(target_plan, accepted[:-1])


@pytest.mark.unit
def test_target_root_rejects_slice_with_mismatched_finding_assignment() -> None:
    _, target_plan, accepted, _ = _accepted_fixture()
    tampered = replace(accepted[0], addressed_finding_ids=(digest("extra-finding"),))

    with pytest.raises(Protocol28GraphError, match="finding assignment"):
        build_target_root(target_plan, (tampered, *accepted[1:]))


@pytest.mark.unit
def test_target_root_canonicalizes_accepted_input_order() -> None:
    _plan_value, target_plan, accepted, _verifiers = _accepted_fixture()
    second_entry = replace(target_plan.entries[0], category_id="security")
    target_plan = replace(
        target_plan,
        entries=tuple(
            sorted(
                (*target_plan.entries, second_entry),
                key=lambda item: (item.category_id, item.ordinal),
            )
        ),
    )
    second_spec = realize_slice(second_entry, {})
    second = replace(
        accepted[0],
        plan_entry_id=second_entry.identity,
        slice_spec_id=second_spec.identity,
        output_artifact_key_id=second_spec.output_artifact_key_id,
        candidate_hash=digest("second-candidate"),
        producer_execution_capture_hash=digest("second-producer"),
        verifier_result_hash=digest("second-verifier-result"),
        verifier_execution_capture_hash=digest("second-verifier-capture"),
        certification_receipt_hash=digest("second-certification"),
        acceptance_receipt_hash=digest("second-acceptance"),
    )
    accepted = tuple(
        sorted((*accepted, second), key=lambda item: item.plan_entry_id)
    )

    canonical = build_target_root(target_plan, accepted)
    reordered = build_target_root(target_plan, tuple(reversed(accepted)))

    assert reordered == canonical


@pytest.mark.unit
def test_run_root_requires_exact_target_root_set() -> None:
    plan, target_plan, accepted, _ = _accepted_fixture()
    target_root = build_target_root(target_plan, accepted)

    with pytest.raises(Protocol28GraphError, match="exact target root closure"):
        build_run_root(plan, (), (), "selected-scope")

    root = build_run_root(plan, (target_root,), (), "selected-scope")
    assert root.target_root_ids == (target_root.identity,)


@pytest.mark.unit
def test_run_root_rejects_mutated_target_authority_and_selection_scope() -> None:
    plan, target_plan, accepted, _ = _accepted_fixture()
    target_root = build_target_root(target_plan, accepted)

    with pytest.raises(Protocol28GraphError, match="authenticate its plan"):
        build_run_root(
            plan,
            (replace(target_root, target_l3_projection_id=digest("wrong-l3")),),
            (),
            "selected-scope",
        )
    with pytest.raises(Protocol28GraphError, match="completion scope"):
        build_run_root(plan, (target_root,), (), "all-scope")


@pytest.mark.unit
def test_closure_missing_verifier_is_integrity_failure() -> None:
    plan, target_plan, accepted, _ = _accepted_fixture()
    target_root = build_target_root(target_plan, accepted)
    run_root = build_run_root(plan, (target_root,), (), "selected-scope")
    _, _, parent, _, _ = _plan_authorities()

    with pytest.raises(Protocol28ClosureIntegrityError) as raised:
        build_l4_semantic_closure(parent, run_root, accepted, verifier_receipts=())

    assert raised.value.reason_code == "closure_verifier_receipt_missing"


@pytest.mark.unit
def test_zero_provider_closure_authenticates_all_verifiers() -> None:
    plan, target_plan, accepted, verifiers = _accepted_fixture()
    target_root = build_target_root(target_plan, accepted)
    run_root = build_run_root(plan, (target_root,), (), "selected-scope")
    _, _, parent, _, _ = _plan_authorities()

    closure = build_l4_semantic_closure(parent, run_root, accepted, verifiers)

    assert closure.l4_run_root_id == run_root.identity
    assert closure.verification_receipt_ids == tuple(sorted(item.identity for item in verifiers))


@pytest.mark.unit
def test_closure_rejects_mutated_verifier_receipt() -> None:
    plan, target_plan, accepted, verifiers = _accepted_fixture()
    target_root = build_target_root(target_plan, accepted)
    run_root = build_run_root(plan, (target_root,), (), "selected-scope")
    _, _, parent, _, _ = _plan_authorities()
    corrupted = replace(verifiers[0], verifier_result_hash=digest("wrong-verifier"))

    with pytest.raises(Protocol28ClosureIntegrityError) as raised:
        build_l4_semantic_closure(parent, run_root, accepted, (corrupted, *verifiers[1:]))

    assert raised.value.reason_code == "closure_verifier_receipt_mismatch"


def _plan_authorities():  # type: ignore[no-untyped-def]
    # Keep the graph fixture tied to the same authenticated authority builder.
    from tests.unit.test_re_v2_protocol_28_planning import _authorities

    return _authorities()
