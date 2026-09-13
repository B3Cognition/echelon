from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2 import knowledge_discovery
from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.policies import DOMAIN_CATEGORIES, SOURCE_CATEGORIES
from tests.unit.test_re_v2_protocol_28_evidence import _fixture

ORIGIN = "sha256:" + "a" * 64


def _api():
    return knowledge_discovery


def _setup(tmp_path: Path, files=None):
    files = files if files is not None else {"app.py": "def run(): return 3\n", "worker.py": "def retry(): return False\n"}
    snapshot, partition = _fixture(tmp_path, files)
    objects = ObjectStore(tmp_path / "objects")
    quarantine = ObjectStore(tmp_path / "quarantine")
    args = (snapshot, partition, "api", "standard", ORIGIN, objects, quarantine)
    boundary = _api().DiscoveryBoundary(*args)
    selectors = (EvidenceSelectorV1("api", "app.py", 0, len(files["app.py"])),) if "app.py" in files else ()
    binding = boundary.prepare(selectors)
    context = json.loads(boundary.provider_bytes(binding))
    return boundary, binding, context, objects, args


def _proposal(context):
    refs = [context["evidence"][0]["projection_id"]]
    return {
        "schema_version": 1, "kind": "discovery_proposal", "source_id": "api",
        "domains": [{"key": "execution", "description": "Command execution", "evidence_ids": refs}],
        "subjects": [{"key": "runner", "target": "execution", "description": "Run entry point", "evidence_ids": refs}],
        "inventory": [{"path": row["path"], "owner": "runner" if row["path"] == "app.py" else None,
                       "reason": "Ownership requires more evidence" if row["path"] != "app.py" else "Run implementation"}
                      for row in context["inventory"]],
        "obligations": ([{"target": "source", "category": category} for category in SOURCE_CATEGORIES]
                        + [{"target": "execution", "category": category} for category in DOMAIN_CATEGORIES]),
        "questions": [{"target": "source", "question": "How is the worker connected?", "evidence_ids": []}],
    }


@pytest.mark.unit
def test_discovery_records_orphans_without_certifying_coverage(tmp_path: Path) -> None:
    boundary, binding, context, objects, _ = _setup(tmp_path)
    result = json.loads(objects.read_blob(boundary.admit(binding, canonical_json_bytes(_proposal(context)))))
    assert result["state"] == "proposal_validated"
    assert result["unassigned_paths"] == ["worker.py"]
    assert result["review_required"] is True
    assert len(result["subject_ids"]) == 1
    assert result["binding_id"] == binding
    assert "accepted" not in result


@pytest.mark.unit
def test_reopening_and_reordering_preserve_discovery_identity(tmp_path: Path) -> None:
    boundary, binding, context, objects, args = _setup(tmp_path)
    proposal = _proposal(context)
    first = boundary.admit(binding, canonical_json_bytes(proposal))
    proposal["inventory"].reverse()
    proposal["obligations"].reverse()
    reopened = _api().DiscoveryBoundary(*args)
    assert reopened.admit(binding, canonical_json_bytes(proposal)) == first
    assert objects.read_blob(first)


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ["missing-file", "duplicate-file", "missing-category", "fake-category", "foreign-evidence", "raw-evidence", "extra-field", "unknown-owner", "duplicate-subject", "unknown-target"])
def test_invalid_proposals_do_not_enter_the_staged_response_store(tmp_path: Path, mutation: str) -> None:
    boundary, binding, context, objects, args = _setup(tmp_path)
    proposal = _proposal(context)
    if mutation == "missing-file": proposal["inventory"].pop()
    elif mutation == "duplicate-file": proposal["inventory"].append(proposal["inventory"][0])
    elif mutation == "missing-category": proposal["obligations"].pop()
    elif mutation == "fake-category": proposal["obligations"][0]["category"] = "not-applicable"
    elif mutation == "foreign-evidence": proposal["subjects"][0]["evidence_ids"] = ["sha256:" + "b" * 64]
    elif mutation == "raw-evidence": proposal["domains"][0]["evidence_ids"] = [args[1].sources[0].files[0].content_hash]
    elif mutation == "extra-field": proposal["budget"] = 999999999
    elif mutation == "unknown-owner": proposal["inventory"][0]["owner"] = "invented"
    elif mutation == "duplicate-subject": proposal["subjects"].append(proposal["subjects"][0])
    else: proposal["subjects"][0]["target"] = "invented"
    before = {p for p in objects.root.rglob("*") if p.is_file()}
    with pytest.raises(_api().DiscoveryError):
        boundary.admit(binding, canonical_json_bytes(proposal))
    assert {p for p in objects.root.rglob("*") if p.is_file()} == before


