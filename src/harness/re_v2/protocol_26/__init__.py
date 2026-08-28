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
    "RunManifestV5",
)
