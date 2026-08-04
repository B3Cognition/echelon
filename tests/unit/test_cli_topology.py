from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner


def _audit_report(
    status: str = "current",
    *,
    source_ids: tuple[str, ...] = ("api", "web"),
    findings: tuple[object, ...] = (),
):
    from echelon.topology_audit import TopologyAuditReport, TopologyAuditSource

    exit_code = 0 if status == "current" else 2 if status == "invalid" else 1
    return TopologyAuditReport(
        status=status,  # type: ignore[arg-type]
        exit_code=exit_code,
        sources=tuple(
            TopologyAuditSource(source_id, status, ("codegraph",))  # type: ignore[arg-type]
            for source_id in source_ids
        ),
        findings=findings,  # type: ignore[arg-type]
    )


def _published_topology():
    from echelon.topology_provider import PublishedTopology, load_provider_document
    from tests.unit.test_topology_provider import _codegraph, _symbol

    caller = _symbol("src/caller.py", "api.caller")
    first = _symbol("src/one.py", "api.shared")
    second = _symbol("src/two.py", "api.shared")
    api = load_provider_document(
        _codegraph(
            symbols=[caller, first, second],
            relationships=[
                {
                    "kind": "calls",
                    "source_key": caller["symbol_key"],
                    "target_key": first["symbol_key"],
                    "file_path": "src/caller.py",
                    "line_start": 4,
                },
                {
                    "kind": "calls",
                    "source_key": second["symbol_key"],
                    "target_key": caller["symbol_key"],
                    "file_path": "src/two.py",
                    "line_start": 8,
                },
            ],
        ),
        provider="codegraph",
        source_id="api",
    )
    web_symbol = _symbol("src/web.py", "web.shared")
    web = load_provider_document(
        _codegraph(symbols=[web_symbol], relationships=[]),
        provider="codegraph",
        source_id="web",
    )
    return PublishedTopology.from_loaded_providers(
        [api, web],
        generation=7,
        source_fingerprints={"api": "a" * 64, "web": "b" * 64},
        provider_receipt_hashes={
            "api": {"codegraph": "sha256:" + "c" * 64},
            "web": {"codegraph": "sha256:" + "d" * 64},
        },
        provider_artifact_paths={
            "api": {
                "codegraph": "re/topology/sources/api/codegraph-analysis.json"
            },
            "web": {
                "codegraph": "re/topology/sources/web/codegraph-analysis.json"
            },
        },
        provider_statuses={
            "api": {"codegraph": "ready"},
            "web": {"codegraph": "ready"},
        },
    )


def _patch_reads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str = "current",
    topology: object | None = None,
) -> list[tuple[str, ...]]:
    import echelon.topology_cli as topology_cli

    loaded: list[tuple[str, ...]] = []
    published = topology or _published_topology()

    def audit(_root: Path, source_id: str | None = None):
        source_ids = (source_id,) if source_id else ("api", "web")
        return _audit_report(status, source_ids=source_ids)

    def load(_root: Path, source_ids: tuple[str, ...] = ()):
        loaded.append(tuple(source_ids))
        return published

    monkeypatch.setattr(topology_cli, "audit_topology", audit)
    monkeypatch.setattr(topology_cli, "load_published_topology", load)
    return loaded


