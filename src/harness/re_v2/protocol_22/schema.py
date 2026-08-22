"""Strict canonical decoding and scalar validation for protocol 2.2."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import PurePosixPath
import re
from typing import Callable, Mapping, TypeVar

from harness.re_v2.canonical import canonical_json_bytes


class Protocol22SchemaError(ValueError):
    """Raised when protocol-2.2 authority violates its closed schema."""


T = TypeVar("T")

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_SAFE_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def exact_object(
    value: object,
    fields: frozenset[str] | set[str],
    label: str,
) -> Mapping[str, object]:
    """Return *value* only when it has exactly the declared string fields."""
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise Protocol22SchemaError(f"{label} must be an object with string fields")
    expected = frozenset(fields)
    present = frozenset(value)
    if present != expected:
        unknown = sorted(present - expected)
        missing = sorted(expected - present)
        raise Protocol22SchemaError(
            f"{label} has unknown fields {unknown} and missing fields {missing}"
        )
    return value


def safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise Protocol22SchemaError(f"{field} must be a nonempty safe ID")
    return value


def text_value(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        requirement = "a string" if allow_empty else "a nonempty string"
        raise Protocol22SchemaError(f"{field} must be {requirement}")
    _validate_unicode(value, field)
    return value


def digest_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise Protocol22SchemaError(f"{field} must be a lowercase sha256 digest")
    return value


def nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Protocol22SchemaError(f"{field} must be a nonnegative integer")
    return value


def bounded_int(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise Protocol22SchemaError(
            f"{field} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise Protocol22SchemaError(f"{field} must be a positive integer")
    return value


def positive_or_none(value: object, field: str) -> int | None:
    if value is None:
        return None
    return positive_int(value, field)


def integer_or_none(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise Protocol22SchemaError(f"{field} must be an integer or null")
    return value


def boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise Protocol22SchemaError(f"{field} must be a boolean")
    return value


def literal(value: object, expected: object, field: str) -> object:
    if value != expected or type(value) is not type(expected):
        raise Protocol22SchemaError(f"{field} must be {expected!r}")
    return value


def one_of(value: object, choices: frozenset[str] | set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise Protocol22SchemaError(f"{field} must be one of {sorted(choices)}")
    return value


def optional_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    return digest_value(value, field)


def optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return text_value(value, field)


def utc_timestamp(value: object, field: str) -> str:
    text = text_value(value, field)
    if not text.endswith("Z"):
        raise Protocol22SchemaError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise Protocol22SchemaError(
            f"{field} must be an RFC3339 UTC timestamp"
        ) from exc
    if parsed.tzinfo != timezone.utc:
        raise Protocol22SchemaError(f"{field} must be an RFC3339 UTC timestamp")
    return text


def safe_relative_path(value: object, field: str) -> str:
    text = text_value(value, field)
    if "\\" in text:
        raise Protocol22SchemaError(f"{field} must be a normalized relative path")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or path.as_posix() != text
        or not path.parts
        or any(
            part in {"", ".", ".."} or not _SAFE_PATH_SEGMENT_RE.fullmatch(part)
            for part in path.parts
        )
    ):
        raise Protocol22SchemaError(f"{field} must be a normalized relative path")
    return text


def sorted_unique_digests(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise Protocol22SchemaError(f"{field} must be an array")
    result = tuple(digest_value(value, field) for value in values)
    if result != tuple(sorted(set(result))):
        raise Protocol22SchemaError(f"{field} must be sorted and unique")
    return result


def load_canonical_object(payload: bytes, decoder: Callable[[object], T]) -> T:
    """Decode one exact canonical JSON object, then apply a closed decoder."""
    if not isinstance(payload, bytes):
        raise Protocol22SchemaError("canonical payload must be bytes")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Protocol22SchemaError("canonical payload must be valid UTF-8") from exc
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except Protocol22SchemaError:
        raise
    except json.JSONDecodeError as exc:
        raise Protocol22SchemaError(f"canonical payload is invalid JSON: {exc.msg}") from exc
    if not isinstance(raw, Mapping):
        raise Protocol22SchemaError("canonical payload must contain one JSON object")
    _validate_unicode(raw, "canonical payload")
    try:
        canonical = canonical_json_bytes(raw)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise Protocol22SchemaError("canonical payload contains invalid JSON values") from exc
    if payload != canonical:
        raise Protocol22SchemaError("canonical payload bytes are not canonical JSON")
    try:
        return decoder(raw)
    except Protocol22SchemaError:
        raise
    except (TypeError, ValueError) as exc:
        raise Protocol22SchemaError(f"canonical object failed schema decoding: {exc}") from exc


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Protocol22SchemaError(f"canonical payload contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise Protocol22SchemaError(f"canonical payload contains non-finite number {value}")


def _validate_unicode(value: object, field: str) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise Protocol22SchemaError(f"{field} contains invalid Unicode") from exc
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _validate_unicode(key, field)
            _validate_unicode(item, field)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_unicode(item, field)
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise Protocol22SchemaError(f"{field} contains a non-finite number")
