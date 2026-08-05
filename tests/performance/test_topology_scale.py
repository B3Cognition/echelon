from __future__ import annotations

import hashlib
import json
import math
import os
import resource
from pathlib import Path
import subprocess
import sys
import time

import pytest

from echelon.spec_graph import build_spec_graph, write_spec_graph
from echelon.topology_cli import (
    explain_command,
    impact_command,
    neighbors_command,
    search_command,
)
from echelon.topology_model import TopologySymbol, canonical_symbol_key
from echelon.workspace_graph import build_workspace_graph
from harness.re_fingerprint import fingerprint_source, resolve_re_fingerprint_profile
from harness.topology_publication import (
    TopologyProviderCandidate,
    TopologySnapshotCandidate,
    publish_topology_snapshots,
)


SYMBOL_COUNT = 31_000
RELATIONSHIP_COUNT = 65_000
MEASUREMENT_KEYS = frozenset(
    {
        "elapsed",
        "peak_rss_bytes",
        "max_payload_bytes",
        "total_payload_bytes",
    }
)


def _scale_subprocess_env() -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in (
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "TZ",
            "WINDIR",
        )
        if key in os.environ
    }
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _validate_measurement(value: object) -> dict[str, float | int]:
    if not isinstance(value, dict) or set(value) != MEASUREMENT_KEYS:
        raise ValueError("scale measurement has the wrong schema")
    elapsed = value["elapsed"]
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed <= 0
    ):
        raise ValueError("scale elapsed measurement must be finite and positive")
    for key in ("peak_rss_bytes", "max_payload_bytes", "total_payload_bytes"):
        metric = value[key]
        if isinstance(metric, bool) or not isinstance(metric, int) or metric <= 0:
            raise ValueError(f"scale {key} measurement must be a positive integer")
    return value


@pytest.mark.parametrize(
    "measurement",
    (
        {
            "elapsed": -1.0,
            "peak_rss_bytes": 1,
            "max_payload_bytes": 1,
            "total_payload_bytes": 1,
        },
        {
            "elapsed": float("nan"),
            "peak_rss_bytes": 1,
            "max_payload_bytes": 1,
            "total_payload_bytes": 1,
        },
        {
            "elapsed": 1.0,
            "peak_rss_bytes": 1.5,
            "max_payload_bytes": 1,
            "total_payload_bytes": 1,
        },
        {
            "elapsed": 1.0,
            "peak_rss_bytes": 1,
            "max_payload_bytes": 0,
            "total_payload_bytes": 1,
        },
        {
            "elapsed": 1.0,
            "peak_rss_bytes": 1,
            "max_payload_bytes": 1,
            "total_payload_bytes": 1,
            "unexpected": 1,
        },
    ),
)
def test_validate_measurement_rejects_invalid_worker_output(
    measurement: object,
) -> None:
    with pytest.raises(ValueError):
        _validate_measurement(measurement)


def test_scale_subprocess_env_drops_startup_and_runtime_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "ECHELON_HOME",
        "ECHELON_CODEGRAPH_RUNTIME_DIR",
        "ECHELON_PERLGRAPH_RUNTIME_DIR",
    ):
        monkeypatch.setenv(key, f"host-{key.lower()}")

    env = _scale_subprocess_env()

    assert env["PYTHONNOUSERSITE"] == "1"
    assert not set(env) & {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "ECHELON_HOME",
        "ECHELON_CODEGRAPH_RUNTIME_DIR",
        "ECHELON_PERLGRAPH_RUNTIME_DIR",
    }


def _workspace(root: Path) -> Path:
    source = root / "sources" / "scale"
    source.mkdir(parents=True)
    source.joinpath("tracked.txt").write_text("scale fixture\n", encoding="utf-8")
    config = root / ".echelon" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "workspace:\n"
        "  git_role: orchestration\n"
        "sources:\n"
        "  - id: scale\n"
        "    path: sources/scale\n",
        encoding="utf-8",
    )
    return source


