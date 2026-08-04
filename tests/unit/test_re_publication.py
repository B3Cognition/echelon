from __future__ import annotations

import hashlib
import json
import shutil
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

import pytest

import harness.re_lock as re_lock
import harness.re_publication as re_publication
from harness.re_artifacts import ReArtifactDescriptor
from harness.publication_transaction import PublicationTransactionError
from harness.re_architecture import build_re_architecture_map, write_re_architecture_catalog
from harness.re_quality_gate import (
    QUALITY_CONTRACT_VERSION,
    measure_source_quality,
    write_re_source_quality_report,
)
from harness.re_fingerprint import ReFingerprintProfile, SourceFingerprint
from harness.re_planner import ReExecutionPlan, RePlanSource
from harness.re_publication import (
    RePublicationConflict,
    RePublicationError,
    RePublicationValidationError,
    publish_re_run,
    recover_interrupted_publication,
)
from harness.re_lock import RePublishLock
from harness.re_registry import ensure_re_layout
from harness.re_registry import ReRegistryError


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _descriptor(manifest: dict[str, object], path: str) -> dict[str, str]:
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, list)
    return next(row for row in artifacts if row["path"] == path)


def _durable_artifact_paths(directory: Path, prefix: str) -> set[str]:
    return {
        f"{prefix}/{path.relative_to(directory).as_posix()}"
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() != "manifest.json"
    }


def _fingerprint(source_id: str, version: str, profile: ReFingerprintProfile) -> SourceFingerprint:
    value = hashlib.sha256(f"{source_id}:{version}".encode()).hexdigest()
    return SourceFingerprint(
        value=value,
        kind="file-tree",
        dirty=False,
        profile_hash=profile.profile_hash(),
    )


