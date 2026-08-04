from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _key(path: str, name: str) -> str:
    raw = json.dumps([path, name, "function", "()"], separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _analysis() -> bytes:
    key = _key("src/api.py", "api.run")
    value = {
        "schema_version": 2, "version": "2.0.0", "tool": "codegraph", "tool_version": "1.4.1",
        "repo_path": "/native/provider/path", "provider_status": "complete", "complete": True,
        "supported": True,
        "counts": {"discovered_symbols": 1, "emitted_symbols": 1, "excluded_symbols": 0, "discovered_relationships": 0, "emitted_relationships": 0, "excluded_relationships": 0},
        "diagnostics": {"unresolved_relationships": []},
        "symbols": [{"symbol_key": key, "file_path": "src/api.py", "qualified_name": "api.run", "name": "run", "kind": "function", "signature": "()", "line_start": 1, "line_end": 1}],
        "relationships": [], "call_graph": [], "type_hierarchy": [], "impact_radius": [],
    }
    return json.dumps(value, sort_keys=True).encode()


def _candidate(source_id: str, version: str = "0"):
    from harness.re_fingerprint import SourceFingerprint
    from harness.topology_publication import TopologyProviderCandidate, TopologySnapshotCandidate

    fingerprint = SourceFingerprint(
        value=version * 64,
        kind="git",
        dirty=False,
        profile_hash="1" * 64,
        git_head="0123456789abcdef0123456789abcdef01234567",
    )
    return TopologySnapshotCandidate(
        source_id=source_id,
        source_path=f"sources/{source_id}",
        source_fingerprint=fingerprint,
        analyzed_commit=fingerprint.git_head,
        provenance={"kind": "re", "run_id": "re-20260804-120000"},
        providers=(TopologyProviderCandidate("codegraph", _analysis(), b'{"summary":"ok"}\n'),),
    )


def _workspace(root: Path, source_ids: tuple[str, ...]) -> None:
    sources = "\n".join(f"    - id: {source_id}\n      path: sources/{source_id}" for source_id in source_ids)
    (root / ".echelon").mkdir()
    (root / ".echelon/config.yml").write_text(f"workspace:\n  sources:\n{sources}\n", encoding="utf-8")
    for source_id in source_ids:
        (root / "sources" / source_id).mkdir(parents=True)


@pytest.mark.unit
def test_publish_topology_snapshots_merges_untouched_sources_byte_for_byte(tmp_path: Path) -> None:
    from harness.topology_publication import publish_topology_snapshots

    _workspace(tmp_path, ("api", "web"))
    first = publish_topology_snapshots(tmp_path, (_candidate("api"), _candidate("web")), owner_id="run-1", owner_run_dir=None)
    web_bytes = (tmp_path / "re/topology/sources/web/receipt.json").read_bytes()
    second = publish_topology_snapshots(tmp_path, (_candidate("api", "2"),), owner_id="run-2", owner_run_dir=None, expected_generation=1)

    assert first.generation == 1
    assert second.generation == 2
    assert (tmp_path / "re/topology/sources/web/receipt.json").read_bytes() == web_bytes
    from echelon.topology_registry import load_published_topology
    assert load_published_topology(tmp_path).generation == 2


@pytest.mark.unit
def test_first_topology_publication_requires_every_workspace_source(tmp_path: Path) -> None:
    from harness.topology_publication import TopologyPublicationValidationError, publish_topology_snapshots

    _workspace(tmp_path, ("api", "web"))
    with pytest.raises(TopologyPublicationValidationError, match="every configured"):
        publish_topology_snapshots(tmp_path, (_candidate("api"),), owner_id="run-1", owner_run_dir=None)


@pytest.mark.unit
def test_topology_rejects_sources_without_provider_evidence(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyPublicationValidationError, publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    with pytest.raises(TopologyPublicationValidationError, match="no usable providers"):
        publish_topology_snapshots(
            tmp_path, (replace(_candidate("api"), providers=()),), owner_id="run-1", owner_run_dir=None
        )


@pytest.mark.unit
def test_topology_generation_conflict_and_fault_rollback_do_not_mutate(tmp_path: Path) -> None:
    from harness.topology_publication import TopologyPublicationConflict, publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    publish_topology_snapshots(tmp_path, (_candidate("api"),), owner_id="run-1", owner_run_dir=None)
    before_index = (tmp_path / "re/topology/index.json").read_bytes()
    before_receipt = (tmp_path / "re/topology/sources/api/receipt.json").read_bytes()
    with pytest.raises(TopologyPublicationConflict):
        publish_topology_snapshots(tmp_path, (_candidate("api", "2"),), owner_id="run-2", owner_run_dir=None, expected_generation=0)

    def fail(point: str) -> None:
        if point == "before_replace:topology/index.json":
            raise OSError("stop")
    with pytest.raises(OSError, match="stop"):
        publish_topology_snapshots(tmp_path, (_candidate("api", "2"),), owner_id="run-2", owner_run_dir=None, expected_generation=1, fault_hook=fail)
    assert (tmp_path / "re/topology/index.json").read_bytes() == before_index
    assert (tmp_path / "re/topology/sources/api/receipt.json").read_bytes() == before_receipt
