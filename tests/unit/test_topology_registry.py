from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _key(path: str, name: str, kind: str = "function", signature: str = "()") -> str:
    locator = json.dumps([path, name, kind, signature], separators=(",", ":"))
    return _sha(locator.encode("utf-8"))


def _codegraph() -> dict[str, object]:
    key = _key("src/api.py", "api.run")
    return {
        "schema_version": 2,
        "version": "2.0.0",
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "repo_path": "/provider/native/path",
        "provider_status": "complete",
        "complete": True,
        "supported": True,
        "counts": {
            "discovered_symbols": 1,
            "emitted_symbols": 1,
            "excluded_symbols": 0,
            "discovered_relationships": 0,
            "emitted_relationships": 0,
            "excluded_relationships": 0,
        },
        "diagnostics": {"unresolved_relationships": []},
        "symbols": [
            {
                "symbol_key": key,
                "file_path": "src/api.py",
                "qualified_name": "api.run",
                "name": "run",
                "kind": "function",
                "signature": "()",
                "line_start": 1,
                "line_end": 2,
            }
        ],
        "relationships": [],
        "call_graph": [],
        "type_hierarchy": [],
        "impact_radius": [],
    }


def _perlgraph() -> dict[str, object]:
    return {
        "schema_version": 2,
        "tool": "perlgraph",
        "tool_version": "0.1.0",
        "repo_path": "/provider/native/path",
        "provider_status": "unsupported",
        "complete": True,
        "supported": False,
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
            "discovered_symbols": 0,
            "emitted_symbols": 0,
            "discovered_relationships": 0,
            "emitted_relationships": 0,
            "unresolved_relationships": 0,
            "parse_failures": 0,
            "parse_diagnostics": 0,
            "dynamic_patterns": 0,
        },
        "symbols": [],
        "relationships": [],
        "unresolved_relationships": [],
        "call_graph": [],
        "module_graph": [],
        "unsupported_patterns": [],
        "parse_failures": [],
        "parse_diagnostics": [],
    }


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return _sha(raw)


