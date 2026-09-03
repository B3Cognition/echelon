from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from tests.unit.test_re_v2_protocol_27_inputs import _input_set


def _production_input_set(run_id: str = "re-synthesis-child"):
    return _input_set(run_id)


def _validated_inputs(tmp_path: Path):
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    run_dir = tmp_path / "runs" / "re-synthesis-child"
    create_protocol_27_run_store(run_dir, _production_input_set(run_dir.name))
    return load_protocol_27_inputs(run_dir)


def _source_item(inputs, source_id: str = "api", kind: str = "source-contracts"):
    return next(
        item
        for item in inputs.graph.ready_work_items({})
        if item.output_key.scope.source_id == source_id
        and item.output_key.artifact_kind == kind
    )


@pytest.mark.unit
def test_context_excludes_unrelated_source_objects(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.context import build_synthesis_context

    inputs = _validated_inputs(tmp_path)
    context = build_synthesis_context(inputs, _source_item(inputs, "api"))

    assert context.source_ids == ("api",)
    assert {item.source_id for item in context.source_outcomes} == {"api"}
    assert all("web" not in item.source_ids for item in context.authorized_objects)
    assert all("web" not in item.source_ids for item in context.dependency_artifacts)


@pytest.mark.unit
def test_context_binds_exact_work_item_dependencies_and_public_contract(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.context import build_synthesis_context

    inputs = _validated_inputs(tmp_path)
    item = _source_item(inputs, "web", "source-architecture")
    context = build_synthesis_context(inputs, item)

    assert context.work_item_id == item.work_item_id
    assert context.artifact_key_id == item.output_key.artifact_key_id
    assert {entry.artifact_key_id for entry in context.dependency_artifacts} == set(
        item.dependency_key_ids
    )
    assert context.debt_refs == item.output_key.debt_manifest_hashes
    assert context.input_quality == "partial"
    assert context.public_contract.public_path == "re/sources/web/architecture.md"
    assert len(canonical_json_bytes(context.to_json_dict())) <= context.max_canonical_json_bytes
    assert type(context).from_json_dict(
        json.loads(canonical_json_bytes(context.to_json_dict()))
    ) == context


@pytest.mark.unit
def test_context_rejects_unrelated_or_missing_dependency_authority(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.context import (
        Protocol27ContextError,
        build_synthesis_context,
    )

    inputs = _validated_inputs(tmp_path)
    item = _source_item(inputs, "api")
    broken = replace(
        item,
        output_key=replace(
            item.output_key,
            non_artifact_dependency_hashes=(content_digest(b"unrelated"),),
        ),
    )

    with pytest.raises(Protocol27ContextError, match="graph authority"):
        build_synthesis_context(inputs, broken)


@pytest.mark.unit
def test_context_policy_enforces_hard_canonical_byte_ceiling(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.context import (
        Protocol27ContextError,
        build_synthesis_context,
    )

    inputs = _validated_inputs(tmp_path)
    item = _source_item(inputs)
    context = build_synthesis_context(inputs, item)

    with pytest.raises(Protocol27ContextError, match="byte ceiling"):
        replace(context, max_canonical_json_bytes=256)


@pytest.mark.unit
def test_domain_context_uses_only_participant_sources_and_generated_dependencies(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.context import build_synthesis_context

    inputs = _validated_inputs(tmp_path)
    store = ObjectStore(inputs.paths.objects)
    accepted = {
        inputs.graph.node_for_work_item(item).node_id: store.put_blob(
            canonical_json_bytes(
                {
                    "artifact_kind": item.output_key.artifact_kind,
                    "schema_version": 1,
                }
            )
        )
        for item in inputs.graph.ready_work_items({})
    }
    web_domain_id = next(
        domain.workspace_domain_id
        for domain in inputs.graph.topology.workspace_domains
        if {participant.source_id for participant in domain.participants} == {"web"}
    )
    web_domain = next(
        item
        for item in inputs.graph.ready_work_items(accepted)
        if item.output_key.scope.workspace_domain_id == web_domain_id
    )

    context = build_synthesis_context(inputs, web_domain)

    assert context.source_ids == ("web",)
    assert context.input_quality == "partial"
    assert len(context.dependency_artifacts) == 3
    assert all(entry.source_ids == ("web",) for entry in context.dependency_artifacts)
