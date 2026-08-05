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
    discovered_files: int | None = None,
    parse_failures: list[dict[str, object]] | None = None,
    parse_diagnostics: list[dict[str, object]] | None = None,
    unsupported_patterns: list[dict[str, object]] | None = None,
    unresolved_relationships: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    symbols = [] if symbols is None else symbols
    relationships = [] if relationships is None else relationships
    parse_failures = [] if parse_failures is None else parse_failures
    parse_diagnostics = [] if parse_diagnostics is None else parse_diagnostics
    unsupported_patterns = [] if unsupported_patterns is None else unsupported_patterns
    unresolved_relationships = (
        [] if unresolved_relationships is None else unresolved_relationships
    )
    if discovered_files is None:
        discovered_files = 0 if status == "unsupported" else 1
    emitted_files = discovered_files - len(parse_failures)
    parse_diagnostic_count = sum(
        int(diagnostic.get("error_count", 0)) for diagnostic in parse_diagnostics
    )
    return {
        "schema_version": 2,
        "tool": "perlgraph",
        "tool_version": "0.1.0",
        "repo_path": "/absolute/provider-only/path",
        "provider_status": status,
        "complete": complete,
        "supported": discovered_files > 0,
        "capabilities": {
            "language": "perl",
            "supported_extensions": [".pm"],
            "exact_symbol_keys": True,
            "exact_relationship_endpoints": True,
            "unresolved_relationship_diagnostics": True,
        },
        "counts": {
            "discovered_files": discovered_files,
            "emitted_files": emitted_files,
            "discovered_symbols": len(symbols),
            "emitted_symbols": len(symbols),
            "discovered_relationships": len(relationships) + len(unresolved_relationships),
            "emitted_relationships": len(relationships),
            "unresolved_relationships": len(unresolved_relationships),
            "parse_failures": len(parse_failures),
            "parse_diagnostics": parse_diagnostic_count,
            "dynamic_patterns": len(unsupported_patterns),
        },
        "symbols": symbols,
        "relationships": relationships,
        "unresolved_relationships": unresolved_relationships,
        "call_graph": [],
        "module_graph": [],
        "unsupported_patterns": unsupported_patterns,
        "parse_failures": parse_failures,
        "parse_diagnostics": parse_diagnostics,
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
    assert loaded.relationships[0].confidence is None
    assert loaded.relationships[0].provenance == ()
    assert loaded.relationships[0].notes is None
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

    document = _perlgraph(status="degraded", unsupported_patterns=[{}])
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
        ("codegraph", _codegraph(symbols=[], status="complete", supported=False), "unsupported"),
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
        provider_statuses={"api": {"codegraph": "ready"}},
    )

    with pytest.raises(TopologyNodeResolutionError, match="ambiguous") as error:
        topology.explain(None, "api.shared")
    assert len(error.value.candidates) == 2
    assert error.value.candidate_count == 2
    assert error.value.candidates_truncated is False
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
    impact = topology.impact(None, loaded.symbols[1].id, 3, frozenset())
    assert [step.relationship.type for step in impact.steps] == ["CALLS"]
    assert all(step.relationship.type != "OTHER" for step in impact.steps)
    search = topology.search("api", "shared", frozenset({"SYMBOL"}), 1)
    assert len(search.nodes) == 1
    assert search.truncated is True


@pytest.mark.unit
def test_ambiguous_resolution_retains_cardinality_after_candidate_cap() -> None:
    from echelon.topology_provider import (
        PublishedTopology,
        TopologyNodeResolutionError,
        load_provider_document,
    )

    symbols = [_symbol(f"src/{index:02d}.py", "api.shared") for index in range(12)]
    loaded = load_provider_document(
        _codegraph(symbols=symbols, relationships=[]),
        provider="codegraph",
        source_id="api",
    )
    topology = PublishedTopology.from_loaded_providers([loaded], generation=7)

    with pytest.raises(TopologyNodeResolutionError) as error:
        topology.explain("api", "api.shared")

    assert len(error.value.candidates) == 10
    assert error.value.candidate_count == 12
    assert error.value.candidates_truncated is True


