"""Protocol-2.6 workspace checkpoint authority over existing RE v2 layers."""

PROTOCOL_VERSION = "2.6"
RUN_MANIFEST_SCHEMA_VERSION = 5

from .model import (
    CheckpointArtifactDependencyV1,
    CheckpointDispositionV1,
    CheckpointManifestV1,
    CheckpointRankV1,
    CheckpointSelectionBundleV1,
    CheckpointSelectionEntryV1,
    LayerExecutionContractV1,
    Protocol26SchemaError,
    RunManifestV5,
)

__all__ = (
    "PROTOCOL_VERSION",
    "RUN_MANIFEST_SCHEMA_VERSION",
    "CheckpointArtifactDependencyV1",
    "CheckpointDispositionV1",
    "CheckpointManifestV1",
    "CheckpointRankV1",
    "CheckpointSelectionBundleV1",
    "CheckpointSelectionEntryV1",
    "LayerExecutionContractV1",
    "Protocol26SchemaError",
    "Protocol26InputSet",
    "Protocol26InputStoreError",
    "RunManifestV5",
    "ValidatedProtocol26Inputs",
    "create_protocol_26_run_store",
    "load_protocol_26_inputs",
)


_LAZY_INPUT_EXPORTS = frozenset(
    {
        "Protocol26InputSet",
        "Protocol26InputStoreError",
        "ValidatedProtocol26Inputs",
        "create_protocol_26_run_store",
        "load_protocol_26_inputs",
    }
)


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name not in _LAZY_INPUT_EXPORTS:
        raise AttributeError(name)
    from . import inputs as module

    value = getattr(module, name)
    globals()[name] = value
    return value
