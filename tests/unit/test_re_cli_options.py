from __future__ import annotations

import pytest

from echelon.re_cli_options import (
    KnowledgeDepthError,
    resolve_knowledge_depth,
    resolve_source_depths,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("explicit", "published", "workspace_default", "expected"),
    [
        ("quick", "deep", "standard", "quick"),
        ("full", "quick", "standard", "deep"),
        (None, "deep", "quick", "deep"),
        (None, None, "quick", "quick"),
        (None, None, None, "standard"),
    ],
)
def test_resolve_knowledge_depth_uses_product_precedence(
    explicit: str | None,
    published: str | None,
    workspace_default: str | None,
    expected: str,
) -> None:
    assert (
        resolve_knowledge_depth(
            explicit=explicit,
            published=published,
            workspace_default=workspace_default,
        )
        == expected
    )


@pytest.mark.unit
def test_resolve_source_depths_preserves_mixed_published_depths() -> None:
    assert resolve_source_depths(
        ("worker", "api", "new"),
        explicit=None,
        published={"api": "deep", "worker": "quick"},
        workspace_default="standard",
    ) == {
        "api": "deep",
        "new": "standard",
        "worker": "quick",
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("explicit", "thorough", "--depth"),
        ("published", "full", "published depth"),
        ("workspace_default", "full", "re.default_depth"),
    ],
)
def test_resolve_knowledge_depth_rejects_unknown_or_unmigrated_values(
    field: str,
    value: str,
    message: str,
) -> None:
    values = {"explicit": None, "published": None, "workspace_default": None}
    values[field] = value

    with pytest.raises(KnowledgeDepthError, match=message):
        resolve_knowledge_depth(**values)
