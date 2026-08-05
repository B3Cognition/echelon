from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner
import yaml


def _audit_report(
    status: str = "current",
    *,
    source_ids: tuple[str, ...] = ("api", "web"),
    findings: tuple[object, ...] = (),
    snapshot: object | None = None,
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
        snapshot=snapshot,  # type: ignore[arg-type]
    )


def _audit_snapshot(topology: object, source_ids: tuple[str, ...]):
    from echelon.topology_audit import (
        TopologyAuditSnapshot,
        TopologyAuditSnapshotSource,
    )

    paths = {"api": "services/api", "web": "apps/web"}
    rows = []
    for source_id in source_ids:
        receipt = topology.receipt(source_id)
        receipt_hashes = set(receipt.provider_receipt_hashes.values())
        rows.append(
            TopologyAuditSnapshotSource(
                source_id=source_id,
                source_path=paths[source_id],
                source_fingerprint=receipt.source_fingerprint,
                receipt_sha256=next(
                    iter(receipt_hashes), "sha256:" + "e" * 64
                ),
            )
        )
    return TopologyAuditSnapshot(
        generation=topology.generation,
        sources=tuple(rows),
    )


def _published_topology(*, generation: int = 7):
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
        generation=generation,
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
        return _audit_report(
            status,
            source_ids=source_ids,
            snapshot=_audit_snapshot(published, source_ids),
        )

    def load(_root: Path, source_ids: tuple[str, ...] = ()):
        loaded.append(tuple(source_ids))
        return published

    monkeypatch.setattr(topology_cli, "audit_topology", audit)
    monkeypatch.setattr(topology_cli, "load_published_topology", load)
    return loaded


def _patch_current_then_stale_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> list[object]:
    from harness.re_fingerprint import SourceFingerprint

    current = SourceFingerprint(
        "0" * 64,
        "git",
        False,
        "1" * 64,
        "0123456789abcdef0123456789abcdef01234567",
    )
    stale = SourceFingerprint(
        "f" * 64,
        "git",
        False,
        "1" * 64,
        "0123456789abcdef0123456789abcdef01234567",
    )
    observed: list[object] = []
    values = iter((current, stale))

    def fingerprint(path: Path, profile: object) -> SourceFingerprint:
        value = next(values)
        observed.append(value)
        return value

    monkeypatch.setattr(
        "echelon.topology_audit.resolve_re_fingerprint_profile",
        lambda root: object(),
    )
    monkeypatch.setattr("echelon.topology_audit.fingerprint_source", fingerprint)
    return observed


def _invoke_topology_service(
    topology_cli: object,
    command: str,
    root: Path,
    *,
    as_json: bool,
):
    if command == "audit":
        return topology_cli.audit_command(root, as_json=as_json)
    if command == "list-sources":
        return topology_cli.list_sources_command(root, as_json=as_json)
    if command == "search":
        return topology_cli.search_command(root, "shared", as_json=as_json)
    if command == "explain":
        return topology_cli.explain_command(root, "api.shared", as_json=as_json)
    if command == "neighbors":
        return topology_cli.neighbors_command(root, "api.shared", as_json=as_json)
    if command == "impact":
        return topology_cli.impact_command(root, "api.shared", as_json=as_json)
    raise AssertionError(f"unknown test command: {command}")


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
    assert loaded == [(), ()]
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
    assert loaded == [("web",), ("web",), ("web",), ("web",)]
    assert [row["source_id"] for row in json.loads(first.stdout)["results"]] == ["web"]
    assert "generated_at" not in first.stdout
    assert "published_at" not in first.stdout


@pytest.mark.unit
def test_source_node_search_uses_final_audited_source_path_in_json_and_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    _patch_reads(monkeypatch)

    json_result = topology_cli.search_command(
        Path("/workspace"),
        "api",
        source="api",
        node_types=("source",),
        as_json=True,
    )
    text_result = topology_cli.search_command(
        Path("/workspace"),
        "api",
        source="api",
        node_types=("source",),
    )
    row = json.loads(json_result.stdout)["results"][0]

    assert row["node_id"] == "source:api"
    assert row["path"] == "services/api"
    assert row["source_relative_path"] == "services/api"
    source_line = next(
        line for line in text_result.stdout.splitlines() if "[SOURCE]" in line
    )
    assert "source:api" in source_line
    assert "path=services/api" in source_line


