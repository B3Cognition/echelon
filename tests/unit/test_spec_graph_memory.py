"""Captured memory observations preserve native planning and graph semantics."""

from dataclasses import asdict, fields, replace
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon import spec_graph
from echelon.mempalace_requirements import PlannedRequirementDrawer
from echelon.spec_graph import GraphEdge, GraphInput, GraphNode, MemoryReceipt, SpecGraphError
from echelon.spec_memory_miner import (
    plan_canonical_requirement_drawers,
    plan_canonical_support_drawers, plan_re_artifact_drawers,
    plan_spec_evidence_artifact_drawers,
)


pytestmark = pytest.mark.unit


def _api():
    return importlib.import_module("echelon.spec_graph_memory")


def _audit(**changes):
    return replace(_api().GraphMemoryAudit(
        "returned", 1, "wing", "pass", 1, 1, 1, (), (), (), (), (), (), (), (),
    ), **changes)


def _report(audit):
    values = asdict(audit)
    return SimpleNamespace(**{
        key: list(value) if type(value) is tuple else value
        for key, value in values.items() if key != "origin"
    })


def _kwargs():
    source = _api().GraphMemorySource("specs/demo/plan.md", b"captured", "supporting-context", "notes")
    digest = "b737815f5ca9697f685dfe2b5fe1f7b12a180562f97da5a72e90eaedd9890876"
    row = PlannedRequirementDrawer(
        "drawer-selected", "FR-1000000", "retained-row-room", source.path,
        "sha256:" + digest, digest, "c" * 64,
    )
    return dict(spec_id="demo", lifecycle="build", domain="canonical-spec",
                sources=(source,), planned_rows=(row,), audit=_audit(), known_node_ids=())


def _render(result):
    # Deliberately a contribution test container, not the complete graph wire.
    return (json.dumps({
        "spec_id": result.spec_id,
        "inputs": [x.to_dict() for x in sorted(result.inputs, key=lambda x: (x.role, x.path))],
        "nodes": [x.to_dict() for x in sorted(result.nodes, key=lambda x: x.id)],
        "edges": [x.to_dict() for x in sorted(result.edges, key=lambda x: (x.source, x.type, x.target))],
        "receipt": result.receipt.to_dict(),
    }, sort_keys=True, indent=2) + "\n").encode()


def _digest(payload):
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_captured_memory_retains_native_plan_after_input_damage():
    # Catch altered native identities/hashes and retained caller-owned records.
    content = b"# Requirements\n\nFR-1000000: Preserve the question identity.\n"
    source = "specs/demo/spec.md"
    digest = hashlib.sha256(content).hexdigest()
    rows = plan_canonical_requirement_drawers(
        content, source=source,
        artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + digest},
        wing="graph-test-wing",
    )
    assert [row.requirement_id for row in rows] == ["FR-1000000"]
    nodes = {"req:demo:FR-1000000": GraphNode("req:demo:FR-1000000", "Requirement", {})}
    edges = []
    spec_graph._add_drawer_rows(
        Path("specs/demo"), rows, SimpleNamespace(status="pass"), nodes, edges,
        source_artifact_kind={source: "requirement"},
    )
    node_id = "drawer:demo:" + rows[0].drawer_id
    expected_properties = {
        "drawer_id": rows[0].drawer_id,
        "source_path": source,
        "room": "functional-requirements",
        "artifact_kind": "requirement",
        "artifact_hash": "sha256:" + digest,
        "content_hash": hashlib.sha256(b"FR-1000000: Preserve the question identity.").hexdigest(),
        "presence": "present",
        "reconciliation_status": "pass",
        "issue_codes": [],
    }
    expected_edge = GraphEdge(
        "req:demo:FR-1000000", "STORED_AS", node_id,
        {"presence": "present", "reconciliation_status": "pass"},
    )
    assert edges == [expected_edge]
    assert nodes[node_id].properties == expected_properties
    module = importlib.import_module("echelon.spec_graph_memory")
    captured = module.GraphMemorySource(source, content, "requirement", "")
    audit = module.GraphMemoryAudit(
        "returned", 1, "graph-test-wing", "pass", 1, 1, 1, (), (), (), (), (), (), (), (),
    )
    result = module.build_memory_graph_contribution(
        spec_id="demo", lifecycle="build", domain="canonical-spec",
        sources=(captured,), planned_rows=tuple(rows), audit=audit,
        known_node_ids=("req:demo:FR-1000000",),
    )
    object.__setattr__(captured, "content", b"damaged")
    object.__setattr__(rows[0], "source", "damaged")
    object.__setattr__(audit, "missing", ("damaged",))
    assert result.nodes == (GraphNode(node_id, "MemPalaceDrawer", expected_properties),)
    assert result.edges == (expected_edge,)


@pytest.mark.parametrize("domain,path,kind,room,role,mining,source_digest,audit_hash", [
    ("canonical-spec", "specs/demo/plan.md", "supporting-context", "notes",
     "supporting-context", "mined",
     "sha256:c2d7f5c01e9787792e138b785e0e65d749e35f9bedd1bf5cbab5f4fc7ce66067",
     "sha256:6cf785542c6486aaacd1629afc9f61644e383a7b993019d465f6d4141f2fe4ad"),
    ("spec-evidence", "specs/demo/evidence/verify.md", "spec-evidence", "verification",
     "verification-evidence", "mined",
     "sha256:fbf300094a2b4322985f726e29ca6c1750c2e331b69adf745a8d88dd809c719b",
     "sha256:6cf785542c6486aaacd1629afc9f61644e383a7b993019d465f6d4141f2fe4ad"),
    ("published-re", "re/architecture.md", "re-architecture", "architecture",
     "reverse-engineering", "not-mined-by-policy",
     "sha256:917078a1b4bb82c41e4acb5a2be70e4b0c99f7a0f5d82b7f3d91d078cf50f10d",
     "sha256:b9466188b2271d599b4f5910f7d3ee844de4a392ff84a5916262d4770af8e4d4"),
])
def test_complete_domain_records_and_literal_hash_payloads(
    domain, path, kind, room, role, mining, source_digest, audit_hash,
):
    # Catch digest policy drift, artifact role changes, and omitted record fields.
    args = _kwargs()
    args.update(domain=domain, sources=(_api().GraphMemorySource(path, b"captured", kind, room),),
                planned_rows=(replace(args["planned_rows"][0], source=path),))
    got = _api().build_memory_graph_contribution(**args)
    digest = "sha256:b737815f5ca9697f685dfe2b5fe1f7b12a180562f97da5a72e90eaedd9890876"
    source_payload = [{"path": path, "hash": digest, "artifact_kind": kind, "room": room}]
    normalized = {
        "schema_version": 1, "wing": "wing", "status": "pass",
        "artifact_count": 0 if domain == "published-re" else 1,
        "expected_count": 1, "present_current_count": 1,
        "missing": [], "stale": [], "wrong_wing": [], "wrong_room": [],
        "duplicate": [], "non_canonical": [], "lifecycle_excluded": [], "errors": [],
    }
    assert _digest(source_payload) == source_digest
    assert _digest(normalized) == audit_hash
    virtual = "mempalace://published-re/audit" if domain == "published-re" else f"mempalace://{domain}/demo/audit"
    artifact_id = "artifact:demo:" + path
    expected = _api().MemoryGraphContribution(
        "demo", (
            GraphInput(path, digest, role.replace("-", "_"), False),
            GraphInput(virtual, audit_hash, "memory_audit_report", domain == "canonical-spec", "pass", source_digest),
        ), (
            GraphNode(artifact_id, "Artifact", {"path": path, "role": role, "hash": digest, "mining_status": mining}),
            GraphNode("drawer:demo:drawer-selected", "MemPalaceDrawer", {
                "drawer_id": "drawer-selected", "source_path": path, "room": "retained-row-room",
                "artifact_kind": kind, "artifact_hash": digest, "content_hash": "c" * 64,
                "presence": "present", "reconciliation_status": "pass", "issue_codes": [],
            }),
        ), (
            GraphEdge(artifact_id, "STORED_AS", "drawer:demo:drawer-selected",
                      {"presence": "present", "reconciliation_status": "pass"}),
        ), MemoryReceipt(domain, source_digest, audit_hash, "pass"),
    )
    assert got == expected
    assert _render(got) == _render(expected)


