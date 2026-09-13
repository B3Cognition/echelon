from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import DiscoveryBoundary, DiscoveryError
from harness.re_v2.knowledge_discovery_review import (
    DiscoveryReviewAdmissionError,
    DiscoveryReviewBoundary,
    DiscoveryReviewError,
    DiscoveryReviewStorageError,
)
from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.policies import DOMAIN_CATEGORIES, SOURCE_CATEGORIES
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


ORIGIN = "sha256:" + "a" * 64


def _stored_files(objects: ObjectStore) -> set[Path]:
    return {path for path in objects.root.rglob("*") if path.is_file()}


def _setup(tmp_path: Path, files: dict[str, str | bytes] | None = None):
    files = files or {
        "app.py": "def run():\n    return retry()\n",
        "worker.py": "def retry():\n    return False\n",
    }
    snapshot, partition = _fixture(tmp_path, files)
    objects = ObjectStore(tmp_path / "objects")
    quarantine = ObjectStore(tmp_path / "quarantine")
    boundary = DiscoveryBoundary(
        snapshot, partition, "api", "standard", ORIGIN, objects, quarantine
    )
    selectors = tuple(
        EvidenceSelectorV1("api", path, 0, len(payload.encode("utf-8")))
        for path, payload in sorted(files.items())
        if isinstance(payload, str)
    )
    binding_id = boundary.prepare(selectors)
    context = json.loads(boundary.provider_bytes(binding_id))
    return boundary, binding_id, context, objects, quarantine


def _proposal(context: dict) -> dict:
    by_path = {
        row["projection"]["path"]: row["projection_id"]
        for row in context["evidence"]
    }
    app_id = by_path["app.py"]
    worker_id = by_path["worker.py"]
    return {
        "schema_version": 1,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [
            {
                "key": "execution",
                "description": "Command execution",
                "evidence_ids": [app_id],
            }
        ],
        "subjects": [
            {
                "key": "runner",
                "target": "execution",
                "description": "Run entry point",
                "evidence_ids": [app_id, worker_id],
            },
            {
                "key": "retry",
                "target": "execution",
                "description": "Retry behavior",
                "evidence_ids": [worker_id],
            },
        ],
        "inventory": [
            {"path": "app.py", "owner": "runner", "reason": "Run implementation"},
            {"path": "worker.py", "owner": "retry", "reason": "Retry implementation"},
        ],
        "obligations": [
            *(
                {"target": "source", "category": category}
                for category in SOURCE_CATEGORIES
            ),
            *(
                {"target": "execution", "category": category}
                for category in DOMAIN_CATEGORIES
            ),
        ],
        "questions": [
            {
                "target": "source",
                "question": "What invokes the runner?",
                "evidence_ids": [],
            }
        ],
    }


def _review(context: dict, proposal_id: str, *, verdict: str = "ready") -> dict:
    by_path = {
        row["projection"]["path"]: row["projection_id"]
        for row in context["evidence"]
    }
    app_id = by_path["app.py"]
    worker_id = by_path["worker.py"]
    return {
        "schema_version": 1,
        "kind": "discovery_review",
        "proposal_id": proposal_id,
        "verdict": verdict,
        "domains": [
            {
                "key": "execution",
                "verdict": "supported",
                "rationale": "The entry point supports command execution.",
                "evidence_ids": [app_id],
            }
        ],
        "subjects": [
            {
                "key": "runner",
                "verdict": "supported",
                "rationale": "The runner is visible in the supplied implementation.",
                "evidence_ids": [app_id],
            },
            {
                "key": "retry",
                "verdict": "supported",
                "rationale": "The retry behavior is visible in the worker.",
                "evidence_ids": [worker_id],
            },
        ],
        "inventory": [
            {
                "path": "app.py",
                "owner": "runner",
                "disposition": "owned",
                "rationale": "The runner owns the entry point.",
                "evidence_ids": [app_id],
            },
            {
                "path": "worker.py",
                "owner": "retry",
                "disposition": "owned",
                "rationale": "The retry subject owns the worker.",
                "evidence_ids": [worker_id],
            },
        ],
        "overlaps": [
            {
                "subject_keys": ["retry", "runner"],
                "disposition": "shared-evidence",
                "rationale": "Both subjects use the worker evidence.",
                "evidence_ids": [worker_id],
            }
        ],
        "findings": [],
    }