@pytest.mark.unit
def test_source_root_impact_uses_final_audited_source_path_in_json_and_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    _patch_reads(monkeypatch)

    json_result = topology_cli.impact_command(
        Path("/workspace"),
        "source:api",
        source="api",
        max_depth=1,
        relations=("contains",),
        as_json=True,
    )
    text_result = topology_cli.impact_command(
        Path("/workspace"),
        "source:api",
        source="api",
        max_depth=1,
        relations=("contains",),
    )
    source_row = next(
        row for row in json.loads(json_result.stdout)["nodes"]
        if row["node_id"] == "source:api"
    )

    assert source_row["path"] == "services/api"
    assert source_row["source_relative_path"] == "services/api"
    source_line = next(
        line for line in text_result.stdout.splitlines() if "[SOURCE]" in line
    )
    assert "source:api" in source_line
    assert "path=services/api" in source_line


@pytest.mark.unit
@pytest.mark.parametrize("command", ("audit", "list", "search"))
def test_topology_commands_revalidate_live_freshness_before_rendering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    from tests.unit.test_topology_registry import build_topology
    import echelon.topology_cli as topology_cli

    build_topology(tmp_path)
    observed = _patch_current_then_stale_fingerprint(monkeypatch)

    if command == "audit":
        result = topology_cli.audit_command(tmp_path, source="api", as_json=True)
    elif command == "list":
        result = topology_cli.list_sources_command(tmp_path, as_json=True)
    else:
        result = topology_cli.search_command(
            tmp_path, "run", source="api", as_json=True
        )

    assert len(observed) == 2
    assert result.exit_code in {1, 2}
    rendered = result.stdout or result.stderr
    assert json.loads(rendered)["audit"]["status"] in {"stale", "invalid"}


@pytest.mark.unit
@pytest.mark.parametrize("command", ("audit", "list", "search"))
def test_final_canonical_load_precedes_live_audit_and_exposes_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    from echelon.topology_registry import load_topology_index
    from tests.unit.test_topology_registry import build_topology
    import echelon.topology_cli as topology_cli

    build_topology(tmp_path)
    index = load_topology_index(tmp_path)
    assert index is not None
    topology = _published_topology()
    events: list[str] = []
    mutated = False
    load_count = 0

    def audit(root: Path, source_id: str | None = None):
        events.append("audit-stale" if mutated else "audit-current")
        return _audit_report(
            "stale" if mutated else "current",
            source_ids=(source_id,) if source_id else ("api",),
        )

    def load_index(root: Path):
        nonlocal load_count, mutated
        load_count += 1
        if load_count == 2:
            mutated = True
        events.append(f"load-{load_count}")
        return index

    def load_published(root: Path, source_ids: tuple[str, ...] = ()):
        nonlocal load_count, mutated
        load_count += 1
        if load_count == 2:
            mutated = True
        events.append(f"load-{load_count}")
        return topology

    monkeypatch.setattr(topology_cli, "audit_topology", audit)
    if command in {"audit", "list"}:
        monkeypatch.setattr(topology_cli, "load_topology_index", load_index)
    else:
        monkeypatch.setattr(topology_cli, "load_published_topology", load_published)

    if command == "audit":
        result = topology_cli.audit_command(tmp_path, source="api", as_json=True)
    elif command == "list":
        result = topology_cli.list_sources_command(tmp_path, as_json=True)
    else:
        result = topology_cli.search_command(
            tmp_path, "shared", source="api", as_json=True
        )

    assert events == ["audit-current", "load-1", "load-2", "audit-stale"]
    assert result.exit_code == 1
    assert json.loads(result.stdout)["audit"]["status"] == "stale"