def _topology_codegraph(source_id: str) -> dict[str, object]:
    locator = ["src/api.py", f"{source_id}.run", "function", "()"]
    key = "sha256:" + hashlib.sha256(
        json.dumps(locator, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
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
                "qualified_name": f"{source_id}.run",
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


def _topology_summary(analysis: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "tool": "codegraph",
        "tool_version": analysis["tool_version"],
        "provider_status": analysis["provider_status"],
        "complete": analysis["complete"],
        "counts": analysis["counts"],
        "diagnostics": analysis["diagnostics"],
    }


def _deep_spec(source_id: str, version: str) -> str:
    evidence = "\n".join(
        f"- `src/file-{number}.ts:1`" for number in range(1, 6)
    )
    scenarios = "\n\n".join(
        (
            f"### Scenario {number}: Current behavior {number}\n\n"
            f"Source Evidence: `src/file-{((number - 1) % 5) + 1}.ts:1`\n\n"
            "Given the current source state, When the behavior is invoked, "
            "Then the observed result is preserved."
        )
        for number in range(1, 6)
    )
    functional_requirements = "\n\n".join(
        (
            f"### FR-{number:03d}: Current functional requirement {number}\n\n"
            f"Source Evidence: `src/file-{((number - 1) % 5) + 1}.ts:1`"
        )
        for number in range(1, 8)
    )
    non_functional_requirements = "\n\n".join(
        (
            f"### NFR-{number:03d}: Current operational constraint {number}\n\n"
            f"Source Evidence: `src/file-{((number - 1) % 5) + 1}.ts:1`"
        )
        for number in range(1, 4)
    )
    return (
        f"# {source_id} domain {version}\n\n"
        "## User Scenarios & Testing\n\n"
        f"{scenarios}\n\n"
        "## Requirements (Functional)\n\n"
        f"{functional_requirements}\n\n"
        "## Requirements (Non-Functional)\n\n"
        f"{non_functional_requirements}\n\n"
        "## Key Entities\n\n"
        "The source entity and its fields are preserved.\n\n"
        "## Edge Cases\n\n"
        "Invalid input follows the existing error path.\n\n"
        "## Behavior Coverage\n\n"
        "| Category | Status | Observed Scope | Source Evidence |\n"
        "|---|---|---|---|\n"
        "| public operations | observed | current behavior | `src/file-1.ts:1` |\n"
        "| configuration keys | not-observed | none found | — |\n"
        "| errors and recovery | observed | invalid input | `src/file-2.ts:1` |\n"
        "| boundaries and edge cases | observed | current edge | `src/file-3.ts:1` |\n"
        "| operator-visible behavior | not-observed | none found | — |\n"
        "| tests | not-observed | none found | — |\n"
        "| evidence scope | observed | domain files | `src/file-4.ts:1` |\n\n"
        "## Source Evidence\n\n"
        f"{evidence}\n"
    )


def write_valid_re_run(
    root: Path,
    sources: tuple[str, ...],
    *,
    run_id: str = "run-1",
    status: str = "complete",
    versions: dict[str, str] | None = None,
    actions: dict[str, str] | None = None,
    removed_sources: tuple[str, ...] = (),
) -> Path:
    versions = versions or {source_id: "v1" for source_id in sources}
    actions = actions or {source_id: "refresh" for source_id in sources}
    run_dir = root / "runs" / run_id
    run_re = run_dir / "re"
    profile = ReFingerprintProfile()
    planned: list[RePlanSource] = []
    workspace_inputs: list[dict[str, object]] = []

    for source_id in sources:
        version = versions[source_id]
        source_root = root / "sources" / source_id
        if actions[source_id] == "skip-empty" and source_root.exists():
            shutil.rmtree(source_root)
        source_root.mkdir(parents=True, exist_ok=True)
        if actions[source_id] != "skip-empty":
            for number in range(1, 6):
                (source_root / "src").mkdir(exist_ok=True)
                (source_root / "src" / f"file-{number}.ts").write_text(
                    f"export const version{number} = '{version}';\nexport default version{number};\n",
                    encoding="utf-8",
                )

        action = actions[source_id]
        classification = {
            "refresh": "refresh",
            "reuse": "current",
            "skip-empty": "empty",
            "missing": "unavailable",
        }[action]
        fingerprint = _fingerprint(source_id, version, profile)
        plan_source = RePlanSource(
            id=source_id,
            path=f"sources/{source_id}",
            absolute_path=str(source_root),
            action=action,
            fingerprint=fingerprint,
            cache_path=str(root / "re" / ".cache" / "sources" / source_id / fingerprint.value),
            dirty=False,
            selected=True,
            classification=classification,
        )
        planned.append(plan_source)
        workspace_inputs.append(
            {
                "id": source_id,
                "decision": classification,
                "source_path": plan_source.path,
                "fingerprint": fingerprint.value,
                "profile_hash": fingerprint.profile_hash,
                "input_path": (
                    f"runs/{run_id}/re/sources/{source_id}"
                    if action in {"refresh", "skip-empty"}
                    else f"re/sources/{source_id}/manifest.json"
                ),
            }
        )

        if action == "refresh":
            staged_source = run_re / "sources" / source_id
            _write_json(staged_source / "analysis.json", {"source_id": source_id, "version": version})
            _write_json(
                staged_source / "domain-manifest.json",
                {
                    "schema_version": 1,
                    "source_id": source_id,
                    "source_path": plan_source.path,
                    "domains": [
                        {
                            "domain_id": "001-re-domain",
                            "root": "src",
                            "source_file_count": 5,
                            "source_line_count": 10,
                        }
                    ],
                },
            )
            (staged_source / "overview.md").write_text(
                f"# {source_id}\n\nVersion {version}.\n",
                encoding="utf-8",
            )
            (staged_source / "architecture.md").write_text(
                f"# {source_id} Architecture\n\nVersion {version}.\n",
                encoding="utf-8",
            )
            (staged_source / "contracts.md").write_text(
                f"# {source_id} Contracts\n\nVersion {version}.\n",
                encoding="utf-8",
            )
            (staged_source / "components.md").write_text(
                f"# {source_id} Components\n\nVersion {version}.\n",
                encoding="utf-8",
            )
            adrs = staged_source / "adrs"
            adrs.mkdir(parents=True)
            (adrs / "ADR-001-source-boundary.md").write_text(
                "# Source Boundary ADR\n",
                encoding="utf-8",
            )
            spec = staged_source / "specs" / "001-re-domain" / "spec.md"
            spec.parent.mkdir(parents=True)
            spec.write_text(_deep_spec(source_id, version), encoding="utf-8")
        elif action == "skip-empty":
            (run_re / "sources" / source_id).mkdir(parents=True, exist_ok=True)

    for source_id in removed_sources:
        workspace_inputs.append({"id": source_id, "decision": "removed"})

    analysis_required = any(source.action == "refresh" for source in planned)
    plan = ReExecutionPlan(
        policy="changed",
        requested_policy="changed",
        target_source="",
        sources=tuple(planned),
        forbidden_source_roots=[],
        profile=profile,
        removed_sources=removed_sources,
        analysis_required=analysis_required,
        workspace_synthesis_required=True,
        publication_required=True,
    )
    _write_json(run_re / "re-execution-plan.json", plan.to_json_dict())
    _write_json(
        run_re / "re-source-index.json",
        {
            "schema_version": 1,
            "sources": [source.to_json_dict() for source in plan.sources],
        },
    )
    _write_json(
        run_re / "re-workspace-inputs.json",
        {"schema_version": 1, "sources": workspace_inputs},
    )
    _write_json(run_dir / "state.json", {"run_id": run_id, "status": "running", "golddigger_status": status})
    _write_json(run_re / "state.json", {"status": "done" if status != "failed" else "failed"})
    workspace = run_re / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "overview.md").write_text(f"# Workspace {run_id}\n", encoding="utf-8")
    (workspace / "relationships.md").write_text("# Relationships\n", encoding="utf-8")
    (workspace / "contracts.md").write_text("# Contracts\n", encoding="utf-8")
    architecture = build_re_architecture_map(plan, run_re_dir=run_re)
    write_re_architecture_catalog(run_re, architecture)
    workspace_domains = workspace / "domains"
    workspace_domains.mkdir()
    for domain_id in sorted({domain.domain_id for domain in architecture.domains}):
        (workspace_domains / f"{domain_id}.md").write_text(
            f"# Workspace domain {domain_id}\n",
            encoding="utf-8",
        )
    _write_json(
        run_re / "quality" / "semantic-quality-review.json",
        {
            "schema_version": 1,
            "quality_contract_version": QUALITY_CONTRACT_VERSION,
            "passed": True,
            "failures": [],
        },
    )
    return run_dir


def test_publication_rejects_missing_architecture_catalog(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    (run_dir / "re" / "workspace" / "architecture-map.json").unlink()

    with pytest.raises(RePublicationValidationError, match="architecture catalog validation failed"):
        publish_re_run(tmp_path, run_dir)


def _durable_snapshot(root: Path) -> dict[str, bytes]:
    re_root = root / "re"
    if not re_root.exists():
        return {}
    result: dict[str, bytes] = {}
    for path in sorted(re_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(re_root)
        if relative.parts and relative.parts[0] in {".cache", ".staging", ".locks"}:
            continue
        result[relative.as_posix()] = path.read_bytes()
    return result


def _source_child_snapshot(source_dir: Path) -> dict[str, bytes]:
    return {
        path.relative_to(source_dir).as_posix(): path.read_bytes()
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and path.relative_to(source_dir).as_posix() != "manifest.json"
    }


def _finish_run(run_dir: Path) -> None:
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    state["status"] = "done"
    _write_json(run_dir / "state.json", state)


def _assert_corrupt_catalog_blocks_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[
        [Path, tuple[ReArtifactDescriptor, ...]],
        tuple[ReArtifactDescriptor, ...],
    ],
    *,
    match: str,
) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )
    build_catalog = re_publication.build_re_artifact_catalog

    def corrupt_catalog(
        directory: Path,
        *,
        published_prefix: PurePosixPath,
        scope: str,
        source_id: str | None = None,
    ) -> tuple[ReArtifactDescriptor, ...]:
        rows = build_catalog(
            directory,
            published_prefix=published_prefix,
            scope=scope,
            source_id=source_id,
        )
        return mutate(directory, rows) if source_id == "api" else rows

    monkeypatch.setattr(re_publication, "build_re_artifact_catalog", corrupt_catalog)

    with pytest.raises(RePublicationValidationError, match=match):
        publish_re_run(tmp_path, run_2, expected_generation=1)

    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_complete_two_source_publish_creates_generation_with_typed_artifact_catalog(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("web", "api"))
    source_re = run_dir / "re" / "sources" / "api"
    _write_json(source_re / "structure.json", {"source_id": "api", "structure": True})
    _write_json(source_re / "dependencies.json", {"source_id": "api", "dependencies": True})
    _write_json(source_re / "configs.json", {"source_id": "api", "configs": True})
    (source_re / "supporting-artifacts.md").write_text(
        "# Supporting Artifacts\n",
        encoding="utf-8",
    )
    _write_json(
        run_dir / "re" / "codegraph-summary.json",
        {"workspace": True, "sources": ["api"]},
    )

    result = publish_re_run(tmp_path, run_dir)

    assert result.generation == 1
    assert result.changed_sources == ("api", "web")
    index = json.loads((tmp_path / "re" / "index.json").read_text(encoding="utf-8"))
    assert index["generation"] == 1
    assert set(index["sources"]) == {"api", "web"}
    assert json.loads((tmp_path / "re/sources/api/manifest.json").read_text())["source_id"] == "api"
    assert (tmp_path / "re/sources/web/specs/001-re-domain/spec.md").is_file()
    manifest = json.loads((tmp_path / "re/sources/api/manifest.json").read_text())
    assert manifest["domain_manifest"] == "re/sources/api/domain-manifest.json"
    assert manifest["architecture"] == "re/sources/api/architecture.md"
    assert manifest["contracts"] == "re/sources/api/contracts.md"
    assert manifest["components"] == "re/sources/api/components.md"
    assert manifest["supporting_artifacts"] == "re/sources/api/supporting-artifacts.md"
    assert manifest["extraction_artifacts"] == {
        "analysis": "re/sources/api/analysis.json",
        "configs": "re/sources/api/configs.json",
        "dependencies": "re/sources/api/dependencies.json",
        "structure": "re/sources/api/structure.json",
    }
    assert "codegraph_summary" not in manifest
    assert "codegraph_analysis" not in manifest
    assert (tmp_path / "re/sources/api/domain-manifest.json").is_file()
    assert (tmp_path / "re/sources/api/architecture.md").is_file()
    assert (tmp_path / "re/sources/api/contracts.md").is_file()
    assert (tmp_path / "re/sources/api/components.md").is_file()
    assert (tmp_path / "re/sources/api/adrs/ADR-001-source-boundary.md").is_file()
    assert (tmp_path / "re/sources/api/supporting-artifacts.md").is_file()
    assert json.loads((tmp_path / "re/sources/api/structure.json").read_text()) == {
        "source_id": "api",
        "structure": True,
    }
    assert not (tmp_path / "re/sources/api/codegraph-summary.json").exists()
    assert not (tmp_path / "re/sources/api/codegraph-analysis.json").exists()
    fingerprint = index["sources"]["api"]["fingerprint"]
    assert (tmp_path / f"re/.cache/sources/api/{fingerprint}/analysis.json").is_file()
    assert (tmp_path / "re/workspace/contracts.md").is_file()
    assert (tmp_path / "re/workspace/architecture-map.json").is_file()
    assert (tmp_path / "re/workspace/domain-catalog.md").is_file()
    assert "codegraph_summary" not in index["workspace"]
    assert not (tmp_path / "re/workspace/codegraph-summary.json").exists()
    source_manifest = _read_json(tmp_path / "re/sources/api/manifest.json")
    assert source_manifest["artifacts"] == sorted(
        source_manifest["artifacts"], key=lambda row: row["path"]
    )
    assert _descriptor(source_manifest, "re/sources/api/architecture.md")["kind"] == (
        "re-architecture"
    )
    assert _descriptor(
        source_manifest, "re/sources/api/adrs/ADR-001-source-boundary.md"
    )["kind"] == "re-decision"
    assert {row["path"] for row in source_manifest["artifacts"]} == (
        _durable_artifact_paths(tmp_path / "re/sources/api", "re/sources/api")
    )

    workspace_manifest = _read_json(tmp_path / "re/workspace/manifest.json")
    assert workspace_manifest["artifacts"] == sorted(
        workspace_manifest["artifacts"], key=lambda row: row["path"]
    )
    assert {row["path"] for row in workspace_manifest["artifacts"]} == (
        _durable_artifact_paths(tmp_path / "re/workspace", "re/workspace")
    )
    assert index["sources"]["api"]["manifest_artifact"]["kind"] == (
        "re-source-manifest"
    )
    assert index["workspace"]["manifest_artifact"]["kind"] == (
        "re-workspace-manifest"
    )


@pytest.mark.unit
def test_publication_stages_semantic_and_topology_authorities_together(tmp_path: Path) -> None:
    from echelon.topology_registry import load_topology_index

    run_dir = write_valid_re_run(tmp_path, ("api", "web"))
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n    - id: web\n      path: sources/web\n",
        encoding="utf-8",
    )
    for source_id in ("api", "web"):
        source = run_dir / "re" / "sources" / source_id
        _write_json(source / "codegraph-analysis.json", _topology_codegraph(source_id))
        _write_json(source / "codegraph-summary.json", _topology_summary(_topology_codegraph(source_id)))

    result = publish_re_run(tmp_path, run_dir)

    semantic = _read_json(tmp_path / "re" / "index.json")
    topology = load_topology_index(tmp_path)
    assert result.generation == semantic["generation"] == 1
    assert result.topology_generation == 1
    assert topology is not None and topology.generation == 1
    assert semantic["sources"]["api"]["fingerprint"] == (
        topology.sources["api"].source_fingerprint.value
    )
    assert topology.sources["api"].providers["codegraph"].counts[
        "discovered_symbols"
    ] == 1
    assert not (tmp_path / "re/sources/api/codegraph-analysis.json").exists()
    assert not (tmp_path / "re/sources/api/codegraph-summary.json").exists()
    assert (tmp_path / "re/topology/sources/api/codegraph-analysis.json").is_file()
    assert (tmp_path / "re/topology/sources/api/codegraph-summary.json").is_file()
    manifest = _read_json(tmp_path / "re/sources/api/manifest.json")
    assert "codegraph_analysis" not in manifest
    assert "codegraph_summary" not in manifest