@pytest.mark.unit
def test_impact_applies_its_fixed_default_edge_budget() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    symbols = [_symbol(f"src/{index}.py", f"api.{index}") for index in range(52)]
    relationships = [
        {
            "kind": "calls",
            "source_key": symbol["symbol_key"],
            "target_key": symbols[0]["symbol_key"],
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

    root_id = next(symbol.id for symbol in loaded.symbols if symbol.qualified_name == "api.0")
    result = topology.impact(None, root_id, 10, frozenset({"CALLS"}))

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


@pytest.mark.unit
@pytest.mark.parametrize(
    "document",
    [
        _perlgraph(status="unsupported", discovered_files=1),
        _perlgraph(status="ready", discovered_files=1),
        _perlgraph(
            status="empty",
            discovered_files=1,
            parse_failures=[{"file_path": "lib/API.pm", "error": "broken"}],
        ),
        _perlgraph(status="degraded", symbols=[_symbol("lib/API.pm", "API::run")]),
        _perlgraph(
            status="ready",
            symbols=[_symbol("lib/API.pm", "API::run")],
            parse_diagnostics=[{"file_path": "lib/API.pm", "error_count": 1, "notes": "partial"}],
        ),
    ],
)
def test_perlgraph_rejects_status_claims_that_contradict_task_two_producer_rules(
    document: dict[str, object]
) -> None:
    from echelon.topology_provider import TopologyProviderError, load_provider_document

    with pytest.raises(TopologyProviderError):
        load_provider_document(document, provider="perlgraph", source_id="api")


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document["counts"].update(discovered_files=2),
        lambda document: document["counts"].update(discovered_symbols=1),
    ],
)
def test_perlgraph_reconciles_task_two_count_claims(mutate: object) -> None:
    from echelon.topology_provider import TopologyProviderError, load_provider_document

    document = _perlgraph(status="empty", discovered_files=1)
    mutate(document)  # type: ignore[operator]
    with pytest.raises(TopologyProviderError):
        load_provider_document(document, provider="perlgraph", source_id="api")


@pytest.mark.unit
def test_impact_follows_dependents_and_structural_expansion_with_typed_directions() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    caller = _symbol("src/caller.py", "api.caller")
    callee = _symbol("src/callee.py", "api.callee")
    child = _symbol("src/child.py", "api.child")
    parent = _symbol("src/parent.py", "api.parent")
    document = _codegraph(
        symbols=[caller, callee, child, parent],
        relationships=[
            {"kind": "calls", "source_key": caller["symbol_key"], "target_key": callee["symbol_key"], "file_path": "src/caller.py"},
            {"kind": "extends", "source_key": child["symbol_key"], "target_key": parent["symbol_key"], "file_path": "src/child.py"},
        ],
    )
    loaded = load_provider_document(document, provider="codegraph", source_id="api")
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)
    symbol_ids = {symbol.qualified_name: symbol.id for symbol in loaded.symbols}

    callee_impact = topology.impact(None, symbol_ids["api.callee"], 3, frozenset())
    parent_impact = topology.impact(None, symbol_ids["api.parent"], 3, frozenset())
    source_impact = topology.impact(None, "source:api", 2, frozenset())
    filtered = topology.impact(None, symbol_ids["api.callee"], 3, frozenset({"CALLS"}))

    assert [step.node_id for step in callee_impact.steps] == [symbol_ids["api.caller"]]
    assert [step.node_id for step in parent_impact.steps] == [symbol_ids["api.child"]]
    assert [step.relationship.type for step in source_impact.steps].count("CONTAINS") == 4
    assert [step.relationship.type for step in source_impact.steps].count("DECLARES") == 4
    assert [step.relationship.type for step in filtered.steps] == ["CALLS"]


@pytest.mark.unit
def test_impact_is_cycle_safe_and_marks_budget_truncation_only_for_omitted_edges() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    first = _symbol("src/first.py", "api.first")
    second = _symbol("src/second.py", "api.second")
    cycle = _codegraph(
        symbols=[first, second],
        relationships=[
            {"kind": "calls", "source_key": first["symbol_key"], "target_key": second["symbol_key"], "file_path": "src/first.py"},
            {"kind": "calls", "source_key": second["symbol_key"], "target_key": first["symbol_key"], "file_path": "src/second.py"},
        ],
    )
    cycle_loaded = load_provider_document(cycle, provider="codegraph", source_id="api")
    cycle_topology = PublishedTopology.from_loaded_providers([cycle_loaded], generation=1)
    cycle_result = cycle_topology.impact(None, cycle_loaded.symbols[1].id, 10, frozenset())

    symbols = [_symbol(f"src/{index}.py", f"api.{index}") for index in range(51)]
    leaves = [
        {"kind": "calls", "source_key": symbol["symbol_key"], "target_key": symbols[0]["symbol_key"], "file_path": "src/0.py"}
        for symbol in symbols[1:]
    ]
    loaded = load_provider_document(
        _codegraph(symbols=symbols, relationships=leaves), provider="codegraph", source_id="api"
    )
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)
    root_id = next(symbol.id for symbol in loaded.symbols if symbol.qualified_name == "api.0")
    exact_budget = topology.impact(None, root_id, 10, frozenset({"CALLS"}))

    assert [step.node_id for step in cycle_result.steps] == [
        cycle_loaded.symbols[0].id,
        cycle_loaded.symbols[1].id,
    ]
    assert cycle_result.truncated is False
    assert len(exact_budget.steps) == 50
    assert exact_budget.truncated is False


