from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_discovery import DiscoveryBoundary, DiscoveryError
from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.partition import (
    PartitionAuthoritiesV1,
    SourceDescriptorV1,
    SourcePartitionIdentityInputV1,
    WorkspacePartitionCatalogV1,
    source_content_id,
    source_partition_id,
)
from tests.unit.test_re_v2_knowledge_discovery import ORIGIN, _proposal as legacy_proposal
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


DOMAIN_CATEGORIES = (
    "public-surfaces",
    "state-models-transformations-invariants",
    "boundaries-integrations-protocols-dependencies",
    "failure-retry-recovery-degraded-behavior",
    "configuration-controls-security-permissions",
    "observability-operations-lifecycle",
    "negative-space",
)
SOURCE_CATEGORIES = (
    "source-composition",
    "cross-domain-boundaries",
    "source-configuration-security",
    "source-operations-lifecycle",
    "source-negative-space",
)
QUICK_DOMAIN = frozenset({
    "public-surfaces",
    "boundaries-integrations-protocols-dependencies",
    "configuration-controls-security-permissions",
})
QUICK_SOURCE = frozenset({
    "source-composition",
    "cross-domain-boundaries",
    "source-configuration-security",
})
STANDARD_DOMAIN = frozenset(DOMAIN_CATEGORIES[:-1])
STANDARD_SOURCE = frozenset(SOURCE_CATEGORIES[:-1])
EXPECTED_DEPTH_MATRIX = {
    "quick": {
        "domain": {
            "required": sorted(QUICK_DOMAIN),
            "outside_requested_depth": sorted(set(DOMAIN_CATEGORIES) - QUICK_DOMAIN),
        },
        "source": {
            "required": sorted(QUICK_SOURCE),
            "outside_requested_depth": sorted(set(SOURCE_CATEGORIES) - QUICK_SOURCE),
        },
    },
    "standard": {
        "domain": {
            "required": sorted(STANDARD_DOMAIN),
            "outside_requested_depth": sorted(set(DOMAIN_CATEGORIES) - STANDARD_DOMAIN),
        },
        "source": {
            "required": sorted(STANDARD_SOURCE),
            "outside_requested_depth": sorted(set(SOURCE_CATEGORIES) - STANDARD_SOURCE),
        },
    },
    "deep": {
        "domain": {"required": sorted(DOMAIN_CATEGORIES), "outside_requested_depth": []},
        "source": {"required": sorted(SOURCE_CATEGORIES), "outside_requested_depth": []},
    },
}


@pytest.mark.unit
def test_depth_category_matrix_is_one_canonical_protocol_28_policy() -> None:
    """Discovery and later activation must not grow independent depth matrices."""
    from harness.re_v2.knowledge_discovery import categories_for_depth
    from harness.re_v2.protocol_28.policies import (
        categories_for_depth as protocol_28_categories_for_depth,
    )

    assert categories_for_depth("quick", "domain") == QUICK_DOMAIN
    assert categories_for_depth("quick", "source") == QUICK_SOURCE
    assert categories_for_depth("standard", "domain") == STANDARD_DOMAIN
    assert categories_for_depth("standard", "source") == STANDARD_SOURCE
    assert categories_for_depth("deep", "domain") == frozenset(DOMAIN_CATEGORIES)
    assert categories_for_depth("deep", "source") == frozenset(SOURCE_CATEGORIES)
    for depth in ("quick", "standard", "deep"):
        for target_kind in ("domain", "source"):
            assert categories_for_depth(depth, target_kind) == (
                protocol_28_categories_for_depth(depth, target_kind)
            )


@pytest.mark.unit
@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
def test_schema_2_discovery_provider_receives_the_exact_canonical_depth_matrix(
    tmp_path: Path, depth: str
) -> None:
    """The tools-free producer must receive the literal policy admission enforces."""
    from harness.re_v2.knowledge_discovery import category_depth_applicability

    _boundary, _binding_id, context, _objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
        depth=depth,
    )

    assert context["schema_version"] == 2
    assert context["category_depth_applicability"] == EXPECTED_DEPTH_MATRIX
    assert context["category_depth_applicability"] == category_depth_applicability()