@pytest.mark.unit
def test_targeted_publication_preserves_sibling_receipts_and_resynthesizes_workspace(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n"
        "    - id: web\n      path: sources/web\n",
        encoding="utf-8",
    )
    run_1 = write_valid_re_run(tmp_path, ("api", "web"), run_id="run-1")
    for source_id in ("api", "web"):
        analysis = _topology_codegraph(source_id)
        _write_json(run_1 / f"re/sources/{source_id}/codegraph-analysis.json", analysis)
        _write_json(
            run_1 / f"re/sources/{source_id}/codegraph-summary.json",
            _topology_summary(analysis),
        )
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    sibling_semantic_before = _source_child_snapshot(tmp_path / "re/sources/web")
    sibling_topology_before = {
        path.relative_to(tmp_path / "re/topology/sources/web").as_posix(): path.read_bytes()
        for path in sorted((tmp_path / "re/topology/sources/web").rglob("*"))
        if path.is_file()
    }
    workspace_before = _source_child_snapshot(tmp_path / "re/workspace")

    run_2 = write_valid_re_run(
        tmp_path,
        ("api", "web"),
        run_id="run-2",
        versions={"api": "v2", "web": "v1"},
        actions={"api": "refresh", "web": "reuse"},
    )
    plan_path = run_2 / "re/re-execution-plan.json"
    plan = _read_json(plan_path)
    plan["policy"] = "target-only"
    plan["requested_policy"] = "target-only"
    plan["target_source"] = "api"
    plan["forbidden_source_roots"] = [str(tmp_path / "sources/web")]
    plan["sources"][1]["selected"] = False
    _write_json(plan_path, plan)
    source_index_path = run_2 / "re/re-source-index.json"
    source_index = _read_json(source_index_path)
    source_index["sources"][1]["selected"] = False
    _write_json(source_index_path, source_index)
    analysis = _topology_codegraph("api")
    _write_json(run_2 / "re/sources/api/codegraph-analysis.json", analysis)
    _write_json(
        run_2 / "re/sources/api/codegraph-summary.json",
        _topology_summary(analysis),
    )

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.changed_sources == ("api",)
    assert _source_child_snapshot(tmp_path / "re/sources/web") == sibling_semantic_before
    assert {
        path.relative_to(tmp_path / "re/topology/sources/web").as_posix(): path.read_bytes()
        for path in sorted((tmp_path / "re/topology/sources/web").rglob("*"))
        if path.is_file()
    } == sibling_topology_before
    assert _source_child_snapshot(tmp_path / "re/workspace") != workspace_before
    assert (tmp_path / "re/workspace/overview.md").read_text(encoding="utf-8") == (
        "# Workspace run-2\n"
    )