@pytest.mark.unit
@pytest.mark.parametrize("command", ("audit", "list", "search"))
def test_cli_fails_closed_on_index_swap_inside_final_live_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    from harness.re_fingerprint import SourceFingerprint
    from tests.unit.test_topology_audit import _advance_publication_generation
    from tests.unit.test_topology_registry import build_topology
    import echelon.topology_audit as topology_audit
    import echelon.topology_cli as topology_cli

    build_topology(tmp_path)
    real_audit = topology_cli.audit_topology
    real_load_index = topology_audit.load_topology_index
    audit_count = 0
    arm_swap = False
    swapped = False

    def audit(root: Path, source_id: str | None = None):
        nonlocal audit_count, arm_swap
        audit_count += 1
        arm_swap = audit_count == 2
        return real_audit(root, source_id=source_id)

    def load_index(root: Path):
        nonlocal swapped
        index = real_load_index(root)
        if arm_swap and not swapped:
            swapped = True
            _advance_publication_generation(root)
        return index

    fingerprint = SourceFingerprint(
        "0" * 64,
        "git",
        False,
        "1" * 64,
        "0123456789abcdef0123456789abcdef01234567",
    )
    monkeypatch.setattr(topology_cli, "audit_topology", audit)
    monkeypatch.setattr(topology_audit, "load_topology_index", load_index)
    monkeypatch.setattr(
        topology_audit, "resolve_re_fingerprint_profile", lambda root: object()
    )
    monkeypatch.setattr(
        topology_audit, "fingerprint_source", lambda path, profile: fingerprint
    )

    if command == "audit":
        result = topology_cli.audit_command(tmp_path, source="api", as_json=True)
    elif command == "list":
        result = topology_cli.list_sources_command(tmp_path, as_json=True)
    else:
        result = topology_cli.search_command(
            tmp_path, "run", source="api", as_json=True
        )

    assert swapped is True
    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["audit"]["status"] == "invalid"
    assert "publication changed during audit" in payload["error"]["message"]