def _setup(
    tmp_path: Path,
    files: dict[str, str | bytes],
    *,
    depth: str = "standard",
    schema_version: int = 2,
) -> tuple[DiscoveryBoundary, str, dict, ObjectStore]:
    snapshot, partition = _fixture(tmp_path, files)
    objects = ObjectStore(tmp_path / "objects")
    boundary = DiscoveryBoundary(
        snapshot,
        partition,
        "api",
        depth,
        ORIGIN,
        objects,
        ObjectStore(tmp_path / "quarantine"),
    )
    selectors = tuple(
        EvidenceSelectorV1("api", path, 0, len(payload.encode("utf-8")))
        for path, payload in sorted(files.items())
        if isinstance(payload, str) and payload
    )
    binding_id = boundary.prepare(selectors, schema_version=schema_version)
    return boundary, binding_id, json.loads(boundary.provider_bytes(binding_id)), objects


@pytest.mark.unit
def test_schema_3_discovery_context_freezes_exact_analysis_domain_targets(
    tmp_path: Path,
) -> None:
    boundary, _binding_id, context, _objects = _setup(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle(): return 'ok'\n",
        },
        schema_version=3,
    )
    source = boundary.partition_authority.sources[0]

    assert context["schema_version"] == 3
    assert context["analysis_domain_targets"] == [
        {
            "key": domain.domain_key,
            "source_relative_root": domain.source_relative_root,
        }
        for domain in source.domains
    ]
    assert context["category_depth_applicability"] == EXPECTED_DEPTH_MATRIX


@pytest.mark.unit
def test_schema_3_rejects_domains_outside_frozen_analysis_targets(
    tmp_path: Path,
) -> None:
    boundary, binding_id, context, _objects = _setup(
        tmp_path,
        {
            "README.md": "Deployment stack\n",
            "src/stack.yml": "services:\n  app: {}\n",
        },
        schema_version=3,
    )
    assert context["analysis_domain_targets"] == []
    evidence_id = context["evidence"][0]["projection_id"]
    proposal = {
        "schema_version": 2,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [{
            "key": "invented",
            "description": "Invented target",
            "evidence_ids": [evidence_id],
        }],
        "subjects": [],
        "inventory": [],
        "obligations": [],
        "questions": [],
    }

    with pytest.raises(DiscoveryError, match="discovery-domain-target-closure"):
        boundary.admit(
            binding_id,
            canonical_json_bytes(proposal),
        )


@pytest.mark.unit
def test_schema_3_accepts_exact_frozen_analysis_target_keys(
    tmp_path: Path,
) -> None:
    boundary, binding_id, context, _objects = _setup(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle(): return 'ok'\n",
        },
        depth="deep",
        schema_version=3,
    )
    from tests.unit.test_re_v2_knowledge_activation import _candidate

    target = context["analysis_domain_targets"][0]["key"]
    proposal = _candidate(context)
    proposal["domains"][0]["key"] = target
    for row in (*proposal["subjects"], *proposal["obligations"]):
        if row["target"] == "behavior":
            row["target"] = target

    receipt_id = boundary.admit(binding_id, canonical_json_bytes(proposal))

    assert boundary.read_proposal(binding_id, receipt_id)["domains"][0]["key"] == target


@pytest.mark.unit
def test_schema_3_rejects_supporting_only_domain_target_evidence(
    tmp_path: Path,
) -> None:
    boundary, binding_id, context, _objects = _setup(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle(): return 'ok'\n",
        },
        depth="deep",
        schema_version=3,
    )
    from tests.unit.test_re_v2_knowledge_activation import _candidate

    target = context["analysis_domain_targets"][0]["key"]
    proposal = _candidate(context)
    proposal["domains"][0].update(
        key=target,
        evidence_ids=[_projection_ids(context)["README.md"]],
    )
    for row in (*proposal["subjects"], *proposal["obligations"]):
        if row["target"] == "behavior":
            row["target"] = target

    with pytest.raises(DiscoveryError, match="discovery-domain-target-evidence"):
        boundary.admit(binding_id, canonical_json_bytes(proposal))


