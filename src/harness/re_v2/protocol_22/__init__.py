"""Isolated contracts for the RE v2 protocol 2.2 engine."""

from .model import RunManifestV2
from .schema import Protocol22SchemaError, load_canonical_object

PROTOCOL_VERSION = "2.2"
RUN_MANIFEST_SCHEMA_VERSION = 2

__all__ = (
    "PROTOCOL_VERSION",
    "Protocol22SchemaError",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "RunManifestV2",
    "load_canonical_object",
)
