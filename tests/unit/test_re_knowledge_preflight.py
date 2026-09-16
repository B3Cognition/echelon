from types import SimpleNamespace as NS

import pytest

from harness.re_v2.knowledge_preflight import estimate_knowledge_request

pytestmark = pytest.mark.unit


def catalog(*rows):
    return NS(sources=tuple(
        NS(source_id=name, domains=(None,) * domains, files=(
            NS(object_kind="regular", text_status="eligible_utf8",
               byte_count=size, line_count=size // 40),
            NS(object_kind="regular", text_status="contains_nul",
               byte_count=100_000_000, line_count=0),
        )) for name, size, domains in rows
    ))


def test_small_and_large_whole_requests_have_different_recommendations():
    small = estimate_knowledge_request(catalog(("a", 4_000, 1)), {"a": "standard"})
    large = estimate_knowledge_request(catalog(("a", 1_200_000, 8)), {"a": "standard"})
    assert small.recommended_tokens <= 5_000_000 < large.recommended_tokens
    assert small.text_bytes == 4_000
    assert small.file_count == 1
    assert small.lower_tokens < small.upper_tokens <= small.recommended_tokens


def test_depth_and_changed_source_scope_affect_the_whole_estimate():
    inventory = catalog(("a", 100_000, 3), ("b", 100_000, 3))
    estimates = [estimate_knowledge_request(inventory, {"a": depth})
                 for depth in ("quick", "standard", "deep")]
    assert estimates[0].recommended_tokens < estimates[1].recommended_tokens < estimates[2].recommended_tokens
    full = estimate_knowledge_request(inventory, {"a": "standard", "b": "standard"})
    refresh = estimate_knowledge_request(inventory, {"a": "standard"}, retained_source_count=1)
    assert refresh.recommended_tokens < full.recommended_tokens
    assert refresh.source_count == 1


def test_no_op_has_no_provider_budget_and_synthesis_only_is_nonzero():
    inventory = catalog(("a", 10_000, 1))
    assert estimate_knowledge_request(inventory, {}, synthesis_required=False).recommended_tokens == 0
    assert estimate_knowledge_request(inventory, {}, retained_source_count=1).recommended_tokens > 0


@pytest.mark.parametrize("depths", [{"unknown": "standard"}, {"a": "ultra"}])
def test_invalid_selection_is_rejected(depths):
    with pytest.raises(ValueError):
        estimate_knowledge_request(catalog(("a", 10_000, 1)), depths)