@pytest.mark.unit
def test_topology_typer_parses_repeatable_filters_without_skill_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli_app import app

    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    fake = ModuleType("echelon.topology_cli")

    class Result:
        stdout = "ok\n"
        stderr = ""
        exit_code = 0

    def command(name: str):
        def invoke(*args: object, **kwargs: object) -> Result:
            calls.append((name, args, kwargs))
            return Result()

        return invoke

    for name in (
        "audit_command",
        "list_sources_command",
        "search_command",
        "explain_command",
        "neighbors_command",
        "impact_command",
    ):
        setattr(fake, name, command(name))
    monkeypatch.setitem(sys.modules, "echelon.topology_cli", fake)
    monkeypatch.setattr(
        "echelon.cli_app._dispatch_skill",
        lambda *args, **kwargs: pytest.fail("topology invoked the LLM skill dispatcher"),
    )

    response = CliRunner().invoke(
        app,
        [
            "topology",
            "search",
            "shared",
            "--source",
            "api",
            "--type",
            "file",
            "--type",
            "symbol",
            "--limit",
            "12",
            "--json",
        ],
    )
    neighbors = CliRunner().invoke(
        app,
        [
            "topology",
            "neighbors",
            "api.shared",
            "--direction",
            "in",
            "--relation",
            "calls",
            "--relation",
            "tests",
            "--limit",
            "9",
        ],
    )
    impact = CliRunner().invoke(
        app,
        [
            "topology",
            "impact",
            "api.shared",
            "--max-depth",
            "4",
            "--relation",
            "calls",
            "--relation",
            "extends",
            "--json",
        ],
    )

    assert response.exit_code == neighbors.exit_code == impact.exit_code == 0
    assert calls[0][2] == {
        "source": "api",
        "node_types": ("file", "symbol"),
        "limit": 12,
        "as_json": True,
    }
    assert calls[1][2]["direction"] == "in"
    assert calls[1][2]["relations"] == ("calls", "tests")
    assert calls[2][2]["max_depth"] == 4
    assert calls[2][2]["relations"] == ("calls", "extends")


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    (
        ("search", "shared", "--limit", "0"),
        ("search", "shared", "--limit", "501"),
        ("neighbors", "api.shared", "--direction", "sideways"),
        ("neighbors", "api.shared", "--limit", "0"),
        ("impact", "api.shared", "--max-depth", "0"),
        ("impact", "api.shared", "--max-depth", "11"),
    ),
)
def test_topology_typer_rejects_invalid_bounds_and_direction(argv: tuple[str, ...]) -> None:
    from echelon.cli_app import app

    response = CliRunner().invoke(app, ["topology", *argv])

    assert response.exit_code == 2


