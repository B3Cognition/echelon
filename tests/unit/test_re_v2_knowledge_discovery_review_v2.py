from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import (
    KnowledgeDispatchAccount,
    KnowledgeDispatchPolicy,
)
from harness.re_v2.knowledge_discovery import DiscoveryBoundary
from harness.re_v2.knowledge_acquisition import DiscoveryAcquisition
from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.knowledge_discovery_review import (
    DiscoveryReviewAdmissionError,
    DiscoveryReviewBoundary,
)
from harness.re_v2.knowledge_dispatch import (
    DiscoveryController,
    ProviderReply,
)
from harness.re_v2.knowledge_review_dispatch import DiscoveryReviewController
from harness.re_v2.protocol_22.provider import DispatchReservationV1, NormalizedUsageV1
from harness.re_v2.run_store import ReV2Paths
from tests.unit.test_re_v2_knowledge_acquisition import _phase_setup
from tests.unit.test_re_v2_knowledge_discovery import (
    ORIGIN,
    _proposal as legacy_proposal,
    _request as evidence_request,
)
from tests.unit.test_re_v2_knowledge_discovery_review import _review as legacy_review
from tests.unit.test_re_v2_knowledge_discovery_review import (
    _proposal as legacy_review_proposal,
)
from tests.unit.test_re_v2_knowledge_discovery_review import _setup as legacy_setup
from tests.unit.test_re_v2_knowledge_discovery_v2 import (
    EXPECTED_DEPTH_MATRIX,
    _application_proposal,
    _empty_repository_setup,
    _empty_source_proposal,
    _projection_ids,
    _setup,
)
from tests.unit.test_re_v2_knowledge_dispatch import _contract
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


RESERVATION = DispatchReservationV1(100_000, 100_000, 10_000)


def _review_v2(context: dict, *, verdict: str = "ready") -> dict:
    candidate = context["candidate"]
    return {
        "schema_version": 2,
        "kind": "discovery_review",
        "proposal_id": context["candidate_id"],
        "verdict": verdict,
        "domains": [
            {
                "key": row["key"],
                "verdict": "supported",
                "rationale": "The supplied safe evidence supports this domain.",
                "evidence_ids": row["evidence_ids"],
            }
            for row in candidate["domains"]
        ],
        "subjects": [
            {
                "key": row["key"],
                "verdict": "supported",
                "rationale": "The supplied safe evidence supports this subject.",
                "evidence_ids": row["evidence_ids"],
            }
            for row in candidate["subjects"]
        ],
        "inventory": [
            {
                "path": row["path"],
                "owner": row["owner"],
                "disposition": "owned" if row["owner"] is not None else "needs-assignment",
                "rationale": (
                    "The owner is supported by same-path evidence."
                    if row["owner"] is not None else "This path still needs assignment."
                ),
                "evidence_ids": (
                    next(
                        subject["evidence_ids"] for subject in candidate["subjects"]
                        if subject["key"] == row["owner"]
                    )
                    if row["owner"] is not None else []
                ),
            }
            for row in candidate["inventory"]
        ],
        "overlaps": [],
        "obligations": [
            {
                "target": row["target"],
                "category": row["category"],
                "disposition": row["disposition"],
                "subject_keys": row["subject_keys"],
                "verdict": "supported",
                "rationale": "The category assessment is supported within the frozen scope.",
                "evidence_ids": row["evidence_ids"],
            }
            for row in candidate["obligations"]
        ],
        "findings": [],
    }


def _admitted_v2(tmp_path: Path, *, unknown: bool = False):
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
    )
    proposal = _application_proposal(context)
    if unknown:
        category = "boundaries-integrations-protocols-dependencies"
        runner = next(row for row in proposal["subjects"] if row["key"] == "runner")
        runner["category_ids"].remove(category)
        row = next(
            row for row in proposal["obligations"]
            if row["target"] == "execution" and row["category"] == category
        )
        row.update(
            disposition="unknown",
            subject_keys=[],
            rationale="The dynamic integration remains unresolved in supplied evidence.",
        )
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    reviewer = DiscoveryReviewBoundary(boundary)
    review_context_bytes = reviewer.provider_bytes(binding_id, proposal_receipt_id)
    review_context = json.loads(review_context_bytes)
    return (
        boundary, reviewer, binding_id, proposal_receipt_id,
        review_context_bytes, review_context, objects,
    )


