from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_27.authority import ResolvedSynthesisParentV1
from harness.re_v2.protocol_27.graph import build_synthesis_graph
from harness.re_v2.protocol_27.lifecycle import (
    partial_acceptances_for,
    synthesis_request,
)
from tests.re_v2_protocol_27_fixtures import (
    digest,
    synthesis_budget_policy_v1,
)
from tests.unit.test_re_v2_protocol_27_graph import _inputs as graph_inputs


def _input_set(run_id: str = "re-synthesis-child"):
    from harness.prosaic_prompt_loader import ProsaicCommandArtifact
    from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
    from harness.re_v2.protocol_27.context import default_synthesis_context_policy
    from harness.re_v2.protocol_27.execution import compose_synthesis_executor
    from harness.re_v2.protocol_27.inputs import Protocol27InputSet
    from harness.re_v2.protocol_27.schemas import (
        canonical_synthesis_response_schema_bytes,
    )

    graph_input = graph_inputs(partial_sources=frozenset({"web"}))
    response_schema_bytes = {
        kind: canonical_synthesis_response_schema_bytes(kind)
        for kind in graph_input.response_schema_hashes
    }
    context_policy = default_synthesis_context_policy()
    prosaic = canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            frontmatter={
                "description": "Bounded RE workspace synthesis",
                "effort": "high",
                "model_tier": "strong",
                "name": "echelon.re-synthesizer",
                "tools": "write",
            },
            body="Generate exactly the authorized synthesis.json artifact.\n",
        )
    )
    from tests.unit.test_re_v2_protocol_22_cli_provider import _cli_executor

    executor = compose_synthesis_executor(
        _cli_executor(),
        agent_contract_hash=content_digest(prosaic),
        response_schema_hashes={
            kind: content_digest(payload)
            for kind, payload in response_schema_bytes.items()
        },
        renderer_implementation_digest=content_digest(b"synthesis:renderer"),
        verifier_implementation_digest=(
            graph_input.policy_catalog.implementation_authority.verifier_authority_hash
        ),
    )
    implementation = replace(
        graph_input.policy_catalog.implementation_authority,
        producer_authority_hash=content_digest(prosaic),
        executor_contract_hash=executor.executor_contract_hash,
    )
    graph_input = replace(
        graph_input,
        policy_catalog=replace(
            graph_input.policy_catalog,
            implementation_authority=implementation,
        ),
        response_schema_hashes={
            kind: content_digest(payload)
            for kind, payload in response_schema_bytes.items()
        },
        context_policy_hash=context_policy.identity,
    )
    graph = build_synthesis_graph(graph_input)
    authority_objects: dict[str, bytes] = {}
    for source in graph_input.accepted_sources:
        root_payload = f"{source.source_id}:root".encode()
        lower_payload = f"{source.source_id}:lower".encode()
        assert content_digest(root_payload) == source.source_root_hash
        assert content_digest(lower_payload) in source.lower_authority_ids
        authority_objects[source.source_root_hash] = root_payload
        authority_objects[content_digest(lower_payload)] = lower_payload
        if source.debt_manifest_hash is not None:
            debt_payload = f"{source.source_id}:debt".encode()
            assert content_digest(debt_payload) == source.debt_manifest_hash
            authority_objects[source.debt_manifest_hash] = debt_payload
    overview_payloads = {
        projection.object_hash: f"{projection.source_id}:overview-markdown".encode()
        for projection in graph_input.source_overviews.projections
    }
    parent = ResolvedSynthesisParentV1(
        parent_run_id="re-parent",
        parent_manifest_hash=digest("parent-manifest"),
        source_snapshot_id=digest("workspace-snapshot"),
        partition_manifest_id=graph_input.topology.partition_manifest_id,
        selected_layers={"api": "L3", "web": "L3"},
        accepted_sources=graph_input.accepted_sources,
        authority_objects=authority_objects,
        debt_summary_hashes={"web": digest("web:debt-summary")},
        _overview_catalog=graph_input.source_overviews,
        _overview_payloads=dict(overview_payloads),
        _overview_authorities={
            item.source_id: (item.source_root_key_id, item.content_hash)
            for item in graph_input.source_overviews.projections
        },
    )
    budget = synthesis_budget_policy_v1()
    request = synthesis_request(
        parent,
        budget,
        expected_v2_index_hash=digest("v2-index"),
        expected_compatibility_generation=4,
    )
    partials = partial_acceptances_for(parent, request)
    from harness.re_v2.protocol_27.model import SynthesisCheckpointSelectionV1

    checkpoint = canonical_json_bytes(
        SynthesisCheckpointSelectionV1.empty(graph.graph_id).to_json_dict()
    )
    graph_objects = {
        content_digest(payload): payload for payload in response_schema_bytes.values()
    }
    graph_objects[graph.context_policy_hash] = canonical_json_bytes(
        context_policy.to_json_dict()
    )
    implementation = graph.policy_catalog.implementation_authority
    graph_objects.update(
        {
            implementation.producer_authority_hash: prosaic,
            implementation.executor_contract_hash: canonical_json_bytes(
                executor.to_json_dict()
            ),
            implementation.verifier_authority_hash: b"policy:verifier",
        }
    )
    return Protocol27InputSet(
        run_id=run_id,
        created_at="2026-08-28T14:00:00Z",
        parent=parent,
        request=request,
        partial_acceptances=partials,
        source_overview_catalog=graph_input.source_overviews,
        source_overview_bytes=overview_payloads,
        graph=graph,
        prosaic_authority_bytes=prosaic,
        budget_policy=budget,
        checkpoint_selection_bytes=checkpoint,
        authority_objects={**authority_objects, **graph_objects},
        checkpoint_objects={},
    )