@pytest.mark.parametrize("status,issue,presence,reconciliation", [
    ("pass", None, "present", "pass"),
    ("fail", None, "present", "pass"),
    ("warn", None, "present", "pass"),
    ("other-observation", None, "present", "pass"),
    ("unavailable", "missing", "unavailable", "unavailable"),
    ("pass", "missing", "missing", "fail"),
    ("fail", "stale", "invalid", "fail"),
    ("warn", "wrong_wing", "invalid", "fail"),
    ("pass", "wrong_room", "invalid", "fail"),
    ("pass", "duplicate", "invalid", "fail"),
    ("pass", "non_canonical", "invalid", "fail"),
    ("pass", "lifecycle_excluded", "invalid", "fail"),
    ("warn", "errors", "present", "pass"),
])
def test_audit_observations_do_not_invent_currentness(status, issue, presence, reconciliation):
    args = _kwargs()
    changes = dict(status=status, expected_count=87, present_current_count=42)
    if issue:
        changes[issue] = ("unrelated", "drawer-selected", "drawer-selected")
    args["audit"] = _audit(**changes)
    got = _api().build_memory_graph_contribution(**args)
    props = got.nodes[-1].properties
    assert props["presence"] == presence
    assert props["reconciliation_status"] == reconciliation
    assert props["issue_codes"] == ([issue, issue] if issue and issue != "errors" else [])
    assert got.edges[0].properties == {"presence": presence, "reconciliation_status": reconciliation}
    assert got.receipt.status == status
    normalized = {
        "schema_version": 1, "wing": "wing", "status": status, "artifact_count": 1,
        "expected_count": 87, "present_current_count": 42, "missing": [], "stale": [],
        "wrong_wing": [], "wrong_room": [], "duplicate": [], "non_canonical": [],
        "lifecycle_excluded": [], "errors": [],
    }
    if issue:
        normalized[issue] = ["drawer-selected", "drawer-selected", "unrelated"]
    assert got.receipt.audit_hash == _digest(normalized)


@pytest.mark.parametrize("status,issues,want_status,want_current", [
    ("fail", {"missing": ("elsewhere",), "errors": ("global failure",)}, "pass", 1),
    ("pass", {"stale": ("drawer-selected", "elsewhere")}, "fail", 0),
    ("fail", {"duplicate": ("drawer-selected",)}, "warn", 1),
    ("fail", {"errors": ("drawer-selected: broken", "unrelated")}, "warn", 1),
    ("unavailable", {"missing": ("elsewhere",), "errors": ("global failure",)}, "unavailable", 1),
])
def test_global_re_report_is_projected_before_hashing(status, issues, want_status, want_current):
    args = _kwargs()
    path = "re/architecture.md"
    args.update(domain="published-re", sources=(replace(args["sources"][0], path=path),),
                planned_rows=(replace(args["planned_rows"][0], source=path),),
                audit=_audit(status=status, artifact_count=100, expected_count=100,
                             present_current_count=33, **issues))
    got = _api().build_memory_graph_contribution(**args)
    expected = dict(schema_version=1, wing="wing", status=want_status, artifact_count=0,
                    expected_count=1, present_current_count=want_current, missing=[], stale=[],
                    wrong_wing=[], wrong_room=[], duplicate=[], non_canonical=[], lifecycle_excluded=[], errors=[])
    for key, values in issues.items():
        expected[key] = sorted(x for x in values if x.startswith("drawer-selected"))
    assert got.receipt.status == want_status
    assert got.receipt.audit_hash == _digest(expected)


@pytest.mark.parametrize("domain", ["canonical-spec", "spec-evidence", "published-re"])
def test_empty_observation_retains_one_receipt(domain):
    args = _kwargs()
    args.update(domain=domain, sources=(), planned_rows=(), audit=_audit(status="unavailable", errors=("offline",)))
    result = _api().build_memory_graph_contribution(**args)
    assert result.nodes == result.edges == ()
    assert len(result.inputs) == 1
    assert result.receipt.source_set_digest == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    assert result.receipt.status == result.inputs[0].status == "unavailable"


@pytest.mark.parametrize("lifecycle,required", [("phase_a", False), ("build", True), ("verified", True), ("landed", True)])
@pytest.mark.parametrize("domain,role", [("canonical-spec", "supporting-context"), ("spec-evidence", "verification-evidence")])
def test_task_artifact_override_uses_supplied_lifecycle(lifecycle, required, domain, role):
    args = _kwargs()
    args.update(lifecycle=lifecycle, domain=domain, planned_rows=(),
                sources=(replace(args["sources"][0], path="specs/demo/tasks.md"),))
    got = _api().build_memory_graph_contribution(**args)
    assert got.inputs[0].required is required
    assert got.inputs[0].role == role.replace("-", "_")
    assert got.nodes[0].properties["role"] == role


@pytest.mark.parametrize("kind,known,want_source", [
    ("requirement", ("req:demo:FR-1000000",), "req:demo:FR-1000000"),
    ("requirement", (), "artifact:demo:specs/demo/plan.md"),
    ("supporting-context", ("req:demo:FR-1000000",), "artifact:demo:specs/demo/plan.md"),
])
def test_requirement_endpoint_requires_both_kind_and_known_node(kind, known, want_source):
    args = _kwargs()
    args.update(known_node_ids=known + ("unrelated",), sources=(replace(args["sources"][0], artifact_kind=kind),))
    got = _api().build_memory_graph_contribution(**args)
    assert got.edges[0].source == want_source
    assert {node.id for node in got.nodes} == {"artifact:demo:specs/demo/plan.md", "drawer:demo:drawer-selected"}