@pytest.mark.unit
def test_schema_3_rejects_inventory_owner_on_wrong_primary_target(
    tmp_path: Path,
) -> None:
    boundary, binding_id, context, _objects = _setup(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle(): return 'ok'\n",
        },
        depth="deep",
        schema_version=3,
    )
    from tests.unit.test_re_v2_knowledge_activation import _candidate

    target = context["analysis_domain_targets"][0]["key"]
    proposal = _candidate(context)
    proposal["domains"][0]["key"] = target
    for row in (*proposal["subjects"], *proposal["obligations"]):
        if row["target"] == "behavior":
            row["target"] = target
    next(
        row for row in proposal["inventory"] if row["path"] == "README.md"
    )["owner"] = "handler"

    with pytest.raises(DiscoveryError, match="discovery-target-ownership"):
        boundary.admit(binding_id, canonical_json_bytes(proposal))


def _empty_repository_setup(
    tmp_path: Path, *, depth: str
) -> tuple[DiscoveryBoundary, str, dict, ObjectStore]:
    snapshot, populated = _fixture(tmp_path, {"placeholder.txt": ""})
    authorities = PartitionAuthoritiesV1(
        populated.partitioner, populated.ownership_policy
    )
    original = populated.sources[0]
    identity = SourcePartitionIdentityInputV1(
        source_id="api",
        partitioner=populated.partitioner,
        ownership_policy=populated.ownership_policy,
        source_supporting_paths=(),
        domains=(),
    )
    empty_source = SourceDescriptorV1(
        source_id="api",
        workspace_relative_path=original.workspace_relative_path,
        snapshot_id=populated.snapshot_id,
        source_content_id=source_content_id(
            populated.source_selection_policy_version, ()
        ),
        source_partition_id=source_partition_id(identity),
        files=(),
        source_supporting_paths=(),
        domains=(),
    )
    partition = WorkspacePartitionCatalogV1(
        schema_version=1,
        snapshot_id=populated.snapshot_id,
        source_selection_policy_version=populated.source_selection_policy_version,
        partitioner=authorities.partitioner,
        ownership_policy=authorities.ownership_policy,
        sources=(empty_source,),
    )
    objects = ObjectStore(tmp_path / "objects")
    boundary = DiscoveryBoundary(
        snapshot,
        partition,
        "api",
        depth,
        ORIGIN,
        objects,
        ObjectStore(tmp_path / "quarantine"),
    )
    binding_id = boundary.prepare(())
    return boundary, binding_id, json.loads(boundary.provider_bytes(binding_id)), objects


def _projection_ids(context: dict) -> dict[str, str]:
    return {
        row["projection"]["path"]: row["projection_id"]
        for row in context["evidence"]
    }


def _obligation_rows(
    *,
    target: str,
    categories: tuple[str, ...],
    applicable: frozenset[str],
    subject_key: str,
    evidence_ids: list[str],
) -> list[dict]:
    return [
        {
            "target": target,
            "category": category,
            "disposition": "analyze" if category in applicable else "outside-requested-depth",
            "subject_keys": [subject_key] if category in applicable else [],
            "rationale": (
                "The supplied behavior requires analysis."
                if category in applicable
                else "This category is beyond the frozen requested depth."
            ),
            "evidence_ids": evidence_ids,
        }
        for category in categories
    ]


