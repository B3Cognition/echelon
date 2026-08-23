from __future__ import annotations

from dataclasses import replace

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_23.authority import (
    ProsaicAgentAuthorityV1,
    Protocol23AuthorityError,
)


def _artifact() -> ProsaicCommandArtifact:
    return ProsaicCommandArtifact(
        frontmatter={
            "name": "echelon.re-baseliner",
            "description": "RE-BASELINER — authors one bounded compact baseline payload",
            "execution": "agent",
            "tools": "write",
            "color": "orange",
            "model_tier": "strong",
            "effort": "high",
        },
        body="# Baseliner\n\nUse only supplied context.\n",
    )


@pytest.mark.unit
def test_authority_separates_and_hashes_body_and_frontmatter() -> None:
    authority = ProsaicAgentAuthorityV1.from_artifact(
        "echelon.re-baseliner", _artifact()
    )

    assert authority.body_bytes == _artifact().body.encode("utf-8")
    assert authority.body_hash == content_digest(authority.body_bytes)
    assert authority.frontmatter_hash == content_digest(
        canonical_json_bytes(_artifact().frontmatter)
    )
    assert authority.to_json_dict()["frontmatter"] == _artifact().frontmatter
    assert authority.artifact_id == content_digest(authority.to_json_dict())


@pytest.mark.unit
def test_authority_frontmatter_is_immutable() -> None:
    authority = ProsaicAgentAuthorityV1.from_artifact(
        "echelon.re-baseliner", _artifact()
    )

    with pytest.raises(TypeError):
        authority.frontmatter["effort"] = "low"  # type: ignore[index]
    with pytest.raises(Protocol23AuthorityError, match="frontmatter"):
        replace(authority, frontmatter={"name": "echelon.re-baseliner"})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("name", "another-agent"),
        ("execution", "command"),
        ("tools", "none"),
        ("model_tier", "standard"),
        ("effort", "low"),
    ),
)
def test_authority_rejects_wrong_neutral_metadata(field: str, value: str) -> None:
    artifact = _artifact()
    artifact.frontmatter[field] = value

    with pytest.raises(Protocol23AuthorityError, match=field):
        ProsaicAgentAuthorityV1.from_artifact("echelon.re-baseliner", artifact)