def test_source_digest_sorts_records_without_aliasing_or_reinterpreting_rooms():
    args = _kwargs()
    second = replace(args["sources"][0], path="specs/demo/other.md", content=b"other", artifact_kind="original-kind", room="")
    args.update(sources=(second, *args["sources"]), planned_rows=())
    first = _api().build_memory_graph_contribution(**args)
    second_result = _api().build_memory_graph_contribution(**(args | {"sources": tuple(reversed(args["sources"]))}))
    expected = [
        {"path": "specs/demo/other.md", "hash": "sha256:" + hashlib.sha256(b"other").hexdigest(), "artifact_kind": "original-kind", "room": ""},
        {"path": "specs/demo/plan.md", "hash": "sha256:b737815f5ca9697f685dfe2b5fe1f7b12a180562f97da5a72e90eaedd9890876", "artifact_kind": "supporting-context", "room": "notes"},
    ]
    assert first.receipt.source_set_digest == _digest(expected)
    assert _render(first) == _render(second_result)


class _Str(str):
    pass


class _Int(int):
    pass


class _Bytes(bytes):
    pass


class _Tuple(tuple):
    pass


@pytest.mark.parametrize("field,value", [
    ("spec_id", ""), ("spec_id", " demo"), ("spec_id", "demo "), ("spec_id", "."),
    ("spec_id", ".."), ("spec_id", "de/mo"), ("spec_id", "de\\mo"), ("spec_id", "de\x00mo"),
    ("spec_id", "\ud800"), ("spec_id", _Str("demo")), ("spec_id", 1),
    ("lifecycle", "unknown"), ("lifecycle", _Str("build")), ("lifecycle", None),
    ("domain", "canonical"), ("domain", _Str("canonical-spec")), ("domain", []),
    ("sources", []), ("sources", _Tuple()), ("planned_rows", []), ("planned_rows", _Tuple()),
    ("known_node_ids", []), ("known_node_ids", _Tuple()), ("known_node_ids", ("same", "same")),
    ("known_node_ids", ("",)), ("known_node_ids", (b"node",)), ("known_node_ids", (_Str("node"),)),
    ("known_node_ids", ("\ud800",)), ("audit", SimpleNamespace()),
])
def test_exact_outer_types_and_scope_reject(field, value):
    args = _kwargs()
    args[field] = value
    _assert_bounded(args)


def _assert_bounded(args):
    with pytest.raises(SpecGraphError) as caught:
        _api().build_memory_graph_contribution(**args)
    assert str(caught.value) == "invalid captured memory graph contribution"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("field,value", [
    ("path", ""), ("path", "."), ("path", ".."), ("path", "/specs/demo/plan.md"),
    ("path", "specs/demo/../plan.md"), ("path", "specs/demo/./plan.md"),
    ("path", "specs//demo/plan.md"), ("path", "specs/demo/plan.md/"),
    ("path", "specs/demo\\plan.md"), ("path", "specs/democracy/plan.md"),
    ("path", "specs/demo"), ("path", "re/plan.md"), ("path", "specs/demo/\x00plan.md"),
    ("path", "specs/demo/\ud800"), ("path", _Str("specs/demo/plan.md")), ("path", Path("specs/demo/plan.md")),
    ("content", "captured"), ("content", bytearray(b"captured")), ("content", _Bytes(b"captured")), ("content", b"modified"),
    ("artifact_kind", ""), ("artifact_kind", _Str("kind")), ("artifact_kind", "\ud800"),
    ("room", None), ("room", _Str("")), ("room", "\ud800"),
])
def test_source_values_are_validated_before_transformation(field, value):
    args = _kwargs()
    args["sources"] = (replace(args["sources"][0], **{field: value}),)
    _assert_bounded(args)


@pytest.mark.parametrize("field", ["schema_version", "artifact_count", "expected_count", "present_current_count"])
@pytest.mark.parametrize("value", [-1, True, 1.0, "1", _Int(1)])
def test_audit_counters_are_nonnegative_exact_integers(field, value):
    args = _kwargs()
    args["audit"] = _audit(**{field: value})
    _assert_bounded(args)


@pytest.mark.parametrize("field", ["missing", "stale", "wrong_wing", "wrong_room", "duplicate", "non_canonical", "lifecycle_excluded", "errors"])
@pytest.mark.parametrize("value", [[], _Tuple(), (1,), (_Str("drawer-selected"),), ("\ud800",)])
def test_every_audit_collection_is_an_exact_tuple_of_utf8_strings(field, value):
    args = _kwargs()
    args["audit"] = _audit(**{field: value})
    _assert_bounded(args)


@pytest.mark.parametrize("field,value", [
    ("wing", 1), ("wing", _Str("wing")), ("wing", "\ud800"),
    ("status", ""), ("status", None), ("status", _Str("pass")), ("status", "\ud800"),
])
def test_audit_text_validation(field, value):
    args = _kwargs()
    args["audit"] = _audit(**{field: value})
    _assert_bounded(args)


@pytest.mark.parametrize("field", [f.name for f in fields(PlannedRequirementDrawer)])
@pytest.mark.parametrize("value", ["", 1, _Str("value"), "\ud800"])
def test_all_seven_planned_fields_are_exact_nonempty_utf8_strings(field, value):
    args = _kwargs()
    args["planned_rows"] = (replace(args["planned_rows"][0], **{field: value}),)
    _assert_bounded(args)


@pytest.mark.parametrize("field,value", [
    ("artifact_hash", "b" * 64), ("artifact_hash", "sha256:" + "B" * 64),
    ("artifact_hash", "sha256:" + "0" * 64), ("canonical_spec_sha256", "0" * 64),
    ("canonical_spec_sha256", "b" * 63), ("requirement_content_sha256", "C" * 64),
    ("requirement_content_sha256", "g" * 64), ("requirement_content_sha256", "c" * 65),
    ("source", "specs/demo/missing.md"),
])
def test_planned_hashes_and_source_coherence_reject_invalid_claims(field, value):
    args = _kwargs()
    args["planned_rows"] = (replace(args["planned_rows"][0], **{field: value}),)
    _assert_bounded(args)


@pytest.mark.parametrize("kind", ["source-subclass", "audit-subclass", "row-subclass", "duck-row", "duplicate-source", "duplicate-row", "deleted-source", "deleted-row", "deleted-audit"])
def test_records_must_be_exact_complete_and_unique(kind):
    args = _kwargs()
    if kind == "source-subclass":
        subtype = type("SourceSubclass", (_api().GraphMemorySource,), {})
        args["sources"] = (subtype(**asdict(args["sources"][0])),)
    elif kind == "audit-subclass":
        subtype = type("AuditSubclass", (_api().GraphMemoryAudit,), {})
        args["audit"] = subtype(**asdict(args["audit"]))
    elif kind == "row-subclass":
        subtype = type("RowSubclass", (PlannedRequirementDrawer,), {})
        args["planned_rows"] = (subtype(**asdict(args["planned_rows"][0])),)
    elif kind == "duck-row":
        args["planned_rows"] = (SimpleNamespace(**asdict(args["planned_rows"][0])),)
    elif kind == "duplicate-source":
        args["sources"] *= 2
    elif kind == "duplicate-row":
        args["planned_rows"] *= 2
    elif kind == "deleted-source":
        object.__delattr__(args["sources"][0], "artifact_kind")
    elif kind == "deleted-row":
        object.__delattr__(args["planned_rows"][0], "room")
    else:
        object.__delattr__(args["audit"], "errors")
    _assert_bounded(args)