def _application_proposal(context: dict, *, depth: str = "standard") -> dict:
    refs = _projection_ids(context)
    domain_categories = (
        frozenset(DOMAIN_CATEGORIES)
        if depth == "deep"
        else QUICK_DOMAIN if depth == "quick" else STANDARD_DOMAIN
    )
    source_categories = (
        frozenset(SOURCE_CATEGORIES)
        if depth == "deep"
        else QUICK_SOURCE if depth == "quick" else STANDARD_SOURCE
    )
    app_ids = [refs["app.py"]]
    worker_ids = [refs["worker.py"]]
    return {
        "schema_version": 2,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [{
            "key": "execution",
            "description": "Command execution behavior",
            "evidence_ids": app_ids,
        }],
        "subjects": [
            {
                "key": "runner",
                "target": "execution",
                "description": "Application entry point",
                "category_ids": sorted(domain_categories),
                "evidence_ids": app_ids,
            },
            {
                "key": "worker",
                "target": "source",
                "description": "Repository worker composition",
                "category_ids": sorted(source_categories),
                "evidence_ids": worker_ids,
            },
        ],
        "inventory": [
            {"path": "app.py", "owner": "runner", "reason": "Entry point implementation"},
            {"path": "worker.py", "owner": "worker", "reason": "Worker implementation"},
        ],
        "obligations": [
            *_obligation_rows(
                target="source",
                categories=SOURCE_CATEGORIES,
                applicable=source_categories,
                subject_key="worker",
                evidence_ids=worker_ids,
            ),
            *_obligation_rows(
                target="execution",
                categories=DOMAIN_CATEGORIES,
                applicable=domain_categories,
                subject_key="runner",
                evidence_ids=app_ids,
            ),
        ],
        "questions": [],
    }


def _empty_source_proposal(context: dict, *, depth: str) -> dict:
    required = (
        frozenset(SOURCE_CATEGORIES)
        if depth == "deep"
        else QUICK_SOURCE if depth == "quick" else STANDARD_SOURCE
    )
    return {
        "schema_version": 2,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [],
        "subjects": [],
        "inventory": [
            {"path": row["path"], "owner": None, "reason": "Authenticated empty file."}
            for row in context["inventory"]
        ],
        "obligations": [
            {
                "target": "source",
                "category": category,
                "disposition": (
                    "not-applicable" if category in required else "outside-requested-depth"
                ),
                "subject_keys": [],
                "rationale": "The authenticated source inventory contains no bytes.",
                "evidence_ids": [],
            }
            for category in SOURCE_CATEGORIES
        ],
        "questions": [],
    }