@pytest.mark.unit
def test_inventory_and_safe_context_never_expose_raw_credentials_or_hashes(tmp_path: Path) -> None:
    canary = "ghp_" + "C" * 36
    boundary, binding, context, _, args = _setup(tmp_path, {"app.py": f'TOKEN="{canary}"\nretries=3\n'})
    payload = boundary.provider_bytes(binding)
    assert canary.encode() not in payload
    assert args[1].sources[0].files[0].content_hash.encode() not in payload
    assert b"retries=3" in payload
    assert context["kind"] == "untrusted_discovery_context"


@pytest.mark.unit
def test_unsafe_response_is_quarantined_before_admission(tmp_path: Path) -> None:
    boundary, binding, context, objects, args = _setup(tmp_path)
    proposal = _proposal(context)
    canary = "ghp_" + "Q" * 36
    proposal["domains"][0]["description"] = canary
    before = {p for p in objects.root.rglob("*") if p.is_file()}
    with pytest.raises(_api().DiscoveryError) as error:
        boundary.admit(binding, canonical_json_bytes(proposal))
    assert canary not in str(error.value)
    assert {p for p in objects.root.rglob("*") if p.is_file()} == before
    assert any(p.is_file() for p in args[-1].root.rglob("*"))


@pytest.mark.unit
def test_json_byte_order_mark_cannot_bypass_output_screening(tmp_path: Path) -> None:
    boundary, binding, context, objects, args = _setup(tmp_path)
    proposal = _proposal(context)
    canary = "ghp_" + "B" * 36
    proposal["domains"][0]["description"] = canary
    payload = b"\xef\xbb\xbf" + canonical_json_bytes(proposal).replace(b"ghp_", b"\\u0067hp_")
    before = {p for p in objects.root.rglob("*") if p.is_file()}
    with pytest.raises(_api().DiscoveryError):
        boundary.admit(binding, payload)
    assert {p for p in objects.root.rglob("*") if p.is_file()} == before
    assert any(p.is_file() for p in args[-1].root.rglob("*"))


@pytest.mark.unit
def test_withheld_evidence_cannot_ground_a_subject(tmp_path: Path) -> None:
    boundary, _, _, objects, _ = _setup(tmp_path, {"app.py": "safe\n", ".env": "secret-material"})
    binding = boundary.prepare((EvidenceSelectorV1("api", ".env", 0, 15),))
    proposal = _proposal(json.loads(boundary.provider_bytes(binding)))
    with pytest.raises(_api().DiscoveryError):
        boundary.admit(binding, canonical_json_bytes(proposal))


@pytest.mark.unit
def test_withheld_projection_can_explain_an_unknown_without_grounding_facts(tmp_path: Path) -> None:
    boundary, _, _, objects, _ = _setup(tmp_path, {".env": "secret-material"})
    binding = boundary.prepare((EvidenceSelectorV1("api", ".env", 0, 15),))
    ref = json.loads(boundary.provider_bytes(binding))["evidence"][0]["projection_id"]
    proposal = {"schema_version": 1, "kind": "discovery_proposal", "source_id": "api", "domains": [], "subjects": [],
                "inventory": [{"path": ".env", "owner": None, "reason": "Evidence is withheld"}],
                "questions": [{"target": "source", "question": "Configuration values are unknown", "evidence_ids": [ref]}],
                "obligations": [{"target": "source", "category": c} for c in SOURCE_CATEGORIES]}
    staged = json.loads(objects.read_blob(boundary.admit(binding, canonical_json_bytes(proposal))))
    assert staged["unassigned_paths"] == [".env"]
    assert staged["review_required"] is True


@pytest.mark.unit
def test_tampered_context_is_rejected_even_when_content_addressed(tmp_path: Path) -> None:
    boundary, binding, _, objects, _ = _setup(tmp_path)
    record = json.loads(objects.read_blob(binding))
    public = json.loads(objects.read_blob(record["context_id"]))
    public["inventory"].pop()
    record["context_id"] = objects.put_blob(canonical_json_bytes(public))
    forged = objects.put_blob(canonical_json_bytes(record))
    with pytest.raises(_api().DiscoveryError):
        boundary.provider_bytes(forged)