def test_missing_canonical_source_endpoint_is_bounded_and_main_spec_is_not_added():
    args = _kwargs()
    args["sources"] = (replace(args["sources"][0], path="specs/demo/spec.md", artifact_kind="requirement"),)
    args["planned_rows"] = (replace(args["planned_rows"][0], source="specs/demo/spec.md"),)
    _assert_bounded(args)
    args["known_node_ids"] = ("artifact:demo:specs/demo/spec.md",)
    got = _api().build_memory_graph_contribution(**args)
    assert [n.type for n in got.nodes] == ["MemPalaceDrawer"]
    assert len(got.inputs) == 1
    assert got.edges[0].source == "artifact:demo:specs/demo/spec.md"


def test_valid_retained_claims_do_not_require_semantic_proof_or_count_agreement():
    args = _kwargs()
    args["sources"] = (replace(args["sources"][0], content=b"\x00\xff", room=""),)
    digest = hashlib.sha256(b"\x00\xff").hexdigest()
    args["planned_rows"] = (replace(args["planned_rows"][0],
        artifact_hash="sha256:" + digest, canonical_spec_sha256=digest,
        requirement_content_sha256="0" * 64),)
    args["audit"] = _audit(schema_version=0, wing=None, status="unavailable",
                          artifact_count=0, expected_count=0, present_current_count=0,
                          errors=("", "retained observation"))
    got = _api().build_memory_graph_contribution(**args)
    assert got.nodes[-1].properties["content_hash"] == "0" * 64
    assert got.nodes[-1].properties["presence"] == "unavailable"


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_process_control_propagates(failure, monkeypatch):
    module = _api()
    args = _kwargs()
    def stop(*args, **kwargs):
        raise failure("control")
    monkeypatch.setattr(module, "_source_records_digest", stop)
    with pytest.raises(failure, match="control"):
        module.build_memory_graph_contribution(**args)


def test_source_bearing_exception_chain_is_discarded(monkeypatch):
    module = _api()
    args = _kwargs()
    def reject(*args, **kwargs):
        try:
            json.loads('{"private-source":')
        except Exception as exc:
            raise ValueError("private metadata") from exc
    monkeypatch.setattr(module, "_source_records_digest", reject)
    _assert_bounded(args)


def test_every_returned_record_and_nested_container_is_independently_owned():
    args = _kwargs()
    args["audit"] = _audit(duplicate=("drawer-selected",))
    first = _api().build_memory_graph_contribution(**args)
    baseline = _render(first)
    other = _api().build_memory_graph_contribution(**args)
    assert first is not other
    for left, right in zip((*first.inputs, *first.nodes, *first.edges, first.receipt),
                           (*other.inputs, *other.nodes, *other.edges, other.receipt)):
        assert left is not right
    other.nodes[-1].properties["issue_codes"].append("changed")
    other.nodes[0].properties["hash"] = "changed"
    other.edges[0].properties["presence"] = "changed"
    object.__setattr__(other.inputs[0], "path", "changed")
    object.__setattr__(other.receipt, "audit_hash", "changed")
    for item in (*args["sources"], *args["planned_rows"], args["audit"]):
        for field in fields(item):
            object.__setattr__(item, field.name, {"damaged": []})
    assert _render(first) == baseline


def test_pure_projection_never_replans_or_reads_external_state(monkeypatch):
    import builtins
    import os
    import random
    import socket
    import sqlite3
    import subprocess
    import time
    import echelon.mempalace_requirements as requirements
    import echelon.mempalace_audit as audits
    import echelon.mempalace_re as re_memory
    import echelon.mempalace_spec_evidence as evidence
    import echelon.spec_memory_miner as miner
    import harness.squad_source_snapshot as capture
    import harness.squad_source_manifest as manifest
    import echelon.spec_graph_identity as identity
    module = _api()
    content = b"FR-1000000: Preserve identity.\n"
    digest = hashlib.sha256(content).hexdigest()
    rows = plan_canonical_requirement_drawers(content, source="specs/demo/spec.md",
        artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + digest}, wing="wing")
    args = _kwargs()
    args.update(sources=(module.GraphMemorySource("specs/demo/spec.md", content, "requirement", ""),),
                planned_rows=tuple(rows), known_node_ids=("req:demo:FR-1000000",))
    def forbidden(*args, **kwargs):
        raise AssertionError("external state or native planning was accessed")
    targets = [
        (builtins, "open"), (os, "open"), (os, "stat"), (os, "lstat"), (os, "listdir"),
        (os, "scandir"), (os, "getenv"), (os, "getcwd"), (os, "urandom"),
        (Path, "read_bytes"), (Path, "read_text"), (Path, "stat"), (Path, "resolve"),
        (Path, "iterdir"), (Path, "glob"), (Path, "exists"), (Path, "write_bytes"),
        (subprocess, "Popen"), (socket, "socket"), (sqlite3, "connect"), (time, "time"),
        (random, "random"), (requirements, "create_requirement_memory_adapter"),
        (requirements, "load_canonical_spec_snapshot"), (requirements, "load_supporting_artifact_snapshots"),
        (audits, "audit_spec_memory"), (re_memory, "audit_re_memory"),
        (evidence, "audit_spec_evidence_memory"),
        (miner, "plan_canonical_requirement_drawers"), (miner, "plan_canonical_support_drawers"),
        (miner, "plan_spec_evidence_artifact_drawers"), (miner, "plan_re_artifact_drawers"),
        (miner, "scrub_secrets"), (capture, "inspect_project_tree"),
        (manifest, "snapshot_source_manifest"), (identity, "project_identity_history"),
    ]
    with monkeypatch.context() as guard:
        for owner, name in targets:
            guard.setattr(owner, name, forbidden)
        got = module.build_memory_graph_contribution(**args)
    assert got.nodes[0].properties["drawer_id"] == rows[0].drawer_id