@pytest.mark.unit
def test_neighbors_both_deduplicates_a_self_loop_with_a_stable_direction() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    loaded = load_provider_document(_codegraph(), provider="codegraph", source_id="api")
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)

    result = topology.neighbors(None, loaded.symbols[0].id, "both", frozenset(), 50)

    calls = [step for step in result.steps if step.relationship.type == "CALLS"]
    assert len(calls) == 1
    assert calls[0].direction == "in"


@pytest.mark.unit
def test_perlgraph_resolved_relationship_retains_immutable_evidence() -> None:
    from dataclasses import FrozenInstanceError

    from echelon.topology_provider import load_provider_document

    caller = _symbol("lib/API.pm", "API::caller")
    callee = _symbol("lib/API.pm", "API::callee")
    loaded = load_provider_document(
        _perlgraph(
            status="ready",
            symbols=[caller, callee],
            relationships=[
                {
                    "kind": "calls",
                    "source_key": caller["symbol_key"],
                    "target_key": callee["symbol_key"],
                    "file_path": "lib/API.pm",
                    "line_start": 10,
                    "confidence": "medium",
                    "provenance": [
                        "tree-sitter",
                        "constructor-assignment",
                    ],
                    "notes": "Receiver inferred from constructor assignment.",
                }
            ],
        ),
        provider="perlgraph",
        source_id="api",
    )

    relationship = loaded.relationships[0]
    assert relationship.provider == "perlgraph"
    assert relationship.provider_kind == "calls"
    assert relationship.path == "lib/API.pm"
    assert relationship.line_start == 10
    assert relationship.confidence == "medium"
    assert relationship.provenance == (
        "tree-sitter",
        "constructor-assignment",
    )
    assert relationship.notes == "Receiver inferred from constructor assignment."
    with pytest.raises(FrozenInstanceError):
        relationship.notes = "changed"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", ["high"]),
        ("provenance", ("tree-sitter",)),
        ("provenance", [""]),
        ("notes", 7),
    ],
)
def test_perlgraph_rejects_invalid_resolved_relationship_evidence(
    field: str, value: object
) -> None:
    from echelon.topology_provider import TopologyProviderError, load_provider_document

    caller = _symbol("lib/API.pm", "API::caller")
    callee = _symbol("lib/API.pm", "API::callee")
    relationship = {
        "kind": "calls",
        "source_key": caller["symbol_key"],
        "target_key": callee["symbol_key"],
        field: value,
    }

    with pytest.raises(TopologyProviderError):
        load_provider_document(
            _perlgraph(
                status="ready",
                symbols=[caller, callee],
                relationships=[relationship],
            ),
            provider="perlgraph",
            source_id="api",
        )


@pytest.mark.unit
def test_perlgraph_preserves_evidence_distinct_relationship_observations_but_rejects_exact_duplicates() -> None:
    from echelon.topology_provider import TopologyProviderError, load_provider_document

    first = _symbol("lib/API.pm", "API::first")
    second = _symbol("lib/API.pm", "API::second")
    first_call = {
        "kind": "calls", "source_key": first["symbol_key"], "target_key": second["symbol_key"],
        "file_path": "lib/API.pm", "line_start": 10, "confidence": "high",
        "provenance": ["tree-sitter"],
    }
    second_call = {
        **first_call,
        "confidence": "medium",
        "provenance": ["tree-sitter", "constructor-assignment"],
        "notes": "Receiver inferred from constructor assignment.",
    }
    document = _perlgraph(
        status="ready", symbols=[first, second], relationships=[first_call, second_call]
    )

    loaded = load_provider_document(document, provider="perlgraph", source_id="api")
    assert [relationship.confidence for relationship in loaded.relationships] == [
        "high",
        "medium",
    ]

    with pytest.raises(TopologyProviderError, match="duplicate"):
        load_provider_document(
            _perlgraph(status="ready", symbols=[first, second], relationships=[first_call, first_call]),
            provider="perlgraph",
            source_id="api",
        )


