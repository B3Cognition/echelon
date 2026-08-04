from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _key(path: str, qualified_name: str, kind: str, signature: str = "") -> str:
    locator = json.dumps(
        [path, qualified_name, kind, signature], ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()


def _symbol(
    path: str = "src/api.py",
    qualified_name: str = "api.run",
    kind: str = "function",
    signature: str = "()",
) -> dict[str, object]:
    return {
        "symbol_key": _key(path, qualified_name, kind, signature),
        "file_path": path,
        "qualified_name": qualified_name,
        "name": qualified_name.rpartition(".")[2],
        "kind": kind,
        "signature": signature,
        "line_start": 1,
        "line_end": 2,
    }


def _codegraph(
    *,
    symbols: list[dict[str, object]] | None = None,
    relationships: list[dict[str, object]] | None = None,
    status: str = "complete",
    complete: bool = True,
    supported: bool = True,
) -> dict[str, object]:
    symbols = [_symbol()] if symbols is None else symbols
    relationships = (
        [
            {
                "kind": "calls",
                "source_key": symbols[0]["symbol_key"],
                "target_key": symbols[0]["symbol_key"],
                "file_path": symbols[0]["file_path"],
            }
        ]
        if relationships is None and symbols
        else relationships or []
    )
    return {
        "schema_version": 2,
        "version": "2.0.0",
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "repo_path": "/absolute/provider-only/path",
        "provider_status": status,
        "complete": complete,
        "supported": supported,
        "counts": {
            "discovered_symbols": len(symbols),
            "emitted_symbols": len(symbols),
            "excluded_symbols": 0,
            "discovered_relationships": len(relationships),
            "emitted_relationships": len(relationships),
            "excluded_relationships": 0,
        },
        "diagnostics": {"unresolved_relationships": []},
        "symbols": symbols,
        "relationships": relationships,
        "call_graph": [],
        "type_hierarchy": [],
        "impact_radius": [],
    }


def _perlgraph(
    *,
    symbols: list[dict[str, object]] | None = None,
    relationships: list[dict[str, object]] | None = None,
    status: str = "empty",
    complete: bool = True,
) -> dict[str, object]:
    symbols = [] if symbols is None else symbols
    relationships = [] if relationships is None else relationships
    return {
        "schema_version": 2,
        "tool": "perlgraph",
        "tool_version": "0.1.0",
        "repo_path": "/absolute/provider-only/path",
        "provider_status": status,
        "complete": complete,
        "supported": status != "unsupported",
        "capabilities": {
            "language": "perl",
            "supported_extensions": [".pm"],
            "exact_symbol_keys": True,
            "exact_relationship_endpoints": True,
            "unresolved_relationship_diagnostics": True,
        },
        "counts": {
            "discovered_files": 0,
            "emitted_files": 0,
            "discovered_symbols": len(symbols),
            "emitted_symbols": len(symbols),
            "discovered_relationships": len(relationships),
            "emitted_relationships": len(relationships),
            "unresolved_relationships": 0,
            "parse_failures": 0,
            "parse_diagnostics": 0,
            "dynamic_patterns": 0,
        },
        "symbols": symbols,
        "relationships": relationships,
        "unresolved_relationships": [],
        "call_graph": [],
        "module_graph": [],
        "unsupported_patterns": [],
        "parse_failures": [],
        "parse_diagnostics": [],
    }


def _write(path: Path, document: dict[str, object]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.unit
def test_load_provider_normalizes_exact_keys_and_hides_native_host_paths(tmp_path: Path) -> None:
    from echelon.topology_provider import load_provider_artifact

    loaded = load_provider_artifact(
        _write(tmp_path / "codegraph.json", _codegraph()),
        provider="codegraph",
        source_id="api",
    )

    assert loaded.status == "ready"
    assert loaded.native_status == "complete"
    assert loaded.symbols[0].id == f"symbol:api:codegraph:{_symbol()['symbol_key'][7:]}"
    assert loaded.relationships[0].type == "CALLS"
    assert "/absolute/" not in repr(loaded)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("provider", "kind", "normalized"),
    [
        ("codegraph", "contains", "CONTAINS"),
        ("codegraph", "declares", "DECLARES"),
        ("codegraph", "import", "IMPORTS"),
        ("codegraph", "imports", "IMPORTS"),
        ("codegraph", "require", "REQUIRES"),
        ("codegraph", "requires", "REQUIRES"),
        ("codegraph", "calls", "CALLS"),
        ("codegraph", "extends", "EXTENDS"),
        ("codegraph", "implements", "IMPLEMENTS"),
        ("codegraph", "uses_role", "USES_ROLE"),
        ("codegraph", "tests", "TESTS"),
        ("codegraph", "references", "REFERENCES"),
        ("codegraph", "instantiates", "INSTANTIATES"),
        ("codegraph", "decorates", "DECORATES"),
        ("perlgraph", "declares", "DECLARES"),
        ("perlgraph", "imports", "IMPORTS"),
        ("perlgraph", "requires", "REQUIRES"),
        ("perlgraph", "inherits", "EXTENDS"),
        ("perlgraph", "uses_role", "USES_ROLE"),
        ("perlgraph", "calls", "CALLS"),
        ("perlgraph", "tests", "TESTS"),
        ("perlgraph", "references", "REFERENCES"),
        ("codegraph", "provider_private_kind", "OTHER"),
    ],
)
def test_load_provider_maps_each_native_relationship_kind_explicitly(
    provider: str, kind: str, normalized: str
) -> None:
    from echelon.topology_provider import load_provider_document

    first = _symbol("src/one.py", "api.one")
    second = _symbol("src/two.py", "api.two")
    relationship = {
        "kind": kind,
        "source_key": first["symbol_key"],
        "target_key": second["symbol_key"],
        "file_path": "src/one.py",
        "line_start": 1,
    }
    document = (
        _codegraph(symbols=[first, second], relationships=[relationship])
        if provider == "codegraph"
        else _perlgraph(symbols=[first, second], relationships=[relationship], status="ready")
    )

    loaded = load_provider_document(document, provider=provider, source_id="api")

    assert loaded.relationships[0].type == normalized
    assert loaded.relationships[0].provider_kind == kind


@pytest.mark.unit
def test_load_provider_retains_unresolved_observations_without_creating_edges() -> None:
    from echelon.topology_provider import load_provider_document

    document = _perlgraph(status="degraded")
    document["unresolved_relationships"] = [
        {
            "kind": "calls",
            "source": "api.run",
            "target": "External::run",
            "file_path": "lib/API.pm",
            "line_start": 5,
        }
    ]
    document["counts"]["discovered_relationships"] = 1  # type: ignore[index]
    document["counts"]["unresolved_relationships"] = 1  # type: ignore[index]

    loaded = load_provider_document(document, provider="perlgraph", source_id="api")

    assert loaded.relationships == ()
    assert loaded.diagnostic_count == 1
    assert loaded.diagnostics[0].target_name == "External::run"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("provider", "document", "status"),
    [
        ("codegraph", _codegraph(), "ready"),
        ("codegraph", _codegraph(status="partial", complete=False), "degraded"),
        ("codegraph", _codegraph(symbols=[], status="complete", supported=False), "empty"),
        ("perlgraph", _perlgraph(status="empty"), "empty"),
        ("perlgraph", _perlgraph(status="unsupported"), "unsupported"),
    ],
)
def test_load_provider_maps_provider_specific_status_vocabularies(
    tmp_path: Path, provider: str, document: dict[str, object], status: str
) -> None:
    from echelon.topology_provider import load_provider_artifact

    loaded = load_provider_artifact(
        _write(tmp_path / f"{provider}.json", document), provider=provider, source_id="api"
    )

    assert loaded.status == status


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.update(provider_status="ready"),
        lambda document: document["symbols"].append(dict(document["symbols"][0])),
        lambda document: document["symbols"][0].update(symbol_key="sha256:" + "0" * 64),
        lambda document: document["relationships"][0].update(target_key="sha256:" + "f" * 64),
        lambda document: document["relationships"].append(dict(document["relationships"][0])),
        lambda document: document["counts"].update(emitted_symbols=99),
    ],
)
def test_load_provider_rejects_native_contract_drift(
    tmp_path: Path, mutate: object
) -> None:
    from echelon.topology_provider import TopologyProviderError, load_provider_artifact

    document = _codegraph()
    mutate(document)  # type: ignore[operator]
    with pytest.raises(TopologyProviderError):
        load_provider_artifact(
            _write(tmp_path / "codegraph.json", document), provider="codegraph", source_id="api"
        )