@pytest.mark.unit
def test_schema_2_application_has_exact_category_rows_and_stable_normalized_ids(
    tmp_path: Path,
) -> None:
    """Dropping, duplicating, or order-binding a target/category row must fail."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
    )
    proposal = _application_proposal(context)

    first_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    first_receipt = json.loads(objects.read_blob(first_receipt_id))
    first = json.loads(objects.read_blob(first_receipt["proposal_id"]))
    proposal["domains"].reverse()
    proposal["subjects"].reverse()
    proposal["inventory"].reverse()
    proposal["obligations"].reverse()
    second_receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    second_receipt = json.loads(objects.read_blob(second_receipt_id))
    second = json.loads(objects.read_blob(second_receipt["proposal_id"]))

    assert first["schema_version"] == 2
    assert len(first["obligations"]) == 12
    assert {(row["target"], row["category"]) for row in first["obligations"]} == {
        *(('source', category) for category in SOURCE_CATEGORIES),
        *(('execution', category) for category in DOMAIN_CATEGORIES),
    }
    assert all(row["obligation_id"].startswith("sha256:") for row in first["obligations"])
    assert first_receipt["proposal_id"] == second_receipt["proposal_id"]
    assert first_receipt["authorial_response_id"] != second_receipt["authorial_response_id"]
    assert [row["obligation_id"] for row in first["obligations"]] == [
        row["obligation_id"] for row in second["obligations"]
    ]


@pytest.mark.unit
def test_schema_2_deployment_only_source_stays_at_source_scope(tmp_path: Path) -> None:
    """A deployment-only source must not need an invented application domain."""
    boundary, binding_id, context, objects = _setup(
        tmp_path, {"deployment.yml": "image: api:1\nport: 8080\nhealth: /ready\n"}
    )
    evidence_id = _projection_ids(context)["deployment.yml"]
    analyzed = frozenset({
        "source-composition", "source-configuration-security", "source-operations-lifecycle"
    })
    proposal = {
        "schema_version": 2,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [],
        "subjects": [{
            "key": "deployment",
            "target": "source",
            "description": "Deployment and runtime configuration",
            "category_ids": sorted(analyzed),
            "evidence_ids": [evidence_id],
        }],
        "inventory": [{
            "path": "deployment.yml", "owner": "deployment", "reason": "Deployment wiring"
        }],
        "obligations": [
            {
                "target": "source",
                "category": category,
                "disposition": (
                    "analyze" if category in analyzed
                    else "not-applicable" if category == "cross-domain-boundaries"
                    else "outside-requested-depth"
                ),
                "subject_keys": ["deployment"] if category in analyzed else [],
                "rationale": "Scoped deployment evidence supports this assessment.",
                "evidence_ids": [evidence_id],
            }
            for category in SOURCE_CATEGORIES
        ],
        "questions": [],
    }

    receipt = json.loads(objects.read_blob(boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )))
    normalized = json.loads(objects.read_blob(receipt["proposal_id"]))

    assert normalized["domains"] == []
    assert {row["target"] for row in normalized["obligations"]} == {"source"}
    assert receipt["review_required"] is True


@pytest.mark.unit
def test_schema_2_empty_deep_source_can_record_evidence_backed_non_applicability(
    tmp_path: Path,
) -> None:
    """An authenticated empty inventory must permit an explicit reviewed disposition."""
    boundary, binding_id, _context, objects = _setup(
        tmp_path, {"empty.txt": ""}, depth="deep"
    )
    proposal = {
        "schema_version": 2,
        "kind": "discovery_proposal",
        "source_id": "api",
        "domains": [],
        "subjects": [],
        "inventory": [{
            "path": "empty.txt", "owner": None, "reason": "The file is empty."
        }],
        "obligations": [
            {
                "target": "source",
                "category": category,
                "disposition": "not-applicable",
                "subject_keys": [],
                "rationale": "The frozen source inventory is empty.",
                "evidence_ids": [],
            }
            for category in SOURCE_CATEGORIES
        ],
        "questions": [],
    }

    receipt = json.loads(objects.read_blob(boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )))
    normalized = json.loads(objects.read_blob(receipt["proposal_id"]))

    assert {row["disposition"] for row in normalized["obligations"]} == {"not-applicable"}
    assert receipt["unassigned_paths"] == ["empty.txt"]


@pytest.mark.unit
@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
@pytest.mark.parametrize("inventory_kind", ["empty-inventory", "zero-byte-file"])
def test_schema_2_authenticated_empty_source_admits_exact_depth_table(
    tmp_path: Path, depth: str, inventory_kind: str
) -> None:
    """Empty authority proves both in-depth absence and the canonical complement."""
    if inventory_kind == "empty-inventory":
        boundary, binding_id, context, objects = _empty_repository_setup(
            tmp_path, depth=depth
        )
    else:
        boundary, binding_id, context, objects = _setup(
            tmp_path, {"empty.txt": ""}, depth=depth
        )

    receipt_id = boundary.admit(
        binding_id,
        canonical_json_bytes(_empty_source_proposal(context, depth=depth)),
        capture_bound=True,
    )
    receipt = json.loads(objects.read_blob(receipt_id))
    normalized = boundary.read_proposal(binding_id, receipt_id)

    required = EXPECTED_DEPTH_MATRIX[depth]["source"]["required"]
    assert {
        row["category"] for row in normalized["obligations"]
        if row["disposition"] == "not-applicable"
    } == set(required)
    assert {
        row["category"] for row in normalized["obligations"]
        if row["disposition"] == "outside-requested-depth"
    } == set(EXPECTED_DEPTH_MATRIX[depth]["source"]["outside_requested_depth"])
    assert receipt["review_required"] is True


@pytest.mark.unit
def test_schema_2_quick_partial_evidence_preserves_unknown_and_depth_limits(
    tmp_path: Path,
) -> None:
    """Unknown evidence must stay explicit instead of becoming absence or dropped work."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return dynamic_call()\n", "worker.py": "def work(): return 1\n"},
        depth="quick",
    )
    proposal = _application_proposal(context, depth="quick")
    category = "boundaries-integrations-protocols-dependencies"
    subject = next(row for row in proposal["subjects"] if row["key"] == "runner")
    subject["category_ids"].remove(category)
    row = next(
        row for row in proposal["obligations"]
        if row["target"] == "execution" and row["category"] == category
    )
    row.update(
        disposition="unknown",
        subject_keys=[],
        rationale="The supplied safe evidence leaves the dynamic target unresolved.",
    )

    receipt = json.loads(objects.read_blob(boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )))
    normalized = json.loads(objects.read_blob(receipt["proposal_id"]))
    unknown = next(
        item for item in normalized["obligations"]
        if item["target"] == "execution" and item["category"] == category
    )

    assert unknown["disposition"] == "unknown"
    assert unknown["evidence_ids"]
    assert any(row["disposition"] == "outside-requested-depth" for row in normalized["obligations"])