@pytest.mark.unit
def test_perlgraph_diagnostic_retains_confidence_provenance_and_notes() -> None:
    from dataclasses import FrozenInstanceError

    from echelon.topology_provider import load_provider_document

    document = _perlgraph(
        status="degraded",
        unsupported_patterns=[{}],
        unresolved_relationships=[
            {
                "kind": "calls", "source": "API::run", "target": "External::run",
                "file_path": "lib/API.pm", "line_start": 5, "confidence": "dynamic",
                "provenance": ["tree-sitter", "dynamic-call"], "notes": "Receiver is dynamic.",
            }
        ],
    )
    loaded = load_provider_document(document, provider="perlgraph", source_id="api")
    diagnostic = loaded.diagnostics[0]

    assert diagnostic.confidence == "dynamic"
    assert diagnostic.provenance == ("tree-sitter", "dynamic-call")
    assert diagnostic.notes == "Receiver is dynamic."
    with pytest.raises(FrozenInstanceError):
        diagnostic.notes = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_selector_indexes_are_deterministic_and_added_once_per_node() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    loaded = load_provider_document(_codegraph(), provider="codegraph", source_id="api")
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)

    assert topology._selectors["qualified_name"]["api.run"] == (loaded.symbols[0].id,)


@pytest.mark.unit
@pytest.mark.parametrize("generation", ("1", True, 0, -1))
def test_published_topology_rejects_noncanonical_generation(generation: object) -> None:
    from echelon.topology_provider import PublishedTopology

    with pytest.raises(ValueError):
        PublishedTopology.from_loaded_providers([], generation=generation)  # type: ignore[arg-type]


@pytest.mark.unit
def test_from_loaded_providers_rejects_duplicate_provider_rows_and_incomplete_explicit_provenance() -> None:
    from echelon.topology_provider import (
        PublishedTopology,
        TopologyProviderError,
        load_provider_document,
    )

    loaded = load_provider_document(_codegraph(), provider="codegraph", source_id="api")
    with pytest.raises(TopologyProviderError, match="duplicate"):
        PublishedTopology.from_loaded_providers([loaded, loaded], generation=1)
    with pytest.raises(TopologyProviderError, match="explicit provider provenance"):
        PublishedTopology.from_loaded_providers(
            [loaded],
            generation=1,
            provider_receipt_hashes={"api": {"codegraph": "sha256:" + "a" * 64}},
            provider_artifact_paths={"api": {"codegraph": "re/topology/sources/api/codegraph-analysis.json"}},
        )
    with pytest.raises(TopologyProviderError, match="provider provenance"):
        PublishedTopology.from_loaded_providers(
            [loaded],
            generation=1,
            provider_receipt_hashes={"api": {"codegraph": "sha256:" + "a" * 64, "perlgraph": "sha256:" + "b" * 64}},
            provider_artifact_paths={"api": {"codegraph": "re/topology/sources/api/codegraph-analysis.json", "perlgraph": "re/topology/sources/api/perlgraph-analysis.json"}},
            provider_statuses={"api": {"codegraph": "ready", "perlgraph": "empty"}},
        )


@pytest.mark.unit
def test_public_receipts_preserve_unavailable_provider_without_traversal_paths() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    loaded = load_provider_document(_codegraph(), provider="codegraph", source_id="api")
    topology = PublishedTopology.from_loaded_providers(
        [loaded],
        generation=1,
        source_fingerprints={"api": "f" * 64},
        provider_receipt_hashes={"api": {"codegraph": "sha256:" + "a" * 64}},
        provider_artifact_paths={"api": {"codegraph": "re/topology/sources/api/codegraph-analysis.json"}},
        provider_statuses={"api": {"codegraph": "ready", "perlgraph": "unavailable"}},
    )

    receipt = topology.receipt("api")
    search = topology.search("api", "api.run", frozenset(), 10)

    assert receipt.provider_statuses == {"codegraph": "ready", "perlgraph": "unavailable"}
    assert receipt.provider_artifact_paths == ("re/topology/sources/api/codegraph-analysis.json",)
    assert search.receipt.provider_statuses == receipt.provider_statuses
    assert all(node.provider == "codegraph" for node in search.nodes if hasattr(node, "provider"))