def _admitted_review(tmp_path: Path):
    boundary, binding_id, context, objects, quarantine = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    reviewer = DiscoveryReviewBoundary(boundary)
    review_receipt_id = reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(review)
    )
    return (
        boundary,
        reviewer,
        binding_id,
        proposal_receipt_id,
        review_receipt_id,
        context,
        review,
        objects,
        quarantine,
    )


@pytest.mark.unit
@pytest.mark.parametrize("capture_bound", [False, True])
def test_read_proposal_authenticates_passive_and_captured_receipts_without_writes(
    tmp_path: Path, capture_bound: bool
) -> None:
    """Removing proposal replay must prevent review of an unauthenticated candidate."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal = _proposal(context)
    receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=capture_bound
    )
    before = _stored_files(objects)

    restored = boundary.read_proposal(binding_id, receipt_id)

    assert restored["kind"] == "discovery_proposal"
    assert restored["domains"][0]["key"] == "execution"
    assert restored["questions"] == proposal["questions"]
    assert _stored_files(objects) == before


@pytest.mark.unit
def test_read_proposal_rejects_a_content_addressed_forgery_and_missing_objects(
    tmp_path: Path,
) -> None:
    """A hash-addressed JSON blob must not become proposal authority by existing."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    receipt_id = boundary.admit(binding_id, canonical_json_bytes(_proposal(context)))
    receipt = json.loads(objects.read_blob(receipt_id))
    receipt["review_required"] = False
    forged_id = objects.put_blob(canonical_json_bytes(receipt))

    with pytest.raises(DiscoveryError):
        boundary.read_proposal(binding_id, forged_id)

    proposal_id = json.loads(objects.read_blob(receipt_id))["proposal_id"]
    object_path = objects.root / "sha256" / proposal_id[7:9] / proposal_id[9:]
    object_path.unlink()
    with pytest.raises(DiscoveryError, match="storage-unavailable"):
        boundary.read_proposal(binding_id, receipt_id)