@pytest.mark.unit
def test_schema_2_review_records_exact_category_rows_unknowns_and_context_roots(
    tmp_path: Path,
) -> None:
    """Dropping category rows or roots must make reviewed discovery non-authoritative."""
    (
        _boundary, reviewer, binding_id, proposal_receipt_id,
        context_bytes, context, objects,
    ) = _admitted_v2(tmp_path, unknown=True)
    response = _review_v2(context)

    receipt_id = reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(response)
    )
    receipt = reviewer.read_review(binding_id, proposal_receipt_id, receipt_id)
    normalized = json.loads(objects.read_blob(receipt["review_id"]))

    assert receipt["outcome"] == "ready_for_planning"
    assert receipt["analysis_certified"] is False
    assert normalized["schema_version"] == 2
    assert normalized["proposal_id"] == context["candidate_id"]
    assert normalized["safe_context_id"] == content_digest(
        canonical_json_bytes(context["safe_discovery_context"])
    )
    assert receipt["reviewer_context_id"] == content_digest(context_bytes)
    assert len(normalized["obligations"]) == len(context["candidate"]["obligations"])
    unknown_ids = {
        row["obligation_id"] for row in context["candidate"]["obligations"]
        if row["disposition"] == "unknown"
    }
    assert set(normalized["unknown_obligation_ids"]) == unknown_ids
    assert all(row["row_id"].startswith("sha256:") for row in normalized["obligations"])


@pytest.mark.unit
@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
def test_schema_2_review_provider_receives_the_exact_canonical_depth_matrix(
    tmp_path: Path, depth: str
) -> None:
    """Actual producer and reviewer dispatches receive one literal canonical matrix."""
    from harness.re_v2.knowledge_discovery import category_depth_applicability

    files = {
        "app.py": "def run(): return work()\n",
        "worker.py": "def work(): return 1\n",
    }
    snapshot, partition = _fixture(tmp_path, files)
    paths = ReV2Paths.for_run(tmp_path / "re-test")
    paths.root.mkdir(parents=True)
    objects = ObjectStore(paths.objects)
    boundary = DiscoveryBoundary(
        snapshot,
        partition,
        "api",
        depth,
        ORIGIN,
        objects,
        ObjectStore(tmp_path / "quarantine"),
    )
    binding_id = boundary.prepare(tuple(
        EvidenceSelectorV1("api", path, 0, len(payload.encode("utf-8")))
        for path, payload in sorted(files.items())
    ))
    phase = DiscoveryAcquisition(paths, boundary, binding_id)
    account = KnowledgeDispatchAccount(
        paths,
        KnowledgeDispatchPolicy(500_000, 100_000, 3),
        _contract(),
        boundary.run_authority(),
    )
    calls = []

    def produce(_agent, context_bytes, _reservation):
        context = json.loads(context_bytes)
        calls.append(context)
        return ProviderReply(
            canonical_json_bytes(_application_proposal(context, depth=depth)),
            NormalizedUsageV1("unavailable", None, {}),
        )

    produce.contract_id = account.opening["provider_contract_id"]
    producer = DiscoveryController(
        phase, account, b"schema-2 discovery role", produce, RESERVATION
    )

    def review(_agent, context_bytes, _reservation):
        context = json.loads(context_bytes)
        calls.append(context)
        return ProviderReply(
            canonical_json_bytes(_review_v2(context)),
            NormalizedUsageV1("unavailable", None, {}),
        )

    review.contract_id = account.opening["provider_contract_id"]
    assert producer.step().state == "proposal_ready"
    assert DiscoveryReviewController(
        producer, b"schema-2 independent review role", review, RESERVATION
    ).step().state == "review_ready"

    assert calls[0]["category_depth_applicability"] == EXPECTED_DEPTH_MATRIX
    supplied = calls[1]["safe_discovery_context"]["category_depth_applicability"]
    assert supplied == EXPECTED_DEPTH_MATRIX == category_depth_applicability()