@pytest.mark.unit
def test_targeted_publication_is_atomic_when_selected_source_disappears(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    analysis = _topology_codegraph("api")
    _write_json(run_1 / "re/sources/api/codegraph-analysis.json", analysis)
    _write_json(
        run_1 / "re/sources/api/codegraph-summary.json",
        _topology_summary(analysis),
    )
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)

    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )
    plan_path = run_2 / "re/re-execution-plan.json"
    plan = _read_json(plan_path)
    plan["policy"] = "target-only"
    plan["requested_policy"] = "target-only"
    plan["target_source"] = "api"
    _write_json(plan_path, plan)
    analysis = _topology_codegraph("api")
    _write_json(run_2 / "re/sources/api/codegraph-analysis.json", analysis)
    _write_json(
        run_2 / "re/sources/api/codegraph-summary.json",
        _topology_summary(analysis),
    )
    shutil.rmtree(tmp_path / "sources/api")

    with pytest.raises(
        RePublicationValidationError,
        match="selected source api is unavailable",
    ):
        publish_re_run(tmp_path, run_2, expected_generation=1)

    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_configured_refresh_without_provider_evidence_is_atomic_failure(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    (tmp_path / ".echelon").mkdir()
    (tmp_path / ".echelon" / "config.yml").write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )

    with pytest.raises(RePublicationValidationError, match="no usable topology evidence"):
        publish_re_run(tmp_path, run_dir)

    assert not (tmp_path / "re/index.json").exists()
    assert not (tmp_path / "re/topology/index.json").exists()


@pytest.mark.unit
@pytest.mark.parametrize("topology_target", ("topology/index.json", "topology/sources/api"))
def test_topology_staging_corruption_rolls_back_both_authorities(
    tmp_path: Path,
    topology_target: str,
) -> None:
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    _write_json(run_1 / "re/sources/api/codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(run_1 / "re/sources/api/codegraph-summary.json", _topology_summary(_topology_codegraph("api")))
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)

    run_2 = write_valid_re_run(tmp_path, ("api",), run_id="run-2", versions={"api": "v2"})
    _write_json(run_2 / "re/sources/api/codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(run_2 / "re/sources/api/codegraph-summary.json", _topology_summary(_topology_codegraph("api")))

    def corrupt_topology_index(step: str) -> None:
        if step == f"after_backup:{topology_target}":
            staged = tmp_path / "re/.staging/run-2/new/re" / topology_target
            if staged.is_dir():
                staged = staged / "receipt.json"
            staged.write_text("{}", encoding="utf-8")

    with pytest.raises(PublicationTransactionError, match="staged artifact changed before install"):
        publish_re_run(tmp_path, run_2, expected_generation=1, fault_hook=corrupt_topology_index)

    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
@pytest.mark.parametrize("topology_target", ("topology/index.json", "topology/sources/api"))
def test_post_install_topology_validation_restores_both_authorities(
    tmp_path: Path, topology_target: str
) -> None:
    from echelon.topology_registry import load_published_topology, load_topology_index

    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    _write_json(run_1 / "re/sources/api/codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(run_1 / "re/sources/api/codegraph-summary.json", _topology_summary(_topology_codegraph("api")))
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)

    run_2 = write_valid_re_run(tmp_path, ("api",), run_id="run-2", versions={"api": "v2"})
    _write_json(run_2 / "re/sources/api/codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(run_2 / "re/sources/api/codegraph-summary.json", _topology_summary(_topology_codegraph("api")))

    def corrupt_installed_topology(step: str) -> None:
        if step == f"after_replace:{topology_target}":
            path = tmp_path / "re" / topology_target
            if path.is_dir():
                path = path / "receipt.json"
            path.write_text("{}", encoding="utf-8")

    with pytest.raises(Exception, match="topology|schema_version|hash"):
        publish_re_run(tmp_path, run_2, expected_generation=1, fault_hook=corrupt_installed_topology)

    assert _durable_snapshot(tmp_path) == before
    assert _read_json(tmp_path / "re/index.json")["generation"] == 1
    assert load_topology_index(tmp_path).generation == 1  # type: ignore[union-attr]
    assert load_published_topology(tmp_path).generation == 1
    assert _read_json(tmp_path / "re/.staging/run-2/rollback-journal.json")["status"] == "rolled_back"


@pytest.mark.unit
def test_removing_a_configured_source_removes_its_topology_in_the_same_publication(
    tmp_path: Path,
) -> None:
    from echelon.topology_registry import load_topology_index

    run_1 = write_valid_re_run(tmp_path, ("api", "web"), run_id="run-1")
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n    - id: web\n      path: sources/web\n",
        encoding="utf-8",
    )
    for source_id in ("api", "web"):
        source = run_1 / "re" / "sources" / source_id
        _write_json(source / "codegraph-analysis.json", _topology_codegraph(source_id))
        _write_json(source / "codegraph-summary.json", _topology_summary(_topology_codegraph(source_id)))
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)

    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        actions={"api": "reuse"},
        removed_sources=("web",),
    )
    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    topology = load_topology_index(tmp_path)
    assert result.generation == 2
    assert result.topology_generation == 2
    assert topology is not None and set(topology.sources) == {"api"}
    assert not (tmp_path / "re/sources/web").exists()
    assert not (tmp_path / "re/topology/sources/web").exists()


@pytest.mark.unit
def test_reuse_migrates_valid_schema_two_provider_artifacts_from_legacy_semantic_source(
    tmp_path: Path,
) -> None:
    from echelon.topology_registry import load_topology_index

    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    config = tmp_path / ".echelon" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    legacy = tmp_path / "re/sources/api"
    _write_json(legacy / "codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(legacy / "codegraph-summary.json", _topology_summary(_topology_codegraph("api")))

    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        actions={"api": "reuse"},
    )
    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    topology = load_topology_index(tmp_path)
    assert result.topology_generation == 1
    assert topology is not None and set(topology.sources) == {"api"}
    assert not (legacy / "codegraph-analysis.json").exists()
    assert (tmp_path / "re/topology/sources/api/codegraph-analysis.json").is_file()


