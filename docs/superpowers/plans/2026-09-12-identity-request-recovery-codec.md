# Identity request recovery codec implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reconstruct exact immutable lifecycle/reference/issue requests from persisted JSON without weakening their existing validators or changing operation digests.

**Architecture:** A pure closed codec wraps the existing lifecycle and binding request validators and their existing serialized payload shapes. It neither stores requests nor authorizes their execution. The future publication-intent owner will bind these bytes to its own versioned/authenticated envelope and recovery state.

**Tech Stack:** Python standard-library JSON, frozen request dataclasses, real SQLite compatibility tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Existing Phase A completion transactions, candidate isolation, and repair facilities remain the integration owners.
- Existing labels, including FR-001 and historical composite IDs, remain exactly as published.
- IDs travel through interfaces as strings.
- No schema, allocator, import, lifecycle application, binding persistence, provider, controller routing, publication or activation changes in this task.

---

### Task 1: strictly round-trip existing immutable request payloads

**Files:** Create `src/harness/element_identity_request_codec.py` and `tests/unit/test_element_identity_request_codec.py`; document the boundary in `docs/element-identity-storage.md`. Do not modify the existing lifecycle/binding/store modules or their existing tests.

**Interfaces:**

```python
from collections.abc import Sequence
from harness.element_identity_lifecycle import LifecycleChange
from harness.element_identity_bindings import ReferenceClaim, IssueOccurrence

class IdentityRequestCodecError(ValueError):
    """Malformed serialized request; no execution or authority is implied."""

def encode_request(method: str, entries: Sequence) -> str:
    """Return canonical ASCII JSON of the existing method-specific payload."""

def decode_request(method: str, payload: str) -> tuple[LifecycleChange | ReferenceClaim | IssueOccurrence, ...]:
    """Return a nonempty immutable validated batch; never execute it."""
```

`method` must have exact type str and be exactly `lifecycle`, `reference_claims`, or `issue_occurrences`. The payload is the existing request payload, not a new request envelope: lifecycle is an array of `[class_name, field_object]` pairs using exactly `ElementCreate`, `ElementAdopt`, `ElementRevision`, `ElementRetirement`, `ElementTransition`; bindings are arrays of field objects for the selected exact class. Canonical JSON uses `sort_keys=True, separators=(",", ":"), ensure_ascii=True`, matching current operation digest serialization. Do not change existing digest inputs, add tags/versions to these payloads, or infer a method from their content. The eventual intent envelope will own versioning and method/spec/operation/source associations.

Encode by calling `lifecycle.request(entries)` or `bindings.request(entries, exact_type)` and serializing their returned payload. This revalidates frozen objects even if a caller used object.__setattr__ to damage them. Preserve existing Sequence acceptance, ordering, duplicate checks, exact class restrictions and nonempty rules. Never mutate caller values, normalize whitespace/content/newlines/Unicode, pad existing labels, or convert numeric ID/revision strings to integers.

Decode exact str input with strict standard JSON decoding. Reject duplicate object keys at every depth (including nested successor objects), malformed/trailing JSON, NaN/Infinity, and numeric JSON tokens: all numbers in these request schemas must remain strings. Reject boolean values and null except the existing `ReferenceClaim.target_revision=None` case through exact existing field validation. Unknown/missing/extra fields, unknown class tags, incorrect pair/list/object shapes, method mismatches, invalid nested transition structures, invalid types, blank/NUL/unencodable text, invalid IDs/revisions/relations, overlapping/duplicate lifecycle labels and duplicate bindings must reject. Do not silently filter fields, coerce scalars or instantiate arbitrary classes. Use one explicit closed type map and dataclass field names rather than eval/import-by-name or copied validation rules.

Only decode wire arrays as lists. For `ElementTransition`, validate exact predecessor arrays of two values and successor field objects, convert these arrays to the required nested tuples, construct exact `ElementCreate` successors and then construct the transition. Let the existing constructors enforce cardinality/kind/label/subject/content constraints. Re-run the existing batch validator on the fully constructed tuple before returning it. All returned values, including transition collections and successors, must be detached immutable types; no raw dict/list escapes. Decoding an `ElementAdopt` is supported for recovery compatibility but does not authorize adoption in managed candidates.