class _NativeAdapter:
    """Only replace external adapter construction; actual planners stay real."""
    def __init__(self, events, *, fail_source=None, failure=None):
        self.events = events
        self.fail_source = fail_source
        self.failure = failure
        self.rows = []

    def _plan(self, planner, content, source, metadata):
        self.events.append(("plan", source))
        if source == self.fail_source:
            raise self.failure("external unavailable")
        rows = planner(content, source=source, artifact_metadata=metadata, wing="wing")
        # The legacy adapter's seven-field plan type retains its import identity.
        rows = [PlannedRequirementDrawer(**asdict(row)) for row in rows]
        self.rows.extend(rows)
        return rows

    def plan_canonical_rows(self, content, *, source, artifact_metadata):
        return self._plan(plan_canonical_requirement_drawers, content, source, artifact_metadata)

    def plan_canonical_support_rows(self, content, *, source, artifact_metadata):
        return self._plan(plan_canonical_support_drawers, content, source, artifact_metadata)

    def plan_spec_evidence_artifact_rows(self, content, *, source, artifact_metadata):
        return self._plan(plan_spec_evidence_artifact_drawers, content, source, artifact_metadata)

    def plan_re_artifact_rows(self, content, *, source, artifact_metadata):
        return self._plan(plan_re_artifact_drawers, content, source, artifact_metadata)


_NATIVE_SPEC = (
    b"# Requirements\n\nFR-000001: Six digits.\n"
    b"FR-1000000: Seven digits.\nNFR-10000000: Eight digits.\nFR-016b: Legacy suffix.\n"
)


@pytest.mark.parametrize("failure_name,stage,retains_rows", [
    (None, "audit", True),
    ("RuntimeError", "audit", True),
    ("SystemExit", "audit", True),
    ("SpecMemoryError", "audit", False),
    ("RuntimeError", "support", True),
    ("SpecMemoryError", "support", False),
])
def test_real_canonical_helper_preserves_native_rows_and_exception_continuation(
    tmp_path, monkeypatch, failure_name, stage, retains_rows,
):
    from echelon import mempalace_requirements as requirements
    from echelon import mempalace_audit as audits
    from echelon.spec_graph_structure import build_spec_graph_structure
    spec_dir = tmp_path / "specs/demo"
    spec_dir.mkdir(parents=True)
    files = {"spec.md": _NATIVE_SPEC, "plan.md": b"# Plan\n\nKeep FR-1000000 intact.\n",
             "tasks.md": b"- [ ] T-1000000 complexity=trivial phase=build req=FR-1000000 depends=none\n"}
    for name, content in files.items():
        (spec_dir / name).write_bytes(content)
    # Real legacy lifecycle inference needs an actual build marker.
    (spec_dir / "run-history.json").write_text("{}", encoding="utf-8")
    structure = build_spec_graph_structure(spec_id="demo", tree=_tree(files), lifecycle="build")
    events = []
    failures = {"RuntimeError": RuntimeError, "SystemExit": SystemExit, "SpecMemoryError": requirements.SpecMemoryError}
    failure = failures.get(failure_name)
    adapter = _NativeAdapter(events, fail_source="specs/demo/tasks.md" if stage == "support" else None, failure=failure)
    observed_audit = _audit(artifact_count=0, expected_count=19, present_current_count=18,
                            status="warn", errors=("unrelated observation",))
    def make_adapter(root, run_id):
        assert root == tmp_path and run_id == "graph"
        events.append(("adapter",))
        return adapter
    def audit(root, selector):
        assert root == tmp_path and selector == spec_dir
        events.append(("audit",))
        if failure:
            raise failure("external unavailable")
        return _report(observed_audit)
    monkeypatch.setattr(requirements, "create_requirement_memory_adapter", make_adapter)
    monkeypatch.setattr(audits, "audit_spec_memory", audit)
    nodes = {node.id: node for node in structure.nodes}
    before_nodes = dict(nodes)
    inputs = {item.path: item for item in structure.inputs}
    before_inputs = dict(inputs)
    edges, receipts = [], []
    spec_graph._add_canonical_memory(tmp_path, spec_dir, nodes, edges, inputs, receipts)
    assert events == [
        ("adapter",), ("plan", "specs/demo/spec.md"), ("plan", "specs/demo/plan.md"),
        ("plan", "specs/demo/tasks.md"), *([("audit",)] if stage == "audit" else []),
    ]
    snapshots = [requirements.load_canonical_spec_snapshot(tmp_path, spec_dir),
                 *requirements.load_supporting_artifact_snapshots(tmp_path, spec_dir)]
    sources = tuple(_api().GraphMemorySource(
        item.source, item.content, item.artifact_metadata.get("artifact_kind", "requirement"),
        item.artifact_metadata.get("room", ""),
    ) for item in snapshots)
    if failure:
        observed_audit = _audit(origin="exception", wing=None, status="unavailable", artifact_count=0,
                               expected_count=0, present_current_count=0, errors=(failure_name,))
    contribution = _api().build_memory_graph_contribution(
        spec_id="demo", lifecycle="build", domain="canonical-spec",
        sources=sources, planned_rows=tuple(adapter.rows) if retains_rows else (),
        audit=observed_audit, known_node_ids=tuple(before_nodes),
    )
    # Include replaced support artifacts even if a value equals its old record.
    contributed_ids = {node.id for node in contribution.nodes}
    contributed_paths = {item.path for item in contribution.inputs}
    actual = _api().MemoryGraphContribution(
        "demo", tuple(inputs[path] for path in contributed_paths),
        tuple(nodes[node_id] for node_id in contributed_ids), tuple(edges), receipts[0],
    )
    assert _render(actual) == _render(contribution)
    assert set(nodes) == set(before_nodes) | contributed_ids
    assert set(inputs) == set(before_inputs) | contributed_paths
    assert len(receipts) == 1
    assert [row.requirement_id for row in adapter.rows[:4]] == [
        "FR-000001", "FR-1000000", "NFR-10000000", "FR-016b",
    ]
    for row, body in zip(adapter.rows[:4], [
        b"FR-000001: Six digits.", b"FR-1000000: Seven digits.",
        b"NFR-10000000: Eight digits.", b"FR-016b: Legacy suffix.",
    ]):
        assert row.requirement_content_sha256 == hashlib.sha256(body).hexdigest()
        assert row.canonical_spec_sha256 == hashlib.sha256(_NATIVE_SPEC).hexdigest()
    if retains_rows:
        assert sum(n.type == "MemPalaceDrawer" for n in contribution.nodes) == len(adapter.rows)
        assert all(e.properties["presence"] == ("unavailable" if failure else "present") for e in edges)
    else:
        assert edges == []
    assert next(n for n in contribution.nodes if n.id.endswith("/tasks.md")).properties["role"] == "supporting-context"
    assert next(i for i in contribution.inputs if i.path.endswith("/tasks.md")).required is True


