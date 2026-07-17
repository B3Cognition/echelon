from __future__ import annotations

from enum import StrEnum


class ProviderCapability(StrEnum):
    ARTIFACT = "artifact"
    BUILD = "build"


CLI_PROVIDER_CAPABILITIES = frozenset(
    {ProviderCapability.ARTIFACT, ProviderCapability.BUILD}
)
ARTIFACT_PROVIDER_CAPABILITIES = frozenset({ProviderCapability.ARTIFACT})
BUILD_PROVIDER_CAPABILITIES = frozenset({ProviderCapability.BUILD})