@pytest.mark.unit
def test_cross_source_search_receipt_covers_all_queried_sources_and_fingerprints() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    api = load_provider_document(_codegraph(), provider="codegraph", source_id="api")
    worker = load_provider_document(_codegraph(), provider="codegraph", source_id="worker")
    hashes = {
        "api": {"codegraph": "sha256:" + "a" * 64},
        "worker": {"codegraph": "sha256:" + "b" * 64},
    }
    paths = {
        "api": {"codegraph": "re/topology/sources/api/codegraph-analysis.json"},
        "worker": {"codegraph": "re/topology/sources/worker/codegraph-analysis.json"},
    }
    statuses = {"api": {"codegraph": "ready"}, "worker": {"codegraph": "ready"}}
    topology = PublishedTopology.from_loaded_providers(
        [api, worker], generation=3,
        source_fingerprints={"api": "fingerprint-api", "worker": "fingerprint-worker"},
        provider_receipt_hashes=hashes, provider_artifact_paths=paths, provider_statuses=statuses,
    )

    result = topology.search(None, "run", frozenset({"SYMBOL"}), 1)

    assert result.truncated is True
    assert result.receipt.source_id is None
    assert dict(result.receipt.source_fingerprints) == {
        "api": "fingerprint-api", "worker": "fingerprint-worker",
    }


@pytest.mark.unit
@pytest.mark.parametrize(("call_sites", "truncated"), ((50, False), (51, True)))
def test_impact_accounts_for_repeated_perl_call_site_observations(
    call_sites: int, truncated: bool
) -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    caller = _symbol("lib/API.pm", "API::caller")
    callee = _symbol("lib/API.pm", "API::callee")
    relationships = [
        {
            "kind": "calls",
            "source_key": caller["symbol_key"],
            "target_key": callee["symbol_key"],
            "file_path": "lib/API.pm",
            "line_start": line,
        }
        for line in range(1, call_sites + 1)
    ]
    loaded = load_provider_document(
        _perlgraph(status="ready", symbols=[caller, callee], relationships=relationships),
        provider="perlgraph",
        source_id="api",
    )
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)
    callee_id = next(symbol.id for symbol in loaded.symbols if symbol.qualified_name == "API::callee")

    result = topology.impact(None, callee_id, 3, frozenset({"CALLS"}))

    assert len(result.steps) == min(call_sites, 50)
    assert [step.relationship.line_start for step in result.steps] == list(
        range(1, min(call_sites, 50) + 1)
    )
    assert result.truncated is truncated


@pytest.mark.unit
def test_impact_counts_cycle_observations_once_and_deduplicates_both_direction_other() -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document

    first = _symbol("src/first.py", "api.first")
    second = _symbol("src/second.py", "api.second")
    document = _codegraph(
        symbols=[first, second],
        relationships=[
            {"kind": "calls", "source_key": first["symbol_key"], "target_key": second["symbol_key"], "file_path": "src/first.py", "line_start": 1},
            {"kind": "calls", "source_key": second["symbol_key"], "target_key": first["symbol_key"], "file_path": "src/second.py", "line_start": 2},
            {"kind": "unrecognized", "source_key": first["symbol_key"], "target_key": second["symbol_key"], "file_path": "src/first.py", "line_start": 3},
        ],
    )
    loaded = load_provider_document(document, provider="codegraph", source_id="api")
    topology = PublishedTopology.from_loaded_providers([loaded], generation=1)
    second_id = next(symbol.id for symbol in loaded.symbols if symbol.qualified_name == "api.second")
    first_id = next(symbol.id for symbol in loaded.symbols if symbol.qualified_name == "api.first")

    cycle = topology.impact(None, second_id, 5, frozenset({"CALLS"}))
    other = topology.impact(None, first_id, 5, frozenset({"OTHER"}))

    assert [step.relationship.line_start for step in cycle.steps] == [1, 2]
    assert len(other.steps) == 1
    assert other.steps[0].relationship.type == "OTHER"


@pytest.mark.unit
@pytest.mark.parametrize("unc_name", ("\\\\server\\share\\secret", "//server/share/secret"))
def test_provider_rejects_unc_symbol_names_before_they_become_searchable(unc_name: str) -> None:
    from echelon.topology_provider import TopologyProviderError, load_provider_document

    document = _codegraph()
    document["symbols"][0]["name"] = unc_name  # type: ignore[index]

    with pytest.raises(TopologyProviderError):
        load_provider_document(document, provider="codegraph", source_id="api")