@pytest.mark.parametrize("domain", ["spec-evidence", "published-re"])
@pytest.mark.parametrize("failure_name,stage", [(None, "audit"), ("RuntimeError", "audit"), ("SpecMemoryError", "audit"), ("RuntimeError", "second-plan")])
def test_real_artifact_domain_helpers_preserve_planning_projection_and_partial_rows(
    tmp_path, domain, failure_name, stage,
):
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_re import ReArtifactSnapshot
    from echelon.mempalace_spec_evidence import SpecEvidenceArtifactSnapshot
    spec_dir = tmp_path / "specs/demo"
    spec_dir.mkdir(parents=True)
    is_re = domain == "published-re"
    paths = ("re/architecture.md", "re/components.md") if is_re else (
        "specs/demo/evidence/verify.md", "specs/demo/evidence/qa.md",
    )
    snapshots = []
    for path in paths:
        content = b"# Results\n\nFR-1000000 retains its original evidence.\n"
        artifact_file = tmp_path / path
        artifact_file.parent.mkdir(parents=True, exist_ok=True)
        artifact_file.write_bytes(content)
        metadata = dict(canonical=True, artifact_hash="sha256:" + hashlib.sha256(content).hexdigest(),
                        artifact_kind="re-architecture" if is_re else "spec-evidence",
                        scope="reverse-engineering" if is_re else "spec-evidence", room="original-room")
        snapshots.append(ReArtifactSnapshot(tmp_path / "re", artifact_file, content, path, metadata)
                         if is_re else SpecEvidenceArtifactSnapshot("demo", spec_dir, artifact_file, content, path, metadata))
    events = []
    failure = {"RuntimeError": RuntimeError, "SpecMemoryError": SpecMemoryError}.get(failure_name)
    adapter = _NativeAdapter(events, fail_source=paths[1] if stage == "second-plan" else None, failure=failure)
    observed = _audit(artifact_count=45, expected_count=99, present_current_count=20,
                      status="fail", missing=("global-other-drawer",), errors=("unrelated global error",))
    def factory():
        events.append(("adapter",))
        return adapter
    def audit():
        events.append(("audit",))
        if failure:
            raise failure("storage unavailable")
        return _report(observed)
    inputs, nodes, edges, receipts = {}, {}, [], []
    virtual = "mempalace://published-re/audit" if is_re else "mempalace://spec-evidence/demo/audit"
    spec_graph._add_artifact_memory_domain(
        root=tmp_path, spec_dir=spec_dir, domain=domain, virtual_path=virtual,
        snapshots=snapshots,
        planner_name="plan_re_artifact_rows" if is_re else "plan_spec_evidence_artifact_rows",
        adapter_factory=factory, audit=audit, required=False,
        nodes=nodes, edges=edges, inputs=inputs, receipts=receipts, project_audit=is_re,
    )
    assert events == [("adapter",), ("plan", paths[0]), ("plan", paths[1]),
                      *([("audit",)] if stage == "audit" else [])]
    if failure:
        observed = _audit(origin="exception", wing=None, status="unavailable", artifact_count=0, expected_count=0,
                          present_current_count=0, errors=(failure_name,))
    # Explicit origin preserves the legacy exception branch's projection bypass.
    sources = tuple(_api().GraphMemorySource(
        item.source, item.content, item.artifact_metadata["artifact_kind"], item.artifact_metadata["room"],
    ) for item in snapshots)
    captured = _api().build_memory_graph_contribution(
        spec_id="demo", lifecycle="build", domain=domain, sources=sources,
        planned_rows=tuple(adapter.rows), audit=observed, known_node_ids=(),
    )
    assert tuple(nodes.values()) == captured.nodes
    assert tuple(edges) == captured.edges
    actual = _api().MemoryGraphContribution("demo", tuple(inputs.values()), tuple(nodes.values()), tuple(edges), receipts[0])
    assert _render(actual) == _render(captured)
    if is_re and failure:
        expected_audit = dict(schema_version=1, wing=None, status="unavailable", artifact_count=0,
            expected_count=0, present_current_count=0, missing=[], stale=[], wrong_wing=[], wrong_room=[],
            duplicate=[], non_canonical=[], lifecycle_excluded=[], errors=[failure_name])
        assert receipts[0].audit_hash == _digest(expected_audit)
        assert receipts[0].audit_hash == captured.receipt.audit_hash
        assert receipts[0].source_set_digest == captured.receipt.source_set_digest
    assert len(adapter.rows) == (1 if stage == "second-plan" else 2)
    assert all(node.properties["room"] == "original-room" for node in nodes.values() if node.type == "MemPalaceDrawer")


def test_legacy_duck_types_defaults_lists_and_duplicate_updates_are_preserved():
    row = SimpleNamespace(drawer_id=17, source=23, room=None, artifact_hash=False, requirement_content_sha256=42)
    nodes = {"artifact:demo:23": GraphNode("artifact:demo:23", "Artifact", {})}
    edges = []
    report = SimpleNamespace(status=None, missing=("17",), stale=[17], duplicate=["17"])
    spec_graph._add_drawer_rows(Path("specs/demo"), [row, row], report, nodes, edges, source_artifact_kind={})
    assert nodes["drawer:demo:17"].properties == {
        "drawer_id": "17", "source_path": "23", "room": "None", "artifact_kind": "unknown",
        "artifact_hash": "False", "content_hash": "42", "presence": "invalid",
        "reconciliation_status": "fail", "issue_codes": ["duplicate"],
    }
    assert edges == [GraphEdge("artifact:demo:23", "STORED_AS", "drawer:demo:17",
                              {"presence": "invalid", "reconciliation_status": "fail"})] * 2
    report = SimpleNamespace(schema_version="2", status=None, expected_count=True,
                             missing=("z", 17), errors={"b": 1, "a": 2})
    assert spec_graph._normalized_memory_audit(report) == {
        "schema_version": 2, "wing": None, "status": "None", "artifact_count": 0,
        "expected_count": 1, "present_current_count": 0, "missing": ["17", "z"],
        "stale": [], "wrong_wing": [], "wrong_room": [], "duplicate": [], "non_canonical": [],
        "lifecycle_excluded": [], "errors": ["a", "b"],
    }
    assert spec_graph._memory_source_set_digest([SimpleNamespace(source=23)]) == _digest([
        {"path": "23", "hash": "None", "artifact_kind": "requirement", "room": ""},
    ])
    # The old helper mutates its drawer dictionary before raising for an endpoint.
    nodes, edges = {}, []
    with pytest.raises(SpecGraphError, match="memory planner source has no Artifact node: 23"):
        spec_graph._add_drawer_rows(Path("specs/demo"), [row], SimpleNamespace(), nodes, edges,
                                   source_artifact_kind={})
    assert nodes["drawer:demo:17"].properties["presence"] == "unavailable"
    assert edges == []


def _tree(files):
    from harness.squad_publication_snapshot import PublicationImageDescriptor
    from harness.squad_source_snapshot import ProjectDirectorySnapshot, ProjectFileSnapshot, ProjectTreeSnapshot
    return ProjectTreeSnapshot("specs/demo", True, (ProjectDirectorySnapshot("specs/demo", 0o755),), tuple(
        ProjectFileSnapshot("specs/demo/" + name,
            PublicationImageDescriptor("file", hashlib.sha256(content).hexdigest(), 0o644), content)
        for name, content in sorted(files.items())
    ))