@pytest.mark.unit
def test_reuse_upgrades_actual_codegraph_v1_without_discarding_valid_perlgraph(
    tmp_path: Path,
) -> None:
    from echelon.topology_registry import load_topology_index
    from tests.unit.test_topology_evidence import _perl_unsupported, _summary

    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    legacy = tmp_path / "re/sources/api"
    _write_json(
        legacy / "codegraph-analysis.json",
        {
            "version": "1.0.0",
            "repo_path": "/provider/native/path",
            "supported": True,
            "symbols": [
                {"file_path": "src/api.py", "qualified_name": "api.run", "kind": "function", "signature": "()", "line_start": 1, "line_end": 1}
            ],
            "relationships": [],
        },
    )
    _write_json(legacy / "codegraph-summary.json", {"legacy": True})
    perlgraph = _perl_unsupported()
    _write_json(legacy / "perlgraph-analysis.json", perlgraph)
    _write_json(legacy / "perlgraph-summary.json", _summary("perlgraph", perlgraph))

    run_2 = write_valid_re_run(tmp_path, ("api",), run_id="run-2", actions={"api": "reuse"})
    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    topology = load_topology_index(tmp_path)
    assert result.topology_generation == 1
    assert topology is not None
    assert set(topology.sources["api"].providers) == {"codegraph", "perlgraph"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,value",
    (
        ("source_fingerprint", "f" * 64),
        ("profile_hash", "e" * 64),
        ("dirty", True),
        ("source_path", "sources/other"),
        ("git_head", "0123456789abcdef0123456789abcdef01234567"),
    ),
)
def test_untrusted_legacy_topology_bytes_do_not_block_semantic_republish(
    tmp_path: Path, field: str, value: object
) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n",
        encoding="utf-8",
    )
    legacy = tmp_path / "re/sources/api"
    _write_json(legacy / "codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(legacy / "codegraph-summary.json", _topology_summary(_topology_codegraph("api")))
    manifest = _read_json(legacy / "manifest.json")
    manifest[field] = value
    _write_json(legacy / "manifest.json", manifest)
    index = _read_json(tmp_path / "re/index.json")
    index["sources"]["api"]["manifest_artifact"]["sha256"] = "sha256:" + hashlib.sha256(
        (legacy / "manifest.json").read_bytes()
    ).hexdigest()
    _write_json(tmp_path / "re/index.json", index)

    run_2 = write_valid_re_run(tmp_path, ("api",), run_id="run-2", actions={"api": "reuse"})
    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.generation == 2
    assert result.topology_generation is None
    assert not (tmp_path / "re/topology/index.json").exists()


@pytest.mark.unit
@pytest.mark.parametrize("legacy_case", ("malformed", "ambiguous-schema-one"))
def test_optional_reused_legacy_failures_skip_first_topology_but_publish_semantic_re(
    tmp_path: Path, legacy_case: str
) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api", "web"), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: api\n      path: sources/api\n    - id: web\n      path: sources/web\n",
        encoding="utf-8",
    )
    legacy = tmp_path / "re/sources/web"
    _write_json(legacy / "codegraph-summary.json", {"legacy": True})
    if legacy_case == "malformed":
        (legacy / "codegraph-analysis.json").write_text("{", encoding="utf-8")
    else:
        _write_json(
            legacy / "codegraph-analysis.json",
            {
                "symbols": [
                    {"file_path": "a.py", "qualified_name": "duplicate", "kind": "function", "line_start": 1, "line_end": 1},
                    {"file_path": "b.py", "qualified_name": "duplicate", "kind": "function", "line_start": 1, "line_end": 1},
                ],
                "relationships": [{"kind": "calls", "source": "duplicate", "target": "duplicate"}],
            },
        )
    run_2 = write_valid_re_run(
        tmp_path,
        ("api", "web"),
        run_id="run-2",
        versions={"api": "v2", "web": "v1"},
        actions={"api": "refresh", "web": "reuse"},
    )
    _write_json(run_2 / "re/sources/api/codegraph-analysis.json", _topology_codegraph("api"))
    _write_json(run_2 / "re/sources/api/codegraph-summary.json", _topology_summary(_topology_codegraph("api")))

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.generation == 2
    assert result.topology_generation is None
    assert not (tmp_path / "re/topology/index.json").exists()


@pytest.mark.unit
def test_publication_rejects_omitted_catalog_file_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_corrupt_catalog_blocks_publication(
        tmp_path,
        monkeypatch,
        lambda _directory, rows: rows[1:],
        match="catalog inventory does not match durable files",
    )


@pytest.mark.unit
def test_publication_rejects_duplicate_catalog_path_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_corrupt_catalog_blocks_publication(
        tmp_path,
        monkeypatch,
        lambda _directory, rows: rows + (rows[0],),
        match="duplicate artifact path",
    )


@pytest.mark.unit
def test_publication_rejects_unsupported_catalog_kind_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def replace_kind(
        _directory: Path,
        rows: tuple[ReArtifactDescriptor, ...],
    ) -> tuple[ReArtifactDescriptor, ...]:
        return (replace(rows[0], kind="not-supported"), *rows[1:])

    _assert_corrupt_catalog_blocks_publication(
        tmp_path,
        monkeypatch,
        replace_kind,
        match="unsupported artifact kind",
    )


@pytest.mark.unit
def test_publication_rejects_bytes_modified_after_cataloging_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def modify_bytes(
        directory: Path,
        rows: tuple[ReArtifactDescriptor, ...],
    ) -> tuple[ReArtifactDescriptor, ...]:
        (directory / "overview.md").write_text(
            "modified after cataloging\n",
            encoding="utf-8",
        )
        return rows

    _assert_corrupt_catalog_blocks_publication(
        tmp_path,
        monkeypatch,
        modify_bytes,
        match="artifact hash mismatch",
    )


@pytest.mark.unit
def test_fast_profile_publication_records_semantics_as_not_evaluated(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    state_path = run_dir / "re/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["re_execution_profile"] = {
        "name": "fast",
        "semantic_audit_mode": "none",
        "max_semantic_repair_rounds": 0,
    }
    _write_json(state_path, state)
    (run_dir / "re/quality/semantic-quality-review.json").unlink()

    publish_re_run(tmp_path, run_dir)

    index = json.loads((tmp_path / "re/index.json").read_text(encoding="utf-8"))
    assert index["quality"]["semantic_audit_status"] == "not-evaluated"
    assert index["quality"]["execution_profile"] == "fast"


@pytest.mark.unit
def test_partial_publication_accepts_only_controller_recorded_quality_debt(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), status="partial")
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    report = measure_source_quality(run_dir / "re", plan, "api")
    report_path = write_re_source_quality_report(run_dir / "re", report)
    _write_json(
        run_dir / "re" / "state.json",
        {
            "status": "done",
            "re_source_states": {
                "api": {
                    "status": "partial_quality_debt",
                    "quality_debt_report": str(report_path),
                }
            },
        },
    )

    result = publish_re_run(tmp_path, run_dir, allow_partial=True)

    assert result.status == "partial"
    index = json.loads((tmp_path / "re" / "index.json").read_text(encoding="utf-8"))
    assert index["sources"]["api"]["status"] == "partial"