@pytest.mark.unit
def test_changed_snapshot_cannot_reuse_context_binding(tmp_path: Path) -> None:
    boundary, binding, _, objects, args = _setup(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    snapshot, partition = _fixture(other, {"app.py": "different\n"})
    changed = _api().DiscoveryBoundary(snapshot, partition, "api", "standard", ORIGIN, objects, args[-1])
    with pytest.raises(_api().DiscoveryError):
        changed.provider_bytes(binding)


@pytest.mark.unit
def test_config_source_needs_source_obligations_but_no_invented_domain(tmp_path: Path) -> None:
    boundary, binding, _, objects, _ = _setup(tmp_path, {"deployment.yml": "replicas: 3\n"})
    proposal = {"schema_version": 1, "kind": "discovery_proposal", "source_id": "api", "domains": [],
                "subjects": [], "inventory": [{"path": "deployment.yml", "owner": None, "reason": "Needs source-level inspection"}], "questions": [],
                "obligations": [{"target": "source", "category": c} for c in SOURCE_CATEGORIES]}
    result = json.loads(objects.read_blob(boundary.admit(binding, canonical_json_bytes(proposal))))
    assert result["unassigned_paths"] == ["deployment.yml"]
    assert result["review_required"] is True


def _request(path="worker.py", origin=ORIGIN):
    return {"schema_version": 1, "kind": "evidence_requests", "source_id": "api",
            "requests": [{"obligation_id": origin, "reason_class": "missing-behavior",
                          "selector": {"source_id": "api", "path": path, "byte_start": 0, "byte_end": 10}}]}


@pytest.mark.unit
@pytest.mark.parametrize("path,state", [("worker.py", "pending"), ("missing.py", "unavailable")])
def test_evidence_requests_keep_origin_and_explicit_availability_without_dispatch(tmp_path: Path, path: str, state: str) -> None:
    boundary, binding, _, objects, _ = _setup(tmp_path)
    result_id = boundary.admit(binding, canonical_json_bytes(_request(path)))
    result = json.loads(objects.read_blob(result_id))
    assert result["state"] == "evidence_requested"
    assert result["binding_id"] == binding
    assert result["requests"][0]["obligation_id"] == ORIGIN
    assert result["requests"][0]["state"] == state
    assert "projection_id" not in result["requests"][0]
    assert boundary.admit(binding, canonical_json_bytes(_request(path))) == result_id
    assert (tmp_path / "workspace/sources/api/worker.py").read_text() == "def retry(): return False\n"


@pytest.mark.unit
@pytest.mark.parametrize("mutation", ["origin", "source", "escape", "duplicate", "empty", "tool", "range", "unknown-reason"])
def test_invalid_evidence_requests_cannot_change_scope_or_controller_authority(tmp_path: Path, mutation: str) -> None:
    boundary, binding, _, objects, _ = _setup(tmp_path)
    request = _request()
    row = request["requests"][0]
    if mutation == "origin": row["obligation_id"] = "sha256:" + "b" * 64
    elif mutation == "source": row["selector"]["source_id"] = "other"
    elif mutation == "escape": row["selector"]["path"] = "../credentials"
    elif mutation == "duplicate": request["requests"].append(row)
    elif mutation == "empty": request["requests"] = []
    elif mutation == "tool": row["shell"] = "read external file"
    elif mutation == "range": row["selector"]["byte_end"] = 65537
    else: row["reason_class"] = "raise-budget"
    before = {p for p in objects.root.rglob("*") if p.is_file()}
    with pytest.raises(_api().DiscoveryError):
        boundary.admit(binding, canonical_json_bytes(request))
    assert {p for p in objects.root.rglob("*") if p.is_file()} == before


@pytest.mark.unit
def test_provider_cannot_submit_more_than_a_bounded_request_batch(tmp_path: Path) -> None:
    boundary, binding, _, _, _ = _setup(tmp_path)
    request = _request()
    request["requests"] = [_request(f"missing-{i}.py")["requests"][0] for i in range(17)]
    with pytest.raises(_api().DiscoveryError):
        boundary.admit(binding, canonical_json_bytes(request))


@pytest.mark.unit
def test_distinct_request_reasons_retain_distinct_stable_identities(tmp_path: Path) -> None:
    boundary, binding, _, objects, _ = _setup(tmp_path)
    request = _request()
    second = _request()["requests"][0]
    second["reason_class"] = "relationship"
    request["requests"].append(second)
    first = boundary.admit(binding, canonical_json_bytes(request))
    rows = json.loads(objects.read_blob(first))["requests"]
    assert len({row["request_id"] for row in rows}) == 2
    assert {row["reason_class"] for row in rows} == {"missing-behavior", "relationship"}
    request["requests"].reverse()
    assert boundary.admit(binding, canonical_json_bytes(request)) == first


@pytest.mark.unit
def test_quarantine_cannot_be_nested_in_ordinary_artifacts(tmp_path: Path) -> None:
    _, _, _, objects, args = _setup(tmp_path)
    nested = ObjectStore(objects.root / "nested-quarantine")
    with pytest.raises(_api().DiscoveryError, match="quarantine-not-separate"):
        _api().DiscoveryBoundary(*args[:-1], nested)


@pytest.mark.unit
@pytest.mark.parametrize("payload", [b'{"kind":"discarded","kind":"discovery_proposal"}', b"[]", b'{"schema_version":NaN}'])
def test_malformed_or_ambiguous_json_is_not_retained(tmp_path: Path, payload: bytes) -> None:
    boundary, binding, _, objects, _ = _setup(tmp_path)
    before = {p for p in objects.root.rglob("*") if p.is_file()}
    with pytest.raises(_api().DiscoveryError):
        boundary.admit(binding, payload)
    assert {p for p in objects.root.rglob("*") if p.is_file()} == before