@pytest.mark.unit
@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
@pytest.mark.parametrize("inventory_kind", ["empty-inventory", "zero-byte-file"])
def test_schema_2_authenticated_empty_source_reaches_ready_review(
    tmp_path: Path, depth: str, inventory_kind: str
) -> None:
    """Review independently accepts the exact empty-source depth complement."""
    if inventory_kind == "empty-inventory":
        boundary, binding_id, context, objects = _empty_repository_setup(
            tmp_path, depth=depth
        )
    else:
        boundary, binding_id, context, objects = _setup(
            tmp_path, {"empty.txt": ""}, depth=depth
        )
    proposal_receipt_id = boundary.admit(
        binding_id,
        canonical_json_bytes(_empty_source_proposal(context, depth=depth)),
        capture_bound=True,
    )
    reviewer = DiscoveryReviewBoundary(boundary)
    review_context = json.loads(reviewer.provider_bytes(binding_id, proposal_receipt_id))

    response = _review_v2(review_context)
    for row in response["inventory"]:
        row.update(
            disposition="excluded",
            rationale="The authenticated inventory records a zero-byte file.",
            evidence_ids=[],
        )
    receipt_id = reviewer.admit(
        binding_id,
        proposal_receipt_id,
        canonical_json_bytes(response),
    )

    assert reviewer.read_review(binding_id, proposal_receipt_id, receipt_id)["outcome"] == (
        "ready_for_planning"
    )


@pytest.mark.unit
def test_schema_2_review_rejects_cross_target_evidence_added_to_unknown(
    tmp_path: Path,
) -> None:
    """Fresh review rechecks every unknown citation, not merely one candidate match."""
    (
        _boundary, reviewer, binding_id, proposal_receipt_id,
        _context_bytes, context, objects,
    ) = _admitted_v2(tmp_path, unknown=True)
    response = _review_v2(context)
    row = next(
        item for item in response["obligations"]
        if item["target"] == "execution"
        and item["category"] == "boundaries-integrations-protocols-dependencies"
    )
    row["evidence_ids"].append(
        _projection_ids(context["safe_discovery_context"])["worker.py"]
    )
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    with pytest.raises(
        DiscoveryReviewAdmissionError,
        match="unsupported-discovery-review-obligation",
    ):
        reviewer.admit(binding_id, proposal_receipt_id, canonical_json_bytes(response))

    assert {path for path in objects.root.rglob("*") if path.is_file()} == before