@pytest.mark.unit
def test_allow_partial_infers_partial_from_controller_quality_debt(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), status="complete")
    spec = run_dir / "re" / "sources" / "api" / "specs" / "001-re-domain" / "spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_dir / "re" / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    report = measure_source_quality(run_dir / "re", plan, "api")
    report_path = write_re_source_quality_report(run_dir / "re", report)
    _write_json(
        run_dir / "re" / "state.json",
        {
            "status": "done",
            "re_source_states": {
                "api": {
                    "status": "partial_quality_debt",
                    "quality_debt_report": str(report_path),
                }
            },
        },
    )

    with pytest.raises(RePublicationValidationError, match="quality debt"):
        publish_re_run(tmp_path, run_dir)

    result = publish_re_run(tmp_path, run_dir, allow_partial=True)

    assert result.status == "partial"
    index = json.loads((tmp_path / "re" / "index.json").read_text(encoding="utf-8"))
    assert index["publication_status"] == "partial"


@pytest.mark.unit
def test_complete_publication_accepts_line_range_source_evidence(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re/sources/api/specs/001-re-domain/spec.md"
    text = spec.read_text(encoding="utf-8")
    for line in range(1, 6):
        text = text.replace(f"file-{line}.ts:{line}`", f"file-{line}.ts:{line}-{line + 1}`")
    spec.write_text(text, encoding="utf-8")

    result = publish_re_run(tmp_path, run_dir)

    assert result.generation == 1


@pytest.mark.unit
def test_partial_publication_requires_explicit_override(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), status="partial")

    with pytest.raises(RePublicationValidationError, match="allow-partial"):
        publish_re_run(tmp_path, run_dir)

    result = publish_re_run(tmp_path, run_dir, allow_partial=True)
    assert result.status == "partial"
    assert json.loads((tmp_path / "re/index.json").read_text())["publication_status"] == "partial"


@pytest.mark.unit
def test_failed_run_is_never_publishable(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), status="failed")

    with pytest.raises(RePublicationValidationError, match="failed"):
        publish_re_run(tmp_path, run_dir, allow_partial=True)
    assert not (tmp_path / "re/index.json").exists()


@pytest.mark.unit
def test_one_source_refresh_preserves_unchanged_source_bytes(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(
        tmp_path,
        ("web", "api"),
        run_id="run-1",
        versions={"web": "v1", "api": "v1"},
    )
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    web_before = _durable_snapshot(tmp_path)["sources/web/manifest.json"]
    run_2 = write_valid_re_run(
        tmp_path,
        ("web", "api"),
        run_id="run-2",
        versions={"web": "v1", "api": "v2"},
        actions={"web": "reuse", "api": "refresh"},
    )

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.generation == 2
    assert result.changed_sources == ("api",)
    assert _durable_snapshot(tmp_path)["sources/web/manifest.json"] == web_before
    assert "Version v2" in (tmp_path / "re/sources/api/overview.md").read_text()


@pytest.mark.unit
def test_legacy_reused_source_is_atomically_upgraded_to_typed_catalog(
    tmp_path: Path,
) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)

    source_dir = tmp_path / "re/sources/api"
    source_manifest_path = source_dir / "manifest.json"
    legacy_source_manifest = _read_json(source_manifest_path)
    legacy_source_manifest.pop("artifacts")
    legacy_source_manifest["legacy_extension"] = {"retained": True}
    _write_json(source_manifest_path, legacy_source_manifest)

    workspace_manifest_path = tmp_path / "re/workspace/manifest.json"
    legacy_workspace_manifest = _read_json(workspace_manifest_path)
    legacy_workspace_manifest.pop("artifacts")
    _write_json(workspace_manifest_path, legacy_workspace_manifest)

    index_path = tmp_path / "re/index.json"
    legacy_index = _read_json(index_path)
    legacy_index["sources"]["api"].pop("manifest_artifact")
    legacy_index["workspace"].pop("manifest_artifact")
    _write_json(index_path, legacy_index)

    before = _durable_snapshot(tmp_path)
    child_bytes_before = _source_child_snapshot(source_dir)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        actions={"api": "reuse"},
    )

    def fail_before_index(step: str) -> None:
        if step == "before_index_replace":
            raise OSError("injected legacy upgrade failure")

    with pytest.raises(OSError, match="injected legacy upgrade failure"):
        publish_re_run(
            tmp_path,
            run_2,
            expected_generation=1,
            fault_hook=fail_before_index,
        )
    assert _durable_snapshot(tmp_path) == before

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.generation == 2
    assert _source_child_snapshot(source_dir) == child_bytes_before
    typed_manifest = _read_json(source_manifest_path)
    artifacts = typed_manifest.pop("artifacts")
    assert typed_manifest == legacy_source_manifest
    assert {row["path"] for row in artifacts} == _durable_artifact_paths(
        source_dir,
        "re/sources/api",
    )
    for descriptor in artifacts:
        artifact_path = tmp_path / descriptor["path"]
        assert descriptor["sha256"] == (
            "sha256:" + hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        )

    typed_index = _read_json(index_path)
    manifest_artifact = typed_index["sources"]["api"]["manifest_artifact"]
    assert manifest_artifact["kind"] == "re-source-manifest"
    assert manifest_artifact["sha256"] == (
        "sha256:" + hashlib.sha256(source_manifest_path.read_bytes()).hexdigest()
    )


@pytest.mark.unit
def test_empty_source_publishes_manifest_without_specs(tmp_path: Path) -> None:
    config = tmp_path / ".echelon/config.yml"
    config.parent.mkdir()
    config.write_text(
        "workspace:\n  sources:\n    - id: empty\n      path: sources/empty\n",
        encoding="utf-8",
    )
    run_dir = write_valid_re_run(
        tmp_path,
        ("empty",),
        actions={"empty": "skip-empty"},
    )

    result = publish_re_run(tmp_path, run_dir)

    assert result.generation == 1
    manifest = json.loads((tmp_path / "re/sources/empty/manifest.json").read_text())
    assert manifest["publication_status"] == "empty"
    assert manifest["specs"] == []
    assert "No analyzable source files" in (tmp_path / "re/sources/empty/overview.md").read_text()
    topology = _read_json(tmp_path / "re/topology/sources/empty/receipt.json")
    assert topology["providers"]["codegraph"]["status"] == "empty"


@pytest.mark.unit
def test_refresh_source_with_zero_domains_publishes_without_specs(
    tmp_path: Path,
) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    run_re = run_dir / "re"
    manifest_path = run_re / "sources/api/domain-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["domains"] = []
    _write_json(manifest_path, manifest)
    shutil.rmtree(run_re / "sources/api/specs")
    plan = ReExecutionPlan.from_json_dict(
        json.loads((run_re / "re-execution-plan.json").read_text(encoding="utf-8"))
    )
    architecture = build_re_architecture_map(plan, run_re_dir=run_re)
    write_re_architecture_catalog(run_re, architecture)

    result = publish_re_run(tmp_path, run_dir)

    assert result.generation == 1
    published = json.loads((tmp_path / "re/sources/api/manifest.json").read_text())
    assert published["publication_status"] == "complete"
    assert published["specs"] == []
    assert (tmp_path / "re/sources/api/specs").is_dir()


