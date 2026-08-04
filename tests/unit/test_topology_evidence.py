from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.re_fingerprint import SourceFingerprint


def _key(path: str, qualified_name: str) -> str:
    locator = json.dumps([path, qualified_name, "function", "()"], separators=(",", ":"))
    return "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()


def _codegraph(*, status: str = "complete") -> dict[str, object]:
    key = _key("src/api.py", "api.run")
    return {
        "schema_version": 2,
        "version": "2.0.0",
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "repo_path": "/provider/native/path",
        "provider_status": status,
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
                "line_end": 1,
            }
        ],
        "relationships": [],
        "call_graph": [],
        "type_hierarchy": [],
        "impact_radius": [],
    }


def _perl_unsupported() -> dict[str, object]:
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


def _fingerprint() -> SourceFingerprint:
    return SourceFingerprint(
        value="a" * 64,
        kind="git",
        dirty=False,
        profile_hash="b" * 64,
        git_head="0123456789abcdef0123456789abcdef01234567",
    )


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True).encode("utf-8") + b"\n")


def _summary(provider: str, analysis: dict[str, object]) -> dict[str, object]:
    diagnostics: object
    if provider == "codegraph":
        diagnostics = analysis["diagnostics"]
    else:
        diagnostics = {
            "unresolved_relationships": analysis["unresolved_relationships"],
            "parse_failures": analysis["parse_failures"],
            "parse_diagnostics": analysis["parse_diagnostics"],
            "unsupported_patterns": analysis["unsupported_patterns"],
        }
    summary = {
        "schema_version": 2,
        "tool": provider,
        "tool_version": analysis["tool_version"],
        "provider_status": analysis["provider_status"],
        "complete": analysis["complete"],
        "counts": analysis["counts"],
        "diagnostics": diagnostics,
    }
    if provider == "perlgraph":
        summary["repo_path"] = analysis["repo_path"]
        summary["capabilities"] = analysis["capabilities"]
    return summary


@pytest.mark.unit
def test_build_candidate_validates_explicit_paths_and_preserves_provider_bytes(
    tmp_path: Path,
) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        build_topology_snapshot_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = source_output / "codegraph-analysis.json"
    summary = source_output / "codegraph-summary.json"
    codegraph = _codegraph()
    _write_json(analysis, codegraph)
    _write_json(summary, _summary("codegraph", codegraph))

    evidence = build_topology_snapshot_candidate(
        "api",
        "sources/api",
        _fingerprint(),
        {
            "codegraph": ProviderArtifactPaths(
                owner_dir=source_output,
                analysis=analysis,
                summary=summary,
            )
        },
        {"kind": "re", "run_id": "re-1"},
    )

    assert evidence.candidate.source_id == "api"
    assert evidence.unavailable_providers == ()
    provider = evidence.candidate.providers[0]
    assert provider.provider == "codegraph"
    assert provider.analysis == analysis.read_bytes()
    assert provider.summary == summary.read_bytes()


@pytest.mark.unit
def test_build_candidate_keeps_unsupported_provider_and_records_missing_provider(
    tmp_path: Path,
) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        build_topology_snapshot_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    perlgraph = _perl_unsupported()
    _write_json(source_output / "perlgraph-analysis.json", perlgraph)
    _write_json(source_output / "perlgraph-summary.json", _summary("perlgraph", perlgraph))
    evidence = build_topology_snapshot_candidate(
        "api",
        "sources/api",
        _fingerprint(),
        {
            "codegraph": ProviderArtifactPaths(
                owner_dir=source_output,
                analysis=source_output / "missing-codegraph-analysis.json",
                summary=source_output / "missing-codegraph-summary.json",
            ),
            "perlgraph": ProviderArtifactPaths(
                owner_dir=source_output,
                analysis=source_output / "perlgraph-analysis.json",
                summary=source_output / "perlgraph-summary.json",
            ),
        },
        {"kind": "re", "run_id": "re-1"},
    )

    assert [provider.provider for provider in evidence.candidate.providers] == ["codegraph", "perlgraph"]
    assert evidence.candidate.providers[0].unavailable_reason is not None
    assert evidence.unavailable_providers == ("codegraph",)


@pytest.mark.unit
def test_build_candidate_preserves_explicit_provider_error_as_unavailable(
    tmp_path: Path,
) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        build_topology_snapshot_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    perlgraph = _perl_unsupported()
    _write_json(source_output / "perlgraph-analysis.json", perlgraph)
    _write_json(source_output / "perlgraph-summary.json", _summary("perlgraph", perlgraph))
    _write_json(
        source_output / "codegraph-error.json",
        {"kind": "runtime-error", "message": "CodeGraph exited 2", "exit_code": 2},
    )

    evidence = build_topology_snapshot_candidate(
        "api",
        "sources/api",
        _fingerprint(),
        {
            "codegraph": ProviderArtifactPaths(
                owner_dir=source_output,
                analysis=source_output / "codegraph-analysis.json",
                summary=source_output / "codegraph-summary.json",
                error=source_output / "codegraph-error.json",
            ),
            "perlgraph": ProviderArtifactPaths(
                owner_dir=source_output,
                analysis=source_output / "perlgraph-analysis.json",
                summary=source_output / "perlgraph-summary.json",
            ),
        },
        {"kind": "re", "run_id": "re-1"},
    )

    unavailable = evidence.candidate.providers[0]
    assert unavailable.provider == "codegraph"
    assert unavailable.unavailable_reason == {
        "kind": "runtime-error",
        "message": "CodeGraph exited 2",
        "exit_code": 2,
    }
    assert evidence.unavailable_providers == ("codegraph",)