def test_native_drawer_keys_and_old_body_hashes_survive_later_source_change():
    results = []
    native_rows = []
    for content in (_NATIVE_SPEC, _NATIVE_SPEC.replace(b"Seven digits.", b"Revised seven digits.")):
        digest = hashlib.sha256(content).hexdigest()
        rows = plan_canonical_requirement_drawers(
            content, source="specs/demo/spec.md", artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + digest},
            wing="wing",
        )
        native_rows.append(rows)
        results.append(_api().build_memory_graph_contribution(
            spec_id="demo", lifecycle="build", domain="canonical-spec",
            sources=(_api().GraphMemorySource("specs/demo/spec.md", content, "requirement", ""),),
            planned_rows=tuple(rows), audit=_audit(), known_node_ids=tuple("req:demo:" + row.requirement_id for row in rows),
        ))
    original_render = _render(results[0])
    for index, (label, room, body) in enumerate([
        ("FR-000001", "functional-requirements", b"FR-000001: Six digits."),
        ("FR-1000000", "functional-requirements", b"FR-1000000: Seven digits."),
        ("NFR-10000000", "non-functional-requirements", b"NFR-10000000: Eight digits."),
        ("FR-016b", "functional-requirements", b"FR-016b: Legacy suffix."),
    ]):
        old_row = native_rows[0][index]
        payload = {
            "schema_version": 1, "wing": "wing", "room": room,
            "canonical_spec_sha256": hashlib.sha256(_NATIVE_SPEC).hexdigest(),
            "requirement_id": label, "requirement_content_sha256": hashlib.sha256(body).hexdigest(),
        }
        want_id = "drawer_wing_" + room + "_" + _digest(payload).removeprefix("sha256:")
        assert old_row.drawer_id == want_id
        assert results[0].nodes[index].id == "drawer:demo:" + want_id
        assert results[0].nodes[index].properties["content_hash"] == hashlib.sha256(body).hexdigest()
        assert native_rows[1][index].drawer_id != old_row.drawer_id
        assert results[1].edges[index].source == results[0].edges[index].source == "req:demo:" + label
    assert results[1].nodes[1].properties["content_hash"] == hashlib.sha256(b"FR-1000000: Revised seven digits.").hexdigest()
    assert results[1].receipt.source_set_digest != results[0].receipt.source_set_digest
    assert _render(results[0]) == original_render


def test_structure_memory_and_retained_history_compose_without_reassessing_old_evidence(tmp_path):
    from echelon.spec_graph import SpecArtifactGraph, render_spec_graph
    from echelon.spec_graph_structure import build_spec_graph_structure
    from echelon.spec_graph_identity import project_identity_history
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate, ElementRevision
    from harness.element_identity_bindings import ReferenceClaim
    # Offline identity fixture acquisition finishes before graph composition.
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    assert label == "FR-000001"
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Requirement", "Original body", "reserve"),))
    store.record_reference_claims(spec_id="demo", operation_id="evidence", claims=(
        ReferenceClaim("old-evidence.md", "a" * 64, "span:0:9", label, "1", "evidence"),))
    store.apply_lifecycle(spec_id="demo", operation_id="revise", changes=(
        ElementRevision(label, "1", "Requirement", "Revised body"),))
    store.import_identities(spec_id="demo", operation_id="task", definitions=(("T-1000000", "Build"),))
    history = store.identity_history(spec_id="demo")
    content = b"FR-000001: Revised body.\n"
    files = {
        "spec.md": content,
        "tasks.md": b"- [x] T-1000000 complexity=trivial phase=build req=FR-000001 depends=none\n",
        "verified-fulfillment-ledger.json": json.dumps({"schema_version": 1, "rows": [{
            "requirement_id": "FR-000001", "status": "implemented", "evidence_refs": ["old-evidence.md"],
            "spec_input_hash": "old-spec", "verified_commit": "old-commit", "verified_at": "2026-09-01",
        }]}).encode(),
    }
    structure = build_spec_graph_structure(spec_id="demo", lifecycle="build", tree=_tree(files))
    digest = hashlib.sha256(content).hexdigest()
    rows = plan_canonical_requirement_drawers(content, source="specs/demo/spec.md",
        artifact_metadata={"canonical": True, "artifact_hash": "sha256:" + digest}, wing="wing")
    memory = _api().build_memory_graph_contribution(
        spec_id="demo", lifecycle="build", domain="canonical-spec",
        sources=(_api().GraphMemorySource("specs/demo/spec.md", content, "requirement", ""),),
        planned_rows=tuple(rows), audit=_audit(status="warn", errors=("old memory observation",)),
        known_node_ids=tuple(node.id for node in structure.nodes),
    )
    node_map = {node.id: node for node in (*structure.nodes, *memory.nodes)}
    input_map = {item.path: item for item in (*structure.inputs, *memory.inputs)}
    graph = SpecArtifactGraph("demo", "offline-test-container", tuple(input_map.values()),
                              tuple(node_map.values()), structure.edges + memory.edges, (memory.receipt,))
    projected = project_identity_history(graph, history)
    payload = json.loads(render_spec_graph(projected))
    assert render_spec_graph(projected) == render_spec_graph(project_identity_history(graph, history))
    by_id = {node["id"]: node for node in payload["nodes"]}
    assert by_id["req:demo:FR-000001"]["properties"]["identity"]["revision"] == "2"
    assert by_id["task:demo:T-1000000"]["properties"]["task_id"] == "T-1000000"
    assert by_id[memory.nodes[0].id]["properties"] == memory.nodes[0].properties
    old = next(node for node in projected.nodes if node.type == "ElementRevision" and node.properties["revision"] == "1")
    assert old.properties["content"] == "Original body"
    assert old.properties["content_sha256"] == hashlib.sha256(b"Original body").hexdigest()
    claim = next(node for node in projected.nodes if node.type == "ReferenceClaim")
    assert claim.properties["target_revision_matches_current"] is False
    assert GraphEdge(claim.id, "ASSESSES_REVISION", old.id, {}) in projected.edges
    legacy_edges = [edge for edge in projected.edges if edge.type in {"VERIFIED_BY", "STORED_AS"}]
    assert {edge.type for edge in legacy_edges} == {"VERIFIED_BY", "STORED_AS"}
    assert all(edge.source == "req:demo:FR-000001" and edge.properties["identity_assessment"] == "unassessed"
               for edge in legacy_edges)
    verified = next(edge for edge in legacy_edges if edge.type == "VERIFIED_BY")
    assert verified.properties["evidence_refs"] == ["old-evidence.md"]
    assert verified.properties["verified_commit"] == "old-commit"
    assert verified.properties["verification_status"] == "IMPLEMENTED"
    assert next(edge for edge in legacy_edges if edge.type == "STORED_AS").properties["presence"] == "present"
    assert projected.memory_receipts == (memory.receipt,)
    assert "identity_assessment" not in memory.edges[0].properties


