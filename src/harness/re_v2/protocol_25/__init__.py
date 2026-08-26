"""Closed protocol-2.5 contracts for RE v2 L3 semantic closure."""

PROTOCOL_VERSION = "2.5"
RUN_MANIFEST_SCHEMA_VERSION = 4

from .model import (
    Protocol25SchemaError,
    RunManifestV4,
    RunModeV1,
    SemanticClosurePolicyV1,
)

__all__ = (
    "PROTOCOL_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "Protocol25SchemaError",
    "RunManifestV4",
    "RunModeV1",
    "SemanticClosurePolicyV1",
)
