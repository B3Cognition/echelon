"""Strict wire recovery for existing immutable identity requests."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import sqlite3
import sys

import pytest

from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle as lifecycle
from harness.element_identity_request_codec import (
    IdentityRequestCodecError,
    decode_request,
    encode_request,
)
from harness.element_identity_store import IdentityStore, IdentityStoreError, _digest


pytestmark = pytest.mark.unit

SPEC = "demo"
SHA256 = hashlib.sha256(b"source bytes").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sql_state(path):
    with sqlite3.connect(path / ".echelon/identity/registry.sqlite3") as connection:
        return tuple(connection.iterdump())


def claim(**changes):
    value = bindings.ReferenceClaim(
        "evidence/grades.md", SHA256, "span:1:4", "FR-000001", "1", "evidence",
    )
    return replace(value, **changes)


def occurrence(**changes):
    value = bindings.IssueOccurrence(
        "ISS-000001", "1", "report legacy/1", SHA256, "ISS-old.alpha",
        "  Unicode Δ title  ", "Exact body.\r\n  Keep spaces. λ",
    )
    return replace(value, **changes)


def test_encoded_existing_lifecycle_request_retries_after_reopen(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    changes = (lifecycle.ElementCreate(label, "Scene", "Original body.\r\n", "reserve"),)
    original = store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=changes)
    payload = canonical(lifecycle.request(changes)[1])

    decoded = decode_request("lifecycle", payload)
    assert decoded == changes
    reopened = IdentityStore.open(tmp_path)
    assert reopened.apply_lifecycle(
        spec_id=SPEC, operation_id="create", changes=decoded,
    ) == original


@pytest.mark.parametrize("change", [
    lifecycle.ElementCreate("FR-000001", "  Scene Δ  ", "Body\r\n λ ", "reserve"),
    lifecycle.ElementAdopt("FR-001.alpha", "Legacy", " Exact legacy.\n"),
    lifecycle.ElementRevision("FR-0000001", "9" * 5000, "Scene", "Revision"),
    lifecycle.ElementRetirement("FR-00000001", "2", " Historical reason "),
    lifecycle.ElementTransition(
        "replace", (("FR-000001", "1"),),
        (lifecycle.ElementCreate("FR-000002", "Next", "Body", "reserve"),), "Replace",
    ),
    lifecycle.ElementTransition(
        "split", (("FR-000001", "1"),),
        (
            lifecycle.ElementCreate("FR-000002", "Left", "L", "reserve"),
            lifecycle.ElementCreate("FR-000003", "Right", "R", "reserve"),
        ), "Split",
    ),
    lifecycle.ElementTransition(
        "merge", (("FR-000001", "1"), ("FR-000002", "7")),
        (lifecycle.ElementCreate("FR-000003", "Merged", "M", "reserve"),), "Merge",
    ),
])
def test_lifecycle_variants_round_trip_with_exact_canonical_existing_payload(change):
    entries = (change,)
    expected_payload = lifecycle.request(entries)[1]
    before = repr(entries)
    encoded = encode_request("lifecycle", entries)
    decoded = decode_request("lifecycle", encoded)
    assert encoded == canonical(expected_payload)
    assert encoded.isascii()
    assert decoded == entries
    assert repr(entries) == before
    assert _digest(["lifecycle", SPEC, lifecycle.request(decoded)[1]]) == _digest(
        ["lifecycle", SPEC, expected_payload],
    )


def test_mixed_disjoint_lifecycle_batch_preserves_order_and_nested_immutability():
    changes = (
        lifecycle.ElementCreate("AC-000001", "A", " first \r\n", "reserve-a"),
        lifecycle.ElementAdopt("FR-legacy.part", "B", "λ"),
        lifecycle.ElementRevision("NFR-12345678", "123", "C", "third"),
        lifecycle.ElementRetirement("U-1234567", "8", "done"),
        lifecycle.ElementTransition(
            "replace", (("T-123456", "9"),),
            (lifecycle.ElementCreate("T-123457", "E", "fifth", "reserve-t"),), "move",
        ),
    )
    decoded = decode_request("lifecycle", encode_request("lifecycle", list(changes)))
    assert decoded == changes
    assert type(decoded) is tuple
    transition = decoded[-1]
    assert type(transition.predecessors) is tuple
    assert type(transition.predecessors[0]) is tuple
    assert type(transition.successors) is tuple
    with pytest.raises(FrozenInstanceError):
        transition.reason = "changed"
    with pytest.raises(FrozenInstanceError):
        transition.successors[0].content = "changed"


def test_arbitrary_width_string_labels_and_revisions_are_preserved():
    digits = "9" * 5000
    value = lifecycle.ElementRevision("FR-" + digits, digits, "Wide", "Still strings")
    assert decode_request("lifecycle", encode_request("lifecycle", (value,))) == (value,)


@pytest.mark.parametrize("relation", ["reference", "requires", "depends", "evidence"])
@pytest.mark.parametrize("revision", [None, "1", "9" * 5000])
def test_reference_claims_round_trip_assessment_and_relations(relation, revision):
    entries = (claim(target_revision=revision, relation=relation),)
    expected = bindings.request(entries, bindings.ReferenceClaim)
    encoded = encode_request("reference_claims", entries)
    decoded = decode_request("reference_claims", encoded)
    assert encoded == canonical(expected)
    assert decoded == entries
    assert _digest(["reference_claims", SPEC, "op", bindings.request(
        decoded, bindings.ReferenceClaim,
    )]) == _digest(["reference_claims", SPEC, "op", expected])


def test_issue_occurrence_round_trip_preserves_exact_legacy_display_and_content():
    entries = (occurrence(),)
    expected = bindings.request(entries, bindings.IssueOccurrence)
    encoded = encode_request("issue_occurrences", entries)
    decoded = decode_request("issue_occurrences", encoded)
    assert encoded == canonical(expected)
    assert decoded == entries
    assert decoded[0].display_id == "ISS-old.alpha"
    assert decoded[0].title == "  Unicode Δ title  "
    assert decoded[0].body == "Exact body.\r\n  Keep spaces. λ"


class StringSubclass(str):
    pass


class CreateSubclass(lifecycle.ElementCreate):
    pass


class ClaimSubclass(bindings.ReferenceClaim):
    pass


@pytest.mark.parametrize("method", ["", "Lifecycle", "reference", "issue_occurrence", None, 1, True])
def test_unknown_or_nonexact_methods_reject(method):
    with pytest.raises(IdentityRequestCodecError):
        decode_request(method, "[]")
    with pytest.raises(IdentityRequestCodecError):
        encode_request(method, ())


def test_subclassed_method_payload_and_entries_reject():
    good = canonical([["ElementAdopt", {
        "element_id": "FR-old", "subject": "Old", "content": "Body",
    }]])
    with pytest.raises(IdentityRequestCodecError):
        decode_request(StringSubclass("lifecycle"), good)
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", StringSubclass(good))
    with pytest.raises(IdentityRequestCodecError):
        encode_request(StringSubclass("lifecycle"), ())
    with pytest.raises(IdentityRequestCodecError):
        encode_request(
            "lifecycle", (CreateSubclass("FR-000001", "A", "B", "reserve"),),
        )
    with pytest.raises(IdentityRequestCodecError):
        encode_request("reference_claims", (ClaimSubclass(
            "a.md", SHA256, "A", "FR-old", None, "reference",
        ),))


@pytest.mark.parametrize("method,payload", [
    ("lifecycle", "{}"), ("lifecycle", "null"), ("lifecycle", "true"),
    ("lifecycle", '"text"'), ("lifecycle", "[]"), ("lifecycle", "[null]"),
    ("lifecycle", "[{}]"), ("lifecycle", '[["ElementCreate"]]'),
    ("lifecycle", '[["ElementCreate",{},"extra"]]'),
    ("lifecycle", '[["ElementCreate",[]]]'),
    ("lifecycle", '[["Unknown",{}]]'), ("reference_claims", "{}"),
    ("reference_claims", "[]"), ("reference_claims", "[[]]"),
    ("reference_claims", "[null]"), ("issue_occurrences", "[[]]"),
])
def test_outer_and_entry_shape_matrix_rejects(method, payload):
    with pytest.raises(IdentityRequestCodecError):
        decode_request(method, payload)


@pytest.mark.parametrize("method,entry", [
    ("lifecycle", ["ElementAdopt", {"element_id": "FR-old", "subject": "S"}]),
    ("lifecycle", ["ElementAdopt", {
        "element_id": "FR-old", "subject": "S", "content": "B", "extra": "x",
    }]),
    ("reference_claims", {
        "source_path": "a.md", "source_sha256": SHA256, "source_anchor": "A",
        "target_id": "FR-old", "target_revision": None,
    }),
    ("reference_claims", {
        "source_path": "a.md", "source_sha256": SHA256, "source_anchor": "A",
        "target_id": "FR-old", "target_revision": None, "relation": "reference",
        "extra": "x",
    }),
    ("issue_occurrences", {
        "issue_id": "ISS-old", "issue_revision": "1", "report_id": "r",
        "report_sha256": SHA256, "display_id": "ISS-view", "title": "T",
    }),
    ("issue_occurrences", {
        "issue_id": "ISS-old", "issue_revision": "1", "report_id": "r",
        "report_sha256": SHA256, "display_id": "ISS-view", "title": "T", "body": "B",
        "issue_fingerprint": SHA256,
    }),
])
def test_missing_and_extra_field_matrix_rejects(method, entry):
    with pytest.raises(IdentityRequestCodecError):
        decode_request(method, canonical([entry]))


@pytest.mark.parametrize("fields", [
    {"kind": "replace", "predecessors": "FR-000001", "successors": [], "reason": "x"},
    {"kind": "replace", "predecessors": [["FR-000001"]], "successors": [], "reason": "x"},
    {"kind": "replace", "predecessors": [["FR-000001", "1", "x"]], "successors": [], "reason": "x"},
    {"kind": "replace", "predecessors": [["FR-000001", "1"]], "successors": {}, "reason": "x"},
    {"kind": "replace", "predecessors": [["FR-000001", "1"]], "successors": [[]], "reason": "x"},
    {"kind": "replace", "predecessors": [["FR-000001", "1"]], "successors": [{
        "element_id": "FR-000002", "subject": "S", "content": "B",
    }], "reason": "x"},
    {"kind": "replace", "predecessors": [["FR-000001", "1"]], "successors": [{
        "element_id": "FR-000002", "subject": "S", "content": "B",
        "reservation_operation_id": "r", "extra": "x",
    }], "reason": "x"},
])
def test_transition_nested_shape_matrix_rejects(fields):
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", canonical([["ElementTransition", fields]]))


@pytest.mark.parametrize("payload", [
    '[["ElementAdopt",{"element_id":"FR-old","element_id":"FR-other",'
    '"subject":"S","content":"B"}]]',
    '[["ElementTransition",{"kind":"replace",'
    '"predecessors":[["FR-000001","1"]],"successors":[{'
    '"element_id":"FR-000002","element_id":"FR-000003","subject":"S",'
    '"content":"B","reservation_operation_id":"r"}],"reason":"x"}]]',
    '{"outer":"one","outer":"two"}',
])
def test_duplicate_object_keys_reject_at_every_depth(payload):
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", payload)


@pytest.mark.parametrize("payload", [
    "[", "[] trailing", "[NaN]", "[Infinity]", "[-Infinity]", "[1]",
    "[1.25]", "[1e1000000]", "[true]",
])
def test_strict_json_rejects_malformed_nonfinite_numeric_and_boolean_values(payload):
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", payload)


def test_oversized_number_rejects_without_integer_conversion_or_global_limit_change():
    before = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else None
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", "[" + "9" * 5000 + "]")
    after = sys.get_int_max_str_digits() if hasattr(sys, "get_int_max_str_digits") else None
    assert after == before


def test_deeply_nested_json_and_unencodable_text_reject():
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", "[" * 2000 + "]" * 2000)
    payload = canonical([["ElementAdopt", {
        "element_id": "FR-old", "subject": "bad\ud800text", "content": "B",
    }]])
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", payload)


@pytest.mark.parametrize("change,field,bad", [
    (lifecycle.ElementCreate("FR-000001", "S", "B", "r"), "element_id", "XX-1"),
    (lifecycle.ElementCreate("FR-000001", "S", "B", "r"), "subject", " "),
    (lifecycle.ElementCreate("FR-000001", "S", "B", "r"), "content", None),
    (lifecycle.ElementCreate("FR-000001", "S", "B", "r"),
     "reservation_operation_id", "bad\x00id"),
    (lifecycle.ElementAdopt("FR-old", "S", "B"), "element_id", "FR-0"),
    (lifecycle.ElementAdopt("FR-old", "S", "B"), "subject", []),
    (lifecycle.ElementAdopt("FR-old", "S", "B"), "content", ""),
    (lifecycle.ElementRevision("FR-old", "1", "S", "B"), "expected_revision", "01"),
    (lifecycle.ElementRevision("FR-old", "1", "S", "B"), "subject", "\t"),
    (lifecycle.ElementRevision("FR-old", "1", "S", "B"), "content", False),
    (lifecycle.ElementRetirement("FR-old", "1", "why"), "expected_revision", "0"),
    (lifecycle.ElementRetirement("FR-old", "1", "why"), "reason", " "),
])
def test_invalid_lifecycle_constructor_fields_reject(change, field, bad):
    wire = lifecycle.request((change,))[1]
    wire[0][1][field] = bad
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", canonical(wire))


@pytest.mark.parametrize("field,bad", [
    ("source_path", "../bad"), ("source_sha256", "A" * 64),
    ("source_anchor", " "), ("target_id", "XX-1"),
    ("target_revision", "01"), ("target_revision", True), ("relation", "verified"),
])
def test_invalid_reference_constructor_fields_reject(field, bad):
    wire = list(bindings.request((claim(),), bindings.ReferenceClaim))
    wire[0][field] = bad
    with pytest.raises(IdentityRequestCodecError):
        decode_request("reference_claims", canonical(wire))


@pytest.mark.parametrize("field,bad", [
    ("issue_id", "FR-1"), ("issue_revision", "0"), ("report_id", " "),
    ("report_sha256", "A" * 64), ("display_id", "FR-1"),
    ("title", None), ("body", False),
])
def test_invalid_occurrence_constructor_fields_reject(field, bad):
    wire = list(bindings.request((occurrence(),), bindings.IssueOccurrence))
    wire[0][field] = bad
    with pytest.raises(IdentityRequestCodecError):
        decode_request("issue_occurrences", canonical(wire))


def test_method_mismatch_duplicate_and_overlapping_batches_reject():
    with pytest.raises(IdentityRequestCodecError):
        decode_request("reference_claims", encode_request("lifecycle", (
            lifecycle.ElementAdopt("FR-old", "S", "B"),
        )))
    duplicate = claim()
    one = bindings.request((duplicate,), bindings.ReferenceClaim)[0]
    with pytest.raises(IdentityRequestCodecError):
        decode_request("reference_claims", canonical([one, one]))
    issue = bindings.request((occurrence(),), bindings.IssueOccurrence)[0]
    with pytest.raises(IdentityRequestCodecError):
        decode_request("issue_occurrences", canonical([issue, issue]))
    first = lifecycle.ElementRevision("FR-old", "1", "S", "B")
    second = lifecycle.ElementRetirement("FR-old", "1", "done")
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", canonical(
            lifecycle.request((first,))[1] + lifecycle.request((second,))[1],
        ))


def test_invalid_transition_kinds_cardinality_labels_and_scalars_reject():
    valid = lifecycle.ElementTransition(
        "replace", (("FR-000001", "1"),),
        (lifecycle.ElementCreate("FR-000002", "S", "B", "r"),), "why",
    )
    wire = lifecycle.request((valid,))[1]
    invalid = []
    for field, value in (
        ("kind", "move"), ("kind", True), ("predecessors", []),
        ("reason", " "), ("reason", None),
    ):
        candidate = json.loads(canonical(wire))
        candidate[0][1][field] = value
        invalid.append(candidate)
    candidate = json.loads(canonical(wire))
    candidate[0][1]["successors"][0]["element_id"] = "FR-000001"
    invalid.append(candidate)
    candidate = json.loads(canonical(wire))
    candidate[0][1]["predecessors"][0][1] = "01"
    invalid.append(candidate)
    for payload in invalid:
        with pytest.raises(IdentityRequestCodecError):
            decode_request("lifecycle", canonical(payload))


def test_encode_revalidates_damaged_frozen_top_level_nested_and_binding_objects():
    create = lifecycle.ElementCreate("FR-000001", "S", "B", "r")
    object.__setattr__(create, "content", " ")
    with pytest.raises(IdentityRequestCodecError):
        encode_request("lifecycle", (create,))
    successor = lifecycle.ElementCreate("FR-000002", "S", "B", "r")
    transition = lifecycle.ElementTransition(
        "replace", (("FR-000001", "1"),), (successor,), "why",
    )
    object.__setattr__(successor, "element_id", "bad")
    with pytest.raises(IdentityRequestCodecError):
        encode_request("lifecycle", (transition,))
    damaged = claim()
    object.__setattr__(damaged, "relation", "verified")
    with pytest.raises(IdentityRequestCodecError):
        encode_request("reference_claims", (damaged,))


def test_error_does_not_echo_complete_content_body():
    secret = "do-not-repeat-this-complete-body"
    payload = canonical([["ElementAdopt", {
        "element_id": "FR-old", "subject": "S", "content": secret, "extra": "x",
    }]])
    with pytest.raises(IdentityRequestCodecError) as caught:
        decode_request("lifecycle", payload)
    assert secret not in str(caught.value)


def test_lifecycle_create_revise_retire_retries_after_later_terminal_history(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    requests = {
        "create": (lifecycle.ElementCreate(label, "Scene", "First", "reserve"),),
        "revise": (lifecycle.ElementRevision(label, "1", "Scene", "Second"),),
        "retire": (lifecycle.ElementRetirement(label, "2", "Done"),),
    }
    payloads = {name: encode_request("lifecycle", value) for name, value in requests.items()}
    receipts = {
        name: store.apply_lifecycle(spec_id=SPEC, operation_id=name, changes=value)
        for name, value in requests.items()
    }
    before = sql_state(tmp_path)
    reopened = IdentityStore.open(tmp_path)
    for name in ("create", "revise", "retire"):
        assert reopened.apply_lifecycle(
            spec_id=SPEC, operation_id=name,
            changes=decode_request("lifecycle", payloads[name]),
        ) == receipts[name]
        assert sql_state(tmp_path) == before


@pytest.mark.parametrize("kind,predecessor_count,successor_count", [
    ("replace", 1, 1), ("split", 1, 2), ("merge", 2, 1),
])
def test_transition_requests_retry_after_reopen(kind, predecessor_count, successor_count, tmp_path):
    store = IdentityStore.initialize(tmp_path)
    total = predecessor_count + successor_count
    labels = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=total)
    creates = tuple(
        lifecycle.ElementCreate(labels[index], f"P{index}", f"Body {index}", "reserve")
        for index in range(predecessor_count)
    )
    store.apply_lifecycle(spec_id=SPEC, operation_id="seed", changes=creates)
    transition = lifecycle.ElementTransition(
        kind,
        tuple((item.element_id, "1") for item in creates),
        tuple(
            lifecycle.ElementCreate(labels[index], f"S{index}", f"Next {index}", "reserve")
            for index in range(predecessor_count, total)
        ),
        f"{kind} reason",
    )
    payload = encode_request("lifecycle", (transition,))
    receipt = store.apply_lifecycle(spec_id=SPEC, operation_id=kind, changes=(transition,))
    before = sql_state(tmp_path)
    assert IdentityStore.open(tmp_path).apply_lifecycle(
        spec_id=SPEC, operation_id=kind, changes=decode_request("lifecycle", payload),
    ) == receipt
    assert sql_state(tmp_path) == before


def test_explicit_import_adopt_request_retries_after_later_revision(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(
        spec_id=SPEC, operation_id="import", definitions=(("FR-001.alpha", "Legacy"),),
    )
    adopt = (lifecycle.ElementAdopt("FR-001.alpha", "Legacy", "Imported body"),)
    payload = encode_request("lifecycle", adopt)
    receipt = store.apply_lifecycle(spec_id=SPEC, operation_id="adopt", changes=adopt)
    store.apply_lifecycle(spec_id=SPEC, operation_id="revise", changes=(
        lifecycle.ElementRevision("FR-001.alpha", "1", "Legacy", "Later"),
    ))
    before = sql_state(tmp_path)
    assert IdentityStore.open(tmp_path).apply_lifecycle(
        spec_id=SPEC, operation_id="adopt", changes=decode_request("lifecycle", payload),
    ) == receipt
    assert sql_state(tmp_path) == before


def test_reference_and_issue_requests_retry_after_later_heads(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    for kind in ("FR", "ISS"):
        label, = store.reserve(spec_id=SPEC, kind=kind, operation_id=f"reserve-{kind}", count=1)
        title = "Issue title" if kind == "ISS" else "Scene"
        body = "Issue body" if kind == "ISS" else "Scene body"
        store.apply_lifecycle(spec_id=SPEC, operation_id=f"create-{kind}", changes=(
            lifecycle.ElementCreate(label, title, body, f"reserve-{kind}"),
        ))
    claims = (
        claim(relation="reference"),
        claim(source_anchor="unassessed", target_revision=None, relation="requires"),
    )
    issues = (occurrence(title="Issue title", body="Issue body"),)
    claim_payload = encode_request("reference_claims", claims)
    issue_payload = encode_request("issue_occurrences", issues)
    claim_receipt = store.record_reference_claims(
        spec_id=SPEC, operation_id="claims", claims=claims,
    )
    issue_receipt = store.record_issue_occurrences(
        spec_id=SPEC, operation_id="issues", occurrences=issues,
    )
    store.apply_lifecycle(spec_id=SPEC, operation_id="revise-fr", changes=(
        lifecycle.ElementRevision("FR-000001", "1", "Scene", "Later"),
    ))
    store.apply_lifecycle(spec_id=SPEC, operation_id="retire-issue", changes=(
        lifecycle.ElementRetirement("ISS-000001", "1", "Done"),
    ))
    before = sql_state(tmp_path)
    reopened = IdentityStore.open(tmp_path)
    assert reopened.record_reference_claims(
        spec_id=SPEC, operation_id="claims",
        claims=decode_request("reference_claims", claim_payload),
    ) == claim_receipt
    assert reopened.record_issue_occurrences(
        spec_id=SPEC, operation_id="issues",
        occurrences=decode_request("issue_occurrences", issue_payload),
    ) == issue_receipt
    assert sql_state(tmp_path) == before


def test_changed_decoded_retry_rejects_and_preserves_complete_sql_state(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    original = (lifecycle.ElementCreate(label, "Scene", "Original", "reserve"),)
    store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=original)
    changed = (replace(original[0], content="Changed"),)
    decoded = decode_request("lifecycle", encode_request("lifecycle", changed))
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path).apply_lifecycle(
            spec_id=SPEC, operation_id="create", changes=decoded,
        )
    assert sql_state(tmp_path) == before


def test_changed_decoded_binding_retry_rejects_and_preserves_complete_sql_state(tmp_path):
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id=SPEC, kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id=SPEC, operation_id="create", changes=(
        lifecycle.ElementCreate(label, "Scene", "Original", "reserve"),
    ))
    original = (claim(),)
    store.record_reference_claims(spec_id=SPEC, operation_id="claims", claims=original)
    changed = (replace(original[0], relation="depends"),)
    decoded = decode_request(
        "reference_claims", encode_request("reference_claims", changed),
    )
    before = sql_state(tmp_path)
    with pytest.raises(IdentityStoreError):
        IdentityStore.open(tmp_path).record_reference_claims(
            spec_id=SPEC, operation_id="claims", claims=decoded,
        )
    assert sql_state(tmp_path) == before


def test_decode_is_pure_and_does_not_invoke_store_methods(monkeypatch, tmp_path):
    store = IdentityStore.initialize(tmp_path)
    before = sql_state(tmp_path)

    def unexpected(*_args, **_kwargs):
        pytest.fail("decode invoked a store method")

    monkeypatch.setattr(store, "apply_lifecycle", unexpected)
    valid = encode_request("lifecycle", (
        lifecycle.ElementAdopt("FR-old", "S", "B"),
    ))
    assert decode_request("lifecycle", valid) == (
        lifecycle.ElementAdopt("FR-old", "S", "B"),
    )
    with pytest.raises(IdentityRequestCodecError):
        decode_request("lifecycle", "not-json")
    assert sql_state(tmp_path) == before