@pytest.mark.unit
def test_generation_conflict_does_not_modify_publication(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    with pytest.raises(RePublicationConflict, match="expected generation 0"):
        publish_re_run(tmp_path, run_2, expected_generation=0)
    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_same_run_republish_can_rebase_its_stale_generation(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    first = publish_re_run(tmp_path, run_dir, expected_generation=0)

    second = publish_re_run(
        tmp_path,
        run_dir,
        expected_generation=0,
        allow_same_run_republish=True,
    )

    assert first.generation == 1
    assert second.generation == 2
    index = _read_json(tmp_path / "re/index.json")
    assert index["generation"] == 2
    assert index["published_from_run"] == run_dir.name


@pytest.mark.unit
def test_stale_different_run_cannot_use_same_run_republish(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1, expected_generation=0)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    with pytest.raises(RePublicationConflict, match="expected generation 0"):
        publish_re_run(
            tmp_path,
            run_2,
            expected_generation=0,
            allow_same_run_republish=True,
        )

    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_failure_before_index_replace_rolls_back_byte_for_byte(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    def fail_before_index(step: str) -> None:
        if step == "before_index_replace":
            assert (tmp_path / "re/index.json").read_bytes() == before["index.json"]
            raise OSError("injected failure")

    with pytest.raises(OSError, match="injected failure"):
        publish_re_run(
            tmp_path,
            run_2,
            expected_generation=1,
            fault_hook=fail_before_index,
        )

    assert _durable_snapshot(tmp_path) == before


@pytest.mark.unit
def test_explicit_removal_updates_source_and_workspace_atomically(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("web", "api"), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        actions={"api": "reuse"},
        removed_sources=("web",),
    )

    result = publish_re_run(tmp_path, run_2, expected_generation=1)

    assert result.removed_sources == ("web",)
    assert not (tmp_path / "re/sources/web").exists()
    index = json.loads((tmp_path / "re/index.json").read_text())
    assert set(index["sources"]) == {"api"}
    workspace = json.loads((tmp_path / "re/workspace/manifest.json").read_text())
    assert [source["source_id"] for source in workspace["sources"]] == ["api"]


@pytest.mark.unit
def test_populated_to_empty_replaces_old_specs_only_after_success(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    assert (tmp_path / "re/sources/api/specs/001-re-domain/spec.md").is_file()
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "empty"},
        actions={"api": "skip-empty"},
    )

    publish_re_run(tmp_path, run_2, expected_generation=1)

    manifest = json.loads((tmp_path / "re/sources/api/manifest.json").read_text())
    assert manifest["publication_status"] == "empty"
    assert manifest["specs"] == []
    assert not (tmp_path / "re/sources/api/specs").exists()


@pytest.mark.unit
def test_workspace_inputs_must_match_plan_fingerprint(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    inputs_path = run_dir / "re/re-workspace-inputs.json"
    inputs = json.loads(inputs_path.read_text())
    inputs["sources"][0]["fingerprint"] = "wrong"
    _write_json(inputs_path, inputs)

    with pytest.raises(RePublicationValidationError, match="workspace input fingerprint"):
        publish_re_run(tmp_path, run_dir)
    assert not (tmp_path / "re/index.json").exists()


@pytest.mark.unit
def test_shallow_full_depth_spec_is_not_publishable(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    spec = run_dir / "re/sources/api/specs/001-re-domain/spec.md"
    spec.write_text("# Architecture summary\n", encoding="utf-8")

    with pytest.raises(
        RePublicationValidationError,
        match=(
                r"shallow reverse-engineering spec is not publishable: .*spec.md; "
                r"missing sections: User Scenarios & Testing, Requirements \(Functional\), "
                r"Requirements \(Non-Functional\), Key Entities, Edge Cases; "
                r"source evidence: 0/5"
        ),
    ):
        publish_re_run(tmp_path, run_dir)


@pytest.mark.unit
def test_publication_requires_a_current_semantic_quality_review(tmp_path: Path) -> None:
    run_dir = write_valid_re_run(tmp_path, ("api",))
    review = run_dir / "re" / "quality" / "semantic-quality-review.json"
    review.unlink()

    with pytest.raises(
        RePublicationValidationError, match="current semantic quality review is required"
    ):
        publish_re_run(tmp_path, run_dir)


@pytest.mark.unit
def test_stale_interrupted_replacement_restores_backup(tmp_path: Path) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    paths = ensure_re_layout(tmp_path)
    stage = paths.staging / "run-stale"
    backup = stage / "rollback/sources/api"
    backup.parent.mkdir(parents=True)
    shutil.copytree(tmp_path / "re/sources/api", backup)
    shutil.rmtree(tmp_path / "re/sources/api")
    (tmp_path / "re/sources/api").mkdir(parents=True)
    (tmp_path / "re/sources/api/corrupt.md").write_text("corrupt\n")
    _write_json(
        stage / "rollback-journal.json",
        {
            "schema_version": 1,
            "status": "replacing",
            "operations": [
                {
                    "final": "sources/api",
                    "staged": "new/sources/api",
                    "backup": "rollback/sources/api",
                    "backed_up": True,
                    "installed": True,
                }
            ],
        },
    )
    lock = paths.locks / "publish.lock"
    lock.mkdir()
    _write_json(
        lock / "owner.json",
        {
            "run_id": "run-stale",
            "run_dir": str(tmp_path / "runs/run-stale"),
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "acquired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        },
    )

    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert _durable_snapshot(tmp_path) == before
    assert not lock.exists()
    assert not stage.exists()


@pytest.mark.unit
def test_concurrent_stale_recovery_has_one_rollback_owner(tmp_path: Path) -> None:
    paths = ensure_re_layout(tmp_path)
    final = paths.root / "canonical"
    final.write_text("new\n", encoding="utf-8")
    stage = paths.staging / "run-stale"
    backup = stage / "rollback/canonical"
    backup.parent.mkdir(parents=True)
    backup.write_text("old\n", encoding="utf-8")
    _write_json(
        stage / "rollback-journal.json",
        {
            "schema_version": 1,
            "status": "replacing",
            "operations": [
                {
                    "final": "canonical",
                    "staged": "new/canonical",
                    "backup": "rollback/canonical",
                    "backed_up": True,
                    "installed": True,
                }
            ],
        },
    )
    lock = paths.locks / "publish.lock"
    lock.mkdir()
    _write_json(
        lock / "owner.json",
        {
            "run_id": "run-stale",
            "run_dir": None,
            "pid": 999_999_999,
            "hostname": socket.gethostname(),
            "acquired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        },
    )
    barrier = threading.Barrier(3)

    def recover() -> bool:
        barrier.wait()
        return recover_interrupted_publication(tmp_path, stale_after_seconds=0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(recover)
        second = executor.submit(recover)
        barrier.wait()
        outcomes = [first.result(), second.result()]

    assert sorted(outcomes) == [False, True]
    assert final.read_text(encoding="utf-8") == "old\n"
    assert not backup.exists()
    assert not lock.exists()


@pytest.mark.unit
@pytest.mark.parametrize("status", ("replacing", "rolling_back"))
def test_orphan_pending_journal_recovers_and_unblocks_publication(tmp_path: Path, status: str) -> None:
    paths = ensure_re_layout(tmp_path)
    (paths.root / "orphan").write_text("new\n", encoding="utf-8")
    stage = paths.staging / "orphan"
    backup = stage / "rollback/orphan"; backup.parent.mkdir(parents=True); backup.write_text("old\n", encoding="utf-8")
    _write_json(stage / "rollback-journal.json", {"schema_version": 1, "status": status, "operations": [{"final": "orphan", "staged": "new/orphan", "backup": "rollback/orphan", "backed_up": True, "installed": True}]})
    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert (paths.root / "orphan").read_text(encoding="utf-8") == "old\n"
    assert not stage.exists()


@pytest.mark.unit
def test_recovery_clean_workspace_does_not_leave_a_publish_lock(tmp_path: Path) -> None:
    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0) is False
    assert not (tmp_path / "re/.locks/publish.lock").exists()


@pytest.mark.unit
def test_orphan_claim_metadata_interruption_does_not_permanently_block_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ensure_re_layout(tmp_path)
    (paths.root / "orphan").write_text("new\n", encoding="utf-8")
    stage = paths.staging / "orphan"
    backup = stage / "rollback/orphan"
    backup.parent.mkdir(parents=True)
    backup.write_text("old\n", encoding="utf-8")
    _write_json(
        stage / "rollback-journal.json",
        {
            "schema_version": 1,
            "status": "replacing",
            "operations": [
                {
                    "final": "orphan",
                    "staged": "new/orphan",
                    "backup": "rollback/orphan",
                    "backed_up": True,
                    "installed": True,
                }
            ],
        },
    )
    original = re_lock._write_claim_temp

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(re_lock, "_write_claim_temp", interrupt)
    with pytest.raises(KeyboardInterrupt):
        recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert not (paths.locks / "publish.lock").exists()

    monkeypatch.setattr(re_lock, "_write_claim_temp", original)
    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert (paths.root / "orphan").read_text(encoding="utf-8") == "old\n"


@pytest.mark.unit
def test_ownerless_recovery_lock_claim_blocks_publishers_and_recovers_after_death(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = ensure_re_layout(tmp_path)
    (paths.root / "orphan").write_text("new\n", encoding="utf-8")
    stage = paths.staging / "orphan"
    backup = stage / "rollback/orphan"
    backup.parent.mkdir(parents=True)
    backup.write_text("old\n", encoding="utf-8")
    _write_json(
        stage / "rollback-journal.json",
        {
            "schema_version": 1,
            "status": "replacing",
            "operations": [
                {
                    "final": "orphan",
                    "staged": "new/orphan",
                    "backup": "rollback/orphan",
                    "backed_up": True,
                    "installed": True,
                }
            ],
        },
    )
    original = re_lock._write_json_atomic

    def interrupt_owner_install(path: Path, *args: object, **kwargs: object) -> None:
        if path == paths.locks / "publish.lock/owner.json":
            raise KeyboardInterrupt()
        original(path, *args, **kwargs)

    monkeypatch.setattr(re_lock, "_write_json_atomic", interrupt_owner_install)
    with pytest.raises(KeyboardInterrupt):
        recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert (paths.locks / "publish.lock").is_dir()
    with pytest.raises(re_lock.RePublishLocked, match="orphan"):
        RePublishLock.acquire(tmp_path, "next", None)

    monkeypatch.setattr(re_lock, "_write_json_atomic", original)
    claim = paths.locks / ".publish-claim.json"
    owner = _read_json(claim)
    owner["pid"] = 999_999_999
    _write_json(claim, owner)

    assert recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert (paths.root / "orphan").read_text(encoding="utf-8") == "old\n"
    assert not (paths.locks / "publish.lock").exists()


@pytest.mark.unit
@pytest.mark.parametrize("with_stale_lock", (False, True))
def test_recovery_releases_lock_before_harmless_rolled_back_stage_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_stale_lock: bool,
) -> None:
    paths = ensure_re_layout(tmp_path)
    (paths.root / "orphan").write_text("new\n", encoding="utf-8")
    stage = paths.staging / "orphan"
    backup = stage / "rollback/orphan"
    backup.parent.mkdir(parents=True)
    backup.write_text("old\n", encoding="utf-8")
    _write_json(
        stage / "rollback-journal.json",
        {
            "schema_version": 1,
            "status": "replacing",
            "operations": [
                {
                    "final": "orphan",
                    "staged": "new/orphan",
                    "backup": "rollback/orphan",
                    "backed_up": True,
                    "installed": True,
                }
            ],
        },
    )
    if with_stale_lock:
        lock = paths.locks / "publish.lock"
        lock.mkdir()
        _write_json(
            lock / "owner.json",
            {
                "run_id": "orphan",
                "run_dir": None,
                "pid": 999_999_999,
                "hostname": socket.gethostname(),
                "acquired_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            },
        )
    original_rmtree = re_publication.shutil.rmtree

    def fail_stage_cleanup(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path) == stage:
            raise OSError("cleanup interrupted")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(re_publication.shutil, "rmtree", fail_stage_cleanup)
    with pytest.raises(OSError, match="cleanup interrupted"):
        recover_interrupted_publication(tmp_path, stale_after_seconds=0)
    assert not (paths.locks / "publish.lock").exists()
    assert _read_json(stage / "rollback-journal.json")["status"] == "rolled_back"
    with RePublishLock.acquire(tmp_path, "next", None):
        pass


@pytest.mark.unit
def test_invalid_installed_index_rolls_back_before_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_1 = write_valid_re_run(tmp_path, ("api",), run_id="run-1")
    publish_re_run(tmp_path, run_1)
    _finish_run(run_1)
    before = _durable_snapshot(tmp_path)
    run_2 = write_valid_re_run(
        tmp_path,
        ("api",),
        run_id="run-2",
        versions={"api": "v2"},
    )

    original = re_publication.PublishedReIndex.from_path

    def reject_installed_index(path: Path):
        if path == tmp_path / "re/index.json":
            raise ReRegistryError("injected installed index validation failure")
        return original(path)

    monkeypatch.setattr(re_publication.PublishedReIndex, "from_path", reject_installed_index)

    with pytest.raises(ReRegistryError, match="injected installed index"):
        publish_re_run(
            tmp_path,
            run_2,
            expected_generation=1,
        )

    assert _durable_snapshot(tmp_path) == before
