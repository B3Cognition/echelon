from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

from harness.re_v2.knowledge_structure import (
    StructuralQueryV1,
    StructuralEvidencePolicyV1,
    StructuralProviderExecutionV1,
    bind_structural_evidence,
    capture_structural_source,
    project_structural_overview,
    project_structural_query,
    _wait_bounded,
)
from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.workspace_snapshot import MaterializedWorkspaceSource


def _key(path: str, name: str, kind: str, signature: str = "") -> str:
    locator = json.dumps(
        [path, name, kind, signature], ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(locator.encode("utf-8")).hexdigest()


def _codegraph_document(repo_path: str) -> bytes:
    symbol_key = _key("src/api.py", "api.run", "function")
    return json.dumps(
        {
            "schema_version": 2,
            "version": "2.0.0",
            "tool": "codegraph",
            "tool_version": "1.6.0",
            "generated_at": "2026-09-15T00:00:00Z",
            "repo_path": repo_path,
            "provider_status": "complete",
            "complete": True,
            "supported": True,
            "counts": {
                "discovered_symbols": 1,
                "emitted_symbols": 1,
                "excluded_symbols": 0,
                "discovered_relationships": 1,
                "emitted_relationships": 1,
                "excluded_relationships": 0,
            },
            "diagnostics": {"unresolved_relationships": []},
            "symbols": [
                {
                    "symbol_key": symbol_key,
                    "file_path": "src/api.py",
                    "qualified_name": "api.run",
                    "name": "run",
                    "kind": "function",
                    "signature": "",
                    "line_start": 1,
                    "line_end": 2,
                }
            ],
            "relationships": [
                {
                    "kind": "calls",
                    "source_key": symbol_key,
                    "target_key": symbol_key,
                    "file_path": "src/api.py",
                }
            ],
            "call_graph": [],
            "type_hierarchy": [],
            "impact_radius": [],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _source(root: Path) -> MaterializedWorkspaceSource:
    return MaterializedWorkspaceSource(
        source_id="api",
        git_role="source",
        workspace_path="sources/api",
        repository_path=".",
        commit="a" * 40,
        source_root=root,
    )


@pytest.mark.unit
def test_capture_normalizes_and_validates_provider_output_without_host_paths(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    (source_root / "src").mkdir(parents=True)
    (source_root / "src/api.py").write_text("def run(): pass\n", encoding="utf-8")

    def runner(provider: str, root: Path, policy: object) -> StructuralProviderExecutionV1:
        assert provider == "codegraph"
        assert root == source_root
        return StructuralProviderExecutionV1("completed", _codegraph_document(str(root)))

    result = capture_structural_source(
        _source(source_root), tmp_path, StructuralEvidencePolicyV1.defaults(), runner=runner
    )

    codegraph = result.providers[0]
    assert codegraph.provider == "codegraph"
    assert codegraph.status == "ready"
    assert codegraph.tool_version == "1.6.0"
    assert codegraph.document_bytes is not None
    normalized = json.loads(codegraph.document_bytes)
    assert normalized["repo_path"] == "."
    assert "generated_at" not in normalized
    assert str(tmp_path) not in codegraph.document_bytes.decode("utf-8")
    assert result.providers[1].status == "not-applicable"


@pytest.mark.unit
def test_capture_degrades_malformed_provider_output_to_closed_reason(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    result = capture_structural_source(
        _source(source_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=lambda *_args: StructuralProviderExecutionV1(
            "completed", b'{"schema_version":2,"tool":"codegraph"}'
        ),
    )

    assert result.providers[0].status == "degraded"
    assert result.providers[0].reason_code == "invalid-provider-artifact"
    assert result.providers[0].document_bytes is None


@pytest.mark.unit
def test_structural_cache_reuses_exact_commit_and_revalidates_artifacts(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    calls = 0

    def runner(*_args) -> StructuralProviderExecutionV1:
        nonlocal calls
        calls += 1
        return StructuralProviderExecutionV1(
            "completed", _codegraph_document(str(first_root))
        )

    cache_root = tmp_path / "cache"
    first = capture_structural_source(
        _source(first_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=runner,
        cache_root=cache_root,
    )
    second = capture_structural_source(
        _source(second_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=runner,
        cache_root=cache_root,
    )

    assert calls == 1
    assert first.reused is False
    assert second.reused is True
    assert second.providers == first.providers
    assert all(path.stat().st_size <= 128 * 1024 * 1024 for path in cache_root.iterdir())


@pytest.mark.unit
def test_invalid_structural_cache_is_ignored_and_replaced(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    cache_root = tmp_path / "cache"
    calls = 0

    def runner(*_args) -> StructuralProviderExecutionV1:
        nonlocal calls
        calls += 1
        return StructuralProviderExecutionV1(
            "completed", _codegraph_document(str(source_root))
        )

    capture_structural_source(
        _source(source_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=runner,
        cache_root=cache_root,
    )
    cache_file = next(cache_root.iterdir())
    cache_file.write_bytes(b'{"forged":true}')

    refreshed = capture_structural_source(
        _source(source_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=runner,
        cache_root=cache_root,
    )

    assert calls == 2
    assert refreshed.reused is False
    assert json.loads(cache_file.read_bytes())["kind"] == "re_structural_cache"


@pytest.mark.unit
def test_structural_policy_has_finite_disk_output_and_time_bounds() -> None:
    policy = StructuralEvidencePolicyV1.defaults()

    assert 0 < policy.max_index_bytes <= 1024 * 1024 * 1024
    assert 0 < policy.max_artifact_bytes <= 128 * 1024 * 1024
    assert 0 < policy.timeout_seconds <= 1800


@pytest.mark.unit
def test_provider_wait_stops_a_live_oversized_artifact(tmp_path: Path) -> None:
    class RunningProcess:
        pid = 4242
        returncode = None

        def poll(self) -> None:
            return None

    policy = StructuralEvidencePolicyV1(
        schema_version=1,
        max_index_bytes=1024,
        max_artifact_bytes=8,
        max_capture_bytes=4,
        timeout_seconds=60,
    )
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "analysis.json").write_bytes(b"123456789")

    with patch(
        "harness.re_v2.knowledge_structure._terminate_process_group"
    ) as terminate:
        reason = _wait_bounded(
            RunningProcess(),  # type: ignore[arg-type]
            tmp_path / "source",
            output_root,
            policy,
        )

    assert reason == "provider-artifact-limit"
    terminate.assert_called_once()


@pytest.mark.unit
def test_structural_catalog_binds_artifact_to_snapshot_and_source_content(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    observation = capture_structural_source(
        _source(source_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=lambda *_args: StructuralProviderExecutionV1(
            "completed", _codegraph_document(str(source_root))
        ),
    )
    objects = ObjectStore(tmp_path / "objects")
    source_content_id = content_digest({"source": "api"})
    snapshot_id = content_digest({"snapshot": "one"})

    catalog = bind_structural_evidence(
        snapshot_id,
        {"api": source_content_id},
        (observation,),
        objects,
    )

    assert catalog.snapshot_id == snapshot_id
    assert catalog.sources[0].source_content_id == source_content_id
    codegraph = catalog.sources[0].providers[0]
    assert codegraph.status == "ready"
    assert codegraph.artifact_id is not None
    assert objects.read_blob(codegraph.artifact_id) == observation.providers[0].document_bytes


@pytest.mark.unit
def test_structural_search_projection_is_bounded_and_provider_neutral(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    observation = capture_structural_source(
        _source(source_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=lambda *_args: StructuralProviderExecutionV1(
            "completed", _codegraph_document(str(source_root))
        ),
    )
    objects = ObjectStore(tmp_path / "objects")
    catalog = bind_structural_evidence(
        content_digest({"snapshot": "one"}),
        {"api": content_digest({"source": "api"})},
        (observation,),
        objects,
    )

    projection = project_structural_query(
        catalog,
        objects,
        StructuralQueryV1(1, "api", "search", "run", "both", (), 1, 10),
    )
    value = json.loads(projection.provider_bytes())

    assert value["kind"] == "untrusted_structural_evidence"
    assert value["source_id"] == "api"
    assert value["providers"] == [
        {"complete": True, "provider": "codegraph", "status": "ready", "tool_version": "1.6.0"},
        {"complete": False, "provider": "perlgraph", "status": "not-applicable", "tool_version": None},
    ]
    assert "api.run" in value["text"]
    assert "repo_path" not in projection.provider_bytes().decode("utf-8")
    assert len(projection.provider_bytes()) <= 262_144


@pytest.mark.unit
def test_structural_overview_is_bounded_persisted_and_replayable(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    observation = capture_structural_source(
        _source(source_root),
        tmp_path,
        StructuralEvidencePolicyV1.defaults(),
        runner=lambda *_args: StructuralProviderExecutionV1(
            "completed", _codegraph_document(str(source_root))
        ),
    )
    objects = ObjectStore(tmp_path / "objects")
    catalog = bind_structural_evidence(
        content_digest({"snapshot": "one"}),
        {"api": content_digest({"source": "api"})},
        (observation,),
        objects,
    )

    projection = project_structural_overview(catalog, objects, "api", 25)
    replayed = project_structural_overview(
        catalog, objects, "api", 25, persist=False
    )
    value = json.loads(projection.provider_bytes())

    assert replayed == projection
    assert objects.read_blob(projection.projection_id) == projection.provider_bytes()
    assert objects.read_blob(projection.mapping_receipt_id)
    assert value["kind"] == "untrusted_structural_evidence"
    assert value["disposition"] == "available"
    assert value["path"] == "."
    assert "api.run" in value["text"]
    assert len(projection.provider_bytes()) <= 262_144


@pytest.mark.unit
def test_installed_codegraph_runs_inside_only_the_materialized_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node.js unavailable")
    source_root = tmp_path / "materialized"
    (source_root / "src").mkdir(parents=True)
    (source_root / "src/api.py").write_text(
        "def run():\n    return 1\n", encoding="utf-8"
    )

    repository_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv(
        "ECHELON_CODEGRAPH_RUNTIME_DIR",
        str(repository_root / "runtime/scripts/node/codegraph"),
    )
    result = capture_structural_source(
        _source(source_root),
        repository_root,
        StructuralEvidencePolicyV1.defaults(),
    )

    assert result.providers[0].status == "ready"
    assert result.providers[0].document_bytes is not None
    assert (source_root / ".codegraph/codegraph.db").is_file()