@pytest.mark.parametrize("first", ["echelon.spec_graph_memory", "echelon.spec_graph", "echelon.spec_graph_structure"])
def test_import_orders_keep_existing_model_and_plan_identities(first):
    import os
    import subprocess
    import sys
    code = """
import importlib
importlib.import_module(FIRST)
from echelon import spec_graph as graph, spec_graph_memory as memory, spec_graph_structure as structure
from echelon.mempalace_requirements import PlannedRequirementDrawer
from echelon.spec_memory_miner import CanonicalRequirementDrawerPlan
assert memory.GraphInput is structure.GraphInput is graph.GraphInput
assert memory.GraphNode is structure.GraphNode is graph.GraphNode
assert memory.GraphEdge is structure.GraphEdge is graph.GraphEdge
assert memory.MemoryReceipt is graph.MemoryReceipt
assert memory.PlannedRequirementDrawer is PlannedRequirementDrawer
assert memory.CanonicalRequirementDrawerPlan is CanonicalRequirementDrawerPlan
assert graph._normalized_memory_audit(object())["status"] == "unavailable"
"""
    completed = subprocess.run([sys.executable, "-c", code.replace("FIRST", repr(first))],
        env={**os.environ, "PYTHONPATH": "src"}, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == completed.stderr == ""


def test_returned_unavailable_and_exception_origin_match_real_legacy_re(tmp_path):
    from echelon.mempalace_re import ReArtifactSnapshot
    module = _api()
    path = "re/architecture.md"
    content = b"# Results\n\nOriginal observation.\n"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    artifact = tmp_path / path
    artifact.parent.mkdir()
    artifact.write_bytes(content)
    metadata = dict(canonical=True, artifact_hash=digest, artifact_kind="re-architecture",
                    scope="reverse-engineering", room="original-room")
    snapshot = ReArtifactSnapshot(tmp_path / "re", artifact, content, path, metadata)
    source_digest = _digest([{"path": path, "hash": digest, "artifact_kind": "re-architecture", "room": "original-room"}])
    fallback_values = dict(schema_version=1, wing=None, status="unavailable", artifact_count=0,
        expected_count=0, present_current_count=0, missing=(), stale=(), wrong_wing=(), wrong_room=(),
        duplicate=(), non_canonical=(), lifecycle_excluded=(), errors=("RuntimeError",))
    observations = []
    # Exercise and check BOTH real legacy branches before using the new origin API.
    for origin in ("exception", "returned"):
        adapter = _NativeAdapter([])
        def audit():
            if origin == "exception":
                raise RuntimeError("external acquisition failed")
            return SimpleNamespace(**{key: list(value) if type(value) is tuple else value for key, value in fallback_values.items()})
        nodes, inputs, edges, receipts = {}, {}, [], []
        spec_graph._add_artifact_memory_domain(
            root=tmp_path, spec_dir=tmp_path / "specs/demo", domain="published-re",
            virtual_path="mempalace://published-re/audit", snapshots=[snapshot],
            planner_name="plan_re_artifact_rows", adapter_factory=lambda: adapter, audit=audit,
            required=False, nodes=nodes, edges=edges, inputs=inputs, receipts=receipts, project_audit=True,
        )
        row, = adapter.rows
        expected_payload = dict(schema_version=1, wing=None, status="unavailable", artifact_count=0,
            expected_count=0 if origin == "exception" else 1,
            present_current_count=0 if origin == "exception" else 1,
            missing=[], stale=[], wrong_wing=[], wrong_room=[], duplicate=[], non_canonical=[],
            lifecycle_excluded=[], errors=["RuntimeError"] if origin == "exception" else [])
        audit_hash = _digest(expected_payload)
        expected = module.MemoryGraphContribution("demo", (
            GraphInput(path, digest, "reverse_engineering", False),
            GraphInput("mempalace://published-re/audit", audit_hash, "memory_audit_report", False, "unavailable", source_digest),
        ), (
            GraphNode("artifact:demo:" + path, "Artifact", {
                "path": path, "hash": digest, "role": "reverse-engineering", "mining_status": "not-mined-by-policy",
            }),
            GraphNode("drawer:demo:" + row.drawer_id, "MemPalaceDrawer", {
                "drawer_id": row.drawer_id, "source_path": path, "room": "original-room",
                "artifact_kind": "re-architecture", "artifact_hash": digest,
                "content_hash": hashlib.sha256(b"RE-re-architecture-md-000: Results: Original observation.").hexdigest(),
                "presence": "unavailable", "reconciliation_status": "unavailable", "issue_codes": [],
            }),
        ), (
            GraphEdge("artifact:demo:" + path, "STORED_AS", "drawer:demo:" + row.drawer_id,
                      {"presence": "unavailable", "reconciliation_status": "unavailable"}),
        ), MemoryReceipt("published-re", source_digest, audit_hash, "unavailable"))
        legacy = module.MemoryGraphContribution("demo", tuple(inputs.values()), tuple(nodes.values()), tuple(edges), receipts[0])
        assert legacy == expected
        observations.append((origin, tuple(adapter.rows), expected))
    assert observations[0][2].receipt.audit_hash != observations[1][2].receipt.audit_hash
    for origin, rows, expected in observations:
        audit = module.GraphMemoryAudit(origin=origin, **fallback_values)
        actual = module.build_memory_graph_contribution(
            spec_id="demo", lifecycle="build", domain="published-re",
            sources=(module.GraphMemorySource(path, content, "re-architecture", "original-room"),),
            planned_rows=rows, audit=audit, known_node_ids=(),
        )
        assert actual == expected
        assert _render(actual) == _render(expected)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 0), ("wing", "wing"), ("status", "pass"),
    ("artifact_count", 1), ("expected_count", 1), ("present_current_count", 1),
    ("missing", ("drawer-selected",)), ("stale", ("drawer-selected",)),
    ("wrong_wing", ("drawer-selected",)), ("wrong_room", ("drawer-selected",)),
    ("duplicate", ("drawer-selected",)), ("non_canonical", ("drawer-selected",)),
    ("lifecycle_excluded", ("drawer-selected",)), ("errors", ()), ("errors", ("",)),
    ("errors", ("RuntimeError", "OtherError")),
])
def test_exception_origin_requires_exact_legacy_fallback_shape(field, value):
    args = _kwargs()
    args["audit"] = _audit(origin="exception", schema_version=1, wing=None, status="unavailable",
                          artifact_count=0, expected_count=0, present_current_count=0,
                          errors=("RuntimeError",))
    args["audit"] = replace(args["audit"], **{field: value})
    _assert_bounded(args)


def test_missing_or_invalid_origin_is_not_inferred_from_status():
    args = _kwargs()
    for value in (None, "", "unavailable", _Str("returned"), "\ud800"):
        args["audit"] = _audit(origin=value, status="unavailable")
        _assert_bounded(args)
    args["audit"] = _audit(status="unavailable")
    object.__delattr__(args["audit"], "origin")
    _assert_bounded(args)
