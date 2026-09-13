from __future__ import annotations

import pytest

from harness.re_v2.protocol_28.model import (
    ExhaustiveRunManifestV7,
    L4ClosureRunManifestV7,
    Protocol28SchemaError,
    decode_run_manifest_v7,
)
from tests.re_v2_protocol_28_fixtures import (
    closure_manifest_v7,
    exhaustive_manifest_v7,
    exhaustive_manifest_with_budget,
)


@pytest.mark.unit
def test_manifest_v7_dispatches_closed_variants() -> None:
    """A wrong run-mode decoder must not accept the other mode's authority."""
    exhaustive = exhaustive_manifest_v7()
    closure = closure_manifest_v7()

    assert decode_run_manifest_v7(exhaustive.to_json_dict()) == exhaustive
    assert decode_run_manifest_v7(closure.to_json_dict()) == closure
    assert isinstance(decode_run_manifest_v7(exhaustive.to_json_dict()), ExhaustiveRunManifestV7)
    assert isinstance(decode_run_manifest_v7(closure.to_json_dict()), L4ClosureRunManifestV7)


@pytest.mark.unit
def test_closure_manifest_rejects_exhaustive_budget_authority() -> None:
    """Closure mode must not accidentally acquire a provider spending surface."""
    raw = closure_manifest_v7().to_json_dict()
    raw["budget_policy"] = exhaustive_manifest_v7().budget_policy.to_json_dict()

    with pytest.raises(Protocol28SchemaError, match="unknown fields"):
        decode_run_manifest_v7(raw)


@pytest.mark.unit
def test_exhaustive_manifest_requires_its_plan_authority() -> None:
    """An L4 evidence run without its frozen plan must be undecodable."""
    raw = exhaustive_manifest_v7().to_json_dict()
    del raw["exhaustive_plan_id"]

    with pytest.raises(Protocol28SchemaError, match="missing fields"):
        decode_run_manifest_v7(raw)


@pytest.mark.unit
def test_resource_increase_does_not_change_exhaustive_request_identity() -> None:
    """Authorization may resume work but must not create different semantic work."""
    first = exhaustive_manifest_v7(token_limit=400_000)
    raised = exhaustive_manifest_with_budget(first, token_limit=800_000)

    assert first.exhaustive_request.request_id == raised.exhaustive_request.request_id
    assert first.run_manifest_id != raised.run_manifest_id


@pytest.mark.unit
def test_exhaustive_request_authenticates_the_exact_plan() -> None:
    manifest = exhaustive_manifest_v7()

    assert manifest.exhaustive_request.exhaustive_plan_id == manifest.exhaustive_plan_id


@pytest.mark.unit
def test_legacy_exhaustive_request_remains_decodable() -> None:
    raw = exhaustive_manifest_v7().to_json_dict()
    request = raw["exhaustive_request"]
    assert isinstance(request, dict)
    del request["exhaustive_plan_id"]

    decoded = decode_run_manifest_v7(raw)

    assert isinstance(decoded, ExhaustiveRunManifestV7)
    assert decoded.exhaustive_request.exhaustive_plan_id is None


@pytest.mark.unit
def test_closure_manifest_has_no_provider_or_resource_fields() -> None:
    """A zero-call closure cannot expose dormant execution authority."""
    raw = closure_manifest_v7().to_json_dict()

    forbidden = {
        "budget_policy",
        "executor_catalog_id",
        "attempt_policy_id",
        "exhaustive_plan_id",
        "snapshot_evidence_catalog_id",
    }
    assert forbidden.isdisjoint(raw)


@pytest.mark.unit
def test_manifest_v7_rejects_unknown_run_mode_before_variant_decoding() -> None:
    """Manifest-first routing must never guess a schema from overlapping fields."""
    raw = exhaustive_manifest_v7().to_json_dict()
    raw["run_mode"] = "unknown"

    with pytest.raises(Protocol28SchemaError, match="run_mode"):
        decode_run_manifest_v7(raw)