@pytest.mark.unit
def test_create_protocol_27_store_publishes_manifest_last(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    observed: list[str] = []
    run_dir = tmp_path / "runs" / "re-synthesis-child"
    manifest = create_protocol_27_run_store(
        run_dir,
        _input_set(run_dir.name),
        fault_hook=observed.append,
    )

    assert observed[-1] == "after_manifest_publish"
    loaded = load_protocol_27_inputs(run_dir)
    assert loaded.manifest == manifest
    assert loaded.graph.graph_id == manifest.synthesis_graph_id
    assert loaded.input_authority_catalog.identity == manifest.input_authority_catalog_id
    assert set(
        loaded.input_authority_catalog.hashes_for("topology-component")
    ) == {
        *(item.identity for item in loaded.graph.topology.sources),
        *(item.identity for item in loaded.graph.topology.workspace_domains),
    }


@pytest.mark.unit
def test_loaded_child_does_not_need_parent_or_cache(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    run_dir = tmp_path / "runs" / "re-synthesis-child"
    parent = tmp_path / "runs" / "re-parent"
    cache = tmp_path / ".echelon" / "re-v2" / "checkpoints"
    parent.mkdir(parents=True)
    cache.mkdir(parents=True)
    create_protocol_27_run_store(run_dir, _input_set(run_dir.name))
    parent.rmdir()
    cache.rmdir()

    loaded = load_protocol_27_inputs(run_dir)

    assert loaded.parent_authority.parent_run_id == "re-parent"
    assert set(loaded.source_overview_bytes) == {
        item.object_hash for item in loaded.source_overview_catalog.projections
    }


@pytest.mark.unit
def test_input_store_rejects_wrong_overview_bytes_before_publication(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from harness.re_v2.protocol_27.inputs import (
        Protocol27InputStoreError,
        create_protocol_27_run_store,
    )

    supplied = _input_set()
    broken = dict(supplied.source_overview_bytes)
    broken[next(iter(broken))] = b"changed"

    with pytest.raises(Protocol27InputStoreError, match="overview.*hash"):
        create_protocol_27_run_store(
            tmp_path / "runs" / supplied.run_id,
            replace(supplied, source_overview_bytes=broken),
        )
    assert not (tmp_path / "runs" / supplied.run_id / "v2").exists()


@pytest.mark.unit
def test_loader_rejects_manifest_catalog_replacement(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.inputs import (
        Protocol27InputStoreError,
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    run_dir = tmp_path / "runs" / "re-synthesis-child"
    create_protocol_27_run_store(run_dir, _input_set(run_dir.name))
    manifest_path = run_dir / "v2" / "run.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["input_authority_catalog_id"] = digest("wrong-catalog")
    manifest_path.write_bytes(canonical_json_bytes(raw))

    with pytest.raises(Protocol27InputStoreError):
        load_protocol_27_inputs(run_dir)


@pytest.mark.unit
@pytest.mark.parametrize(
    "removed_role",
    [
        "source-authority",
        "source-overview-projection",
        "response-schema",
        "context-policy",
        "implementation-authority",
    ],
)
def test_loader_rejects_incomplete_semantic_role_closure(
    tmp_path: Path,
    removed_role: str,
) -> None:
    from harness.re_v2.protocol_27.inputs import (
        Protocol27InputStoreError,
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    run_dir = tmp_path / "runs" / "re-synthesis-child"
    manifest = create_protocol_27_run_store(run_dir, _input_set(run_dir.name))
    store = ObjectStore(run_dir / "v2" / "objects")
    catalog = json.loads(store.read_blob(manifest.input_authority_catalog_id))
    del catalog["object_hashes_by_role"][removed_role]
    catalog["object_hashes"] = sorted(
        {
            object_hash
            for hashes in catalog["object_hashes_by_role"].values()
            for object_hash in hashes
        }
    )
    catalog_id = store.put_blob(canonical_json_bytes(catalog))
    manifest_path = run_dir / "v2" / "run.json"
    raw_manifest = json.loads(manifest_path.read_bytes())
    raw_manifest["input_authority_catalog_id"] = catalog_id
    manifest_path.write_bytes(canonical_json_bytes(raw_manifest))

    with pytest.raises(Protocol27InputStoreError, match=removed_role):
        load_protocol_27_inputs(run_dir)


@pytest.mark.unit
def test_prepare_child_is_no_clobber_and_does_not_change_active_pointer(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.inputs import (
        Protocol27InputStoreError,
        prepare_protocol_27_child,
    )

    pointer = tmp_path / "runs" / ".current-re-v2"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("re-existing\n", encoding="utf-8")
    supplied = _input_set()

    prepared = prepare_protocol_27_child(tmp_path, supplied.run_id, supplied)

    assert prepared.run_dir == tmp_path / "runs" / supplied.run_id
    assert prepared.manifest.run_id == supplied.run_id
    assert pointer.read_text(encoding="utf-8") == "re-existing\n"
    with pytest.raises(Protocol27InputStoreError):
        prepare_protocol_27_child(tmp_path, supplied.run_id, supplied)


@pytest.mark.unit
@pytest.mark.parametrize(
    "boundary",
    [
        "after_object_store",
        "after_source_authority",
        "after_overview_objects",
        "after_graph_authority",
        "before_manifest_publish",
    ],
)
def test_staging_fault_never_publishes_partial_v2_root(
    tmp_path: Path,
    boundary: str,
) -> None:
    from harness.re_v2.protocol_27.inputs import create_protocol_27_run_store

    run_dir = tmp_path / "runs" / "re-synthesis-child"

    def crash(observed: str) -> None:
        if observed == boundary:
            raise RuntimeError(boundary)

    with pytest.raises(RuntimeError, match=boundary):
        create_protocol_27_run_store(
            run_dir,
            _input_set(run_dir.name),
            fault_hook=crash,
        )
    assert not (run_dir / "v2").exists()


@pytest.mark.unit
def test_fault_after_manifest_publication_leaves_complete_child(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    run_dir = tmp_path / "runs" / "re-synthesis-child"

    def crash(boundary: str) -> None:
        if boundary == "after_manifest_publish":
            raise RuntimeError(boundary)

    with pytest.raises(RuntimeError, match="after_manifest_publish"):
        create_protocol_27_run_store(
            run_dir,
            _input_set(run_dir.name),
            fault_hook=crash,
        )

    assert load_protocol_27_inputs(run_dir).manifest.run_id == run_dir.name