@pytest.mark.unit
def test_generated_receipt_subject_key_does_not_trigger_credential_screening(
    tmp_path: Path,
) -> None:
    """Generated subject-id mappings are authority metadata, not credential values."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal = _proposal(context)
    proposal["subjects"][0]["key"] = "api-token"
    proposal["inventory"][0]["owner"] = "api-token"
    receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )

    restored = boundary.read_proposal(binding_id, receipt_id)

    assert {row["key"] for row in restored["subjects"]} == {"api-token", "retry"}
    assert json.loads(objects.read_blob(receipt_id))["subject_ids"]["api-token"].startswith(
        "sha256:"
    )


@pytest.mark.unit
def test_reviewer_context_contains_only_safe_candidate_context_and_obligations(
    tmp_path: Path,
) -> None:
    """Adding private binding data or producer output to review input leaks authority."""
    canary = "ghp_" + "C" * 36
    files = {
        "app.py": f'TOKEN="{canary}"\ndef run(): return retry()\n',
        "worker.py": "def retry(): return False\n",
    }
    boundary, binding_id, context, objects, _ = _setup(tmp_path, files)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    receipt = json.loads(objects.read_blob(proposal_receipt_id))

    payload = DiscoveryReviewBoundary(boundary).provider_bytes(
        binding_id, proposal_receipt_id
    )
    review_context = json.loads(payload)

    assert set(review_context) == {
        "schema_version",
        "kind",
        "candidate_id",
        "candidate",
        "safe_discovery_context",
        "overlap_pairs",
        "review_obligations",
    }
    assert review_context["candidate_id"] == receipt["proposal_id"]
    assert review_context["candidate"]["questions"] == _proposal(context)["questions"]
    assert review_context["candidate"]["obligations"] == sorted(
        _proposal(context)["obligations"], key=lambda row: (row["target"], row["category"])
    )
    assert review_context["safe_discovery_context"] == context
    assert review_context["overlap_pairs"] == [["retry", "runner"]]
    assert canary.encode() not in payload
    assert str(tmp_path).encode() not in payload
    assert b"mapping_ids" not in payload
    assert b"authorial_response_id" not in payload
    assert b"previous_verdict" not in payload


@pytest.mark.unit
def test_oversized_reviewer_context_fails_closed_without_writes(tmp_path: Path) -> None:
    """Truncating candidate questions would silently change the review obligation."""
    files = {
        "app.py": "x" * 60_000,
        "worker.py": "def retry(): return False\n",
    }
    boundary, binding_id, context, objects, _ = _setup(tmp_path, files)
    proposal = _proposal(context)
    proposal["questions"] = [
        {"target": "source", "question": f"{index:03d}" + "q" * 3990, "evidence_ids": []}
        for index in range(50)
    ]
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    before = _stored_files(objects)

    with pytest.raises(DiscoveryReviewError, match="context-bound"):
        DiscoveryReviewBoundary(boundary).provider_bytes(binding_id, proposal_receipt_id)

    assert _stored_files(objects) == before


@pytest.mark.unit
def test_valid_review_receipt_replays_feedback_without_certifying_execution_or_analysis(
    tmp_path: Path,
) -> None:
    """Passive admission must never be mistaken for independent execution authority."""
    (
        _, reviewer, binding_id, proposal_receipt_id, review_receipt_id,
        _, _, objects, _,
    ) = _admitted_review(tmp_path)
    before = _stored_files(objects)

    replay = DiscoveryReviewBoundary(reviewer.discovery).read_review(
        binding_id, proposal_receipt_id, review_receipt_id
    )

    assert replay["outcome"] == "ready_for_planning"
    assert replay["execution_certification_required"] is True
    assert replay["analysis_certified"] is False
    assert replay["proposal_receipt_id"] == proposal_receipt_id
    assert replay["binding_id"] == binding_id
    assert replay["findings"] == []
    assert _stored_files(objects) == before


@pytest.mark.unit
def test_reopening_keeps_findings_and_candidate_ownership(tmp_path: Path) -> None:
    """Restart replay must retain actionable feedback without editing the candidate."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal = _proposal(context)
    proposal["inventory"][1]["owner"] = None
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id, verdict="revise")
    review["inventory"][1]["owner"] = None
    review["inventory"][1]["disposition"] = "needs-assignment"
    review["inventory"][1]["evidence_ids"] = []
    review["findings"] = [{
        "target": "source",
        "reason_class": "ownership",
        "rationale": "Assign worker behavior before planning.",
        "evidence_ids": [],
    }]
    reviewer = DiscoveryReviewBoundary(boundary)
    receipt_id = reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(review)
    )

    replay = DiscoveryReviewBoundary(boundary).read_review(
        binding_id, proposal_receipt_id, receipt_id
    )
    restored = boundary.read_proposal(binding_id, proposal_receipt_id)

    assert replay["outcome"] == "revision_required"
    assert replay["findings"][0]["rationale"] == "Assign worker behavior before planning."
    assert replay["findings"][0]["finding_id"].startswith("sha256:")
    assert next(row for row in restored["inventory"] if row["path"] == "worker.py")["owner"] is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [
        "missing-inventory",
        "duplicate-inventory",
        "extra-field",
        "foreign-evidence",
        "edited-owner",
        "missing-overlap",
        "extraneous-overlap",
    ],
)
def test_invalid_review_shapes_and_foreign_authority_are_not_persisted(
    tmp_path: Path, mutation: str
) -> None:
    """Malformed reconciliation must not enter the ordinary review store."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    if mutation == "missing-inventory":
        review["inventory"].pop()
    elif mutation == "duplicate-inventory":
        review["inventory"].append(review["inventory"][0])
    elif mutation == "extra-field":
        review["budget"] = 999_999
    elif mutation == "foreign-evidence":
        review["domains"][0]["evidence_ids"] = ["sha256:" + "b" * 64]
    elif mutation == "edited-owner":
        review["inventory"][0]["owner"] = "retry"
    elif mutation == "missing-overlap":
        review["overlaps"] = []
    else:
        review["overlaps"].append({
            "subject_keys": ["runner", "runner"],
            "disposition": "conflict",
            "rationale": "A self-overlap is not a candidate pair.",
            "evidence_ids": [],
        })
    before = _stored_files(objects)

    with pytest.raises(DiscoveryReviewAdmissionError):
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )

    assert _stored_files(objects) == before


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    ["verdict-container", "key-container", "reference-container", "finding-container"],
)
def test_unhashable_authorial_values_are_admission_errors(
    tmp_path: Path, mutation: str
) -> None:
    """Malformed model containers are rejection, not replay or storage failures."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    if mutation == "verdict-container":
        review["verdict"] = []
    elif mutation == "key-container":
        review["domains"][0]["key"] = []
    elif mutation == "reference-container":
        review["subjects"][0]["evidence_ids"] = [{}]
    else:
        review["verdict"] = "revise"
        review["findings"] = [{
            "target": [], "reason_class": "ownership",
            "rationale": "Malformed target container.", "evidence_ids": [],
        }]
    before = _stored_files(objects)

    with pytest.raises(DiscoveryReviewAdmissionError):
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )

    assert _stored_files(objects) == before


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ["finding", "domain", "subject", "inventory", "overlap"])
def test_ready_verdict_cannot_hide_revision_work(tmp_path: Path, mutation: str) -> None:
    """A model-authored ready label must not override unresolved reconciliation."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    if mutation == "finding":
        review["findings"] = [{
            "target": "source", "reason_class": "evidence-gap",
            "rationale": "More evidence is required.", "evidence_ids": [],
        }]
    elif mutation == "domain":
        review["domains"][0]["verdict"] = "revise"
    elif mutation == "subject":
        review["subjects"][0]["verdict"] = "revise"
    elif mutation == "inventory":
        review["inventory"][1]["disposition"] = "unknown"
    else:
        review["overlaps"][0]["disposition"] = "conflict"

    with pytest.raises(DiscoveryReviewAdmissionError):
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )


@pytest.mark.unit
def test_revise_requires_an_actionable_finding(tmp_path: Path) -> None:
    """A bare revise label would not preserve usable repair feedback."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id, verdict="revise")

    with pytest.raises(DiscoveryReviewAdmissionError):
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )


@pytest.mark.unit
def test_supported_rows_cannot_rely_on_withheld_evidence(tmp_path: Path) -> None:
    """Withheld-only references cannot substantiate a supported review verdict."""
    files = {
        "app.py": "def run(): return 1\n",
        "worker.py": "def retry(): return False\n",
        ".env": "SECRET=opaque\n",
    }
    boundary, binding_id, context, objects, _ = _setup(tmp_path, files)
    proposal = _proposal(context)
    proposal["inventory"].append({
        "path": ".env", "owner": None, "reason": "Values are withheld"
    })
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    withheld_id = next(
        row["projection_id"] for row in context["evidence"]
        if row["projection"]["path"] == ".env"
    )
    review["domains"][0]["evidence_ids"] = [withheld_id]
    review["inventory"].append({
        "path": ".env", "owner": None, "disposition": "excluded",
        "rationale": "The path is excluded by policy.", "evidence_ids": [withheld_id],
    })

    with pytest.raises(DiscoveryReviewAdmissionError):
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )


@pytest.mark.unit
def test_partially_redacted_file_cannot_prove_non_behavioral_absence(tmp_path: Path) -> None:
    """A redacted ordinary source cannot prove that the whole file lacks behavior."""
    files = {
        "app.py": 'TOKEN="ghp_' + "R" * 36 + '"\ndef run(): return 1\n',
        "worker.py": "def retry(): return False\n",
    }
    boundary, binding_id, context, objects, _ = _setup(tmp_path, files)
    proposal = _proposal(context)
    proposal["inventory"][0]["owner"] = None
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    review["inventory"][0]["owner"] = None
    review["inventory"][0]["disposition"] = "non-behavioral"

    with pytest.raises(DiscoveryReviewAdmissionError):
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )


