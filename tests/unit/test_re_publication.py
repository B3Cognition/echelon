from __future__ import annotations

import hashlib
import json
import shutil
import socket
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

import pytest

import harness.re_publication as re_publication
from harness.re_artifacts import ReArtifactDescriptor
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
    RePublicationValidationError,
    publish_re_run,
    recover_interrupted_publication,
)
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
    _write_json(source_re / "codegraph-summary.json", {"source_id": "api", "summary": True})
    _write_json(source_re / "codegraph-analysis.json", {"source_id": "api", "analysis": True})
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
    assert manifest["codegraph_summary"] == "re/sources/api/codegraph-summary.json"
    assert manifest["codegraph_analysis"] == "re/sources/api/codegraph-analysis.json"
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
    assert json.loads((tmp_path / "re/sources/api/codegraph-summary.json").read_text()) == {
        "source_id": "api",
        "summary": True,
    }
    assert json.loads((tmp_path / "re/sources/api/codegraph-analysis.json").read_text()) == {
        "source_id": "api",
        "analysis": True,
    }
    fingerprint = index["sources"]["api"]["fingerprint"]
    assert (tmp_path / f"re/.cache/sources/api/{fingerprint}/analysis.json").is_file()
    assert (tmp_path / "re/workspace/contracts.md").is_file()
    assert (tmp_path / "re/workspace/architecture-map.json").is_file()
    assert (tmp_path / "re/workspace/domain-catalog.md").is_file()
    assert index["workspace"]["codegraph_summary"] == "re/workspace/codegraph-summary.json"
    assert json.loads((tmp_path / "re/workspace/codegraph-summary.json").read_text()) == {
        "workspace": True,
        "sources": ["api"],
    }
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
