"""Fresh reviewed-analysis creation across a real composite snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
from harness.re_v2.canonical import content_digest
from harness.re_v2.knowledge_creation import (
    ReviewedAnalysisCreationOptions,
    create_or_resume_reviewed_analysis,
)
from harness.re_v2.knowledge_activation import ReviewedDiscoveryAuthorityV1
from harness.re_v2.protocol_22.partition import (
    ImplementationAuthorityV1,
    PartitionAuthoritiesV1,
    build_workspace_partition_catalog,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
from tests.unit.test_re_v2_knowledge_creation import _ReadyBackend
from tests.unit.test_re_v2_protocol_28_evidence import _git, _write_files


@pytest.mark.integration
def test_two_source_fresh_creation_closes_every_selected_source(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sources = []
    for source_id in ("api", "worker"):
        repository = workspace / "sources" / source_id
        repository.mkdir(parents=True)
        _git(repository, "init")
        _write_files(
            repository,
            {
                "README.md": f"{source_id} service\n",
                "src/orders/handler.py": f"SERVICE = {source_id!r}\n",
            },
        )
        _git(repository, "add", ".")
        _git(repository, "commit", "-m", "fixture")
        sources.append(
            SourceRoot(
                id=source_id,
                path=f"sources/{source_id}",
                git_present=True,
            )
        )
    manifest = WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=workspace.resolve(),
            git_role="orchestration",
            git_present=False,
        ),
        sources=tuple(sources),
    )
    snapshot = capture_workspace_snapshot(
        workspace, tuple(sources), tmp_path / "snapshots"
    )
    partition = build_workspace_partition_catalog(
        snapshot,
        manifest,
        PartitionAuthoritiesV1(
            ImplementationAuthorityV1(
                "existing-domain-partitioner", "5", content_digest(b"partitioner")
            ),
            ImplementationAuthorityV1(
                "explicit-domain-ownership", "1", content_digest(b"ownership")
            ),
        ),
    )
    backend = _ReadyBackend()
    options = ReviewedAnalysisCreationOptions(
        request_run_id="re-fresh-request",
        analysis_run_id="re-fresh-analysis",
        created_at="2026-09-12T04:00:00Z",
        snapshot=snapshot,
        workspace_partition=partition,
        selection=SelectionScopeV1(1, True, (), ()),
        source_depths=(("api", "quick"), ("worker", "quick")),
        token_limit=5_000_000,
        active_ms_limit=10_800_000,
        backend=backend,
        discovery_agent_bytes=b"neutral discovery contract",
        review_agent_bytes=b"independent review contract",
        analysis_producer_agent_bytes=b"neutral analysis producer",
        analysis_verifier_agent_bytes=b"independent analysis verifier",
    )

    result = create_or_resume_reviewed_analysis(workspace, options)

    assert result.state == "ready"
    assert backend.calls == [
        "untrusted_discovery_context",
        "untrusted_discovery_review_context",
        "untrusted_discovery_context",
        "untrusted_discovery_review_context",
    ]
    context = load_protocol_28_run_context(workspace / "runs" / result.analysis_run_id)
    reviewed_sources = tuple(
        sorted(
            ReviewedDiscoveryAuthorityV1.from_json_dict(
                json.loads(context.objects.read_blob(authority_id))
            ).source_id
            for authority_id in context.inputs.reviewed_discovery_catalog.authority_ids
        )
    )
    assert reviewed_sources == ("api", "worker")
    assert context.resources.records[0].charged_tokens == 80