@pytest.mark.unit
def test_overlap_is_required_when_subject_evidence_uses_later_ranges_of_same_path(
    tmp_path: Path,
) -> None:
    """Comparing projection IDs instead of paths would miss later-range overlap."""
    files = {
        "app.py": "def run(): return 1\n",
        "worker.py": "first_behavior = True\nsecond_behavior = True\n",
    }
    snapshot, partition = _fixture(tmp_path, files)
    objects = ObjectStore(tmp_path / "objects")
    quarantine = ObjectStore(tmp_path / "quarantine")
    boundary = DiscoveryBoundary(
        snapshot, partition, "api", "standard", ORIGIN, objects, quarantine
    )
    split = files["worker.py"].index("second")
    selectors = (
        EvidenceSelectorV1("api", "app.py", 0, len(files["app.py"])),
        EvidenceSelectorV1("api", "worker.py", 0, split),
        EvidenceSelectorV1("api", "worker.py", split, len(files["worker.py"])),
    )
    binding_id = boundary.prepare(selectors)
    context = json.loads(boundary.provider_bytes(binding_id))
    worker_ids = [
        row["projection_id"] for row in context["evidence"]
        if row["projection"]["path"] == "worker.py"
    ]
    proposal = _proposal(context)
    proposal["subjects"][0]["evidence_ids"] = [
        next(row["projection_id"] for row in context["evidence"] if row["projection"]["path"] == "app.py"),
        worker_ids[0],
    ]
    proposal["subjects"][1]["evidence_ids"] = [worker_ids[1]]
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    review["subjects"][0]["evidence_ids"] = [proposal["subjects"][0]["evidence_ids"][0]]
    review["subjects"][1]["evidence_ids"] = [worker_ids[1]]
    review["inventory"][1]["evidence_ids"] = [worker_ids[1]]
    review["overlaps"][0]["evidence_ids"] = worker_ids
    review["overlaps"][0]["subject_keys"] = ["runner", "retry"]

    receipt_id = DiscoveryReviewBoundary(boundary).admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(review)
    )

    assert json.loads(objects.read_blob(receipt_id))["outcome"] == "ready_for_planning"