@pytest.mark.unit
def test_build_candidate_rejects_unavailable_only_provider_evidence(tmp_path: Path) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        TopologyEvidenceError,
        build_topology_snapshot_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    source_output.mkdir(parents=True)
    with pytest.raises(TopologyEvidenceError, match="no usable provider evidence"):
        build_topology_snapshot_candidate(
            "api",
            "sources/api",
            _fingerprint(),
            {
                "codegraph": ProviderArtifactPaths(
                    owner_dir=source_output,
                    analysis=source_output / "codegraph-analysis.json",
                    summary=source_output / "codegraph-summary.json",
                )
            },
            {"kind": "re", "run_id": "re-1"},
        )


@pytest.mark.unit
def test_build_candidate_rejects_malformed_and_escaping_provider_input(tmp_path: Path) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        TopologyEvidenceError,
        build_topology_snapshot_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    _write_json(source_output / "codegraph-analysis.json", {"schema_version": 2})
    _write_json(source_output / "codegraph-summary.json", {"provider": "codegraph"})
    with pytest.raises(TopologyEvidenceError, match="invalid provider analysis"):
        build_topology_snapshot_candidate(
            "api",
            "sources/api",
            _fingerprint(),
            {
                "codegraph": ProviderArtifactPaths(
                    owner_dir=source_output,
                    analysis=source_output / "codegraph-analysis.json",
                    summary=source_output / "codegraph-summary.json",
                )
            },
            {"kind": "re", "run_id": "re-1"},
        )


@pytest.mark.unit
@pytest.mark.parametrize("summary", ({}, {"schema_version": 2, "tool": "codegraph", "tool_version": "1.4.1", "provider_status": "complete", "complete": True, "counts": {"discovered_symbols": 9}, "diagnostics": {"unresolved_relationships": []}}))
def test_build_candidate_rejects_malformed_or_mismatched_provider_summary(
    tmp_path: Path, summary: dict[str, object]
) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        TopologyEvidenceError,
        build_topology_snapshot_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = _codegraph()
    _write_json(source_output / "codegraph-analysis.json", analysis)
    _write_json(source_output / "codegraph-summary.json", summary)

    with pytest.raises(TopologyEvidenceError, match="summary"):
        build_topology_snapshot_candidate(
            "api",
            "sources/api",
            _fingerprint(),
            {"codegraph": ProviderArtifactPaths(source_output, source_output / "codegraph-analysis.json", source_output / "codegraph-summary.json")},
            {"kind": "re", "run_id": "re-1"},
        )


@pytest.mark.unit
def test_build_candidate_accepts_compact_schema_two_summary(tmp_path: Path) -> None:
    from harness.topology_evidence import ProviderArtifactPaths, build_topology_snapshot_candidate

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = _codegraph()
    _write_json(source_output / "codegraph-analysis.json", analysis)
    _write_json(source_output / "codegraph-summary.json", _summary("codegraph", analysis))

    evidence = build_topology_snapshot_candidate(
        "api",
        "sources/api",
        _fingerprint(),
        {"codegraph": ProviderArtifactPaths(source_output, source_output / "codegraph-analysis.json", source_output / "codegraph-summary.json")},
        {"kind": "re", "run_id": "re-1"},
    )

    assert evidence.candidate.providers[0].summary


