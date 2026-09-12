"""Shared detachment of graph JSON property trees."""

from collections.abc import Mapping
import math


def _require(condition):
    if not condition:
        raise ValueError("inconsistent identity projection input")


def copy_tree(value):
    """Detach JSON property trees, including non-pickleable Mapping proxies."""
    if isinstance(value, Mapping):
        _require(all(type(key) is str for key in value))
        for key in value:
            key.encode("utf-8")
        return {key: copy_tree(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return type(value)(copy_tree(item) for item in value)
    _require(value is None or type(value) in (str, bool, int, float))
    if type(value) is str:
        value.encode("utf-8")
    if type(value) is float:
        _require(math.isfinite(value))
    return value