@pytest.mark.unit
def test_schema_2_unknown_rejects_evidence_from_another_target(tmp_path: Path) -> None:
    """Any supplied projection is not authority for an unrelated target unknown."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
    )
    proposal = _application_proposal(context)
    category = "public-surfaces"
    runner = next(row for row in proposal["subjects"] if row["key"] == "runner")
    runner["category_ids"].remove(category)
    row = next(
        item for item in proposal["obligations"]
        if item["target"] == "execution" and item["category"] == category
    )
    row.update(
        disposition="unknown",
        subject_keys=[],
        evidence_ids=[_projection_ids(context)["worker.py"]],
    )
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    with pytest.raises(DiscoveryError, match="unattempted-discovery-obligation"):
        boundary.admit(binding_id, canonical_json_bytes(proposal), capture_bound=True)

    assert {path for path in objects.root.rglob("*") if path.is_file()} == before


@pytest.mark.unit
def test_schema_2_source_unknown_accepts_authenticated_withheld_boundary(
    tmp_path: Path,
) -> None:
    """A source-local withheld projection is an attempted boundary, not fake absence."""
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
    withheld_id = _projection_ids(context)[".env"]
    assert next(
        item["projection"]["disposition"] for item in context["evidence"]
        if item["projection_id"] == withheld_id
    ) == "withheld"
    row.update(disposition="unknown", subject_keys=[], evidence_ids=[withheld_id])

    receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(proposal), capture_bound=True
    )
    normalized = boundary.read_proposal(binding_id, receipt_id)

    unknown = next(item for item in normalized["obligations"] if item["category"] == category)
    assert unknown["evidence_ids"] == [withheld_id]


def _proposal_with_normalized_size(proposal: dict, target_size: int) -> dict:
    shaped = json.loads(json.dumps(proposal))
    for row in shaped["obligations"]:
        row["obligation_id"] = "sha256:" + "0" * 64
    shaped["questions"] = [
        {"target": "source", "question": "q", "evidence_ids": []}
        for _ in range(64)
    ]
    remaining = target_size - len(canonical_json_bytes(shaped))
    assert 0 <= remaining <= 64 * 4095
    for row in shaped["questions"]:
        growth = min(remaining, 4095)
        row["question"] += "q" * growth
        remaining -= growth
    assert remaining == 0
    result = json.loads(json.dumps(shaped))
    for row in result["obligations"]:
        del row["obligation_id"]
    assert len(canonical_json_bytes(result)) <= 262_144
    return result


@pytest.mark.unit
@pytest.mark.parametrize("capture_bound", [False, True])
@pytest.mark.parametrize("normalized_size", [262_144, 262_145])
def test_schema_2_normalized_authorial_bound_precedes_all_persistence(
    tmp_path: Path, capture_bound: bool, normalized_size: int
) -> None:
    """The exact replay boundary admits 262144 bytes and rejects the next byte."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
        depth="deep",
    )
    proposal = _proposal_with_normalized_size(
        _application_proposal(context, depth="deep"), normalized_size
    )
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    if normalized_size == 262_145:
        with pytest.raises(DiscoveryError, match="discovery-normalized-bound"):
            boundary.admit(
                binding_id, canonical_json_bytes(proposal), capture_bound=capture_bound
            )
        assert {path for path in objects.root.rglob("*") if path.is_file()} == before
    else:
        receipt_id = boundary.admit(
            binding_id, canonical_json_bytes(proposal), capture_bound=capture_bound
        )
        restored = boundary.read_proposal(binding_id, receipt_id)
        assert len(canonical_json_bytes(restored)) == 262_144


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [
        "fabricated-subject-category",
        "fabricated-obligation-category",
        "cross-target-subject",
        "missing-subject-membership",
        "missing-analyze-evidence",
        "unsupported-not-applicable",
        "unattempted-unknown",
        "outside-required-at-standard",
        "analyze-outside-depth",
        "cross-target-evidence",
        "outside-at-deep",
        "missing-row",
        "duplicate-row",
        "extra-target",
    ],
)
def test_schema_2_rejects_unsupported_or_inexact_category_authority(
    tmp_path: Path, mutation: str
) -> None:
    """Each mutation would otherwise create fabricated, cross-target, or omitted work."""
    depth = "deep" if mutation == "outside-at-deep" else "standard"
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
        depth=depth,
    )
    proposal = _application_proposal(context, depth=depth)
    runner = next(row for row in proposal["subjects"] if row["key"] == "runner")
    public = next(
        row for row in proposal["obligations"]
        if row["target"] == "execution" and row["category"] == "public-surfaces"
    )
    negative = next(
        row for row in proposal["obligations"]
        if row["target"] == "execution" and row["category"] == "negative-space"
    )
    if mutation == "fabricated-subject-category":
        runner["category_ids"].append("invented-category")
    elif mutation == "fabricated-obligation-category":
        public["category"] = "invented-category"
    elif mutation == "cross-target-subject":
        public["subject_keys"] = ["worker"]
    elif mutation == "missing-subject-membership":
        runner["category_ids"].remove("public-surfaces")
    elif mutation == "missing-analyze-evidence":
        public["evidence_ids"] = []
    elif mutation == "unsupported-not-applicable":
        negative.update(disposition="not-applicable", evidence_ids=[])
    elif mutation == "unattempted-unknown":
        runner["category_ids"].remove("public-surfaces")
        public.update(disposition="unknown", subject_keys=[], evidence_ids=[])
    elif mutation == "outside-required-at-standard":
        runner["category_ids"].remove("public-surfaces")
        public.update(disposition="outside-requested-depth", subject_keys=[])
    elif mutation == "analyze-outside-depth":
        runner["category_ids"].append("negative-space")
        negative.update(disposition="analyze", subject_keys=["runner"])
    elif mutation == "cross-target-evidence":
        public["evidence_ids"] = [
            *public["evidence_ids"], _projection_ids(context)["worker.py"]
        ]
    elif mutation == "outside-at-deep":
        runner["category_ids"].remove("negative-space")
        negative.update(disposition="outside-requested-depth", subject_keys=[])
    elif mutation == "missing-row":
        proposal["obligations"].remove(public)
    elif mutation == "duplicate-row":
        proposal["obligations"].append(dict(public))
    else:
        proposal["obligations"].append({**public, "target": "invented"})
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    with pytest.raises(DiscoveryError):
        boundary.admit(binding_id, canonical_json_bytes(proposal), capture_bound=True)

    assert {path for path in objects.root.rglob("*") if path.is_file()} == before


