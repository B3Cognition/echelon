from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


@pytest.mark.unit
def test_normalized_records_use_stable_public_ids_and_are_immutable() -> None:
    from echelon.topology_model import (
        TopologyFile,
        TopologyRelationship,
        TopologySource,
        TopologySymbol,
        canonical_symbol_key,
    )

    key = canonical_symbol_key("src/api.py", "api.run", "function", "()")
    source = TopologySource(source_id="api")
    file = TopologyFile(source_id="api", path="src/api.py")
    symbol = TopologySymbol(
        source_id="api",
        provider="codegraph",
        symbol_key=key,
        path="src/api.py",
        qualified_name="api.run",
        kind="function",
        signature="()",
    )
    relationship = TopologyRelationship(
        source_id=symbol.id,
        target_id=symbol.id,
        type="CALLS",
        provider="codegraph",
        provider_kind="calls",
    )

    assert source.id == "source:api"
    assert file.id == "file:api:src/api.py"
    assert symbol.id == f"symbol:api:codegraph:{key.removeprefix('sha256:')}"
    assert relationship.source_id == symbol.id
    assert relationship.target_id == symbol.id
    with pytest.raises(FrozenInstanceError):
        symbol.kind = "method"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source_id", "provider", "path"),
    [
        ("../api", "codegraph", "src/api.py"),
        ("api", "perl/graph", "src/api.py"),
        ("api", "codegraph", "/private/api.py"),
        ("api", "codegraph", "src/../api.py"),
        ("api", "codegraph", "src\\api.py"),
    ],
)
def test_identity_helpers_reject_unsafe_values(
    source_id: str, provider: str, path: str
) -> None:
    from echelon.topology_model import TopologyValidationError, symbol_id

    with pytest.raises(TopologyValidationError):
        symbol_id(source_id, provider, "sha256:" + "a" * 64, path=path)