def _symbol_locator(index: int) -> tuple[str, str]:
    if index < 2:
        return f"src/duplicate-{index}.py", "scale.resolve"
    return f"src/module-{index % 256:03d}.py", f"scale.symbol_{index:05d}"


def _analysis() -> tuple[bytes, bytes, tuple[str, ...]]:
    symbols: list[dict[str, object]] = []
    keys: list[str] = []
    for index in range(SYMBOL_COUNT):
        path, qualified_name = _symbol_locator(index)
        key = canonical_symbol_key(path, qualified_name, "function", "()")
        keys.append(key)
        symbols.append(
            {
                "symbol_key": key,
                "file_path": path,
                "qualified_name": qualified_name,
                "name": qualified_name.rpartition(".")[2],
                "kind": "function",
                "signature": "()",
                "line_start": 1,
                "line_end": 1,
            }
        )

    endpoints = [(index, 4) for index in range(5, SYMBOL_COUNT)]
    endpoints.extend((index, index + 1) for index in range(5, SYMBOL_COUNT - 1))
    endpoints.extend((index, index + 100) for index in range(5, 5 + 3_008))
    endpoints.extend(((0, 1), (1, 2), (2, 3)))
    assert len(endpoints) == RELATIONSHIP_COUNT
    relationships = [
        {
            "kind": "calls",
            "source_key": keys[source],
            "target_key": keys[target],
            "source_name": symbols[source]["qualified_name"],
            "target_name": symbols[target]["qualified_name"],
        }
        for source, target in endpoints
    ]
    counts = {
        "discovered_symbols": SYMBOL_COUNT,
        "emitted_symbols": SYMBOL_COUNT,
        "excluded_symbols": 0,
        "discovered_relationships": RELATIONSHIP_COUNT,
        "emitted_relationships": RELATIONSHIP_COUNT,
        "excluded_relationships": 0,
    }
    document = {
        "schema_version": 2,
        "version": "2.0.0",
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "repo_path": "/provider/native/scale",
        "provider_status": "complete",
        "complete": True,
        "supported": True,
        "counts": counts,
        "diagnostics": {"unresolved_relationships": []},
        "symbols": symbols,
        "relationships": relationships,
        "call_graph": [],
        "type_hierarchy": [],
        "impact_radius": [],
    }
    summary = {
        "schema_version": 2,
        "tool": "codegraph",
        "tool_version": "1.4.1",
        "provider_status": "complete",
        "complete": True,
        "counts": counts,
        "diagnostics": {"unresolved_relationships": []},
    }
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode(),
        json.dumps(summary, sort_keys=True, separators=(",", ":")).encode(),
        tuple(keys),
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _artifact_descriptor(root: Path, path: str, kind: str, scope: str) -> dict[str, str]:
    return {
        "kind": kind,
        "path": path,
        "sha256": "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest(),
        "scope": scope,
        "source_id": "scale",
    }