@pytest.mark.unit
def test_search_json_is_all_source_ordered_bounded_and_provenanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    loaded = _patch_reads(monkeypatch)
    result = topology_cli.search_command(
        Path("/workspace"),
        "shared",
        source=None,
        node_types=("symbol",),
        limit=2,
        as_json=True,
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert result.stderr == ""
    assert loaded == [()]
    assert payload["schema_version"] == 1
    assert payload["command"] == "search"
    assert payload["request"] == {
        "limit": 2,
        "query": "shared",
        "source": None,
        "types": ["SYMBOL"],
    }
    assert payload["truncated"] is True
    assert [row["node_id"] for row in payload["results"]] == sorted(
        row["node_id"] for row in payload["results"]
    )
    assert [row["source_id"] for row in payload["results"]] == ["api", "api"]
    for row in payload["results"]:
        assert row["provider"] == "codegraph"
        assert row["path"].startswith("src/")
        assert row["topology_generation"] == 7
        assert row["topology_status"] == "current"
        assert row["truncated"] is True
        assert row["provider_receipt_hash"] == "sha256:" + "c" * 64
        assert row["provider_artifact_path"].endswith("codegraph-analysis.json")
    assert payload["provenance"]["source_fingerprints"] == {
        "api": "a" * 64,
        "web": "b" * 64,
    }


@pytest.mark.unit
def test_search_source_scope_and_repeated_json_are_exactly_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    loaded = _patch_reads(monkeypatch)
    first = topology_cli.search_command(
        Path("/workspace"),
        "shared",
        source="web",
        node_types=("symbol",),
        limit=50,
        as_json=True,
    )
    second = topology_cli.search_command(
        Path("/workspace"),
        "shared",
        source="web",
        node_types=("symbol",),
        limit=50,
        as_json=True,
    )

    assert first.stdout == second.stdout
    assert loaded == [("web",), ("web",)]
    assert [row["source_id"] for row in json.loads(first.stdout)["results"]] == ["web"]
    assert "generated_at" not in first.stdout
    assert "published_at" not in first.stdout


@pytest.mark.unit
def test_explain_exact_node_and_ambiguous_selector_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    topology = _published_topology()
    _patch_reads(monkeypatch, topology=topology)
    exact_id = next(
        node.id
        for node in topology.nodes_by_id.values()
        if getattr(node, "qualified_name", "") == "api.caller"
    )

    exact = topology_cli.explain_command(
        Path("/workspace"), exact_id, source="api", as_json=True
    )
    ambiguous = topology_cli.explain_command(
        Path("/workspace"), "api.shared", source="api", as_json=True
    )
    payload = json.loads(exact.stdout)

    assert exact.exit_code == 0
    assert payload["node"]["node_id"] == exact_id
    assert [row["relation"] for row in payload["relationships"]] == [
        "CALLS",
        "CALLS",
        "DECLARES",
    ]
    assert ambiguous.exit_code == 2
    assert ambiguous.stdout == ""
    error = json.loads(ambiguous.stderr)
    assert error["error"]["kind"] == "ambiguous"
    assert len(error["error"]["candidates"]) == 2
    assert error["error"]["candidates"] == sorted(error["error"]["candidates"])


@pytest.mark.unit
def test_neighbors_and_impact_emit_direction_depth_paths_and_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    topology = _published_topology()
    _patch_reads(monkeypatch, topology=topology)
    caller_id = next(
        node.id
        for node in topology.nodes_by_id.values()
        if getattr(node, "qualified_name", "") == "api.caller"
    )
    first_id = next(
        node.id
        for node in topology.nodes_by_id.values()
        if getattr(node, "path", "") == "src/one.py"
        and getattr(node, "qualified_name", "") == "api.shared"
    )

    neighbors = topology_cli.neighbors_command(
        Path("/workspace"),
        caller_id,
        source="api",
        direction="both",
        relations=("calls",),
        limit=1,
        as_json=True,
    )
    impact = topology_cli.impact_command(
        Path("/workspace"),
        first_id,
        source="api",
        max_depth=2,
        relations=("calls",),
        as_json=True,
    )
    neighbors_payload = json.loads(neighbors.stdout)
    impact_payload = json.loads(impact.stdout)

    assert neighbors_payload["truncated"] is True
    assert len(neighbors_payload["steps"]) == 1
    assert neighbors_payload["steps"][0]["direction"] == "in"
    assert neighbors_payload["steps"][0]["relation"] == "CALLS"
    assert neighbors_payload["steps"][0]["truncated"] is True
    assert [step["depth"] for step in impact_payload["steps"]] == [1, 2]
    assert [step["relation"] for step in impact_payload["steps"]] == ["CALLS", "CALLS"]
    assert impact_payload["steps"][0]["traversal_path"] == [first_id, caller_id]
    assert impact_payload["steps"][0]["path"] == "src/caller.py"


@pytest.mark.unit
@pytest.mark.parametrize(("status", "exit_code"), (("current", 0), ("degraded", 1), ("stale", 1)))
def test_usable_read_preserves_audit_exit_and_stdout(
    monkeypatch: pytest.MonkeyPatch, status: str, exit_code: int
) -> None:
    import echelon.topology_cli as topology_cli

    _patch_reads(monkeypatch, status=status)
    result = topology_cli.search_command(
        Path("/workspace"), "shared", limit=50, as_json=False
    )

    assert result.exit_code == exit_code
    assert result.stdout.startswith(f"Topology search: {status}")
    assert "api.shared" in result.stdout
    assert result.stderr == ""


@pytest.mark.unit
def test_unavailable_read_is_fatal_and_only_writes_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.topology_model import TopologySource
    from echelon.topology_provider import PublishedTopology
    import echelon.topology_cli as topology_cli

    unavailable = PublishedTopology.from_loaded_providers(
        [],
        generation=7,
        provider_receipt_hashes={"api": {}},
        provider_artifact_paths={"api": {}},
        provider_statuses={"api": {"codegraph": "unavailable"}},
        sources=(TopologySource("api"),),
    )
    _patch_reads(monkeypatch, status="degraded", topology=unavailable)

    result = topology_cli.search_command(
        Path("/workspace"), "api", source="api", limit=50, as_json=False
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "unavailable" in result.stderr


@pytest.mark.unit
def test_audit_with_only_unavailable_providers_exits_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    import echelon.topology_cli as topology_cli

    monkeypatch.setattr(
        topology_cli,
        "audit_topology",
        lambda root, source_id=None: _audit_report(
            "degraded", source_ids=(source_id or "api",)
        ),
    )
    monkeypatch.setattr(
        topology_cli,
        "load_topology_index",
        lambda root: SimpleNamespace(
            sources={
                "api": SimpleNamespace(
                    providers={
                        "codegraph": SimpleNamespace(status="unavailable")
                    }
                )
            }
        ),
    )

    result = topology_cli.audit_command(
        Path("/workspace"), source="api", as_json=True
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["kind"] == "unavailable"


@pytest.mark.unit
def test_audit_fatal_diagnostics_are_bounded_and_written_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.topology_audit import TopologyAuditFinding
    import echelon.topology_cli as topology_cli

    findings = tuple(
        TopologyAuditFinding("invalid", f"failure {index}", "api")
        for index in range(25)
    )
    monkeypatch.setattr(
        topology_cli,
        "audit_topology",
        lambda root, source_id=None: _audit_report(
            "invalid", source_ids=(), findings=findings
        ),
    )

    result = topology_cli.audit_command(Path("/workspace"), as_json=True)
    payload = json.loads(result.stderr)

    assert result.exit_code == 2
    assert result.stdout == ""
    assert len(payload["audit"]["findings"]) == 10
    assert payload["audit"]["findings_truncated"] is True


@pytest.mark.unit
def test_list_sources_uses_canonical_index_and_provider_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.unit.test_topology_registry import build_topology, _write_json
    import echelon.topology_cli as topology_cli

    index = build_topology(tmp_path)
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["generation"] = 2
    index["sources"]["api"]["receipt"]["sha256"] = _write_json(  # type: ignore[index]
        receipt_path, receipt
    )
    _write_json(tmp_path / "re/topology/index.json", index)
    monkeypatch.setattr(
        topology_cli,
        "audit_topology",
        lambda root, source_id=None: _audit_report("current", source_ids=("api",)),
    )

    result = topology_cli.list_sources_command(tmp_path, as_json=True)
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["sources"] == [
        {
            "node_id": "source:api",
            "path": "sources/api",
            "provider": "topology",
            "providers": [
                {"complete": True, "provider": "codegraph", "status": "ready"},
                {"complete": True, "provider": "perlgraph", "status": "unsupported"},
            ],
            "source_fingerprint": "0" * 64,
            "source_id": "api",
            "source_generation": 2,
            "topology_generation": 3,
            "topology_status": "current",
            "truncated": False,
        }
    ]


@pytest.mark.unit
def test_topology_reads_never_publish_build_evidence_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli
    import harness.topology_evidence as topology_evidence
    import harness.topology_publication as topology_publication

    _patch_reads(monkeypatch)

    def forbidden(*args: object, **kwargs: object) -> object:
        pytest.fail("topology read invoked a mutation path")

    monkeypatch.setattr(
        topology_publication, "publish_topology_snapshots", forbidden
    )
    monkeypatch.setattr(
        topology_evidence, "build_topology_snapshot_candidate", forbidden
    )
    result = topology_cli.search_command(
        Path("/workspace"), "shared", node_types=("symbol",), limit=50
    )

    assert result.exit_code == 0