@pytest.mark.unit
def test_topology_read_fails_closed_when_publication_changes_during_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import echelon.topology_cli as topology_cli

    versions = iter(
        (_published_topology(generation=7), _published_topology(generation=8))
    )
    monkeypatch.setattr(
        topology_cli,
        "audit_topology",
        lambda root, source_id=None: _audit_report(
            "current", source_ids=(source_id or "api",)
        ),
    )
    monkeypatch.setattr(
        topology_cli,
        "load_published_topology",
        lambda root, source_ids=(): next(versions),
    )

    result = topology_cli.search_command(
        Path("/workspace"), "shared", source="api", as_json=True
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["error"]["kind"] == "invalid"
    assert "changed during read" in payload["error"]["message"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "command", ("audit", "list-sources", "search", "explain", "neighbors", "impact")
)
@pytest.mark.parametrize(
    "error",
    (
        ValueError("workspace discovery rejected config"),
        OSError("workspace config cannot be read"),
        yaml.YAMLError("workspace config YAML is malformed"),
    ),
)
def test_every_topology_service_bounds_workspace_audit_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    error: Exception,
) -> None:
    import echelon.topology_cli as topology_cli

    def fail_audit(root: Path, source_id: str | None = None) -> object:
        raise error

    monkeypatch.setattr(topology_cli, "audit_topology", fail_audit)

    result = _invoke_topology_service(
        topology_cli, command, Path("/workspace"), as_json=True
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["command"] == command
    assert payload["audit"]["status"] == "invalid"
    assert payload["error"]["kind"] == "invalid"
    assert 0 < len(result.stderr.encode("utf-8")) < 10_000


@pytest.mark.unit
@pytest.mark.parametrize(
    "document",
    (
        "null\n",
        "- api\n- web\n",
        "workspace: [\n",
    ),
)
def test_malformed_workspace_config_is_a_bounded_fatal_result(
    tmp_path: Path,
    document: str,
) -> None:
    from tests.unit.test_topology_registry import build_topology
    import echelon.topology_cli as topology_cli

    build_topology(tmp_path)
    (tmp_path / ".echelon/config.yml").write_text(document, encoding="utf-8")

    result = topology_cli.audit_command(tmp_path, as_json=True)

    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["audit"]["status"] == "invalid"
    assert payload["error"]["kind"] == "invalid"
    assert "workspace config" in payload["error"]["message"]
    assert len(result.stderr.encode("utf-8")) < 10_000


@pytest.mark.unit
@pytest.mark.parametrize(
    ("document", "message"),
    (
        ("workspace: null\nsources: []\n", "workspace must be a mapping"),
        ("workspace: []\nsources: []\n", "workspace must be a mapping"),
        ("sources:\n  - 42\n", "sources entry 1 must be"),
        ("sources:\n  - id: api\n", "sources entry 1 requires a path"),
        ("sources:\n  api: sources/api\n", "sources must be a list"),
        ("sources: api\n", "sources must be a list"),
    ),
)
@pytest.mark.parametrize(
    "command", ("audit", "list-sources", "search", "explain", "neighbors", "impact")
)
def test_every_topology_service_rejects_semantically_malformed_workspace_config(
    tmp_path: Path,
    command: str,
    document: str,
    message: str,
) -> None:
    from tests.unit.test_topology_registry import build_topology
    import echelon.topology_cli as topology_cli

    build_topology(tmp_path)
    (tmp_path / ".echelon/config.yml").write_text(document, encoding="utf-8")

    result = _invoke_topology_service(
        topology_cli, command, tmp_path, as_json=True
    )

    assert result.exit_code == 2
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["error"]["kind"] == "invalid"
    assert message in payload["error"]["message"]
    assert len(result.stderr.encode("utf-8")) < 10_000


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
    for row in payload["relationships"]:
        assert row["source_id"] == "api"
        assert row["provider"]
        assert row["source_node_id"] and row["target_node_id"]
        assert row["source_relative_path"].startswith("src/")
        assert row["topology_generation"] == 7
        assert row["topology_status"] == "current"
        assert row["truncated"] is False
    assert ambiguous.exit_code == 2
    assert ambiguous.stdout == ""
    error = json.loads(ambiguous.stderr)
    assert error["error"]["kind"] == "ambiguous"
    assert len(error["error"]["candidates"]) == 2
    assert error["error"]["candidates"] == sorted(error["error"]["candidates"])


@pytest.mark.unit
def test_perlgraph_relationship_evidence_is_exposed_in_bounded_json_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.topology_provider import PublishedTopology, load_provider_document
    from tests.unit.test_topology_provider import _perlgraph, _symbol
    import echelon.topology_cli as topology_cli

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
                    "line_start": 42,
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
    topology = PublishedTopology.from_loaded_providers(
        [loaded],
        generation=7,
        source_fingerprints={"api": "a" * 64},
        provider_receipt_hashes={
            "api": {"perlgraph": "sha256:" + "c" * 64}
        },
        provider_artifact_paths={
            "api": {
                "perlgraph": "re/topology/sources/api/perlgraph-analysis.json"
            }
        },
        provider_statuses={"api": {"perlgraph": "ready"}},
    )
    _patch_reads(monkeypatch, topology=topology)
    caller_id = next(
        symbol.id
        for symbol in loaded.symbols
        if symbol.qualified_name == "API::caller"
    )

    explained = topology_cli.explain_command(
        Path("/workspace"), caller_id, source="api", as_json=True
    )
    neighbors = topology_cli.neighbors_command(
        Path("/workspace"),
        caller_id,
        source="api",
        direction="out",
        relations=("calls",),
        as_json=True,
    )
    relationship = next(
        row
        for row in json.loads(explained.stdout)["relationships"]
        if row["relation"] == "CALLS"
    )
    step = json.loads(neighbors.stdout)["steps"][0]

    for row in (relationship, step):
        assert row["confidence"] == "medium"
        assert row["provenance"] == [
            "tree-sitter",
            "constructor-assignment",
        ]
        assert row["notes"] == "Receiver inferred from constructor assignment."


@pytest.mark.unit
def test_ambiguous_candidate_output_bounds_one_million_byte_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.topology_provider import (
        PublishedTopology,
        TopologyNodeResolutionError,
    )
    import echelon.topology_cli as topology_cli

    _patch_reads(monkeypatch)

    def fail_explain(
        self: PublishedTopology, source_id: str | None, selector: str
    ) -> object:
        raise TopologyNodeResolutionError(
            "ambiguous topology node selector",
            candidates=("x" * 1_000_000,),
            candidate_count=1,
        )

    monkeypatch.setattr(PublishedTopology, "explain", fail_explain)

    result = topology_cli.explain_command(
        Path("/workspace"), "api.shared", source="api", as_json=True
    )
    payload = json.loads(result.stderr)
    candidates = payload["error"]["candidates"]

    assert result.exit_code == 2
    assert len(candidates) == 1
    assert len(candidates[0].encode("utf-8")) <= topology_cli._MAX_CANDIDATE_BYTES
    assert (
        sum(len(candidate.encode("utf-8")) for candidate in candidates)
        <= topology_cli._MAX_CANDIDATES_TOTAL_BYTES
    )
    assert payload["error"]["candidates_truncated"] is True
    assert len(result.stderr.encode("utf-8")) < 10_000


@pytest.mark.unit
def test_ambiguous_candidates_preserve_exact_total_byte_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.topology_provider import (
        PublishedTopology,
        TopologyNodeResolutionError,
    )
    import echelon.topology_cli as topology_cli

    _patch_reads(monkeypatch)
    count = (
        topology_cli._MAX_CANDIDATES_TOTAL_BYTES
        // topology_cli._MAX_CANDIDATE_BYTES
    )
    candidates = tuple(
        f"{index}" + "x" * (topology_cli._MAX_CANDIDATE_BYTES - 1)
        for index in range(count)
    )

    def fail_explain(
        self: PublishedTopology, source_id: str | None, selector: str
    ) -> object:
        raise TopologyNodeResolutionError(
            "ambiguous topology node selector",
            candidates=candidates,
            candidate_count=len(candidates),
        )

    monkeypatch.setattr(PublishedTopology, "explain", fail_explain)

    result = topology_cli.explain_command(
        Path("/workspace"), "api.shared", source="api", as_json=True
    )
    error = json.loads(result.stderr)["error"]

    assert sum(len(value.encode("utf-8")) for value in error["candidates"]) == (
        topology_cli._MAX_CANDIDATES_TOTAL_BYTES
    )
    assert error["candidates_truncated"] is False


@pytest.mark.unit
def test_explain_and_traversal_text_rows_have_complete_provenance(
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

    explained = topology_cli.explain_command(
        Path("/workspace"), caller_id, source="api"
    )
    neighbors = topology_cli.neighbors_command(
        Path("/workspace"),
        caller_id,
        source="api",
        relations=("calls",),
        limit=1,
    )

    relationship_rows = [
        line for line in explained.stdout.splitlines() if "source_node=" in line
    ]
    assert relationship_rows
    for line in relationship_rows:
        assert "target_node=" in line
        assert "source=api" in line
        assert "provider=" in line
        assert "path=src/" in line
        assert "generation=7" in line
        assert "status=current" in line
        assert "truncated=no" in line

    step = next(line for line in neighbors.stdout.splitlines() if line.startswith("- depth="))
    assert "source_node=" in step and "target_node=" in step
    assert "node=" in step and "source=api" in step
    assert "provider=codegraph" in step and "path=src/" in step
    assert "generation=7" in step and "status=current" in step
    assert "truncated=yes" in step


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
            generation=7,
            sources={
                    "api": SimpleNamespace(
                        source_id="api",
                        source_path="sources/api",
                        source_fingerprint=SimpleNamespace(value="a" * 64),
                    receipt=SimpleNamespace(sha256="sha256:" + "b" * 64),
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
            "source_relative_path": "sources/api",
            "source_generation": 2,
            "topology_generation": 3,
            "topology_status": "current",
            "truncated": False,
        }
    ]

    text_result = topology_cli.list_sources_command(tmp_path)
    source_line = next(
        line for line in text_result.stdout.splitlines() if line.startswith("- node=")
    )
    assert "node=source:api" in source_line
    assert "source=api" in source_line
    assert "provider=topology" in source_line
    assert "path=sources/api" in source_line
    assert "generation=3" in source_line
    assert "status=current" in source_line
    assert "truncated=no" in source_line

@pytest.mark.unit
def test_audit_source_rows_have_explicit_snapshot_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace
    from echelon.topology_audit import snapshot_topology_index
    from echelon.topology_registry import load_topology_index
    from tests.unit.test_topology_registry import build_topology
    import echelon.topology_cli as topology_cli

    build_topology(tmp_path)
    index = load_topology_index(tmp_path)
    assert index is not None
    report = replace(
        _audit_report("current", source_ids=("api",)),
        snapshot=snapshot_topology_index(index),
    )
    monkeypatch.setattr(
        topology_cli,
        "audit_topology",
        lambda root, source_id=None: report,
    )

    result = topology_cli.audit_command(tmp_path)
    source_line = next(
        line for line in result.stdout.splitlines() if line.startswith("- node=")
    )

    assert "node=source:api" in source_line
    assert "source=api" in source_line
    assert "provider=topology" in source_line
    assert "path=sources/api" in source_line
    assert "generation=3" in source_line
    assert "status=current" in source_line
    assert "truncated=no" in source_line

    json_result = topology_cli.audit_command(tmp_path, as_json=True)
    row = json.loads(json_result.stdout)["audit"]["sources"][0]
    assert row["node_id"] == "source:api"
    assert row["source_id"] == "api"
    assert row["provider"] == "topology"
    assert row["source_relative_path"] == "sources/api"
    assert row["topology_generation"] == 3
    assert row["topology_status"] == "current"
    assert row["truncated"] is False


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
