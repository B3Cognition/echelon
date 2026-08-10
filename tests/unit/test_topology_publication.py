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


def _perl_unsupported() -> bytes:
    value = {
        "schema_version": 2, "tool": "perlgraph", "tool_version": "0.1.0", "repo_path": "/native/provider/path",
        "provider_status": "unsupported", "complete": True, "supported": False,
        "capabilities": {"language": "perl", "exact_symbol_keys": True, "exact_relationship_endpoints": True, "unresolved_relationship_diagnostics": True},
        "counts": {"discovered_files": 0, "emitted_files": 0, "discovered_symbols": 0, "emitted_symbols": 0, "discovered_relationships": 0, "emitted_relationships": 0, "unresolved_relationships": 0, "parse_failures": 0, "parse_diagnostics": 0, "dynamic_patterns": 0},
        "symbols": [], "relationships": [], "unresolved_relationships": [], "call_graph": [], "module_graph": [], "unsupported_patterns": [], "parse_failures": [], "parse_diagnostics": [],
    }
    return json.dumps(value, sort_keys=True).encode()


def _summary(provider: str, analysis: bytes) -> bytes:
    document = json.loads(analysis)
    diagnostics: object
    if provider == "codegraph":
        diagnostics = document["diagnostics"]
    else:
        diagnostics = {
            "unresolved_relationships": document["unresolved_relationships"],
            "parse_failures": document["parse_failures"],
            "parse_diagnostics": document["parse_diagnostics"],
            "unsupported_patterns": document["unsupported_patterns"],
        }
    summary = {
        "schema_version": 2,
        "tool": provider,
        "tool_version": document["tool_version"],
        "provider_status": document["provider_status"],
        "complete": document["complete"],
        "counts": document["counts"],
        "diagnostics": diagnostics,
    }
    if provider == "perlgraph":
        summary["repo_path"] = document["repo_path"]
        summary["capabilities"] = document["capabilities"]
    return json.dumps(summary, sort_keys=True).encode()


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
        providers=(TopologyProviderCandidate("codegraph", _analysis(), _summary("codegraph", _analysis())),),
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
    web_bytes = {path.relative_to(tmp_path / "re/topology/sources/web").as_posix(): path.read_bytes() for path in (tmp_path / "re/topology/sources/web").rglob("*") if path.is_file()}
    second = publish_topology_snapshots(tmp_path, (_candidate("api", "2"),), owner_id="run-2", owner_run_dir=None, expected_generation=1)

    assert first.generation == 1
    assert second.generation == 2
    assert {path.relative_to(tmp_path / "re/topology/sources/web").as_posix(): path.read_bytes() for path in (tmp_path / "re/topology/sources/web").rglob("*") if path.is_file()} == web_bytes
    from echelon.topology_registry import load_published_topology, load_topology_index
    assert load_published_topology(tmp_path).generation == 2
    index = load_topology_index(tmp_path)
    assert index is not None
    assert index.sources["api"].generation == 2
    assert index.sources["web"].generation == 1