@pytest.mark.unit
def test_published_topology_resolves_selectors_and_bounds_traversal() -> None:
    from echelon.topology_provider import (
        PublishedTopology,
        TopologyNodeResolutionError,
        load_provider_document,
    )

    first = _symbol("src/one.py", "api.shared")
    second = _symbol("src/two.py", "api.shared")
    document = _codegraph(
        symbols=[first, second],
        relationships=[
            {
                "kind": "calls",
                "source_key": first["symbol_key"],
                "target_key": second["symbol_key"],
                "file_path": "src/one.py",
            },
            {
                "kind": "unknown_provider_relation",
                "source_key": second["symbol_key"],
                "target_key": first["symbol_key"],
                "file_path": "src/two.py",
            },
        ],
    )
    loaded = load_provider_document(document, provider="codegraph", source_id="api")
    topology = PublishedTopology.from_loaded_providers(
        [loaded],
        generation=7,
        source_fingerprints={"api": "sha256:" + "a" * 64},
        provider_receipt_hashes={"api": {"codegraph": "sha256:" + "b" * 64}},
        provider_artifact_paths={"api": {"codegraph": "re/topology/sources/api/codegraph-analysis.json"}},
    )

    with pytest.raises(TopologyNodeResolutionError, match="ambiguous") as error:
        topology.explain(None, "api.shared")
    assert len(error.value.candidates) == 2
    first_id = loaded.symbols[0].id
    explained = topology.explain(None, first_id)
    assert explained.node.id == first_id
    assert explained.receipt.generation == 7
    assert explained.receipt.provider_artifact_paths == (
        "re/topology/sources/api/codegraph-analysis.json",
    )

    neighbors = topology.neighbors(None, first_id, "out", frozenset({"CALLS"}), 1)
    assert [step.relationship.type for step in neighbors.steps] == ["CALLS"]
    assert neighbors.truncated is False
    impact = topology.impact(None, first_id, 3, frozenset())
    assert [step.relationship.type for step in impact.steps] == ["CALLS"]
    assert all(step.relationship.type != "OTHER" for step in impact.steps)
    search = topology.search("api", "shared", frozenset({"SYMBOL"}), 1)
    assert len(search.nodes) == 1
    assert search.truncated is True


