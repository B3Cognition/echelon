from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_24.model import (
    AdoptedArtifactAuthorityV1,
    ParentAuthorityBundleV1,
    Protocol24SchemaError,
    RunManifestV3,
    SelectionScopeV1,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_24_fixtures import manifest_v3


def test_schema_3_manifest_round_trips_canonically() -> None:
    manifest = manifest_v3()
    payload = canonical_json_bytes(manifest.to_json_dict())

    assert load_canonical_object(payload, RunManifestV3.from_json_dict) == manifest
    assert manifest.parent_run_id == "re-parent"


def test_selection_rejects_domain_without_exactly_one_source() -> None:
    with pytest.raises(Protocol24SchemaError, match="exactly one source"):
        SelectionScopeV1(
            schema_version=1,
            all_sources=False,
            source_ids=("api", "web"),
            domain_keys=(digest("orders-domain"),),
        )


@pytest.mark.parametrize(
    ("all_sources", "source_ids", "domain_keys", "message"),
    (
        (True, ("api",), (), "all-sources"),
        (True, (), (digest("orders-domain"),), "all-sources"),
        (False, (), (), "source"),
        (False, ("api", "api"), (), "sorted and unique"),
    ),
)
def test_selection_is_closed_and_normalized(
    all_sources: bool,
    source_ids: tuple[str, ...],
    domain_keys: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(Protocol24SchemaError, match=message):
        SelectionScopeV1(1, all_sources, source_ids, domain_keys)


def test_manifest_rejects_unregistered_layer_and_attempt_policy() -> None:
    with pytest.raises(Protocol24SchemaError, match="target_layer"):
        replace(manifest_v3(), target_layer="L3")

    with pytest.raises(Protocol24SchemaError, match="attempt"):
        replace(
            manifest_v3(),
            initial_budget_policy=replace(
                manifest_v3().initial_budget_policy,
                provider_attempt_limit=3,
            ),
        )


def test_parent_bundle_requires_sorted_unique_adopted_artifacts() -> None:
    artifact = AdoptedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=digest("artifact-key"),
        artifact_hash=digest("artifact"),
        dependency_hashes=(digest("dependency"),),
        certification_receipt_id=digest("certification"),
        candidate_assessment_id=None,
        artifact_acceptance_receipt_id=digest("acceptance"),
        source_run_id="re-parent",
        source_ledger_entry_hash=digest("ledger-entry"),
    )

    with pytest.raises(Protocol24SchemaError, match="sorted and unique"):
        ParentAuthorityBundleV1(
            schema_version=1,
            direct_parent_run_id="re-parent",
            source_manifest_hash=digest("manifest"),
            source_event_chain_hash=digest("events"),
            source_terminal_event_hash=digest("terminal"),
            source_ledger_chain_hash=digest("ledger"),
            lineage_root_run_id="re-root",
            ancestor_bundle_hashes=(),
            artifacts=(artifact, artifact),
        )