@pytest.mark.unit
def test_schema_2_review_accepts_source_local_withheld_unknown_boundary(
    tmp_path: Path,
) -> None:
    """The review recheck preserves legitimate authenticated withholding."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {
            ".env": "PASSWORD=fixture-only\n",
            "app.py": "def run(): return work()\n",
            "worker.py": "def work(): return 1\n",
        },
    )
    proposal = _application_proposal(context)
    proposal["inventory"].append({
        "path": ".env", "owner": None, "reason": "Credential path is withheld."
    })
    category = "cross-domain-boundaries"
    worker = next(row for row in proposal["subjects"] if row["key"] == "worker")
    worker["category_ids"].remove(category)
    row = next(
        item for item in proposal["obligations"]
        if item["target"] == "source" and item["category"] == category
    )
    row.update(
        disposition="unknown",
        subject_keys=[],
        evidence_ids=[_projection_ids(context)[".env"]],
    )
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    reviewer = DiscoveryReviewBoundary(boundary)
    review_context = json.loads(reviewer.provider_bytes(binding_id, proposal_receipt_id))

    response = _review_v2(review_context)
    withheld_id = _projection_ids(context)[".env"]
    excluded = next(item for item in response["inventory"] if item["path"] == ".env")
    excluded.update(
        disposition="excluded",
        rationale="The exact credential path is deterministically excluded.",
        evidence_ids=[withheld_id],
    )
    receipt_id = reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(response)
    )

    assert json.loads(objects.read_blob(receipt_id))["outcome"] == "ready_for_planning"


@pytest.mark.unit
def test_schema_2_review_row_order_does_not_change_normalized_identity(tmp_path: Path) -> None:
    """Reviewer row order must not alter the normalized category certification."""
    (
        _boundary, reviewer, binding_id, proposal_receipt_id,
        _context_bytes, context, objects,
    ) = _admitted_v2(tmp_path)
    first = json.loads(objects.read_blob(reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(_review_v2(context))
    )))
    reordered = _review_v2(context)
    for field in ("domains", "subjects", "inventory", "overlaps", "obligations"):
        reordered[field].reverse()
    second = json.loads(objects.read_blob(reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(reordered)
    )))

    assert first["authorial_response_id"] != second["authorial_response_id"]
    assert first["review_id"] == second["review_id"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [
        "missing-row",
        "duplicate-row",
        "altered-disposition",
        "altered-membership",
        "missing-evidence",
        "obligation-revise",
    ],
)
def test_schema_2_false_ready_or_edited_category_rows_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    """A ready label must not override exact candidate membership or evidence gaps."""
    (
        _boundary, reviewer, binding_id, proposal_receipt_id,
        _context_bytes, context, objects,
    ) = _admitted_v2(tmp_path)
    response = _review_v2(context)
    row = next(
        item for item in response["obligations"]
        if item["target"] == "execution" and item["category"] == "negative-space"
    )
    if mutation == "missing-row":
        response["obligations"].remove(row)
    elif mutation == "duplicate-row":
        response["obligations"].append(dict(row))
    elif mutation == "altered-disposition":
        row["disposition"] = "not-applicable"
    elif mutation == "altered-membership":
        row["subject_keys"] = ["runner"]
    elif mutation == "missing-evidence":
        row["evidence_ids"] = []
    else:
        row["verdict"] = "revise"
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    with pytest.raises(DiscoveryReviewAdmissionError):
        reviewer.admit(binding_id, proposal_receipt_id, canonical_json_bytes(response))

    assert {path for path in objects.root.rglob("*") if path.is_file()} == before


@pytest.mark.unit
def test_schema_2_false_ready_rejects_unsupported_not_applicable(tmp_path: Path) -> None:
    """Not-applicable needs a fresh reviewer judgment grounded in visible scoped evidence."""
    (
        boundary, _reviewer, binding_id, _proposal_receipt_id,
        _context_bytes, context, objects,
    ) = _admitted_v2(tmp_path)
    proposal = _application_proposal(context["safe_discovery_context"])
    worker = next(row for row in proposal["subjects"] if row["key"] == "worker")
    worker["category_ids"].remove("cross-domain-boundaries")
    row = next(
        item for item in proposal["obligations"]
        if item["target"] == "source" and item["category"] == "cross-domain-boundaries"
    )
    row.update(disposition="not-applicable", subject_keys=[])
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    reviewer = DiscoveryReviewBoundary(boundary)
    review_context = json.loads(reviewer.provider_bytes(binding_id, proposal_receipt_id))
    response = _review_v2(review_context)
    reviewed_row = next(
        item for item in response["obligations"]
        if item["target"] == "source" and item["category"] == "cross-domain-boundaries"
    )
    reviewed_row["evidence_ids"] = []
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    with pytest.raises(DiscoveryReviewAdmissionError):
        reviewer.admit(binding_id, proposal_receipt_id, canonical_json_bytes(response))

    assert {path for path in objects.root.rglob("*") if path.is_file()} == before


@pytest.mark.unit
def test_schema_2_false_ready_rejects_unresolved_inventory_ownership(tmp_path: Path) -> None:
    """A complete category table cannot hide unassigned analyzable inventory."""
    (
        boundary, _reviewer, binding_id, _proposal_receipt_id,
        _context_bytes, context, _objects,
    ) = _admitted_v2(tmp_path)
    proposal = _application_proposal(context["safe_discovery_context"])
    proposal["inventory"][1]["owner"] = None
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    reviewer = DiscoveryReviewBoundary(boundary)
    review_context = json.loads(reviewer.provider_bytes(binding_id, proposal_receipt_id))
    response = _review_v2(review_context)

    with pytest.raises(DiscoveryReviewAdmissionError, match="false-ready"):
        reviewer.admit(binding_id, proposal_receipt_id, canonical_json_bytes(response))


@pytest.mark.unit
@pytest.mark.parametrize("response_version", [1, 2])
def test_review_schema_version_must_match_the_exact_candidate_contract(
    tmp_path: Path, response_version: int
) -> None:
    """Schema numbers must never be treated as additive feature flags."""
    if response_version == 1:
        (
            _boundary, reviewer, binding_id, proposal_receipt_id,
            _context_bytes, context, _objects,
        ) = _admitted_v2(tmp_path)
        response = _review_v2(context)
        response["schema_version"] = 1
    else:
        boundary, binding_id, context, objects, _quarantine = legacy_setup(tmp_path)
        proposal_receipt_id = boundary.admit(
            binding_id, canonical_json_bytes(legacy_proposal(context)), capture_bound=True
        )
        reviewer = DiscoveryReviewBoundary(boundary)
        review_context = json.loads(reviewer.provider_bytes(binding_id, proposal_receipt_id))
        proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
        response = legacy_review(context, proposal_id)
        response["schema_version"] = 2
        response["obligations"] = []

    with pytest.raises(DiscoveryReviewAdmissionError):
        reviewer.admit(binding_id, proposal_receipt_id, canonical_json_bytes(response))


@pytest.mark.unit
def test_schema_1_review_receipt_and_normalized_object_remain_unchanged(tmp_path: Path) -> None:
    """Adding schema 2 must not rewrite readable historical review authority."""
    boundary, binding_id, context, objects, _quarantine = legacy_setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(legacy_review_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    reviewer = DiscoveryReviewBoundary(boundary)

    receipt_id = reviewer.admit(
        binding_id,
        proposal_receipt_id,
        canonical_json_bytes(legacy_review(context, proposal_id)),
    )
    receipt = reviewer.read_review(binding_id, proposal_receipt_id, receipt_id)
    normalized = json.loads(objects.read_blob(receipt["review_id"]))

    assert receipt["schema_version"] == 1
    assert set(receipt) == {
        "schema_version", "state", "binding_id", "proposal_receipt_id",
        "proposal_id", "review_id", "authorial_response_id", "reviewer_context_id",
        "outcome", "execution_certification_required", "analysis_certified", "findings",
    }
    assert normalized["schema_version"] == 1
    assert "obligations" not in normalized
    assert "safe_context_id" not in normalized


@pytest.mark.unit
def test_schema_2_review_is_a_separate_shared_account_invocation_without_reasoning(
    tmp_path: Path,
) -> None:
    """Review must consume a separate turn and receive no producer transcript."""
    phase, paths, boundary, binding, _objects, _quarantine = _phase_setup(tmp_path)
    batch_id = boundary.admit(binding, canonical_json_bytes(evidence_request()))
    phase.resolve(binding, batch_id)
    account = KnowledgeDispatchAccount(
        paths,
        KnowledgeDispatchPolicy(500_000, 100_000, 3),
        _contract(),
        boundary.run_authority(),
    )
    calls: list[tuple[str, dict]] = []

    def produce(_agent: bytes, context_bytes: bytes, _reservation: DispatchReservationV1):
        context = json.loads(context_bytes)
        calls.append(("producer", context))
        return ProviderReply(
            canonical_json_bytes(_application_proposal(context)),
            NormalizedUsageV1("unavailable", None, {}),
        )

    produce.contract_id = account.opening["provider_contract_id"]
    producer = DiscoveryController(
        phase, account, b"schema-2 discovery role", produce, RESERVATION
    )
    assert producer.step().state == "proposal_ready"

    def review(_agent: bytes, context_bytes: bytes, _reservation: DispatchReservationV1):
        context = json.loads(context_bytes)
        calls.append(("reviewer", context))
        return ProviderReply(
            canonical_json_bytes(_review_v2(context)),
            NormalizedUsageV1("unavailable", None, {}),
        )

    review.contract_id = account.opening["provider_contract_id"]
    result = DiscoveryReviewController(
        producer, b"schema-2 independent review role", review, RESERVATION
    ).step()

    assert result.state == "review_ready"
    assert [kind for kind, _context in calls] == ["producer", "reviewer"]
    reviewer_context = calls[1][1]
    assert reviewer_context["candidate"]["schema_version"] == 2
    assert "producer_reasoning" not in reviewer_context
    assert "authorial_response_id" not in reviewer_context
    assert account.status().charged_tokens == 200_000