@pytest.mark.unit
def test_impact_applies_its_fixed_default_edge_budget() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    symbols = [_symbol(f"src/{index}.py", f"api.{index}") for index in range(52)]
    relationships = [
        {
            "kind": "calls",
            "source_key": symbols[0]["symbol_key"],
            "target_key": symbol["symbol_key"],
            "file_path": symbols[0]["file_path"],
        }
        for symbol in symbols[1:]
    ]
    loaded = load_provider_document(
        _codegraph(symbols=symbols, relationships=relationships),
        provider="codegraph",
        source_id="api",
    )
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)

    result = topology.impact(None, loaded.symbols[0].id, 10, frozenset({"CALLS"}))

    assert len(result.steps) == 50
    assert result.truncated is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("search", (None, "api", frozenset({"NOPE"}), 50)),
        ("search", (None, "api", frozenset(), 501)),
        ("neighbors", (None, "x", "sideways", frozenset(), 50)),
        ("neighbors", (None, "x", "out", frozenset({"NOPE"}), 50)),
        ("impact", (None, "x", 11, frozenset())),
    ],
)
def test_published_topology_rejects_invalid_read_parameters(method: str, args: tuple[object, ...]) -> None:
    from echelon.topology_provider import PublishedTopology

    topology = PublishedTopology.from_loaded_providers([], generation=1)
    with pytest.raises(ValueError):
        getattr(topology, method)(*args)