def build_topology(root: Path, *, source_path: str = "sources/api") -> dict[str, object]:
    (root / ".echelon").mkdir(exist_ok=True)
    (root / ".echelon/config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    (root / "sources/api").mkdir(parents=True, exist_ok=True)
    base = root / "re/topology/sources/api"
    code_analysis = "re/topology/sources/api/codegraph-analysis.json"
    code_summary = "re/topology/sources/api/codegraph-summary.json"
    perl_analysis = "re/topology/sources/api/perlgraph-analysis.json"
    perl_summary = "re/topology/sources/api/perlgraph-summary.json"
    artifacts = {
        code_analysis: _write_json(root / code_analysis, _codegraph()),
        code_summary: _write_json(root / code_summary, {"summary": "codegraph"}),
        perl_analysis: _write_json(root / perl_analysis, _perlgraph()),
        perl_summary: _write_json(root / perl_summary, {"summary": "perlgraph"}),
    }
    fingerprint = {
        "value": "0" * 64,
        "kind": "git",
        "dirty": False,
        "profile_hash": "1" * 64,
        "git_head": "0123456789abcdef0123456789abcdef01234567",
    }
    providers = {
        "codegraph": {
            "status": "ready",
            "complete": True,
            "artifacts": {
                "analysis": {"path": code_analysis, "sha256": artifacts[code_analysis]},
                "summary": {"path": code_summary, "sha256": artifacts[code_summary]},
            },
        },
        "perlgraph": {
            "status": "unsupported",
            "complete": True,
            "artifacts": {
                "analysis": {"path": perl_analysis, "sha256": artifacts[perl_analysis]},
                "summary": {"path": perl_summary, "sha256": artifacts[perl_summary]},
            },
        },
    }
    receipt = {
        "schema_version": 1,
        "generation": 3,
        "source_id": "api",
        "source_path": source_path,
        "source_fingerprint": fingerprint,
        "analyzed_commit": fingerprint["git_head"],
        "provenance": {"kind": "re", "run_id": "re-20260804-120000"},
        "providers": {
            "codegraph": {
                **providers["codegraph"],
                "artifact_schema_version": 2,
                "tool_version": "1.4.1",
                "capabilities": ["calls", "relationships", "symbols", "types"],
                "counts": {"relationships": 0, "symbols": 1},
                "diagnostics": [],
            },
            "perlgraph": {
                **providers["perlgraph"],
                "artifact_schema_version": 2,
                "tool_version": "0.1.0",
                "capabilities": ["relationships", "symbols"],
                "counts": {"relationships": 0, "symbols": 0},
                "diagnostics": [],
            },
        },
    }
    receipt_path = "re/topology/sources/api/receipt.json"
    receipt_sha = _write_json(root / receipt_path, receipt)
    index = {
        "schema_version": 1,
        "generation": 3,
        "published_at": "2026-08-04T12:00:00+00:00",
        "sources": {
            "api": {
                "source_path": source_path,
                "source_fingerprint": fingerprint,
                "receipt": {"path": receipt_path, "sha256": receipt_sha},
                "providers": providers,
            }
        },
    }
    _write_json(root / "re/topology/index.json", index)
    return index


@pytest.mark.unit
def test_load_published_topology_uses_authoritative_index_and_exact_receipts(tmp_path: Path) -> None:
    build_topology(tmp_path)
    from echelon.topology_registry import load_published_topology, load_topology_index

    index = load_topology_index(tmp_path)
    assert index is not None
    assert tuple(index.sources) == ("api",)
    source = index.sources["api"]
    assert source.generation == 3
    assert tuple(source.providers) == ("codegraph", "perlgraph")
    assert tuple(source.providers["codegraph"].artifacts) == ("analysis", "summary")

    topology = load_published_topology(tmp_path)
    assert topology.generation == 3
    assert topology.receipt("api").source_fingerprint == "0" * 64
    assert topology.receipt("api").provider_receipt_hashes == {
        "codegraph": source.receipt.sha256,
        "perlgraph": source.receipt.sha256,
    }
    assert topology.receipt("api").provider_artifact_paths == (
        "re/topology/sources/api/codegraph-analysis.json",
        "re/topology/sources/api/perlgraph-analysis.json",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    (
        lambda index: index["sources"]["api"]["receipt"].update({"path": "re/topology/sources/other/receipt.json"}),
        lambda index: index["sources"]["api"]["providers"]["codegraph"]["artifacts"]["analysis"].update({"path": "re/topology/sources/api/../escape.json"}),
        lambda index: index["sources"]["api"]["providers"]["codegraph"].update({"status": "unknown"}),
        lambda index: index["sources"]["api"].update({"source_path": "sources/changed"}),
    ),
)
def test_registry_rejects_unsafe_or_manifest_inconsistent_index(
    tmp_path: Path, mutate: object
) -> None:
    index = build_topology(tmp_path)
    assert callable(mutate)
    mutate(index)
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_registry_rejects_receipt_that_elaborates_a_different_artifact_catalog(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["providers"]["codegraph"]["artifacts"]["extra"] = {  # type: ignore[index]
        "path": "re/topology/sources/api/extra.json",
        "sha256": "sha256:" + "a" * 64,
    }
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError, match="artifact"):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_registry_rejects_hash_drift_and_symlink_escape(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    analysis = tmp_path / "re/topology/sources/api/codegraph-analysis.json"
    analysis.write_text("{}", encoding="utf-8")
    from echelon.topology_registry import TopologyRegistryError, load_published_topology

    with pytest.raises(TopologyRegistryError, match="hash"):
        load_published_topology(tmp_path)

    build_topology(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    analysis.unlink()
    analysis.symlink_to(outside)
    with pytest.raises(TopologyRegistryError, match="escape"):
        load_published_topology(tmp_path)


@pytest.mark.unit
def test_registry_rejects_source_directory_and_nested_symlink_escapes(tmp_path: Path) -> None:
    build_topology(tmp_path)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    source_dir = tmp_path / "re/topology/sources/api"
    outside_dir = tmp_path / "outside-source"
    source_dir.rename(outside_dir)
    source_dir.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(TopologyRegistryError, match="escape"):
        load_topology_index(tmp_path)

    source_dir.unlink()
    outside_dir.rename(source_dir)
    nested = source_dir / "codegraph-summary.json"
    outside = tmp_path / "outside-summary.json"
    outside.write_text("{}", encoding="utf-8")
    nested.unlink()
    nested.symlink_to(outside)
    with pytest.raises(TopologyRegistryError, match="escape"):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_registry_rejects_empty_provider_catalog_and_nonstandard_json_constants(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    index["sources"]["api"]["providers"] = {}  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError, match="provider"):
        load_topology_index(tmp_path)

    build_topology(tmp_path)
    (tmp_path / "re/topology/index.json").write_text(
        '{"schema_version":NaN}', encoding="utf-8"
    )
    with pytest.raises(TopologyRegistryError, match="constant"):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_published_loader_uses_the_hash_verified_bytes_without_a_second_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_topology(tmp_path)
    from echelon import topology_registry

    analysis = tmp_path / "re/topology/sources/api/codegraph-analysis.json"
    original_read = Path.read_bytes
    calls = {"analysis": 0}

    def changed_after_hash(self: Path) -> bytes:
        raw = original_read(self)
        if self == analysis:
            calls["analysis"] += 1
            # Index validation is the first read; mutate only after the
            # published loader obtains its authoritative second read.
            if calls["analysis"] == 2:
                analysis.write_text('{"schema_version":2,"schema_version":2}', encoding="utf-8")
        return raw

    monkeypatch.setattr(Path, "read_bytes", changed_after_hash)
    topology = topology_registry.load_published_topology(tmp_path)

    assert calls["analysis"] == 2
    assert topology.receipt("api").provider_statuses["codegraph"] == "ready"


@pytest.mark.unit
def test_provider_analysis_rejects_duplicate_json_keys_before_native_validation(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    analysis = tmp_path / "re/topology/sources/api/codegraph-analysis.json"
    raw = b'{"schema_version":2,"schema_version":2}'
    analysis.write_bytes(raw)
    digest = _sha(raw)
    index["sources"]["api"]["providers"]["codegraph"]["artifacts"]["analysis"]["sha256"] = digest  # type: ignore[index]
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    receipt["providers"]["codegraph"]["artifacts"]["analysis"]["sha256"] = digest
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_published_topology

    with pytest.raises(TopologyRegistryError, match="duplicate JSON"):
        load_published_topology(tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize("value", (True, "1"))
def test_registry_rejects_non_integer_schema_and_invalid_published_timestamp(
    tmp_path: Path, value: object
) -> None:
    index = build_topology(tmp_path)
    index["schema_version"] = value
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError, match="schema"):
        load_topology_index(tmp_path)

    index = build_topology(tmp_path)
    index["published_at"] = "2026-08-04T12:00:00"
    _write_json(tmp_path / "re/topology/index.json", index)
    with pytest.raises(TopologyRegistryError, match="published_at"):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_registry_rejects_source_path_symlink_escaping_workspace(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    source = tmp_path / "sources/api"
    outside = tmp_path.parent / f"{tmp_path.name}-outside-source"
    source.rename(outside)
    source.symlink_to(outside, target_is_directory=True)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError, match="escapes"):
        load_topology_index(tmp_path)
    source.unlink()
    outside.rename(source)


@pytest.mark.unit
def test_registry_accepts_all_unsupported_completed_provider_evidence(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    index["sources"]["api"]["providers"].pop("codegraph")  # type: ignore[index]
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    receipt["providers"].pop("codegraph")
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import load_published_topology

    topology = load_published_topology(tmp_path)
    assert topology.receipt("api").provider_statuses == {"perlgraph": "unsupported"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutate",
    (
        lambda receipt: receipt["providers"]["codegraph"].update({"tool_version": "/private/tool"}),
        lambda receipt: receipt["providers"]["codegraph"].update({"capabilities": ["/private/capability"]}),
        lambda receipt: receipt["providers"]["codegraph"].update({"counts": {"/private/count": 1}}),
        lambda receipt: receipt["providers"]["codegraph"].update({"diagnostics": [{"/private/key": "value"}]}),
        lambda receipt: receipt.update({"provenance": {"kind": "re", "run_id": "/private/run"}}),
    ),
)
def test_registry_rejects_host_path_shaped_public_receipt_metadata(
    tmp_path: Path, mutate: object
) -> None:
    index = build_topology(tmp_path)
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    assert callable(mutate)
    mutate(receipt)
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_registry_rejects_dirty_file_tree_fingerprint(tmp_path: Path) -> None:
    index = build_topology(tmp_path)
    fingerprint = index["sources"]["api"]["source_fingerprint"]  # type: ignore[index]
    fingerprint.update({"kind": "file-tree", "dirty": True, "git_head": None})
    receipt_path = tmp_path / index["sources"]["api"]["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text())
    receipt["source_fingerprint"] = fingerprint
    receipt["analyzed_commit"] = None
    receipt_sha = _write_json(receipt_path, receipt)
    index["sources"]["api"]["receipt"]["sha256"] = receipt_sha  # type: ignore[index]
    _write_json(tmp_path / "re/topology/index.json", index)
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    with pytest.raises(TopologyRegistryError, match="file-tree"):
        load_topology_index(tmp_path)