@pytest.mark.unit
def test_schema_one_codegraph_upgrades_only_when_display_endpoints_are_unique(
    tmp_path: Path,
) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        TopologyEvidenceError,
        build_topology_snapshot_candidate,
        upgrade_legacy_codegraph_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = source_output / "codegraph-analysis.json"
    summary = source_output / "codegraph-summary.json"
    _write_json(
        analysis,
        {
            "version": "1.0.0",
            "repo_path": "/provider/native/path",
            "supported": True,
            "symbols": [
                {
                    "file_path": "src/api.py",
                    "qualified_name": "api.run",
                    "name": "run",
                    "kind": "function",
                    "signature": "()",
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
            "relationships": [
                {"kind": "calls", "source": "api.run", "target": "api.run"}
            ],
        },
    )
    _write_json(summary, {"legacy": True})

    upgraded = upgrade_legacy_codegraph_candidate(
        "api",
        "sources/api",
        _fingerprint(),
        ProviderArtifactPaths(source_output, analysis, summary),
        {"kind": "re", "run_id": "re-1"},
    )

    assert upgraded is not None
    analysis_document = json.loads(upgraded.candidate.providers[0].analysis)
    assert analysis_document["schema_version"] == 2
    assert analysis_document["relationships"][0]["source_key"] == (
        analysis_document["relationships"][0]["target_key"]
    )

    external = tmp_path / "outside.json"
    _write_json(external, _codegraph())
    with pytest.raises(TopologyEvidenceError, match="escapes declared source output"):
        build_topology_snapshot_candidate(
            "api",
            "sources/api",
            _fingerprint(),
            {
                "codegraph": ProviderArtifactPaths(
                    owner_dir=source_output,
                    analysis=external,
                    summary=external,
                )
            },
            {"kind": "re", "run_id": "re-1"},
        )


@pytest.mark.unit
def test_historical_codegraph_v1_signature_requires_exact_pre_schema_shape(tmp_path: Path) -> None:
    from harness.topology_evidence import ProviderArtifactPaths, is_historical_codegraph_v1_artifact

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = source_output / "codegraph-analysis.json"
    summary = source_output / "codegraph-summary.json"
    historical = {
        "version": "1.0.0",
        "repo_path": "/provider/native/path",
        "supported": True,
        "symbols": [],
        "relationships": [],
    }
    _write_json(analysis, historical)
    _write_json(summary, {"legacy": True})
    paths = ProviderArtifactPaths(source_output, analysis, summary)

    assert is_historical_codegraph_v1_artifact(paths)
    historical["schema_version"] = 1
    _write_json(analysis, historical)
    assert not is_historical_codegraph_v1_artifact(paths)


@pytest.mark.unit
def test_schema_one_codegraph_upgrade_preserves_all_exact_projection_keys(
    tmp_path: Path,
) -> None:
    from harness.topology_evidence import (
        ProviderArtifactPaths,
        upgrade_legacy_codegraph_candidate,
    )

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = source_output / "codegraph-analysis.json"
    summary = source_output / "codegraph-summary.json"
    symbols = [
        {
            "file_path": "src/api.py",
            "qualified_name": "api.caller",
            "name": "caller",
            "kind": "function",
            "signature": "()",
            "line_start": 1,
            "line_end": 1,
        },
        {
            "file_path": "src/api.py",
            "qualified_name": "api.target",
            "name": "target",
            "kind": "function",
            "signature": "()",
            "line_start": 3,
            "line_end": 3,
        },
    ]
    _write_json(
        analysis,
        {
            "version": "1.0.0",
            "repo_path": "/provider/native/path",
            "supported": True,
            "symbols": symbols,
            "relationships": [{"kind": "calls", "source": "api.caller", "target": "api.target"}],
            "call_graph": [{"caller": "api.caller", "callee": "api.target", "weight": 3}],
            "type_hierarchy": [{"child": "api.caller", "parent": "api.target", "kind": "extends"}],
            "impact_radius": [{"symbol": "api.caller", "affected": ["api.target"], "depth": 1}],
        },
    )
    _write_json(summary, {"legacy": True})

    upgraded = upgrade_legacy_codegraph_candidate(
        "api", "sources/api", _fingerprint(), ProviderArtifactPaths(source_output, analysis, summary), {"kind": "re", "run_id": "re-1"}
    )

    assert upgraded is not None
    document = json.loads(upgraded.candidate.providers[0].analysis)
    assert document["call_graph"][0]["caller_key"]
    assert document["call_graph"][0]["callee_key"]
    assert document["call_graph"][0]["weight"] == 3
    assert document["type_hierarchy"][0]["child_key"]
    assert document["type_hierarchy"][0]["parent_key"]
    assert document["impact_radius"][0]["symbol_key"]
    assert document["impact_radius"][0]["affected_keys"]


@pytest.mark.unit
def test_schema_one_codegraph_upgrade_rejects_ambiguous_projection_endpoint(
    tmp_path: Path,
) -> None:
    from harness.topology_evidence import ProviderArtifactPaths, upgrade_legacy_codegraph_candidate

    source_output = tmp_path / "runs/re-1/re/sources/api"
    analysis = source_output / "codegraph-analysis.json"
    summary = source_output / "codegraph-summary.json"
    _write_json(
        analysis,
        {
            "symbols": [
                {"file_path": "a.py", "qualified_name": "duplicate", "kind": "function", "line_start": 1, "line_end": 1},
                {"file_path": "b.py", "qualified_name": "duplicate", "kind": "function", "line_start": 1, "line_end": 1},
            ],
            "relationships": [],
            "call_graph": [{"caller": "duplicate", "callee": "duplicate"}],
            "type_hierarchy": [],
            "impact_radius": [],
        },
    )
    _write_json(summary, {"legacy": True})

    assert upgrade_legacy_codegraph_candidate(
        "api", "sources/api", _fingerprint(), ProviderArtifactPaths(source_output, analysis, summary), {"kind": "re", "run_id": "re-1"}
    ) is None