@pytest.mark.unit
def test_schema_1_proposal_remains_readable_with_its_canonical_receipt_shape(
    tmp_path: Path,
) -> None:
    """Schema-2 decoding must not reinterpret or rewrite historical proposal objects."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return 3\n", "worker.py": "def retry(): return False\n"},
    )
    payload = canonical_json_bytes(legacy_proposal(context))

    receipt_id = boundary.admit(binding_id, payload, capture_bound=True)
    receipt_bytes = objects.read_blob(receipt_id)
    restored = boundary.read_proposal(binding_id, receipt_id)

    assert receipt_bytes == canonical_json_bytes({
        "schema_version": 2,
        "state": "proposal_validated",
        "binding_id": binding_id,
        "authorial_response_id": objects.put_blob(payload),
        "proposal_id": json.loads(receipt_bytes)["proposal_id"],
        "review_required": True,
        "unassigned_paths": ["worker.py"],
        "subject_ids": {
            "runner": json.loads(receipt_bytes)["subject_ids"]["runner"]
        },
    })
    assert restored == json.loads(objects.read_blob(json.loads(receipt_bytes)["proposal_id"]))
    assert restored["schema_version"] == 1


@pytest.mark.unit
def test_historical_schema_1_context_binding_bytes_remain_exactly_replayable(
    tmp_path: Path,
) -> None:
    """The schema-2 matrix envelope must not reinterpret an old context identity."""
    boundary, _new_binding_id, current, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return 3\n", "worker.py": "def retry(): return False\n"},
    )
    selectors = tuple(
        EvidenceSelectorV1(
            row["projection"]["source_id"],
            row["projection"]["path"],
            row["projection"]["byte_start"],
            row["projection"]["byte_end"],
        )
        for row in current["evidence"]
    )
    context_bytes, binding_bytes = boundary._context(
        selectors, persist=False, schema_version=1
    )
    context_id = objects.put_blob(context_bytes)
    binding_id = objects.put_blob(binding_bytes)

    restored = json.loads(boundary.provider_bytes(binding_id))

    assert restored["schema_version"] == 1
    assert "category_depth_applicability" not in restored
    assert json.loads(binding_bytes) == {
        "schema_version": 1,
        "kind": "private_discovery_binding",
        "context_id": context_id,
        "snapshot_id": boundary.run_authority()["snapshot_id"],
        "partition_id": boundary.run_authority()["partition_id"],
        "source_id": "api",
        "depth": "standard",
        "origin_obligation_id": ORIGIN,
        "security_policy_id": boundary.run_authority()["security_policy_id"],
        "selectors": [selector.to_json_dict() for selector in selectors],
        "mapping_ids": json.loads(binding_bytes)["mapping_ids"],
    }
    assert boundary.verify_selection(selectors, schema_version=1) == binding_id


@pytest.mark.unit
def test_passive_schema_2_proposal_replays_without_rewriting_its_identity(
    tmp_path: Path,
) -> None:
    """A normalized passive candidate must remain readable after controller restart."""
    boundary, binding_id, context, objects = _setup(
        tmp_path,
        {"app.py": "def run(): return work()\n", "worker.py": "def work(): return 1\n"},
    )
    receipt_id = boundary.admit(
        binding_id, canonical_json_bytes(_application_proposal(context))
    )
    before = {path for path in objects.root.rglob("*") if path.is_file()}

    restored = boundary.read_proposal(binding_id, receipt_id)

    assert restored["schema_version"] == 2
    assert json.loads(objects.read_blob(receipt_id))["proposal_id"] == content_digest(
        canonical_json_bytes(restored)
    )
    assert {path for path in objects.root.rglob("*") if path.is_file()} == before