def _production_artifact_graphs(
    root: Path, fingerprint: object
) -> tuple[dict[str, object], dict[str, object]]:
    source_root = root / "re/sources/scale"
    source_root.mkdir(parents=True)
    for name in ("overview.md", "architecture.md", "contracts.md", "components.md"):
        (source_root / name).write_text(f"# Scale {name}\n", encoding="utf-8")
    source_artifacts = [
        _artifact_descriptor(
            root,
            f"re/sources/scale/{name}",
            f"re-{name.removesuffix('.md')}",
            "source",
        )
        for name in ("architecture.md", "components.md", "contracts.md", "overview.md")
    ]
    _write_json(
        source_root / "manifest.json",
        {
            "schema_version": 1,
            "source_id": "scale",
            "publication_status": "complete",
            "source_fingerprint": fingerprint.value,
            "overview": "re/sources/scale/overview.md",
            "architecture": "re/sources/scale/architecture.md",
            "contracts": "re/sources/scale/contracts.md",
            "components": "re/sources/scale/components.md",
            "specs": [],
            "artifacts": source_artifacts,
        },
    )
    source_manifest_descriptor = _artifact_descriptor(
        root, "re/sources/scale/manifest.json", "re-source-manifest", "source"
    )

    workspace_root = root / "re/workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    for name in ("overview.md", "relationships.md", "contracts.md"):
        (workspace_root / name).write_text(f"# Scale {name}\n", encoding="utf-8")
    _write_json(
        workspace_root / "manifest.json",
        {"schema_version": 1, "sources": [], "artifacts": []},
    )
    workspace_manifest = _artifact_descriptor(
        root, "re/workspace/manifest.json", "re-workspace-manifest", "workspace"
    )
    workspace_manifest.pop("source_id")
    _write_json(
        root / "re/index.json",
        {
            "schema_version": 1,
            "generation": 1,
            "publication_status": "complete",
            "published_at": "2026-08-05T00:00:00Z",
            "published_from_run": "re-scale",
            "sources": {
                "scale": {
                    "path": "sources/scale",
                    "published_path": "re/sources/scale",
                    "fingerprint": fingerprint.value,
                    "profile_hash": fingerprint.profile_hash,
                    "status": "complete",
                    "manifest": "re/sources/scale/manifest.json",
                    "manifest_artifact": source_manifest_descriptor,
                }
            },
            "workspace": {
                "manifest": "re/workspace/manifest.json",
                "manifest_artifact": workspace_manifest,
                "overview": "re/workspace/overview.md",
                "relationships": "re/workspace/relationships.md",
                "contracts": "re/workspace/contracts.md",
            },
            "warnings": [],
        },
    )

    spec_dir = root / "specs" / "001-scale"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("spec.md").write_text(
        "# Scale\n\n- **FR-001**: Preserve bounded topology evidence.\n",
        encoding="utf-8",
    )
    overview_path = "re/sources/scale/overview.md"
    _write_json(
        spec_dir / "re-context.json",
        {
            "schema_version": 1,
            "status": "attached",
            "generation": 1,
            "artifacts": [
                {
                    "path": overview_path,
                    "hash": "sha256:"
                    + hashlib.sha256((root / overview_path).read_bytes()).hexdigest(),
                }
            ],
        },
    )
    member = build_spec_graph(root, spec_dir)
    write_spec_graph(member, spec_dir)
    return member.to_dict(), build_workspace_graph(root).graph.to_dict()