Raise `IdentityRequestCodecError` consistently for malformed method/input/JSON/request values. Keep exception normalization narrowly scoped to decoding/construction/validation, including JSON nesting exhaustion and unencodable strings; do not catch BaseException, swallow unexpected implementation errors, or include complete content bodies in error messages. Reject numeric tokens without converting huge decimal tokens, and do not alter Python's global integer digit limit. No arbitrary ID/revision width limit is introduced.

This module performs no file, database, network, provider or store API calls; accepting a payload only proves its request shape. It does not establish namespace ownership, reservation/head validity, source authenticity, semantic review, pending intent, publication acceptance, or receipt authority. Those remain the existing store and future controller owners' responsibilities.

**First regression before production edits:**

```python
def test_encoded_existing_lifecycle_request_retries_after_reopen(tmp_path):
    import json
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate, request
    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    changes = (ElementCreate(label, "Scene", "Original body.\r\n", "reserve"),)
    original = store.apply_lifecycle(spec_id="demo", operation_id="create", changes=changes)
    payload = json.dumps(request(changes)[1], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    from harness.element_identity_request_codec import decode_request
    decoded = decode_request("lifecycle", payload)
    assert decoded == changes
    reopened = IdentityStore.open(tmp_path)
    assert reopened.apply_lifecycle(spec_id="demo", operation_id="create", changes=decoded) == original
```

- [ ] Add the regression with `pytestmark = pytest.mark.unit`; run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_element_identity_request_codec.py -q` and retain actual missing-module RED **after** successful existing reserve/apply/serialization, not a broken fixture or unrelated import.
- [ ] Implement the pure codec with the exact API and payload contract. Share field-shape checking across the closed known dataclass types, while retaining explicit transition reconstruction. No generic serialization framework or production persistence hook.
- [ ] Add exact round-trip/canonical-byte tests for all five lifecycle variants and all three transition kinds; mixed disjoint batches; assessed and unassessed claims/all relations; issue occurrence exact legacy display ID/title/body. Assert wire payload bytes equal existing validator payload JSON and existing operation digests remain identical. Preserve CRLF, Unicode and whitespace, legacy composites, six/seven/eight-digit labels and 5,000-digit label/revision strings. Verify frozen nested types and unchanged input objects.
- [ ] Add rejection matrices for every outer/entry/nested shape, extra/missing keys, unknown tags/methods and subclassed method/payload/entry values; duplicate keys in outer/nested objects; every invalid constructor field; numeric/boolean/null confusion; malformed/trailing/nonfinite/oversized-number/deeply-nested JSON; duplicate/overlapping batch labels and bindings. Include valid controls, useful error class assertions and damaged-frozen-object encode tests. Do not lower the real schema checks to make tests pass.
- [ ] Exercise real reopened-store compatibility for lifecycle create/revise/retire/replace/split/merge and explicit import/adopt, plus reference/issue records. An original encoded request retried after later heads or terminal history returns its original receipt, with complete SQL state unchanged. Changed decoded request arguments under the same operation ID still reject and preserve SQL state. Decode failure occurs without invoking store methods or changing an initialized ledger. These are codec/application compatibility tests, not a new recovery owner.
- [ ] Run exactly `tests/unit/test_element_identity_request_codec.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, and `tests/unit/test_element_identity_transaction_composition.py` with the checkout virtualenv on final code. No full repository, capacity, provider or live run; no unchanged post-commit repeat.
- [ ] Document byte compatibility versus absent authority, self-review closed decoding and exception handling, run `git diff --check`, commit only the three task files and retain full actual RED/GREEN commands/output in the task report. Root owns independent review and plan/ledger updates.

## Remaining integration

The codec is an internal recovery prerequisite, not an intent schema or a controller proposal format. Complete authenticated before/after capture, projected binding validation, semantic authorization, pending-write protection, durable finalization/graph receipts, all managed producers, targeted repair and final verification remain required by the approved design.