@pytest.mark.unit
def test_single_repo_root_source_publishes_under_reserved_storage_key(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from echelon.topology_audit import audit_topology
    from echelon.topology_registry import load_topology_index
    from harness.topology_publication import publish_topology_snapshots

    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    candidate = replace(_candidate("api"), source_id=".", source_path=".")

    result = publish_topology_snapshots(
        tmp_path,
        (candidate,),
        owner_id="run-1",
        owner_run_dir=None,
    )

    index = load_topology_index(tmp_path)
    assert result.generation == 1
    assert index is not None
    assert set(index.sources) == {"."}
    assert index.sources["."].source_path == "."
    receipt = tmp_path / "re/topology/sources/__root__/receipt.json"
    assert receipt.is_file()
    assert json.loads(receipt.read_text(encoding="utf-8"))["source_id"] == "."
    assert audit_topology(tmp_path, source_id=".").status in {"current", "stale"}


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


@pytest.mark.unit
def test_topology_direct_publication_rejects_malformed_summary_duplicate_locator_and_unowned_path_input(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyProviderCandidate, TopologyPublicationValidationError, publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    malformed = replace(_candidate("api"), providers=(TopologyProviderCandidate("codegraph", _analysis(), b"not json"),))
    with pytest.raises(TopologyPublicationValidationError, match="summary"):
        publish_topology_snapshots(tmp_path, (malformed,), owner_id="run-1", owner_run_dir=None)
    empty_summary = replace(_candidate("api"), providers=(TopologyProviderCandidate("codegraph", _analysis(), b"{}"),))
    with pytest.raises(TopologyPublicationValidationError, match="summary"):
        publish_topology_snapshots(tmp_path, (empty_summary,), owner_id="run-1", owner_run_dir=None)
    duplicate = json.loads(_analysis())
    duplicate["symbols"].append(dict(duplicate["symbols"][0]))
    duplicate["counts"]["discovered_symbols"] = 2
    duplicate["counts"]["emitted_symbols"] = 2
    duplicate_analysis = json.dumps(duplicate).encode()
    duplicate_candidate = replace(_candidate("api"), providers=(TopologyProviderCandidate("codegraph", duplicate_analysis, _summary("codegraph", duplicate_analysis)),))
    with pytest.raises(TopologyPublicationValidationError, match="duplicate"):
        publish_topology_snapshots(tmp_path, (duplicate_candidate,), owner_id="run-1", owner_run_dir=None)
    evidence = tmp_path / "runs/run-1/evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(_analysis())
    path_candidate = replace(_candidate("api"), providers=(TopologyProviderCandidate("codegraph", evidence, Path("missing")),))
    with pytest.raises(TopologyPublicationValidationError, match="owner run directory"):
        publish_topology_snapshots(tmp_path, (path_candidate,), owner_id="run-1", owner_run_dir=None)


@pytest.mark.unit
@pytest.mark.parametrize("summary", (None, [], [{}], "not-an-object", 7))
def test_topology_direct_publication_rejects_non_object_provider_summaries(
    tmp_path: Path, summary: object
) -> None:
    from dataclasses import replace
    from harness.topology_publication import (
        TopologyProviderCandidate,
        TopologyPublicationValidationError,
        publish_topology_snapshots,
    )

    _workspace(tmp_path, ("api",))
    malformed = replace(
        _candidate("api"),
        providers=(
            TopologyProviderCandidate("codegraph", _analysis(), json.dumps(summary).encode()),
        ),
    )

    with pytest.raises(TopologyPublicationValidationError, match="summary"):
        publish_topology_snapshots(tmp_path, (malformed,), owner_id="run-1", owner_run_dir=None)
    assert not (tmp_path / "re/topology/index.json").exists()


@pytest.mark.unit
def test_topology_accepts_unsupported_provider_evidence_and_rejects_future_receipt(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyProviderCandidate, publish_topology_snapshots
    from echelon.topology_registry import TopologyRegistryError, load_topology_index

    _workspace(tmp_path, ("api",))
    perlgraph = _perl_unsupported()
    candidate = replace(_candidate("api"), providers=(TopologyProviderCandidate("perlgraph", perlgraph, _summary("perlgraph", perlgraph)),))
    publish_topology_snapshots(tmp_path, (candidate,), owner_id="run-1", owner_run_dir=None)
    receipt_path = tmp_path / "re/topology/sources/api/receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["generation"] = 2
    raw = json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n"
    receipt_path.write_bytes(raw)
    index_path = tmp_path / "re/topology/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["sources"]["api"]["receipt"]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(TopologyRegistryError, match="generation"):
        load_topology_index(tmp_path)


@pytest.mark.unit
def test_topology_accepts_explicit_empty_provider_evidence(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyProviderCandidate, publish_topology_snapshots
    from echelon.topology_registry import load_topology_index

    _workspace(tmp_path, ("api",))
    empty = json.loads(_perl_unsupported())
    empty["provider_status"] = "empty"
    empty["supported"] = True
    empty["counts"]["discovered_files"] = 1
    empty["counts"]["emitted_files"] = 1
    empty_analysis = json.dumps(empty).encode()
    candidate = replace(_candidate("api"), providers=(TopologyProviderCandidate("perlgraph", empty_analysis, _summary("perlgraph", empty_analysis)),))
    publish_topology_snapshots(tmp_path, (candidate,), owner_id="run-1", owner_run_dir=None)
    index = load_topology_index(tmp_path)
    assert index is not None
    assert index.sources["api"].providers["perlgraph"].status == "empty"


@pytest.mark.unit
def test_topology_direct_publication_requires_exact_perlgraph_summary(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import (
        TopologyProviderCandidate,
        TopologyPublicationValidationError,
        publish_topology_snapshots,
    )

    _workspace(tmp_path, ("api",))
    analysis = _perl_unsupported()
    extra = json.loads(_summary("perlgraph", analysis))
    extra["top_callers"] = []
    extra_candidate = replace(
        _candidate("api"),
        providers=(TopologyProviderCandidate("perlgraph", analysis, json.dumps(extra).encode()),),
    )
    with pytest.raises(TopologyPublicationValidationError, match="summary fields"):
        publish_topology_snapshots(tmp_path, (extra_candidate,), owner_id="run-1", owner_run_dir=None)

    mismatched = json.loads(_summary("perlgraph", analysis))
    mismatched["capabilities"] = {**mismatched["capabilities"], "exact_symbol_keys": False}
    mismatched_candidate = replace(
        _candidate("api"),
        providers=(TopologyProviderCandidate("perlgraph", analysis, json.dumps(mismatched).encode()),),
    )
    with pytest.raises(TopologyPublicationValidationError, match="capabilities disagrees"):
        publish_topology_snapshots(tmp_path, (mismatched_candidate,), owner_id="run-1", owner_run_dir=None)


@pytest.mark.unit
def test_topology_path_evidence_must_stay_in_its_owner_run(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyProviderCandidate, TopologyPublicationValidationError, publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    owner = tmp_path / "runs/run-1"
    owner.mkdir(parents=True)
    analysis = owner / "analysis.json"
    summary = owner / "summary.json"
    analysis.write_bytes(_analysis())
    summary.write_bytes(_summary("codegraph", _analysis()))
    candidate = replace(_candidate("api"), providers=(TopologyProviderCandidate("codegraph", analysis, summary),))
    assert publish_topology_snapshots(tmp_path, (candidate,), owner_id="run-1", owner_run_dir=owner).generation == 1

    outside = tmp_path / "outside.json"
    outside.write_bytes(_analysis())
    escaped = replace(_candidate("api", "2"), providers=(TopologyProviderCandidate("codegraph", outside, summary),))
    with pytest.raises(TopologyPublicationValidationError, match="escapes owner"):
        publish_topology_snapshots(tmp_path, (escaped,), owner_id="run-2", owner_run_dir=owner, expected_generation=1)

    linked = owner / "linked.json"
    linked.symlink_to(outside)
    symlinked = replace(_candidate("api", "2"), providers=(TopologyProviderCandidate("codegraph", linked, summary),))
    with pytest.raises(TopologyPublicationValidationError, match="escapes owner"):
        publish_topology_snapshots(tmp_path, (symlinked,), owner_id="run-2", owner_run_dir=owner, expected_generation=1)


@pytest.mark.unit
def test_topology_rejects_legacy_squad_owner_run(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyProviderCandidate, TopologyPublicationValidationError, publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    owner = tmp_path / "squad" / "re-legacy"
    owner.mkdir(parents=True)
    analysis = owner / "analysis.json"
    summary = owner / "summary.json"
    analysis.write_bytes(_analysis())
    summary.write_bytes(_summary("codegraph", _analysis()))
    candidate = replace(
        _candidate("api"),
        providers=(TopologyProviderCandidate("codegraph", analysis, summary),),
    )

    with pytest.raises(TopologyPublicationValidationError, match="outside workspace lifecycle roots"):
        publish_topology_snapshots(
            tmp_path,
            (candidate,),
            owner_id="re-legacy",
            owner_run_dir=owner,
        )


@pytest.mark.unit
def test_topology_rejects_symlinked_lifecycle_root(tmp_path: Path) -> None:
    from dataclasses import replace
    from harness.topology_publication import TopologyProviderCandidate, TopologyPublicationValidationError, publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    outside = tmp_path / "outside-runs/run-1"
    outside.mkdir(parents=True)
    (outside / "analysis.json").write_bytes(_analysis())
    (outside / "summary.json").write_bytes(_summary("codegraph", _analysis()))
    (tmp_path / "runs").symlink_to(tmp_path / "outside-runs", target_is_directory=True)
    candidate = replace(_candidate("api"), providers=(TopologyProviderCandidate("codegraph", outside / "analysis.json", outside / "summary.json"),))
    with pytest.raises(TopologyPublicationValidationError, match="unsafe"):
        publish_topology_snapshots(tmp_path, (candidate,), owner_id="run-1", owner_run_dir=outside)


@pytest.mark.unit
@pytest.mark.parametrize("checkpoint", ("after_backup_intent", "after_backup_rename", "after_install_rename"))
def test_topology_base_exception_preserves_staging_recovery_evidence(
    tmp_path: Path, checkpoint: str
) -> None:
    from harness.re_lock import RePublishLocked
    from harness.topology_publication import publish_topology_snapshots

    _workspace(tmp_path, ("api",))
    publish_topology_snapshots(tmp_path, (_candidate("api"),), owner_id="run-1", owner_run_dir=None)

    class Crash(BaseException):
        pass

    def crash(point: str) -> None:
        if point == f"{checkpoint}:topology/sources/api":
            raise Crash()

    with pytest.raises(Crash):
        publish_topology_snapshots(tmp_path, (_candidate("api", "2"),), owner_id="run-2", owner_run_dir=None, expected_generation=1, fault_hook=crash)
    journal = tmp_path / "re/.staging/run-2/rollback-journal.json"
    assert journal.is_file()
    assert json.loads(journal.read_text(encoding="utf-8"))["status"] == "replacing"
    with pytest.raises(RePublishLocked, match="run-2"):
        publish_topology_snapshots(tmp_path, (_candidate("api", "3"),), owner_id="run-3", owner_run_dir=None, expected_generation=1)
