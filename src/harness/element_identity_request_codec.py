"""Strict round trips for existing identity requests, without execution authority."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields
import json

from harness import element_identity_bindings as bindings
from harness import element_identity_lifecycle as lifecycle


class IdentityRequestCodecError(ValueError):
    """Malformed serialized request; no execution or authority is implied."""


_LIFECYCLE_TYPES = {
    "ElementCreate": lifecycle.ElementCreate,
    "ElementAdopt": lifecycle.ElementAdopt,
    "ElementRevision": lifecycle.ElementRevision,
    "ElementRetirement": lifecycle.ElementRetirement,
    "ElementTransition": lifecycle.ElementTransition,
}
_BINDING_TYPES = {
    "reference_claims": bindings.ReferenceClaim,
    "issue_occurrences": bindings.IssueOccurrence,
}
_METHODS = frozenset(("lifecycle", *_BINDING_TYPES))
_FIELD_NAMES = {
    item_type: frozenset(field.name for field in fields(item_type))
    for item_type in (*_LIFECYCLE_TYPES.values(), *_BINDING_TYPES.values())
}


class _MalformedRequest(ValueError):
    """Internal sentinel for expected untrusted-wire failures."""


def _method(method):
    if type(method) is not str or method not in _METHODS:
        raise IdentityRequestCodecError(
            "method must be exactly lifecycle, reference_claims, or issue_occurrences",
        )


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def encode_request(method: str, entries: Sequence) -> str:
    """Return canonical ASCII JSON of the existing method-specific payload."""
    _method(method)
    try:
        if method == "lifecycle":
            payload = lifecycle.request(entries)[1]
        else:
            payload = bindings.request(entries, _BINDING_TYPES[method])
        return _canonical(payload)
    except IdentityRequestCodecError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise IdentityRequestCodecError(f"invalid {method} request values") from error


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _MalformedRequest("duplicate JSON object key")
        value[key] = item
    return value


def _reject_number(_token):
    # Reject from the token text: never construct a huge int or float.
    raise _MalformedRequest("numeric JSON tokens are not valid request strings")


def _utf8_strings(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is str:
            item.encode("utf-8")
        elif type(item) is list:
            pending.extend(item)
        elif type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())


def _strict_json(payload):
    if type(payload) is not str:
        raise _MalformedRequest("payload must have exact type str")
    payload.encode("utf-8")
    value = json.loads(
        payload,
        object_pairs_hook=_unique_object,
        parse_int=_reject_number,
        parse_float=_reject_number,
        parse_constant=_reject_number,
    )
    _utf8_strings(value)
    return value


def _field_object(value, item_type, description):
    if type(value) is not dict or frozenset(value) != _FIELD_NAMES[item_type]:
        raise _MalformedRequest(f"{description} must contain exactly its known fields")
    return value


def _transition(value):
    value = _field_object(value, lifecycle.ElementTransition, "transition")
    predecessors = value["predecessors"]
    successors = value["successors"]
    if type(predecessors) is not list or type(successors) is not list:
        raise _MalformedRequest("transition collections must be wire arrays")
    detached_predecessors = []
    for pair in predecessors:
        if type(pair) is not list or len(pair) != 2:
            raise _MalformedRequest("predecessor must be a two-value wire array")
        detached_predecessors.append(tuple(pair))
    detached_successors = []
    for successor in successors:
        successor = _field_object(successor, lifecycle.ElementCreate, "successor")
        detached_successors.append(lifecycle.ElementCreate(**successor))
    return lifecycle.ElementTransition(
        kind=value["kind"],
        predecessors=tuple(detached_predecessors),
        successors=tuple(detached_successors),
        reason=value["reason"],
    )


def _lifecycle_entries(value):
    if type(value) is not list or not value:
        raise _MalformedRequest("lifecycle payload must be a nonempty wire array")
    result = []
    for entry in value:
        if type(entry) is not list or len(entry) != 2 or type(entry[0]) is not str:
            raise _MalformedRequest("lifecycle entry must be a tagged two-value wire array")
        item_type = _LIFECYCLE_TYPES.get(entry[0])
        if item_type is None:
            raise _MalformedRequest("unknown lifecycle class tag")
        field_values = entry[1]
        if item_type is lifecycle.ElementTransition:
            result.append(_transition(field_values))
        else:
            field_values = _field_object(field_values, item_type, "lifecycle entry")
            result.append(item_type(**field_values))
    return lifecycle.request(tuple(result))[0]


def _binding_entries(method, value):
    if type(value) is not list or not value:
        raise _MalformedRequest("binding payload must be a nonempty wire array")
    item_type = _BINDING_TYPES[method]
    result = tuple(
        item_type(**_field_object(entry, item_type, "binding entry"))
        for entry in value
    )
    bindings.request(result, item_type)
    return result


def decode_request(
    method: str,
    payload: str,
) -> tuple[lifecycle.LifecycleChange | bindings.ReferenceClaim | bindings.IssueOccurrence, ...]:
    """Return a nonempty immutable validated batch; never execute it."""
    _method(method)
    try:
        value = _strict_json(payload)
        if method == "lifecycle":
            return _lifecycle_entries(value)
        return _binding_entries(method, value)
    except IdentityRequestCodecError:
        raise
    except (json.JSONDecodeError, _MalformedRequest, ValueError, TypeError,
            UnicodeError, RecursionError) as error:
        raise IdentityRequestCodecError(f"malformed {method} serialized request") from error