def _run_scale_workflow(root: Path) -> dict[str, float | int]:
    from echelon.topology_audit import audit_topology
    from echelon.topology_provider import TopologyNodeResolutionError
    from echelon.topology_registry import load_published_topology, load_topology_index

    started = time.perf_counter()
    source = _workspace(root)
    fingerprint = fingerprint_source(source, resolve_re_fingerprint_profile(root))
    analysis, summary, keys = _analysis()
    candidate = TopologySnapshotCandidate(
        source_id="scale",
        source_path="sources/scale",
        source_fingerprint=fingerprint,
        analyzed_commit=fingerprint.git_head,
        provenance={"kind": "re", "run_id": "re-scale"},
        providers=(TopologyProviderCandidate("codegraph", analysis, summary),),
    )

    publication = publish_topology_snapshots(
        root, (candidate,), owner_id="re-scale", owner_run_dir=None
    )
    audit = audit_topology(root)
    topology = load_published_topology(root)
    published_analysis = json.loads(
        (root / "re/topology/sources/scale/codegraph-analysis.json").read_bytes()
    )

    assert publication.generation == 1
    assert audit.status == "current"
    assert audit.exit_code == 0
    assert published_analysis["counts"]["emitted_symbols"] == SYMBOL_COUNT
    assert published_analysis["counts"]["emitted_relationships"] == RELATIONSHIP_COUNT
    assert sum(isinstance(node, TopologySymbol) for node in topology.nodes_by_id.values()) == SYMBOL_COUNT
    assert sum(relation.provider == "codegraph" for relation in topology.relationships) == RELATIONSHIP_COUNT

    duplicate = topology.search("scale", "scale.resolve", frozenset({"SYMBOL"}), 20)
    bounded = topology.search("scale", "scale.symbol", frozenset({"SYMBOL"}), 20)
    assert [node.path for node in duplicate.nodes] == [
        "src/duplicate-0.py",
        "src/duplicate-1.py",
    ]
    assert not duplicate.truncated
    assert len(bounded.nodes) == 20
    assert bounded.truncated
    assert bounded == topology.search(
        "scale", "scale.symbol", frozenset({"SYMBOL"}), 20
    )

    exact_ids = [
        f"symbol:scale:codegraph:{keys[index][7:]}" for index in range(5)
    ]
    with pytest.raises(TopologyNodeResolutionError) as ambiguous:
        topology.explain("scale", "scale.resolve")
    assert ambiguous.value.candidates == tuple(sorted(exact_ids[:2]))
    assert topology.explain("scale", exact_ids[0]).node.path == "src/duplicate-0.py"
    assert topology.explain("scale", exact_ids[1]).node.path == "src/duplicate-1.py"

    neighbors = topology.neighbors(
        "scale", exact_ids[4], "in", frozenset({"CALLS"}), 20
    )
    assert len(neighbors.steps) == 20
    assert neighbors.truncated
    assert neighbors == topology.neighbors(
        "scale", exact_ids[4], "in", frozenset({"CALLS"}), 20
    )
    impact = topology.impact(
        "scale", exact_ids[3], 3, frozenset({"CALLS"})
    )
    assert [step.depth for step in impact.steps] == [1, 2, 3]
    assert [step.node_id for step in impact.steps] == exact_ids[2::-1]
    assert not impact.truncated
    assert impact == topology.impact(
        "scale", exact_ids[3], 3, frozenset({"CALLS"})
    )

    index = load_topology_index(root)
    assert index is not None
    spec_graph, workspace_graph = _production_artifact_graphs(root, fingerprint)
    for graph in (spec_graph, workspace_graph):
        node_ids = [node["id"] for node in graph["nodes"]]
        assert len(node_ids) < 20
        assert not any(node_id.startswith(("file:", "symbol:")) for node_id in node_ids)
        assert not any(
            edge["type"] in {"CALLS", "DECLARES"} for edge in graph["edges"]
        )

    payloads = (
        search_command(
            root, "scale.symbol", source="scale", limit=20, as_json=True
        ).stdout,
        explain_command(root, exact_ids[0], source="scale", as_json=True).stdout,
        neighbors_command(
            root,
            exact_ids[4],
            source="scale",
            direction="in",
            relations=("CALLS",),
            limit=20,
            as_json=True,
        ).stdout,
        impact_command(
            root,
            exact_ids[3],
            source="scale",
            max_depth=3,
            relations=("CALLS",),
            as_json=True,
        ).stdout,
    )
    repeated = search_command(
        root, "scale.symbol", source="scale", limit=20, as_json=True
    ).stdout
    assert payloads[0] == repeated
    assert all(len(payload.encode("utf-8")) < 128 * 1024 for payload in payloads)
    payload_bytes = [len(payload.encode("utf-8")) for payload in payloads]
    assert sum(payload_bytes) < 256 * 1024

    elapsed = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    return {
        "elapsed": elapsed,
        "peak_rss_bytes": peak_bytes,
        "max_payload_bytes": max(payload_bytes),
        "total_payload_bytes": sum(payload_bytes),
    }


@pytest.mark.performance
def test_published_topology_scales_without_projecting_provider_graphs(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    script = """
import json
import sys
from pathlib import Path
repository = Path.cwd()
sys.path[:0] = [str(repository / "src"), str(repository)]
from tests.performance.test_topology_scale import _run_scale_workflow
print(json.dumps(_run_scale_workflow(Path(sys.argv[1]))))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=repository,
        env=_scale_subprocess_env(),
        check=True,
        capture_output=True,
        text=True,
        timeout=150,
    )
    measurement = _validate_measurement(json.loads(completed.stdout))

    assert measurement["elapsed"] < 120.0, (
        f"topology scale workflow took {measurement['elapsed']:.2f}s"
    )
    assert measurement["peak_rss_bytes"] < 1536 * 1024 * 1024
    assert measurement["max_payload_bytes"] < 128 * 1024
    assert measurement["total_payload_bytes"] < 256 * 1024