@pytest.mark.unit
def test_overlap_preflight_fails_at_cap_plus_one_without_writes(tmp_path: Path) -> None:
    """A quadratic subject overlap set must fail before reviewer context is returned."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal = _proposal(context)
    evidence_id = next(
        row["projection_id"] for row in context["evidence"]
        if row["projection"]["path"] == "app.py"
    )
    proposal["subjects"] = [
        {
            "key": f"subject-{index:03d}",
            "target": "execution",
            "description": "Shared behavior",
            "evidence_ids": [evidence_id],
        }
        for index in range(92)
    ]
    proposal["inventory"][0]["owner"] = "subject-000"
    proposal["inventory"][1]["owner"] = None
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    before = _stored_files(objects)

    with pytest.raises(DiscoveryReviewError, match="overlap-bound"):
        DiscoveryReviewBoundary(boundary).provider_bytes(
            binding_id, proposal_receipt_id
        )

    assert _stored_files(objects) == before


@pytest.mark.unit
def test_config_only_candidate_can_be_revised_without_inventing_a_domain(tmp_path: Path) -> None:
    """Configuration-only input must remain source work rather than a fake domain."""
    files = {"deployment.yml": "replicas: 3\n"}
    boundary, binding_id, context, objects, _ = _setup(tmp_path, files)
    proposal = {
        "schema_version": 1, "kind": "discovery_proposal", "source_id": "api",
        "domains": [], "subjects": [],
        "inventory": [{"path": "deployment.yml", "owner": None,
                       "reason": "Source-level configuration work"}],
        "obligations": [{"target": "source", "category": category}
                        for category in SOURCE_CATEGORIES],
        "questions": [],
    }
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = {
        "schema_version": 1, "kind": "discovery_review", "proposal_id": proposal_id,
        "verdict": "revise", "domains": [], "subjects": [], "overlaps": [],
        "inventory": [{"path": "deployment.yml", "owner": None,
                       "disposition": "needs-assignment",
                       "rationale": "Configuration behavior needs source-level assignment.",
                       "evidence_ids": []}],
        "findings": [{"target": "source", "reason_class": "ownership",
                      "rationale": "Keep configuration work at source scope.",
                      "evidence_ids": []}],
    }

    receipt_id = DiscoveryReviewBoundary(boundary).admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(review)
    )
    replay = DiscoveryReviewBoundary(boundary).read_review(
        binding_id, proposal_receipt_id, receipt_id
    )

    assert replay["outcome"] == "revision_required"
    assert replay["findings"][0]["target"] == "source"


@pytest.mark.unit
def test_normalized_review_row_identities_ignore_input_order(tmp_path: Path) -> None:
    """Reordering complete review rows must not change their normalized identities."""
    boundary, binding_id, context, objects, _ = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    first_review = _review(context, proposal_id)
    reviewer = DiscoveryReviewBoundary(boundary)
    first_receipt = json.loads(objects.read_blob(reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(first_review)
    )))
    reordered = _review(context, proposal_id)
    reordered["subjects"].reverse()
    reordered["inventory"].reverse()
    reordered["domains"].reverse()
    reordered["overlaps"].reverse()
    second_receipt = json.loads(objects.read_blob(reviewer.admit(
        binding_id, proposal_receipt_id, canonical_json_bytes(reordered)
    )))
    first_normalized = json.loads(objects.read_blob(first_receipt["review_id"]))
    second_normalized = json.loads(objects.read_blob(second_receipt["review_id"]))

    assert first_receipt["authorial_response_id"] != second_receipt["authorial_response_id"]
    assert first_receipt["review_id"] == second_receipt["review_id"]
    assert [row["row_id"] for row in first_normalized["subjects"]] == [
        row["row_id"] for row in second_normalized["subjects"]
    ]


@pytest.mark.unit
def test_review_replay_rejects_exact_capture_mismatch_and_corrupt_store(tmp_path: Path) -> None:
    """A normalized match cannot substitute a different exact screened capture."""
    (
        _, reviewer, binding_id, proposal_receipt_id, review_receipt_id,
        _, review, objects, _,
    ) = _admitted_review(tmp_path)
    receipt = json.loads(objects.read_blob(review_receipt_id))
    changed = json.loads(canonical_json_bytes(review))
    changed["subjects"][0]["rationale"] = "A different exact response."
    receipt["authorial_response_id"] = objects.put_blob(canonical_json_bytes(changed))
    forged_id = objects.put_blob(canonical_json_bytes(receipt))

    with pytest.raises(DiscoveryReviewError):
        reviewer.read_review(binding_id, proposal_receipt_id, forged_id)

    review_id = json.loads(objects.read_blob(review_receipt_id))["review_id"]
    object_path = objects.root / "sha256" / review_id[7:9] / review_id[9:]
    object_path.unlink()
    with pytest.raises(DiscoveryReviewStorageError, match="storage-unavailable"):
        reviewer.read_review(binding_id, proposal_receipt_id, review_receipt_id)


@pytest.mark.unit
def test_unsafe_review_is_quarantined_before_parsing_or_ordinary_persistence(
    tmp_path: Path,
) -> None:
    """Secret-bearing feedback must never enter ordinary review objects or errors."""
    boundary, binding_id, context, objects, quarantine = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = _review(context, proposal_id)
    canary = "ghp_" + "Q" * 36
    review["domains"][0]["rationale"] = canary
    before = _stored_files(objects)

    with pytest.raises(DiscoveryReviewAdmissionError) as error:
        DiscoveryReviewBoundary(boundary).admit(
            binding_id, proposal_receipt_id, canonical_json_bytes(review)
        )

    assert canary not in str(error.value)
    assert _stored_files(objects) == before
    assert any(path.is_file() for path in quarantine.root.rglob("*"))


@pytest.mark.unit
def test_normalized_review_above_context_limit_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    """Row identities must not turn an admissible capture into an unreplayable object."""
    files = {f"f/{index:04x}": "" for index in range(1600)}
    snapshot, partition = _fixture(tmp_path, files)
    objects = ObjectStore(tmp_path / "objects")
    quarantine = ObjectStore(tmp_path / "quarantine")
    boundary = DiscoveryBoundary(
        snapshot, partition, "api", "standard", ORIGIN, objects, quarantine
    )
    binding_id = boundary.prepare(())
    context = json.loads(boundary.provider_bytes(binding_id))
    proposal = {
        "schema_version": 1,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [],
        "subjects": [],
        "inventory": [
            {"path": row["path"], "owner": None, "reason": "Empty file"}
            for row in context["inventory"]
        ],
        "obligations": [
            {"target": "source", "category": category}
            for category in SOURCE_CATEGORIES
        ],
        "questions": [],
    }
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    review = {
        "schema_version": 1,
        "kind": "discovery_review",
        "proposal_id": proposal_id,
        "verdict": "ready",
        "domains": [],
        "subjects": [],
        "inventory": [
            {
                "path": row["path"],
                "owner": None,
                "disposition": "excluded",
                "rationale": "Empty file",
                "evidence_ids": [],
            }
            for row in context["inventory"]
        ],
        "overlaps": [],
        "findings": [],
    }
    raw = canonical_json_bytes(review)
    reviewer = DiscoveryReviewBoundary(boundary)
    assert len(reviewer.provider_bytes(binding_id, proposal_receipt_id)) <= 262_144
    assert len(raw) <= 262_144
    before = _stored_files(objects)

    with pytest.raises(DiscoveryReviewAdmissionError, match="normalized-bound"):
        reviewer.admit(binding_id, proposal_receipt_id, raw)

    assert _stored_files(objects) == before
    assert _stored_files(quarantine) == set()


@pytest.mark.unit
def test_self_consistent_unsafe_proposal_forgery_is_rejected_without_replay_writes(
    tmp_path: Path,
) -> None:
    """Content addressing alone must not export a proposal that bypassed screening."""
    boundary, binding_id, context, objects, quarantine = _setup(tmp_path)
    proposal = _proposal(context)
    proposal["domains"][0]["description"] = "ghp_" + "P" * 36
    normalized = boundary._normalize_proposal(proposal, context)
    proposal_bytes = canonical_json_bytes(normalized)
    proposal_id = objects.put_blob(proposal_bytes)
    receipt_id = objects.put_blob(
        boundary._proposal_receipt(binding_id, normalized, None)
    )
    assert proposal_id == json.loads(objects.read_blob(receipt_id))["proposal_id"]
    ordinary_before = _stored_files(objects)
    quarantine_before = _stored_files(quarantine)

    with pytest.raises(DiscoveryError):
        boundary.read_proposal(binding_id, receipt_id)

    assert _stored_files(objects) == ordinary_before
    assert _stored_files(quarantine) == quarantine_before


@pytest.mark.unit
def test_self_consistent_unsafe_review_forgery_is_rejected_without_replay_writes(
    tmp_path: Path,
) -> None:
    """A forged valid receipt must not turn unscanned feedback into replay authority."""
    boundary, binding_id, context, objects, quarantine = _setup(tmp_path)
    proposal_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_proposal(context)), capture_bound=True
    )
    proposal_id = json.loads(objects.read_blob(proposal_receipt_id))["proposal_id"]
    reviewer = DiscoveryReviewBoundary(boundary)
    raw_review = _review(context, proposal_id)
    raw_review["domains"][0]["rationale"] = "ghp_" + "V" * 36
    response_bytes = canonical_json_bytes(raw_review)
    context_bytes = reviewer.provider_bytes(binding_id, proposal_receipt_id)
    normalized = reviewer._normalize(raw_review, json.loads(context_bytes))
    response_id = objects.put_blob(response_bytes)
    objects.put_blob(canonical_json_bytes(normalized))
    receipt_id = objects.put_blob(reviewer._receipt(
        binding_id,
        proposal_receipt_id,
        normalized,
        response_id,
        content_digest(context_bytes),
    ))
    ordinary_before = _stored_files(objects)
    quarantine_before = _stored_files(quarantine)

    with pytest.raises(DiscoveryReviewError):
        reviewer.read_review(binding_id, proposal_receipt_id, receipt_id)

    assert _stored_files(objects) == ordinary_before
    assert _stored_files(quarantine) == quarantine_before
