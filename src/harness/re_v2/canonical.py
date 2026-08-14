"""Canonical JSON serialization and content addressing for RE v2."""

import hashlib
import json


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON-compatible value into canonical UTF-8 bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def content_digest(value: bytes | object) -> str:
    """Return the lower-case SHA-256 content address for bytes or canonical JSON."""
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()
