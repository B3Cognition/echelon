"""Shared strict string-tree JSON decoding; callers own their closed shapes."""

import json


class MalformedJSON(ValueError):
    """Expected untrusted-wire failure."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise MalformedJSON("duplicate JSON object key")
        value[key] = item
    return value


def _reject_number(_token):
    raise MalformedJSON("numeric JSON tokens are not valid request strings")


def strict_json(payload):
    if type(payload) is not str:
        raise MalformedJSON("payload must have exact type str")
    payload.encode("utf-8")
    value = json.loads(payload, object_pairs_hook=_unique_object, parse_int=_reject_number,
                       parse_float=_reject_number, parse_constant=_reject_number)
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
    return value
